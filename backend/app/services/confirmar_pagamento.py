"""O "recebi": o agendamento que esperava o Pix vira CONFIRMADO e a cobranca,
PAGA. Um servico so', para a mao do barbeiro (`painel/agendamentos/<id>/recebi`)
e para o vigia da etapa 3, que chama esta mesma funcao com `como="VIGIA"`.

O desenho de concorrencia esta no cabecalho da varredura, em
`pix_agendamento`: o AGENDAMENTO decide, sob `FOR UPDATE` na linha dele, e a
cobranca segue depois do commit com UPDATE condicional. Aqui isso significa:

- "recebi" x varredura no mesmo instante: quem pega a trava primeiro decide. Se
  a varredura expirou antes, o "recebi" encontra EXPIRADO e tenta ressuscitar
  (so' se o horario ainda nao comecou e a vaga segue livre); se o "recebi"
  confirmou antes, a varredura encontra CONFIRMADO e deixa a cobranca PAGA.
- duplo clique: o segundo espera a trava, encontra CONFIRMADO e responde 200
  sem reenviar nada.
- falha entre os dois commits: a proxima varredura completa a cobranca.
"""

import logging
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.utils import OperationalError

from app.services import lista_do_dia, pix_agendamento
from app.services.agendamentos import (
    AGUARDANDO,
    ErroCliente,
    eh_deadlock,
    eh_sobreposicao,
)
from app.services.lembrete import lembrete_ao_criar
from app.services.mensagens import _reais, msg_barbeiro_novo, msg_confirmacao
from app.services.whatsapp import enviar_a_equipe_da, enviar_ao_cliente
from tenant.models import (
    Agendamento,
    Barbearia,
    Cobranca,
    ComoFoiPaga,
    StatusCobranca,
    TipoMensagem,
)
from tenant.rls import com_barbearia

logger = logging.getLogger(__name__)

ALIAS = "admin"


def _devolva(valor_centavos: int | None, prefixo: str) -> str:
    """O 409 que manda o barbeiro devolver o dinheiro: o cliente pagou e o
    horario nao e' mais dele."""
    quanto = f" de {_reais(valor_centavos)}" if valor_centavos else ""
    return f"{prefixo} Devolva o Pix{quanto} pelo app do banco."


def confirmar_pagamento(
    agendamento_id, *, barbearia_id, agora: datetime, como: str = ComoFoiPaga.MANUAL,
    filtro_barbeiro_id=None, link_base: str = "",
) -> dict:
    """Confirma o agendamento. `filtro_barbeiro_id`: o barbeiro que pede (o
    dono passa None); o horario de outro e' 403. `link_base`: a origem do site
    para o link de cancelar na confirmacao ao cliente.

    Devolve `{"tipo": "confirmado" | "ja_confirmado", ...}`; levanta
    `ErroCliente` (404, 403 ou 409) nos demais desfechos. Os avisos saem
    depois do commit, e so' em `confirmado`."""
    cobranca = Cobranca.objects.using(ALIAS).filter(agendamento_id=agendamento_id).first()
    valor_pago = cobranca.valor_centavos if cobranca else None
    try:
        with com_barbearia(barbearia_id):
            a = (
                Agendamento.objects.select_for_update(of=("self",))
                .select_related("cliente", "barbeiro")
                .filter(id=agendamento_id)
                .first()
            )
            if a is None:
                raise ErroCliente(404, "Agendamento não encontrado.")
            if filtro_barbeiro_id and filtro_barbeiro_id != a.barbeiro_id:
                raise ErroCliente(403, "Esse horário é de outro barbeiro.")
            if a.status == "CONFIRMADO":
                if cobranca is None:
                    raise ErroCliente(409, "Esse horário não está esperando Pix.")
                tipo = "ja_confirmado"
            elif a.status == AGUARDANDO or a.status == "EXPIRADO":
                if a.status == "EXPIRADO" and a.inicio <= agora:
                    raise ErroCliente(409, _devolva(
                        valor_pago, "O prazo do Pix acabou e o horário já começou.",
                    ))
                # Pode estourar o EXCLUDE (outro cliente pegou a vaga depois do
                # prazo): sobe daqui de dentro e o `except` abaixo traduz.
                Agendamento.objects.filter(id=a.id).update(
                    status="CONFIRMADO", lembrete_enviado_em=lembrete_ao_criar(a.inicio, agora),
                )
                tipo = "confirmado"
            else:
                raise ErroCliente(409, "Esse horário foi cancelado.")
            dados = {
                "id": a.id, "codigo": a.codigo, "barbeiro_id": str(a.barbeiro_id),
                "barbeiro_nome": a.barbeiro.nome, "barbeiro_whatsapp": a.barbeiro.whatsapp,
                "cliente_nome": a.cliente.nome, "cliente_whatsapp": a.cliente.whatsapp,
                "servico_nome": a.servico_nome, "inicio": a.inicio,
            }
    except (IntegrityError, OperationalError) as e:
        if eh_sobreposicao(e) or eh_deadlock(e):
            raise ErroCliente(409, _devolva(
                valor_pago, "Esse horário já foi pego por outro cliente.",
            )) from e
        raise

    _marcar_cobranca_paga(agendamento_id, agora, como)
    if tipo == "confirmado":
        _avisar(barbearia_id, dados, link_base, agora)
    return {"tipo": tipo, "valor_centavos": valor_pago}


def _marcar_cobranca_paga(agendamento_id, agora, como) -> None:
    """Condicional: ABERTA (no prazo) ou EXPIRADA (a varredura passou antes) vira
    PAGA; PAGA fica como esta. Se falhar, so' registra: o agendamento ja' esta
    CONFIRMADO e a varredura completa a cobranca."""
    try:
        Cobranca.objects.using(ALIAS).filter(
            agendamento_id=agendamento_id,
            status__in=[StatusCobranca.ABERTA, StatusCobranca.EXPIRADA],
        ).update(status=StatusCobranca.PAGA, paga_em=agora, como_foi_paga=como)
    except Exception:
        logger.exception("[pix] cobranca do agendamento %s nao foi marcada paga", agendamento_id)


def _avisar(barbearia_id, d: dict, link_base: str, agora: datetime) -> None:
    """Exatamente o que um agendamento CONFIRMADO de hoje dispara: a
    confirmacao ao cliente e, ao barbeiro, a lista do dia refeita (ou o aviso
    curto, se a fila estiver fora). Depois do commit, fora de transacao."""
    barbearia = Barbearia.objects.get(id=barbearia_id)
    link = f"{link_base}/agendamento/{d['codigo']}"

    def enviar():
        try:
            enviar_ao_cliente(
                barbearia, d["cliente_whatsapp"],
                msg_confirmacao(
                    cliente_nome=d["cliente_nome"], barbeiro_nome=d["barbeiro_nome"],
                    servico_nome=d["servico_nome"], inicio=d["inicio"],
                    endereco=barbearia.endereco, link=link,
                    barbearia_nome=barbearia.nome, contato=barbearia.whatsapp_contato,
                ),
                tipo=TipoMensagem.CONFIRMACAO, cliente_nome=d["cliente_nome"],
            )
            mudanca = lista_do_dia.avisar_mudanca(
                barbearia_id, d["barbeiro_id"], agora, novos=[(d["id"], d["inicio"])],
            )
            if mudanca == lista_do_dia.FILA_FORA:
                enviar_a_equipe_da(
                    barbearia_id, d["barbeiro_whatsapp"],
                    msg_barbeiro_novo(
                        cliente_nome=d["cliente_nome"], servico_nome=d["servico_nome"],
                        inicio=d["inicio"], agora=agora,
                    ),
                )
        except Exception:
            logger.exception("[pix] avisos da confirmacao nao sairam: agendamento %s", d["id"])

    transaction.on_commit(enviar)
