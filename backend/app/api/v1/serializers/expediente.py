from rest_framework import serializers

from app.api.v1.serializers.horarios import InstanteISO


# ---------------------------------------------------------------- saida


class HorarioSerializer(serializers.Serializer):
    diaSemana = serializers.IntegerField(source="dia_semana")
    minutosInicio = serializers.IntegerField(source="minutos_inicio")
    minutosFim = serializers.IntegerField(source="minutos_fim")


class BloqueioSerializer(serializers.Serializer):
    id = serializers.CharField()
    motivo = serializers.CharField()
    observacao = serializers.CharField()
    repeteSemanalmente = serializers.BooleanField(source="repete_semanalmente")
    diaSemana = serializers.IntegerField(source="dia_semana")
    minutosInicio = serializers.IntegerField(source="minutos_inicio")
    minutosFim = serializers.IntegerField(source="minutos_fim")
    inicio = InstanteISO()
    fim = InstanteISO()


# ---------------------------------------------------------------- entrada


class DefinirHorarioSerializer(serializers.Serializer):
    barbeiroId = serializers.CharField(required=False, allow_null=True)
    diaSemana = serializers.IntegerField()
    # FloatField, e nao IntegerField: o zod do front so exige `z.number()`
    # aqui (nao `.int()`) — quem recusa nao-inteiro e' `jornada_valida`, com
    # a mensagem "Horário fora do dia.", nao a validacao generica de corpo.
    minutosInicio = serializers.FloatField()
    minutosFim = serializers.FloatField()


class CriarBloqueioSerializer(serializers.Serializer):
    barbeiroId = serializers.CharField(required=False, allow_null=True)
    motivo = serializers.ChoiceField(choices=["ALMOCO", "FOLGA", "PESSOAL", "OUTRO"])
    observacao = serializers.CharField(
        max_length=200, required=False, allow_null=True, allow_blank=True,
    )
    repeteSemanalmente = serializers.BooleanField()
    diaSemana = serializers.IntegerField(required=False, allow_null=True)
    minutosInicio = serializers.FloatField(required=False, allow_null=True)
    minutosFim = serializers.FloatField(required=False, allow_null=True)
    inicio = serializers.DateTimeField(required=False, allow_null=True)
    fim = serializers.DateTimeField(required=False, allow_null=True)
