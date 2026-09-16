from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeDono, ExigeSessao
from app.services.whatsapp_painel import desconectar, ver

MENSAGEM_SO_DONO = "Só o dono conecta o WhatsApp."


class WhatsappPainelView(ExigeSessao, APIView):
    """GET /api/painel/whatsapp — de TODO barbeiro logado, de proposito.

    `ExigeSessao` e nao `ExigeDono` porque a faixa de "WhatsApp desconectado"
    e' para a equipe inteira: um barbeiro que nao a visse passaria a tarde sem
    entender por que cliente nenhum confirma. O que o papel filtra e' um campo
    so' — o `qrBase64`, que o servico devolve nulo para quem nao e dono, e que
    na mao de um barbeiro ligaria o WhatsApp da barbearia ao celular dele.
    """

    def get(self, request):
        return Response(ver(request.barbearia, self.papel))


class WhatsappDesconectarView(ExigeDono, APIView):
    """POST /api/painel/whatsapp/desconectar — trocar de celular, so o dono."""

    mensagem_papel_insuficiente = MENSAGEM_SO_DONO

    def post(self, request):
        if not desconectar(request.barbearia):
            # 422 e nao 404: a rota existe: o que nao existe e aparelho para
            # desligar (barbearia sem zap, ou instancia ainda nao criada).
            return Response({"erro": "Não há WhatsApp conectado."}, status=422)
        return Response({"ok": True})
