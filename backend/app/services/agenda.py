import calendar
from datetime import datetime

from django.db.models import Q, F

from tenant.config import DIAS_NA_HOME, JANELA_MAXIMA_DIAS
from tenant.datas import (
    como_utc,
    dia_de_hoje,
    dia_semana_de,
    formatar_dia_longo,
    formatar_hora,
    formatar_instante_iso,
    local_para_utc,
    somar_dias,
)
from tenant.models import Agendamento, Barbeiro, BarbeiroServico, Bloqueio, HorarioTrabalho
from tenant.rls import com_barbearia

from .quadro import ocupacao_pct
from .servicos import QUALQUER
from .slots import Slot, bloqueios_do_dia, slots_livres, unir_slots


def slots_do_dia(barbeiro_id: str, servico_id: str, dia: str, agora: datetime) -> list[Slot]:
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
            slots = slots_do_dia(barbeiro_id, servico_id, dia, agora)
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

    O laco para no primeiro slot de cada dia? Nao — `slots_do_dia` calcula o
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
            if slots_do_dia(barbeiro_id, servico_id, f"{mes}-{d:02d}", agora)
        ]


# ---------------------------------------------------------------- painel


def agenda_do_dia(barbearia_id: str, dia: str, barbeiro_id: str | None) -> list[dict]:
    """GET /painel/agenda — os agendamentos CONFIRMADOS do dia, opcionalmente
    filtrados por barbeiro."""
    abre = local_para_utc(dia, 0)
    fecha = local_para_utc(somar_dias(dia, 1), 0)

    with com_barbearia(barbearia_id):
        qs = Agendamento.objects.filter(status="CONFIRMADO", inicio__gte=abre, inicio__lt=fecha)
        if barbeiro_id:
            qs = qs.filter(barbeiro_id=barbeiro_id)
        linhas = list(
            qs.order_by("inicio").values(
                "id", "inicio", "fim", "servico_nome", "barbeiro_id",
                "barbeiro__nome", "cliente__nome", "cliente__whatsapp",
            )
        )

    return [
        {
            "id": a["id"],
            "inicio": formatar_instante_iso(a["inicio"]),
            "fim": formatar_instante_iso(a["fim"]),
            "servicoNome": a["servico_nome"],
            "barbeiroId": a["barbeiro_id"],
            "barbeiroNome": a["barbeiro__nome"],
            "clienteNome": a["cliente__nome"],
            "clienteWhatsapp": a["cliente__whatsapp"],
        }
        for a in linhas
    ]


def quadro_do_dia(barbearia_id: str, dia: str, barbeiro_id: str | None, agora: datetime) -> list[dict]:
    """GET /painel/dia — uma coluna por barbeiro, lado a lado.

    NAO reusa `slots_do_dia` (que exige vinculo de servico): aqui o
    barbeiro aparece mesmo sem nenhum vinculo — quem decide se ha algo
    ofertavel e' o `servico_mais_curto` que ele pratica, e a coluna precisa
    dizer 'sem servico marcado' em vez de sumir."""
    dia_semana = dia_semana_de(dia)
    abre = local_para_utc(dia, 0)
    fecha = local_para_utc(somar_dias(dia, 1), 0)

    with com_barbearia(barbearia_id):
        # Ativo, ou inativo com agendamento nesse dia: desativar exige agenda
        # futura vazia, mas o passado continua la — sem a segunda metade, o
        # quadro de um dia antigo mostraria menos clientes do que teve.
        barbeiros_qs = Barbeiro.objects.filter(
            Q(ativo=True)
            | Q(
                agendamentos__status="CONFIRMADO",
                agendamentos__inicio__lt=fecha,
                agendamentos__fim__gt=abre,
            )
        ).distinct()
        if barbeiro_id:
            barbeiros_qs = barbeiros_qs.filter(id=barbeiro_id)
        barbeiros = list(
            # `papel` vem da IDENTIDADE desde a fatia 2 — o quadro do dia
            # mostra quem e' dono para pintar a coluna, e o campo mudou de
            # tabela, nao de significado.
            barbeiros_qs.order_by("ordem", "criado_em")
            .values("id", "nome", "ativo", papel=F("usuario__papel"))
        )
        if not barbeiros:
            return []

        ids = [b["id"] for b in barbeiros]
        expedientes = list(
            HorarioTrabalho.objects.filter(barbeiro_id__in=ids, dia_semana=dia_semana)
        )
        bloqueios = list(Bloqueio.objects.filter(barbeiro_id__in=ids))
        # Cruzar a janela, e nao comecar dentro dela: um corte que atravessa
        # a meia-noite pertence aos dois dias.
        agendamentos = list(
            Agendamento.objects.filter(
                barbeiro_id__in=ids, status="CONFIRMADO", inicio__lt=fecha, fim__gt=abre,
            )
            .select_related("cliente")
            .order_by("inicio")
        )
        vinculos = list(
            BarbeiroServico.objects.filter(
                barbeiro_id__in=ids, ativo=True, servico__ativo=True,
            ).values("barbeiro_id", "duracao_min", "servico__nome", "servico__ordem")
        )

    colunas = []
    for b in barbeiros:
        meus_agendamentos = [a for a in agendamentos if a.barbeiro_id == b["id"]]
        meus_bloqueios = [x for x in bloqueios if x.barbeiro_id == b["id"]]
        jornada = next((h for h in expedientes if h.barbeiro_id == b["id"]), None)
        bloqueados_do_dia = bloqueios_do_dia(meus_bloqueios, dia, dia_semana)

        itens = [
            {
                "tipo": "AGENDAMENTO", "id": a.id,
                "inicio": formatar_instante_iso(a.inicio), "fim": formatar_instante_iso(a.fim),
                "servicoNome": a.servico_nome,
                "clienteNome": a.cliente.nome, "clienteWhatsapp": a.cliente.whatsapp,
            }
            for a in meus_agendamentos
        ]
        for x in meus_bloqueios:
            # O semanal chega traduzido em INSTANTE: a tela nao ve
            # `minutosInicio` nem `repeteSemanalmente`. Traduzir recorrencia
            # e' do servidor.
            traduzidos = bloqueios_do_dia([x], dia, dia_semana)
            if traduzidos:
                inicio_x, fim_x = traduzidos[0]
                itens.append(
                    {
                        "tipo": "BLOQUEIO", "id": x.id,
                        "inicio": formatar_instante_iso(inicio_x),
                        "fim": formatar_instante_iso(fim_x),
                        "motivo": x.motivo, "observacao": x.observacao,
                    }
                )
        itens.sort(key=lambda i: i["inicio"])

        # O servico MAIS CURTO que ele pratica: e' a resposta a "cabe alguma
        # coisa?", a pergunta do balcao. Otimista de proposito — por isso o
        # horario nunca sai sozinho, sempre com o servico que o justifica.
        meus_servicos = sorted(
            (v for v in vinculos if v["barbeiro_id"] == b["id"]),
            key=lambda v: (v["duracao_min"], v["servico__ordem"]),
        )
        mais_curto = meus_servicos[0] if meus_servicos else None

        livres = []
        if mais_curto and jornada:
            livres = slots_livres(
                barbeiro_id=b["id"], duracao_min=mais_curto["duracao_min"],
                expediente=[jornada], bloqueios=meus_bloqueios,
                agendamentos=meus_agendamentos, dia=dia, agora=agora,
            )

        janela = (
            (local_para_utc(dia, jornada.minutos_inicio), local_para_utc(dia, jornada.minutos_fim))
            if jornada else None
        )

        colunas.append(
            {
                "barbeiroId": b["id"], "barbeiroNome": b["nome"], "papel": b["papel"],
                "ativo": b["ativo"],
                "abre": jornada.minutos_inicio if jornada else None,
                "fecha": jornada.minutos_fim if jornada else None,
                "ocupacaoPct": (
                    ocupacao_pct(
                        [(como_utc(a.inicio), como_utc(a.fim)) for a in meus_agendamentos],
                        bloqueados_do_dia, janela,
                    )
                    if janela else None
                ),
                # Vem mesmo sem horario livre — e' o que separa dois estados
                # que a tela precisa distinguir porque pedem acoes opostas:
                # nulo aqui E' `servico_mais_curto` nulo e' "nao marcou
                # servico nenhum"; presente com `proximo_livre` nulo e'
                # "esta cheio".
                "proximoLivre": formatar_instante_iso(livres[0].inicio) if livres else None,
                "servicoMaisCurto": mais_curto["servico__nome"] if mais_curto else None,
                "itens": itens,
            }
        )
    return colunas
