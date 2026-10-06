from rest_framework import serializers

from tenant.config import DURACAO_MINIMA_MIN, DURACAO_PADRAO_MIN


class ServicoParaAgendamentoSerializer(serializers.Serializer):
    """Tres campos, e a lista branca vale aqui pelo mesmo motivo de sempre —
    mas com uma ausencia que merece nome: `ordem` NAO sai.

    Ela e a chave de ordenacao e ja fez o seu trabalho antes de chegar aqui; a
    tela recebe a lista na ordem certa e nao tem o que fazer com o numero. Um
    ModelSerializer a publicaria junto, e o front acabaria reordenando por
    conta propria — duas ordenacoes, uma em cada lado, e nenhuma dona.

    Os `source` traduzem o resultado do GROUP BY (`servico_id`,
    `servico__nome`, `duracao`) para o contrato camelCase que a tela ja le.
    """

    id = serializers.CharField(source="servico_id")
    nome = serializers.CharField(source="servico__nome")
    duracaoMin = serializers.IntegerField(source="duracao")
    # Nulo quando NINGUEM que faz este servico definiu preco ainda — o menor
    # preco entre quem faz, mesmo raciocinio do `duracaoMin` acima (ver
    # `listar_para_agendamento`).
    precoCentavos = serializers.IntegerField(source="preco", allow_null=True)


# ---------------------------------------------------------------- painel


class ServicoPainelSerializer(serializers.Serializer):
    """O catalogo inteiro, ativo e inativo — ao contrario do serializer
    publico acima, aqui a `ordem` sai (a tela reordena por arrasto)."""

    id = serializers.CharField()
    nome = serializers.CharField()
    ativo = serializers.BooleanField()
    ordem = serializers.IntegerField()
    duracaoMinimaMin = serializers.IntegerField(source="duracao_minima_min")
    duracaoSugeridaMin = serializers.IntegerField(source="duracao_sugerida_min")
    barbeiros = serializers.IntegerField()


class CriarServicoSerializer(serializers.Serializer):
    """So' o nome e' obrigatorio: a tela deixou de pedir as duracoes
    (06/10/2026), e o tempo passou a ser de cada barbeiro. Elas continuam
    aceitas, e conferidas, para quem ainda as mande."""

    nome = serializers.CharField(min_length=2, max_length=40)
    duracaoMinimaMin = serializers.IntegerField(default=DURACAO_MINIMA_MIN)
    duracaoSugeridaMin = serializers.IntegerField(default=DURACAO_PADRAO_MIN)


class AtualizarServicoSerializer(serializers.Serializer):
    nome = serializers.CharField(min_length=2, max_length=40, required=False)
    duracaoMinimaMin = serializers.IntegerField(required=False)
    duracaoSugeridaMin = serializers.IntegerField(required=False)
    ordem = serializers.IntegerField(required=False)
    ativo = serializers.BooleanField(required=False)

    def validate(self, dados):
        if not dados:
            raise serializers.ValidationError("Nada para mudar.")
        return dados


class BarbeiroServicoPainelSerializer(serializers.Serializer):
    servicoId = serializers.CharField(source="servico_id")
    nome = serializers.CharField()
    duracaoMinimaMin = serializers.IntegerField(source="duracao_minima_min")
    faz = serializers.BooleanField()
    duracaoMin = serializers.IntegerField(source="duracao_min")
    precoCentavos = serializers.IntegerField(source="preco_centavos", allow_null=True)


class DefinirVinculoSerializer(serializers.Serializer):
    barbeiroId = serializers.CharField(required=False, allow_null=True)
    servicoId = serializers.CharField()
    faz = serializers.BooleanField()
    duracaoMin = serializers.IntegerField(required=False, allow_null=True)
    precoCentavos = serializers.IntegerField(required=False, allow_null=True)
