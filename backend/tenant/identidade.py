import uuid


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
