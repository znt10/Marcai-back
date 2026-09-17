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


_SUFIXO_DE_PESSOA = "@s.whatsapp.net"


def do_jid(jid: str | None) -> str | None:
    """O numero de quem escreveu, na MESMA forma de `Cliente.whatsapp`.

    O WhatsApp guarda celular brasileiro antigo SEM o nono digito
    (`558382217869`, medido na fatia 0). Sem recolocar o 9, `normalizar`
    devolveria um fixo de 10 digitos e o bot nunca acharia o cliente que ja
    marcou pela vitrine.

    Celular e' o assinante que comeca de 6 a 9; fixo comeca de 2 a 5 e fica
    como esta. Grupo, `@lid` e numero de fora do Brasil viram `None` — quem
    chama descarta.
    """
    if not isinstance(jid, str) or not jid.endswith(_SUFIXO_DE_PESSOA):
        return None
    digitos = jid[: -len(_SUFIXO_DE_PESSOA)]
    if not digitos.isdigit() or not digitos.startswith("55"):
        return None
    return normalizar(nacional_canonico(digitos[2:]))


_INICIO_DE_CELULAR = "6789"


def nacional_canonico(nacional: str) -> str:
    """A forma de 11 digitos de um numero nacional: celular de 10 digitos
    (assinante comecando de 6 a 9) ganha o nono digito; o resto volta como
    veio. Pura — nao valida, quem chama ja tem digitos."""
    if len(nacional) == 10 and nacional[2] in _INICIO_DE_CELULAR:
        return f"{nacional[:2]}9{nacional[2:]}"
    return nacional


def formas_gravadas(numero: str) -> list[str]:
    """As formas em que o MESMO celular pode estar em `Cliente.whatsapp`.

    `normalizar` aceita o celular sem o nono digito, entao a vitrine pode ter
    gravado `8382217869` enquanto o WhatsApp entrega `83982217869`. Sem
    migracao de dados: quem busca cliente pelo numero procura as duas. A
    canonica vem primeiro. Tirar o 9 de `83912345678` daria um fixo — outra
    pessoa —, entao so' ha segunda forma quando ela voltaria a este numero.
    """
    canonico = nacional_canonico(numero)
    if len(canonico) == 11 and canonico[2] == "9" and canonico[3] in _INICIO_DE_CELULAR:
        return [canonico, f"{canonico[:2]}{canonico[3:]}"]
    return [canonico]


def formatar(digitos: str) -> str:
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2]} {digitos[3:7]}-{digitos[7:]}"
    return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
