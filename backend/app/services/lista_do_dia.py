"""A lista de horarios que cada barbeiro recebe de manha, na hora que o dono
escolheu (06:30 se ele nao mexeu).

E a mensagem que faz o plano SEM ZAP valer alguma coisa: naquele plano o
cliente nao recebe nada, e sem isto o barbeiro tambem nao — ele so saberia da
agenda abrindo o painel. Por isso ela sai nos DOIS planos.

Sai pelo numero CENTRAL (etapa 1, spec 2026-10-06), e fica GUARDADA
(`ListaDoDiaEnviada`) para poder ser apagada e mandada de novo quando a agenda
de hoje muda — ver `avisar_mudanca` e `refazer`, no fim do modulo.

Duas regras que foram decididas e que o codigo aqui so obedece:

- **Cada um recebe so os proprios horarios, o dono inclusive.** O dono ja ve a
  agenda inteira no painel; receber por WhatsApp a agenda de todo mundo todo
  dia as seis e meia da manha e ruido, nao servico.
- **Dia vazio nao manda nada.** "Voce nao tem horario hoje" e uma mensagem que
  so serve para a pessoa aprender a ignorar as mensagens seguintes.
"""

import logging
from datetime import datetime

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

# As horas que o dono pode escolher (`Barbearia.hora_da_lista_min`), de meia
# em meia hora, das 05:00 as 11:30. Meia hora porque o beat dispara em CADA
# uma delas (`crontab(minute="0,30", hour="5-11")` no settings — um teste em
# test_celery.py prende os dois juntos); so' de manha porque a lista abre com
# "Bom dia". Depois da hora da barbearia, mudanca na agenda de hoje refaz a
# lista; antes, a mudanca entra na lista que ainda vai sair.
HORAS_DA_LISTA_MIN = tuple(range(5 * 60, 12 * 60, 30))
HORA_PADRAO_MIN = 6 * 60 + 30

# O que `avisar_mudanca` responde a quem mexeu na agenda.
ENFILEIRADA = "enfileirada"  # a lista de hoje vai ser refeita
SEM_LISTA = "sem_lista"  # outro dia, ou antes da hora da lista: nada sai agora
FILA_FORA = "fila_fora"  # era para refazer, e a fila nao aceitou


def enviar(agora: datetime) -> int:
    """Devolve quantos barbeiros receberam. `agora` entra por parametro (e nao
    sai de um `now()` la dentro) pelo mesmo motivo de `enviar_pendentes`: hora
    e a variavel que mais precisa ser fixada no teste.

    Roda a cada meia hora da manha e so' manda para as barbearias cuja hora e'
    ESTA meia hora. Recortada para baixo, e nao comparada ao minuto: o beat
    dispara as :00 e as :30, e a tarefa pode comecar uns segundos (ou, com a
    fila cheia, uns minutos) depois.

    O dia e' recortado no fuso de Sao Paulo, e nao em UTC. As 06:30 daqui sao
    09:30 UTC — um recorte em UTC pegaria de 21:00 de ontem ate 21:00 de hoje
    e a lista sairia com os horarios da noite anterior dentro.
    """
    hoje, minutos_agora = utc_para_local(agora)
    meia_hora = minutos_agora - minutos_agora % 30
    inicio_do_dia = local_para_utc(hoje, 0)
    fim_do_dia = local_para_utc(hoje, 24 * 60)
    enviados = 0

    for b in Barbearia.objects.filter(ativo=True, hora_da_lista_min=meia_hora):
        with com_barbearia(b.id):
            # O dono que atrasa a hora DEPOIS de a lista sair (06:30 -> 08:00)
            # faz a de hoje sair de novo: a anterior e' apagada, como na
            # lista refeita, para nao ficarem duas "Bom dia" no WhatsApp.
            anteriores = {
                lista.barbeiro_id: lista for lista in ListaDoDiaEnviada.objects.filter(dia=hoje)
            }
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
            anterior = anteriores.get(barbeiro.id)
            if _guardar(b.id, barbeiro.id, hoje, aceita) and anterior is not None:
                apagar_para_todos(anterior.remote_jid, anterior.mensagem_id)
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


def hora_da_lista(barbearia_id) -> int:
    """Do BANCO, e nao do `request.barbearia` (cache de slug por
    `TTL_CACHE_TENANT_S`): o dono que acabou de mudar a hora nao pode ver a
    mudanca valer so' daqui a um minuto."""
    with com_barbearia(barbearia_id):
        hora = (
            Barbearia.objects.filter(id=barbearia_id)
            .values_list("hora_da_lista_min", flat=True).first()
        )
    return HORA_PADRAO_MIN if hora is None else hora


def mudar_hora_da_lista(barbearia_id, minutos: int) -> None:
    """So' as horas de `HORAS_DA_LISTA_MIN`: uma fora dela nunca casaria com
    um disparo do beat, e a lista deixaria de sair sem ninguem saber."""
    if minutos not in HORAS_DA_LISTA_MIN:
        raise ValueError(minutos)
    with com_barbearia(barbearia_id):
        Barbearia.objects.filter(id=barbearia_id).update(hora_da_lista_min=minutos)


def avisar_mudanca(barbearia_id, barbeiro_id, agora: datetime, *, novos=(), cancelados=()) -> str:
    """Chamada por quem mexe na agenda (site, painel, bloqueio), DEPOIS do
    commit. `novos`/`cancelados`: pares `(agendamento_id, inicio)`.

    Enfileira a lista refeita so' para o que e' de HOJE e so' da hora da
    lista da barbearia em diante — antes disso a mudanca entra na lista que
    ainda vai sair, e a de outro dia, na lista daquele dia. Devolve
    ENFILEIRADA, SEM_LISTA ou FILA_FORA: o site so' manda o aviso curto
    ("Novo horário"/"Cancelou") no FILA_FORA, o unico caso em que o barbeiro
    nao ficaria sabendo de hoje por outro caminho.
    """
    hoje, minutos_agora = utc_para_local(agora)

    def de_hoje(pares):
        return [str(i) for i, inicio in pares if utc_para_local(inicio)[0] == hoje]

    ids_novos, ids_cancelados = de_hoje(novos), de_hoje(cancelados)
    if not ids_novos and not ids_cancelados:
        return SEM_LISTA
    if minutos_agora < hora_da_lista(barbearia_id):
        return SEM_LISTA
    try:
        _enfileirar_refazer(str(barbearia_id), str(barbeiro_id), ids_novos, ids_cancelados)
    except Exception as e:  # noqa: BLE001 — roda depois do commit
        # A marcacao ja esta gravada: uma fila fora do ar nao pode virar 500
        # na tela de quem marcou. FILA_FORA faz o site cair no aviso curto.
        logger.error("[lista-do-dia] nao deu para enfileirar a lista de %s: %s", barbeiro_id, e)
        return FILA_FORA
    return ENFILEIRADA


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
    segunda apaga a lista da PRIMEIRA (e nao a das 06:30, que a primeira ja
    apagou). Consultiva e nao `select_for_update` porque segura duas idas a
    Evolution, e a linha pode nem existir ainda.

    O cancelado nao aparece riscado: so' sai da lista, e o barbeiro le a
    agenda como ficou. `cancelados` so' serve para saber que houve mudanca
    quando nao sobrou horario — ai a nova diz que o dia esvaziou.

    MANDA a nova e so' entao apaga a anterior. Na ordem contraria, um envio
    que falhasse deixaria o barbeiro sem lista nenhuma — e, pelo site, sem o
    aviso curto tambem, que ja foi trocado pela lista. Apagar que falha nao
    desfaz nada: uma lista velha que nao sumiu e' feia; uma lista que sumiu
    sem outra no lugar e' prejuizo.
    """
    hoje = dia_de_hoje(agora)
    ids_novos, ids_cancelados = set(novos), set(cancelados)

    with trava_consultiva(f"lista:{barbeiro_id}:{hoje}"):
        with com_barbearia(barbearia_id):
            barbeiro = Barbeiro.objects.filter(id=barbeiro_id, ativo=True).first()
            do_dia = list(
                Agendamento.objects.filter(
                    barbeiro_id=barbeiro_id,
                    status=StatusAgendamento.CONFIRMADO,
                    inicio__gte=local_para_utc(hoje, 0),
                    inicio__lt=local_para_utc(hoje, 24 * 60),
                )
                .select_related("cliente")
                .order_by("inicio")
            )
            anterior = ListaDoDiaEnviada.objects.filter(barbeiro_id=barbeiro_id, dia=hoje).first()

        if barbeiro is None:
            return "sem_barbeiro"
        if not do_dia and not ids_cancelados:
            return "vazia"

        linhas = [
            {
                "cliente_nome": a.cliente.nome, "servico_nome": a.servico_nome,
                "inicio": a.inicio, "marca": "novo" if str(a.id) in ids_novos else None,
            }
            for a in do_dia
        ]

        aceita = enviar_a_equipe_aceita(
            barbeiro.whatsapp,
            msg_lista_refeita(barbeiro_nome=barbeiro.nome, linhas=linhas, agora=agora),
        )
        if not _guardar(barbearia_id, barbeiro_id, hoje, aceita):
            logger.error("[lista-do-dia] lista refeita de %s nao saiu", barbeiro_id)
            return "nao_saiu"
        if anterior is not None:
            apagar_para_todos(anterior.remote_jid, anterior.mensagem_id)
        return "refeita"
