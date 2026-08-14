from rest_framework import serializers


class BarbeiroPublicoSerializer(serializers.Serializer):
    """LISTA BRANCA, e e por isso que nao e um ModelSerializer.

    `Barbeiro` carrega `senhaHash`, `whatsapp`, `conviteTokenHash` e
    `tokenVersion`. Um ModelSerializer com `exclude` publicaria cada coluna
    nova por padrao — bastaria o Prisma ganhar um campo para ele vazar sem
    ninguem escrever uma linha. Declarar os tres campos inverte isso: o que
    nao esta escrito aqui nao sai (§9.1).

    `foto_url` -> `fotoUrl` porque quem consome e o front, e la o contrato ja
    e camelCase. A traducao mora aqui e nao na view.
    """

    id = serializers.CharField()
    nome = serializers.CharField()
    fotoUrl = serializers.CharField(source="foto_url", allow_null=True)
