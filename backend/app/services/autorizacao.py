"""Porte fiel de front/src/lib/autorizacao.ts + front/src/lib/alcance.ts —
funcoes PURAS, sem banco e sem HTTP, porque sao o unico lugar que decide "o
barbeiro so ve o que e dele" e precisam de teste exaustivo por combinacao.

Por que isto nao vira RLS, sendo que o tenant virou: a area publica precisa
ler a ocupacao de TODOS os barbeiros para calcular horario livre. Uma
politica que restringisse ao proprio barbeiro quebraria o fluxo do cliente.
Tenant no banco, barbeiro na aplicacao — a mesma divisao do lado Next.
"""

from tenant.identidade import como_uuid


def filtro_do_barbeiro(sessao: dict) -> dict:
    """`{}` para o dono (ve tudo), `{"barbeiro_id": ...}` para o barbeiro (ve
    so o dele). O UNICO lugar onde esse filtro nasce — nenhuma consulta do
    painel deve monta-lo por fora.

    Le `sessao["barbeiro_id"]`, e nao `sessao["sub"]`, desde a fatia 3: o `sub`
    passou a ser o id do USUARIO, e agenda/bloqueio/conflito referenciam o
    PERFIL. Trocar um pelo outro nao daria erro nenhum — os dois sao uuid — e
    o filtro simplesmente nao casaria com linha alguma: o barbeiro veria a
    agenda vazia e concluiria que perdeu os agendamentos.
    """
    return {} if sessao["papel"] == "DONO" else {"barbeiro_id": sessao["barbeiro_id"]}


def alvo_do_barbeiro(sessao: dict, pedido: str | None):
    """Alcance das rotas de horario/servico: dono mexe no de todos, barbeiro
    so no seu. Devolve None quando o barbeiro pede o id de um colega — a
    rota responde 404 (registro alheio, o status nao pode confirmar que
    existe).

    `pedido` chega da query como TEXTO e `sessao["sub"]` e' `uuid.UUID` desde a
    fatia 1, entao a conversao tem de acontecer antes da comparacao: sem ela os
    dois nunca sao iguais e TODO barbeiro passa a receber 404 no proprio
    registro — a rota fica "certa demais", recusando ate quem tem direito.

    Um `pedido` com forma impossivel recebe o mesmo None de um id de colega, e
    de proposito: distinguir os dois contaria a quem chuta ids qual das duas
    coisas aconteceu. Note que ele NAO pode cair no `or sessao["sub"]` do ramo
    do dono — isso trocaria "voce pediu algo que nao existe" por "aqui esta o
    seu", devolvendo dado que ninguem pediu.
    """
    alvo = como_uuid(pedido)
    if pedido and alvo is None:
        return None

    eu = sessao["barbeiro_id"]
    filtro = filtro_do_barbeiro(sessao)
    if "barbeiro_id" not in filtro:
        return alvo or eu  # dono
    if alvo and alvo != eu:
        return None  # barbeiro pedindo o do colega
    return eu
