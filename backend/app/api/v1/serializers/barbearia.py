from rest_framework import serializers


class AtualizarBarbeariaSerializer(serializers.Serializer):
    horarioResumo = serializers.CharField(min_length=3, max_length=120)
