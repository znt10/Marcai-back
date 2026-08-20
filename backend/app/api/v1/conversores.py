from tenant.identidade import como_uuid


class IdConverter:
    """Casa qualquer segmento de URL e entrega `uuid.UUID` — ou `None`, quando
    o que veio nao tem forma de uuid.

    O conversor `<uuid:...>` de fabrica do Django resolveria metade do
    problema e estragaria a outra: ele simplesmente NAO CASA um id malformado,
    entao `/api/admin/barbearias/nao-existe/convite` deixa de bater em rota
    nenhuma e vira o 404 seco do Django — sem corpo. As rotas deste projeto
    respondem 404 com `{"erro": ...}` e o front le esse corpo; trocar a
    resposta por uma pagina vazia mudaria contrato durante a travessia, que e
    exatamente o que o router se recusa a fazer em outros pontos.

    Entregando `None`, a view roda como sempre rodou: `filter(id=None)` vira
    `WHERE id IS NULL`, nao acha linha nenhuma, e o caminho de "nao encontrado"
    que cada rota JA TEM escrito responde com a mensagem dela — "Barbearia nao
    encontrada." no admin, `NAO_ENCONTRADO` no painel. Um id impossivel e um id
    inexistente passam a ser indistinguiveis de fora, que e a propriedade que
    essas rotas ja perseguiam de proposito (404 e nunca 403, para o status nao
    confirmar a existencia do registro).

    So para id de MODEL. `codigo` (10 caracteres) e `token` (base64url) seguem
    com `<str:...>`: nenhum dos dois e uuid, e passar por aqui os anularia.
    """

    regex = "[^/]+"

    def to_python(self, value):
        return como_uuid(value)

    def to_url(self, value):
        return str(value)
