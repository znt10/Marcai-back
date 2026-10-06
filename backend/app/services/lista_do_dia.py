"""A lista de horarios que cada barbeiro recebe as 07:00.

E a mensagem que faz o plano SEM ZAP valer alguma coisa: naquele plano o
cliente nao recebe nada, e sem isto o barbeiro tambem nao — ele so saberia da
agenda abrindo o painel. Por isso ela sai nos DOIS planos.

Sai pelo numero CENTRAL (etapa 1, spec 2026-10-06), e fica GUARDADA
(`ListaDoDiaEnviada`) para poder ser apagada e mandada de novo quando a agenda
de hoje muda — ver `avisar_mudanca` e `refazer`, no fim do modulo.

Duas regras que foram decididas e que o codigo aqui so obedece:

- **Cada um recebe so os proprios horarios, o dono inclusive.** O dono ja ve a
  agenda inteira no painel; receber por WhatsApp a agenda de todo mundo todo
  dia as sete da manha e ruido, nao servico.
- **Dia vazio nao manda nada.** "Voce nao tem horario hoje" e uma mensagem que
  so serve para a pessoa aprender a ignorar as mensagens seguintes.
"""

import logging
from datetime import datetime

from django.db.models import Q

from tenant.datas import dia_de_hoje, local_para_utc, utc_para_local
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    ListaDoDiaEnviada,
    StatusAgendamento,
)
from tenant.rls import com_barbearia

from .mensagens import msg_lista_do_dia, msg_lista_refeita
from .trava_conversa import trava_consultiva
from .whatsapp import Aceita, apagar_para_todos, enviar_a_equipe_aceita

logger = logging.getLogger(__name__)

# A hora da lista (o `crontab(hour=7)` do settings). Depois dela, mudanca na
# agenda de hoje refaz a lista; antes, a mudanca entra na das 07:00.
HORA_DA_LISTA_MIN = 7 * 60


def enviar(agora: datetime) -> int:
    """Devolve quantos barbeiros receberam. `agora` entra por parametro (e nao
    sai de um `now()` la dentro) pelo mesmo motivo de `enviar_pendentes`: hora
    e a variavel que mais precisa ser fixada no teste.

    O dia e' recortado no fuso de Sao Paulo, e nao em UTC. As 07:00 daqui sao
    10:00 UTC — um recorte em UTC pegaria de 21:00 de ontem ate 21:00 de hoje
    e a lista sairia com os horarios da noite anterior dentro.
    """
    hoje = dia_de_hoje(agora)
    inicio_do_dia = local_para_utc(hoje, 0)
    fim_do_dia = local_para_utc(hoje, 24 * 60)
    enviados = 0

    for b in Barbearia.objects.filter(ativo=True):
        with com_barbearia(b.id):
            agendamentos = list(
                Agendamento.objects.filter(
                    status=StatusAgendamento.CONFIRMADO,
                    inicio__gte=inicio_do_dia,
                    inicio__lt=fim_do_dia,
                    barbeiro__ativo=True,
                )
                .select_related("barbeiro", "cliente")
                .order_by("inicio")
            )

        por_barbeiro: dict = {}
        for a in agendamentos:
            por_barbeiro.setdefault(a.barbeiro_id, []).append(a)

        # Quem nao tem horario nao aparece neste dicionario, e e assim que
        # "dia vazio nao manda nada" acontece: pela ausencia, sem um `if` que
        # alguem possa inverter sem querer.
        for agendamentos_do_barbeiro in por_barbeiro.values():
            barbeiro = agendamentos_do_barbeiro[0].barbeiro
            aceita = enviar_a_equipe_aceita(
                barbeiro.whatsapp,
                msg_lista_do_dia(
                    barbeiro_nome=barbeiro.nome,
                    agendamentos=[
                        {
                            "cliente_nome": a.cliente.nome,
                            "servico_nome": a.servico_nome,
                            "inicio": a.inicio,
                        }
                        for a in agendamentos_do_barbeiro
                    ],
                    agora=agora,
                ),
            )
            _guardar(b.id, barbeiro.id, hoje, aceita)
            enviados += 1

    return enviados


def _guardar(barbearia_id, barbeiro_id, dia: str, aceita: Aceita | None) -> bool:
    """Guarda a lista que saiu, para a proxima mudanca poder apaga-la. Sem id
    ou sem jid nao guarda: a proxima tentativa apagaria `None`."""
    if aceita is None or not aceita.id or not aceita.jid:
        return False
    with com_barbearia(barbearia_id):
        ListaDoDiaEnviada.objects.update_or_create(
            barbearia_id=barbearia_id, barbeiro_id=barbeiro_id, dia=dia,
            defaults={"mensagem_id": aceita.id, "remote_jid": aceita.jid},
        )
    return True


def avisar_mudanca(barbearia_id, barbeiro_id, agora: datetime, *, novos=(), cancelados=()) -> bool:
    """Chamada por quem mexe na agenda (site, painel, bloqueio), DEPOIS do
    commit. `novos`/`cancelados`: pares `(agendamento_id, inicio)`.

    Enfileira a lista refeita so' para o que e' de HOJE e so' de 07:00 em
    diante — antes disso a mudanca entra na lista das 07:00. Devolve se
    enfileirou: quem chama pelo site usa isso para NAO mandar tambem o aviso
    curto ("Novo horário"/"Cancelou").
    """
    hoje, minutos_agora = utc_para_local(agora)
    if minutos_agora < HORA_DA_LISTA_MIN:
        return False

    def de_hoje(pares):
        return [str(i) for i, inicio in pares if utc_para_local(inicio)[0] == hoje]

    ids_novos, ids_cancelados = de_hoje(novos), de_hoje(cancelados)
    if not ids_novos and not ids_cancelados:
        return False
    _enfileirar_refazer(str(barbearia_id), str(barbeiro_id), ids_novos, ids_cancelados)
    return True


def _enfileirar_refazer(barbearia_id: str, barbeiro_id: str, novos: list, cancelados: list) -> None:
    # Import tardio: `app.tasks` importa servicos, e este e' um deles.
    from app.tasks import refazer_lista

    refazer_lista.delay(barbearia_id, barbeiro_id, novos, cancelados)


def refazer(
    barbearia_id: str, barbeiro_id: str, novos: list, cancelados: list, agora: datetime,
) -> str:
    """Apaga a lista de hoje do barbeiro e manda a nova. Roda na task
    `refazer_lista`, fora do pedido HTTP.

    A trava e' por barbeiro e dia: duas mudancas seguidas saem em ordem, e a
    segunda apaga a lista da PRIMEIRA (e nao a das 07:00, que a primeira ja
    apagou). Consultiva e nao `select_for_update` porque segura duas idas a
    Evolution, e a linha pode nem existir ainda.

    Apagar que falha nao segura a lista nova: uma lista velha que nao sumiu
    e' feia; uma lista nova que nao chegou e' prejuizo.
    """
    hoje = dia_de_hoje(agora)
    ids_novos, ids_cancelados = set(novos), set(cancelados)

    with trava_consultiva(f"lista:{barbeiro_id}:{hoje}"):
        with com_barbearia(barbearia_id):
            barbeiro = Barbeiro.objects.filter(id=barbeiro_id, ativo=True).first()
            do_dia = list(
                Agendamento.objects.filter(
                    barbeiro_id=barbeiro_id,
                    inicio__gte=local_para_utc(hoje, 0),
                    inicio__lt=local_para_utc(hoje, 24 * 60),
                )
                .filter(Q(status=StatusAgendamento.CONFIRMADO) | Q(id__in=ids_cancelados))
                .select_related("cliente")
                .order_by("inicio")
            )
            anterior = ListaDoDiaEnviada.objects.filter(barbeiro_id=barbeiro_id, dia=hoje).first()

        if barbeiro is None:
            return "sem_barbeiro"
        if not do_dia:
            return "vazia"

        linhas = []
        for a in do_dia:
            if a.status == StatusAgendamento.CONFIRMADO:
                marca = "novo" if str(a.id) in ids_novos else None
            else:
                marca = "cancelado"
            linhas.append({
                "cliente_nome": a.cliente.nome, "servico_nome": a.servico_nome,
                "inicio": a.inicio, "marca": marca,
            })

        if anterior is not None:
            apagar_para_todos(anterior.remote_jid, anterior.mensagem_id)
        aceita = enviar_a_equipe_aceita(
            barbeiro.whatsapp,
            msg_lista_refeita(barbeiro_nome=barbeiro.nome, linhas=linhas, agora=agora),
        )
        if not _guardar(barbearia_id, barbeiro_id, hoje, aceita):
            logger.error("[lista-do-dia] lista refeita de %s nao saiu", barbeiro_id)
            return "nao_saiu"
        return "refeita"
