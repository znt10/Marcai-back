from rest_framework import serializers


class CriarAgendamentoSerializer(serializers.Serializer):
    barbeiroId = serializers.CharField()
    servicoId = serializers.CharField()
    inicio = serializers.DateTimeField()
    nome = serializers.CharField(min_length=2, max_length=80)
    whatsapp = serializers.CharField()
