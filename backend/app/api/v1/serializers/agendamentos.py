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


class PixDoAgendamentoSerializer(serializers.Serializer):
    copiaECola = serializers.CharField(source="copia_e_cola")
    qrSvg = serializers.CharField(source="qr_svg")
    valorCentavos = serializers.IntegerField(source="valor_centavos")


class BarbeiroDoAgendamentoSerializer(serializers.Serializer):
    nome = serializers.CharField()
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
    # Snapshot do momento de marcar — nulo quando o barbeiro nao tinha preco
    # definido pra aquele servico naquela hora.
    precoCentavos = serializers.IntegerField(source="preco_centavos", allow_null=True)
    inicio = InstanteISO()
    fim = InstanteISO()
    status = serializers.CharField()
    podeCancelar = serializers.BooleanField(source="pode_cancelar")
    endereco = serializers.CharField()
    whatsappBarbearia = serializers.CharField(source="whatsapp_barbearia")
    # So' no AGUARDANDO_PAGAMENTO com a cobranca aberta; senao null.
    pix = PixDoAgendamentoSerializer(allow_null=True)
    expiraEm = InstanteISO(source="expira_em", allow_null=True)
    # O "fale com" da tela. O numero do barbeiro so' sai aqui, onde o codigo
    # do agendamento (segredo do cliente) ja' foi exigido.
    barbeiro = BarbeiroDoAgendamentoSerializer()
