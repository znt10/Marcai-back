"""Porte fiel de front/src/lib/autorizacao.ts + front/src/lib/alcance.ts —
funcoes PURAS, sem banco e sem HTTP, porque sao o unico lugar que decide "o
barbeiro so ve o que e dele" e precisam de teste exaustivo por combinacao.

Por que isto nao vira RLS, sendo que o tenant virou: a area publica precisa
ler a ocupacao de TODOS os barbeiros para calcular horario livre. Uma
politica que restringisse ao proprio barbeiro quebraria o fluxo do cliente.
Tenant no banco, barbeiro na aplicacao — a mesma divisao do lado Next.
"""


def filtro_do_barbeiro(sessao: dict) -> dict:
    """`{}` para o dono (ve tudo), `{"barbeiro_id": sessao["sub"]}` para o
    barbeiro (ve so o dele). O UNICO lugar onde esse filtro nasce — nenhuma
    consulta do painel deve monta-lo por fora."""
    return {} if sessao["papel"] == "DONO" else {"barbeiro_id": sessao["sub"]}


def alvo_do_barbeiro(sessao: dict, pedido: str | None) -> str | None:
    """Alcance das rotas de horario/servico: dono mexe no de todos, barbeiro
    so no seu. Devolve None quando o barbeiro pede o id de um colega — a
    rota responde 404 (registro alheio, o status nao pode confirmar que
    existe)."""
    filtro = filtro_do_barbeiro(sessao)
    if "barbeiro_id" not in filtro:
        return pedido or sessao["sub"]  # dono
    if pedido and pedido != sessao["sub"]:
        return None  # barbeiro pedindo o do colega
    return sessao["sub"]
