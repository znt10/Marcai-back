from rest_framework import serializers


class AtualizarBarbeariaSerializer(serializers.Serializer):
    """So um campo, e sem default: `required=True` (o padrao do DRF) e' o que
    faz corpo sem `ativo`, ou com `ativo` de outro tipo (string, numero),
    cair no mesmo 422 que o `typeof ativo !== 'boolean'` do route.ts."""

    ativo = serializers.BooleanField()
