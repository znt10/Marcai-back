import calendar
from datetime import datetime

from tenant.config import DIAS_NA_HOME, JANELA_MAXIMA_DIAS
from tenant.datas import (
    dia_de_hoje,
    formatar_dia_longo,
    formatar_hora,
    local_para_utc,
    somar_dias,
)
from tenant.models import Agendamento, Barbeiro, BarbeiroServico, Bloqueio, HorarioTrabalho
from tenant.rls import com_barbearia

from .servicos import QUALQUER
from .slots import Slot, slots_livres, unir_slots


def _slots_do_dia(barbeiro_id: str, servico_id: str, dia: str, agora: datetime) -> list[Slot]:
    """A ponte entre o banco e o motor puro do slots.py: le o que o dia precisa
    e entrega ao calculo.

    NAO abre `com_barbearia` — quem chama ja abriu. Isso e obrigatorio e nao
    estilo: `com_barbearia` usa `atomic(durable=True)`, que estoura de
    proposito se for aninhado. E o certo, porque um dia de calendario faz 31
    chamadas destas, e 31 transacoes separadas leriam o mes com o banco
    mudando embaixo.

    As tres consultas leem TODOS os barbeiros de uma vez (`id__in`), e nao um
    por um: com "qualquer" numa equipe de cinco, o laco ingenuo daria 15
    consultas por dia, 465 num mes.
    """
    vinculos = BarbeiroServico.objects.filter(
        servico_id=servico_id, ativo=True, barbeiro__ativo=True
    )
    if barbeiro_id != QUALQUER:
        vinculos = vinculos.filter(barbeiro_id=barbeiro_id)
    vinculos = list(vinculos.values("barbeiro_id", "duracao_min", "barbeiro__ordem"))
    if not vinculos:
        return []

    ids = [v["barbeiro_id"] for v in vinculos]
    expedientes = list(HorarioTrabalho.objects.filter(barbeiro_id__in=ids))
    bloqueios = list(Bloqueio.objects.filter(barbeiro_id__in=ids))
    # So CONFIRMADO ocupa. Um cancelado que continuasse ocupando deixaria o
    # horario morto ate o fim do dia — a barbearia perde dinheiro e nada
    # aparece na tela.
    agendamentos = list(
        Agendamento.objects.filter(barbeiro_id__in=ids, status="CONFIRMADO").only(
            "barbeiro", "inicio", "fim"
        )
    )

    listas = [
        slots_livres(
            barbeiro_id=v["barbeiro_id"],
            duracao_min=v["duracao_min"],
            expediente=[h for h in expedientes if h.barbeiro_id == v["barbeiro_id"]],
            bloqueios=[b for b in bloqueios if b.barbeiro_id == v["barbeiro_id"]],
            agendamentos=[a for a in agendamentos if a.barbeiro_id == v["barbeiro_id"]],
            dia=dia,
            agora=agora,
        )
        for v in vinculos
    ]

    ordem = {v["barbeiro_id"]: v["barbeiro__ordem"] for v in vinculos}
    return unir_slots(listas, ordem)


def _rotulo(dia: str, hoje: str) -> str:
    """"hoje · qua 13 ago". O ponto medio e o separador que a tela ja usa.

    Ancorado ao MEIO-DIA (`12 * 60`) e nao a meia-noite: a meia-noite qualquer
    deslocamento de fuso na formatacao empurraria o rotulo para o dia anterior,
    e o cartao diria "ter 12 ago" no dia 13.
    """
    longo = formatar_dia_longo(local_para_utc(dia, 12 * 60))
    if dia == hoje:
        return f"hoje · {longo}"
    if dia == somar_dias(hoje, 1):
        return f"amanhã · {longo}"
    return longo


def dias_com_horarios(
    barbearia_id: str,
    barbeiro_id: str,
    servico_id: str,
    de: str | None,
    quantos: int | None,
    agora: datetime,
) -> list[dict]:
    """Os proximos dias com os horarios de cada um — o que a home e a tela de
    escolha mostram.

    `quantos` e limitado por `JANELA_MAXIMA_DIAS`, e o teto nao e capricho: o
    parametro vem da query string, e sem ele um `?dias=100000` viraria cem mil
    voltas de laco com tres consultas cada, dentro de uma transacao aberta.
    """
    hoje = dia_de_hoje(agora)
    de = de or hoje
    quantos = min(quantos or DIAS_NA_HOME, JANELA_MAXIMA_DIAS)

    with com_barbearia(barbearia_id):
        saida = []
        for i in range(quantos):
            dia = somar_dias(de, i)
            slots = _slots_do_dia(barbeiro_id, servico_id, dia, agora)
            nomes = dict(
                Barbeiro.objects.filter(
                    id__in={s.barbeiro_id for s in slots}
                ).values_list("id", "nome")
            )
            saida.append(
                {
                    "data": dia,
                    "rotulo": _rotulo(dia, hoje),
                    # SO o que esta livre. Nenhum nome de cliente, nenhum
                    # horario ocupado, nem por omissao: a lista de livres nao
                    # deixa deduzir quem esta marcado, so que aquele instante
                    # nao esta disponivel — e isso o cliente ja saberia ao
                    # tentar (9.1).
                    "slots": [
                        {
                            "hora": formatar_hora(s.inicio),
                            "inicio": s.inicio,
                            "fim": s.fim,
                            "barbeiroId": s.barbeiro_id,
                            "barbeiroNome": nomes.get(s.barbeiro_id, ""),
                            "duracaoMin": round((s.fim - s.inicio).total_seconds() / 60),
                        }
                        for s in slots
                    ],
                }
            )
        return saida


def dias_com_vaga(
    barbearia_id: str, barbeiro_id: str, servico_id: str, mes: str, agora: datetime
) -> list[int]:
    """Quais DIAS do mes tem ao menos um horario — alimenta o mini-calendario.

    Devolve so o numero do dia. A tela nao precisa dos horarios aqui, e mandar
    o mes inteiro com os slots seria trocar um payload de trinta numeros por um
    de milhares de objetos que ninguem le.

    O laco para no primeiro slot de cada dia? Nao — `_slots_do_dia` calcula o
    dia inteiro. Vale anotar como a otimizacao obvia caso o calendario fique
    lento, mas ela mudaria o motor, que hoje serve as duas rotas igual.
    """
    ano, m = (int(p) for p in mes.split("-"))
    # `monthrange` em vez do "dia 0 do mes seguinte" que o route.ts usa: o
    # truque do JS existe porque o `Date` nao tem essa pergunta pronta. Aqui
    # tem, e ela ja sabe de ano bissexto.
    ultimo = calendar.monthrange(ano, m)[1]

    with com_barbearia(barbearia_id):
        return [
            d
            for d in range(1, ultimo + 1)
            if _slots_do_dia(barbeiro_id, servico_id, f"{mes}-{d:02d}", agora)
        ]
