"""O resumo do painel: quantos cortes cada barbeiro fez, e para quantas
pessoas diferentes, num periodo.

'Corte feito' e' `CONFIRMADO` com `fim <= agora`, e nao 'tudo que esta' na
agenda'. A diferenca aparece dentro do proprio dia: as 14h, o horario das 18h
ja' esta' marcado e ainda nao aconteceu. Contando-o, o numero de hoje comecaria
alto e so' cairia conforme cancelamentos chegassem — um resumo que anda para
tras. Contando so' o que terminou, ele so' cresce, que e' como o dono le.
"""

import re
from datetime import date, datetime

from django.db.models import Count, Q
from django.db.models.functions import TruncDate

from tenant.config import RESUMO_JANELA_MAXIMA_DIAS
from tenant.datas import FUSO, local_para_utc, somar_dias
from tenant.models import Agendamento, Barbeiro
from tenant.rls import com_barbearia

_DIA = re.compile(r"\d{4}-\d{2}-\d{2}")


def periodo_pedido(de: str | None, ate: str | None, hoje: str) -> tuple[str, str]:
    """Normaliza o que chegou na query string. Pura: nao toca banco, e por
    isso da' teste por combinacao sem fixture nenhuma.

    Toda recusa cai no MESMO padrao (o mes corrente) em vez de virar 422. E'
    uma tela de leitura chegada por link: responder 422 para um `de` torto
    troca um numero util por uma tela de erro, e o dono nao tem o que
    consertar — ele nao digitou aquilo, o link digitou.

    Os dois filtros de data sao necessarios e nenhum basta: o regex garante a
    FORMA (o `fromisoformat` do Python 3.11+ tambem aceita `20260101` e
    `2026-W01-1`, que nao e' o contrato desta rota) e o `fromisoformat`
    garante que a data EXISTE — `2026-13-45` passa pelo regex inteiro.
    """
    padrao = (f"{hoje[:7]}-01", hoje)

    if not (de and ate and _DIA.fullmatch(de) and _DIA.fullmatch(ate)):
        return padrao
    try:
        d, a = date.fromisoformat(de), date.fromisoformat(ate)
    except ValueError:
        return padrao
    if d > a or (a - d).days + 1 > RESUMO_JANELA_MAXIMA_DIAS:
        return padrao
    return de, ate


def cortes_por_barbeiro(barbearia_id, de: str, ate: str, agora: datetime) -> dict:
    """Uma linha por barbeiro, mais os totais da barbearia.

    Sao TRES consultas, e nao uma, de proposito. A versao de uma consulta
    (`Barbeiro.objects.filter(Q(ativo=True) | Q(agendamentos__...))
    .annotate(Count("agendamentos", filter=...))`) filtra e anota sobre a
    MESMA relacao, e o ORM emite dois JOINs sobre `tenant_agendamento`: a
    contagem sai multiplicada. O sintoma e' o pior possivel numa tela de
    numero — plausivel, e errado. Separar tira o join ambiguo do caminho; as
    tres cabem na mesma transacao e nenhuma delas cresce com o tamanho da
    equipe.

    `ate` e' INCLUSIVO: a janela vai da meia-noite de `de` a' meia-noite do
    dia seguinte a `ate`, meio-aberta. Um resumo em que pedir 01 a 05
    devolvesse ate' o dia 04 seria descoberto tarde e por um numero que nao
    fecha com o caixa.
    """
    abre = local_para_utc(de, 0)
    fecha = local_para_utc(somar_dias(ate, 1), 0)

    feitos = dict(
        status="CONFIRMADO", inicio__gte=abre, inicio__lt=fecha, fim__lte=agora,
    )

    with com_barbearia(barbearia_id):
        # Ativo, OU inativo que atendeu na janela. A segunda metade e' a mesma
        # regra do quadro do dia (`app/services/agenda.py`): desligar um
        # barbeiro exige agenda futura vazia, mas o passado continua la' — sem
        # ela, o resumo de um mes fechado encolheria toda vez que alguem
        # saisse da equipe.
        barbeiros = list(
            Barbeiro.objects.filter(
                Q(ativo=True)
                | Q(
                    agendamentos__status="CONFIRMADO",
                    agendamentos__inicio__gte=abre,
                    agendamentos__inicio__lt=fecha,
                    agendamentos__fim__lte=agora,
                )
            )
            .distinct()
            .order_by("ordem", "criado_em")
            .values("id", "nome", "ativo")
        )

        contagem = {
            r["barbeiro_id"]: r
            for r in Agendamento.objects.filter(**feitos)
            .values("barbeiro_id")
            .annotate(cortes=Count("id"), clientes=Count("cliente_id", distinct=True))
        }

        # `clientes` aqui e' distinto na BARBEARIA, e nao a soma das linhas:
        # quem cortou com dois barbeiros e' uma pessoa so'. Por isso a soma
        # das linhas pode passar do total — e' aritmetica certa de conjunto,
        # e a tela rotula em vez de esconder.
        totais = Agendamento.objects.filter(**feitos).aggregate(
            cortes=Count("id"), clientes=Count("cliente_id", distinct=True),
        )

    return {
        "de": de,
        "ate": ate,
        "linhas": [
            {
                # `str(...)`, e nao o UUID cru: quem cria o barbeiro num teste
                # (`Barbeiro(id=str(uuid.uuid4()))`) guarda o id como STRING no
                # objeto Python ate' ele voltar do banco — o `create()` nao
                # normaliza. Devolver o UUID cru aqui faria a comparacao do
                # teste falhar por TIPO (`UUID != str`), nunca por valor. Nao
                # custa nada na tela: JSON nao tem tipo UUID, os dois viram o
                # mesmo texto.
                "barbeiroId": str(b["id"]),
                "barbeiroNome": b["nome"],
                "ativo": b["ativo"],
                "cortes": contagem.get(b["id"], {}).get("cortes", 0),
                "clientes": contagem.get(b["id"], {}).get("clientes", 0),
            }
            for b in barbeiros
        ],
        # Isto e' `Count`, que devolve 0 (nao None) em queryset vazio — o
        # `or 0` aqui e' rede morta, nao correcao de um `null` de verdade.
        # Fica como defesa caso a agregacao ganhe um `Sum`/`Avg` um dia: esses,
        # sim, devolvem None sem linha nenhuma para agregar.
        "totais": {"cortes": totais["cortes"] or 0, "clientes": totais["clientes"] or 0},
    }


def serie_por_dia(barbearia_id, de: str, ate: str, agora: datetime, barbeiro_id=None) -> list[dict]:
    """Cortes por DIA no periodo — a barbearia inteira, ou um barbeiro so'.

    Existe para a pergunta que a divisao entre barbeiros nao responde: "como
    esta indo", ao longo do tempo. A pizza diz que fatia e' de quem; isto diz
    se a semana passada foi melhor que a retrasada. E funciona onde a pizza se
    apaga — numa barbearia de um barbeiro so', que e' a maioria delas.

    `TruncDate` COM `tzinfo=FUSO`, e essa e' a linha inteira do bug que ela
    evita: sem o fuso o Postgres agrupa por dia UTC, e America/Sao_Paulo esta'
    3h atras. Todo corte a partir das 21h cairia no dia SEGUINTE — o sabado a
    noite, que e' o horario mais cheio de barbearia, apareceria no domingo. O
    numero fecharia no total e estaria errado em cada barra.

    Devolve so' os dias que TEM corte. Preencher os vazios e' da tela, que ja'
    sabe somar dias (`lib/datas.ts`) e e' quem decide se um dia sem movimento
    vira barra zero ou buraco.
    """
    abre = local_para_utc(de, 0)
    fecha = local_para_utc(somar_dias(ate, 1), 0)

    filtro = dict(status="CONFIRMADO", inicio__gte=abre, inicio__lt=fecha, fim__lte=agora)
    if barbeiro_id:
        filtro["barbeiro_id"] = barbeiro_id

    with com_barbearia(barbearia_id):
        linhas = (
            Agendamento.objects.filter(**filtro)
            .annotate(dia=TruncDate("inicio", tzinfo=FUSO))
            .values("dia")
            .annotate(cortes=Count("id"), clientes=Count("cliente_id", distinct=True))
            .order_by("dia")
        )
        return [
            {"dia": r["dia"].isoformat(), "cortes": r["cortes"], "clientes": r["clientes"]}
            for r in linhas
        ]
