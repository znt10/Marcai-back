from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeDono, ExigeSessao
from app.services.whatsapp_painel import desconectar, ligar_bot, ver

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


class WhatsappBotView(ExigeDono, APIView):
    """POST /api/painel/whatsapp/bot — liga ou desliga o atendimento automatico.

    So' o dono: um barbeiro que desligasse o bot mudaria como TODO cliente da
    barbearia e' atendido, sem o dono saber.
    """

    mensagem_papel_insuficiente = "Só o dono liga o atendimento automático."

    def post(self, request):
        ativo = request.data.get("ativo") if isinstance(request.data, dict) else None
        # `isinstance(..., bool)` e nao truthiness: "sim" e 1 ligariam o bot
        # por acidente de um cliente de API mal escrito.
        if not isinstance(ativo, bool):
            return Response({"erro": "Diz se é para ligar ou desligar."}, status=422)
        if not ligar_bot(request.barbearia, ativo):
            return Response(
                {"erro": "Não deu para mudar agora. Confere se o WhatsApp está conectado e tenta de novo."},
                status=422,
            )
        return Response({"ok": True, "botAtivo": ativo})
