import re

# Porte de front/src/lib/telefone.ts. Fica em `tenant` e nao em `app/services`
# pelo mesmo motivo que `slug.py` fica: e regra pura de formato, sem banco e
# sem HTTP, e quem a usa hoje (o login) nao e quem vai usa-la amanha (o
# cadastro da equipe, o disparo do WhatsApp).

_NAO_DIGITO = re.compile(r"\D")


def normalizar(entrada: str | None) -> str | None:
    """Devolve os 10 ou 11 digitos nacionais, ou None se nao puder ser um
    telefone brasileiro. O None e o contrato: quem chama decide a mensagem.

    No login isso importa mais do que parece. O numero digitado com +55, com
    espaco ou com parentese tem que cair no MESMO valor que esta gravado, ou
    o barbeiro erra a senha sem ter errado a senha — e, pior, cada tentativa
    dessas conta para a trava de 5.
    """
    d = _NAO_DIGITO.sub("", entrada or "")
    if len(d) == 13 and d.startswith("55"):
        d = d[2:]
    if len(d) == 12 and d.startswith("55"):
        d = d[2:]
    if len(d) not in (10, 11):
        return None
    ddd = int(d[:2])
    if ddd < 11 or ddd > 99:
        return None
    # 11 digitos so existe com o 9 na frente do numero; sem isso e um fixo com
    # um digito sobrando.
    if len(d) == 11 and d[2] != "9":
        return None
    return d


def formatar(digitos: str) -> str:
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2]} {digitos[3:7]}-{digitos[7:]}"
    return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"


# Os DDDs que existem de verdade. `normalizar` aceita a faixa 11..99 inteira,
# que inclui 89 numeros e so' 67 sao DDD — 20, 23, 25, 26, 29, 30, 60, 70, 72,
# 76, 78 e 90 nao existem, e sao justamente os erros de digitacao mais comuns
# (21 virando 20, 83 virando 30).
#
# Lista fechada e nao regra: nao ha formula. A Anatel ja criou DDD novo (o 66
# saiu do 65 em 2000) e pode criar outro; quando criar, e' esta linha que muda.
DDDS = frozenset({
    11, 12, 13, 14, 15, 16, 17, 18, 19,          # SP
    21, 22, 24,                                   # RJ
    27, 28,                                       # ES
    31, 32, 33, 34, 35, 37, 38,                   # MG
    41, 42, 43, 44, 45, 46,                       # PR
    47, 48, 49,                                   # SC
    51, 53, 54, 55,                               # RS
    61,                                           # DF/GO
    62, 64,                                       # GO
    63,                                           # TO
    65, 66,                                       # MT
    67,                                           # MS
    68,                                           # AC
    69,                                           # RO
    71, 73, 74, 75, 77,                           # BA
    79,                                           # SE
    81, 87,                                       # PE
    82,                                           # AL
    83,                                           # PB
    84,                                           # RN
    85, 88,                                       # CE
    86, 89,                                       # PI
    91, 93, 94,                                   # PA
    92, 97,                                       # AM
    95,                                           # RR
    96,                                           # AP
    98, 99,                                       # MA
})


def celular(entrada: str | None) -> str | None:
    """Os 11 digitos de um CELULAR brasileiro, ou None.

    Mais estrita que `normalizar`, e de proposito — sao duas perguntas
    diferentes. `normalizar` responde "isto pode ser um telefone?", e serve ao
    login e ao cadastro da equipe, onde um fixo e' contato legitimo. Esta
    responde "isto pode ter WhatsApp?", e serve ao agendamento publico, onde o
    produto inteiro depende de mandar mensagem: confirmacao, lembrete, link de
    cancelar. Fixo nunca tem WhatsApp, entao um agendamento com fixo nasce sem
    nenhum dos tres — e ninguem descobre ate' o cliente nao aparecer.

    Vale a pena por si so', sem o oraculo da Evolution: isto pega o erro de
    digitacao SEM chamada de rede, sem depender de servico externo estar de pe
    e sem gastar consulta do limite por IP.
    """
    d = normalizar(entrada)
    if d is None or len(d) != 11:
        return None
    if int(d[:2]) not in DDDS:
        return None
    return d
