import re
import unicodedata
import uuid

from tenant.telefone import normalizar as normalizar_telefone

# Digitos e a pontuacao com que se escreve telefone: espaco, +, (), - e ponto.
# Serve so' para DECIDIR o ramo; quem valida de verdade e' telefone.normalizar.
_PARECE_TELEFONE = re.compile(r"[0-9+()\-.\s]+")


def como_uuid(valor) -> uuid.UUID | None:
    """Converte um id que veio DE FORA para `uuid.UUID`, ou `None` se ele nao
    tiver forma de uuid.

    Existe por causa da fatia 1. Enquanto as colunas de id eram TEXT, um id
    malformado vindo da URL, da query ou do corpo (`?barbeiroId=nao-existe`)
    era so' uma string que nao casava com linha nenhuma: o `filter()` devolvia
    vazio e a rota respondia o 404 — ou a lista vazia — que ela ja tinha
    escrito. Com a coluna sendo `uuid`, o mesmo valor faz o Django levantar
    `ValidationError` ao preparar o parametro, e o que era 404 vira 500.

    `None` e o valor de retorno certo, e nao uma excecao, porque "nao tem forma
    de uuid" e "nao existe" merecem a MESMA resposta: um id impossivel nao pode
    ser distinguivel de um id que so' nao esta la. Distinguir os dois contaria a
    quem chuta ids qual das duas coisas aconteceu — que e' exatamente o que o
    docstring de `test_barbeiro_inexistente_devolve_lista_vazia_e_nao_erro` diz
    ao recusar 404 em favor de lista vazia.

    Aceita `uuid.UUID` de volta sem mexer, para poder ser chamada em cima de um
    valor que ja passou por aqui.
    """
    if isinstance(valor, uuid.UUID):
        return valor
    if not valor:
        return None
    try:
        return uuid.UUID(str(valor))
    except (ValueError, AttributeError, TypeError):
        return None


def normalizar_login(bruto: str | None) -> str | None:
    """Reduz um login digitado a UMA forma canonica, escolhida pelo FORMATO do
    proprio valor. Devolve None quando nao sobra nada.

    Os tres papeis fazem login por coisas diferentes — o admin da plataforma
    por um nome de usuario, o dono por email, o barbeiro pelo whatsapp — e a
    coluna e uma so'. Sem canonizar, o mesmo humano teria varios logins
    possiveis e nenhum deles seria "o" login: `" Joao@X.com "` e `joao@x.com`
    virariam duas linhas, e o `unique` nao veria conflito nenhum.

    No login isso custa mais do que parece, e o motivo esta no docstring de
    `telefone.normalizar`: quem digita o numero com parentese ou +55 erra a
    senha sem ter errado a senha — e cada tentativa dessas conta para a trava
    de 5. A mesma armadilha vale para o email com maiuscula.

    A forma decide a regra:

    - tem `@`  -> email: `strip`, `lower` e SEM acento, para que
      `" Joao@X.com "` e `joao@x.com` sejam a mesma conta. O lado local de um
      email e' tecnicamente sensivel a caixa (RFC 5321) e pode carregar
      acento (SMTPUTF8), mas nenhum provedor brasileiro de verdade emite
      endereco assim — e tratar as duas formas como contas diferentes
      trancaria o dono para fora por ter digitado o proprio nome como ele se
      escreve. O preco, explicito: `joão@x.com` e `joao@x.com` deixam de poder
      coexistir.
    - so' digitos e pontuacao de telefone -> whatsapp: delega para
      `telefone.normalizar`, que ja e a autoridade sobre isso e ja devolve os
      10-11 digitos nacionais.
    - o resto -> usuario do admin: `strip` + `lower`.

    O `@` e conferido ANTES do telefone de proposito: um email nunca casaria a
    regra de telefone, mas a ordem inversa deixaria a intencao dependendo de
    uma coincidencia de formato em vez de estar escrita.
    """
    if bruto is None:
        return None
    valor = bruto.strip()
    if not valor:
        return None

    if "@" in valor:
        return _sem_acento(valor.lower())

    if _PARECE_TELEFONE.fullmatch(valor):
        # None aqui e' um numero que TEM cara de telefone e nao e' um: cai no
        # ramo de baixo em vez de virar login nenhum, porque recusar silencioso
        # transformaria "numero invalido" em "usuario sumiu".
        numero = normalizar_telefone(valor)
        if numero:
            return numero

    return valor.lower()


def _sem_acento(valor: str) -> str:
    """Tira diacritico decompondo (NFKD) e descartando as marcas de combinacao.

    Decompor e' o que faz "ã" virar "a" + til, e so' entao o til pode ser
    jogado fora. Um `replace()` de tabela por letra pareceria equivalente e
    perderia todo caractere que ninguem pensou em listar.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", valor)
        if not unicodedata.combining(c)
    )
