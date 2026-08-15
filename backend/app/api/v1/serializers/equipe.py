from rest_framework import serializers

from app.api.v1.serializers.horarios import InstanteISO


class EquipeItemSerializer(serializers.Serializer):
    """Campo por campo, sem espalhar o model: `senhaHash` e
    `conviteTokenHash` nao saem daqui nem por acidente."""

    id = serializers.CharField()
    nome = serializers.CharField()
    whatsapp = serializers.CharField()
    papel = serializers.CharField()
    ativo = serializers.BooleanField()
    desativadoEm = InstanteISO(source="desativado_em")
    temSenha = serializers.BooleanField(source="tem_senha")
    conviteExpirado = serializers.BooleanField(source="convite_expirado")
    servicos = serializers.IntegerField()
    expediente = serializers.IntegerField()
    agendamentosFuturos = serializers.IntegerField(source="agendamentos_futuros")


class CriarBarbeiroSerializer(serializers.Serializer):
    nome = serializers.CharField(min_length=2, max_length=80)
    whatsapp = serializers.CharField()
    papel = serializers.ChoiceField(choices=["DONO", "BARBEIRO"])


class AtualizarBarbeiroSerializer(serializers.Serializer):
    nome = serializers.CharField(min_length=2, max_length=80, required=False)
    whatsapp = serializers.CharField(required=False)
    papel = serializers.ChoiceField(choices=["DONO", "BARBEIRO"], required=False)

    def validate(self, dados):
        if not dados:
            raise serializers.ValidationError("Nada para mudar.")
        return dados
