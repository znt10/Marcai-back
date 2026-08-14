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
