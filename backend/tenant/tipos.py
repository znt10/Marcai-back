"""As palavras de cada ramo (`TipoNegocio`), do lado do back — so' as que
algum texto do back usa. O front tem a sua tabela, mais completa, em
`src/lib/tipos.ts`; as duas tem de concordar no que repetem.

Tabela e nao `.replace("barbearia", ...)`: o portugues muda o artigo junto
("da barbearia", "do estudio") e o genero de quem atende ("Esse barbeiro esta
desativado", "Essa profissional esta desativada").
"""

from .models import Paleta, TipoNegocio

PALAVRAS = {
    TipoNegocio.BARBEARIA: {
        "o_lugar": "a barbearia",
        # Antes do NOME do estabelecimento. Na barbearia continua o que
        # sempre foi ("da Brutus"); nos outros o nome nao diz o genero
        # ("do Ana Sobrancelhas" estaria errado), entao vai a palavra junto.
        "do_nome": "da {nome}",
        "esse_prof": "Esse barbeiro",
        "desativado": "desativado",
    },
    TipoNegocio.SOBRANCELHA: {
        "o_lugar": "o estúdio",
        "do_nome": "do estúdio {nome}",
        "esse_prof": "Essa profissional",
        "desativado": "desativada",
    },
    TipoNegocio.OUTRO: {
        "o_lugar": "o espaço",
        "do_nome": "do espaço {nome}",
        "esse_prof": "Esse profissional",
        "desativado": "desativado",
    },
}

# A que o admin ve ja' escolhida ao trocar o tipo; ele pode trocar.
PALETA_PADRAO = {
    TipoNegocio.BARBEARIA: Paleta.PRETO_AMARELO,
    TipoNegocio.SOBRANCELHA: Paleta.BRANCO_ROSE,
    TipoNegocio.OUTRO: Paleta.BRANCO_DOURADO,
}


def palavras(tipo) -> dict:
    """Tipo desconhecido (ou None) cai na barbearia: e' o que toda linha
    antiga era."""
    return PALAVRAS.get(tipo, PALAVRAS[TipoNegocio.BARBEARIA])


def do_nome(tipo, nome: str) -> str:
    return palavras(tipo)["do_nome"].format(nome=nome)
