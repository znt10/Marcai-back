from rest_framework import serializers


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
