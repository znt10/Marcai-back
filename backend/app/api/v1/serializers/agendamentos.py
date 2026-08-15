from rest_framework import serializers

from app.api.v1.serializers.horarios import InstanteISO


class CriarAgendamentoSerializer(serializers.Serializer):
    """Serve as DUAS rotas que criam agendamento — a do painel
    (`AgendamentosPainelView`) e a publica (`AgendamentosView`, bloco C da
    travessia): o corpo que o cliente manda e o que o barbeiro digita no
    balcao tem exatamente a mesma forma."""

    barbeiroId = serializers.CharField()
    servicoId = serializers.CharField()
    inicio = serializers.DateTimeField()
    nome = serializers.CharField(min_length=2, max_length=80)
    whatsapp = serializers.CharField()


class AgendamentoDetalheSerializer(serializers.Serializer):
    """GET /api/agendamentos/<codigo>. `endereco`/`whatsappBarbearia` chegam
    ja' misturados no dict que a view monta (vem de `request.barbearia`, nao
    do agendamento) — lista branca pelo mesmo motivo do resto: so' o que a
    tela publica precisa sai, o WhatsApp do CLIENTE nunca (§9.1)."""

    codigo = serializers.CharField()
    clienteNome = serializers.CharField(source="cliente_nome")
    barbeiroNome = serializers.CharField(source="barbeiro_nome")
    servicoNome = serializers.CharField(source="servico_nome")
    duracaoMin = serializers.IntegerField(source="duracao_min")
    inicio = InstanteISO()
    fim = InstanteISO()
    status = serializers.CharField()
    podeCancelar = serializers.BooleanField(source="pode_cancelar")
    endereco = serializers.CharField()
    whatsappBarbearia = serializers.CharField(source="whatsapp_barbearia")
