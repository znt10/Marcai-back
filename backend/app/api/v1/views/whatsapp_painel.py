from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeDono, ExigeSessao
from app.services.lista_do_dia import mudar_hora_da_lista
from app.services.whatsapp_painel import desconectar, hhmm, ligar_bot, minutos_de, ver

MENSAGEM_SO_DONO = "Só o dono conecta o WhatsApp."


class WhatsappPainelView(ExigeSessao, APIView):
    """GET /api/painel/whatsapp — de todo barbeiro logado: a saudacao e' so'
    um texto para copiar, e a contagem de nao enviadas interessa a quem
    atende o cliente que ligou perguntando."""

    def get(self, request):
        return Response(ver(request.barbearia))


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


class WhatsappHoraDaListaView(ExigeDono, APIView):
    """POST /api/painel/whatsapp/hora-da-lista — a hora em que cada barbeiro
    recebe a lista do dia. So' o dono: ela vale para a equipe inteira."""

    mensagem_papel_insuficiente = "Só o dono muda a hora da lista."

    def post(self, request):
        hora = request.data.get("hora") if isinstance(request.data, dict) else None
        minutos = minutos_de(hora)
        try:
            mudar_hora_da_lista(request.barbearia.id, minutos)
        except ValueError:
            return Response(
                {"erro": "Escolhe uma hora entre 05:00 e 11:30, de meia em meia hora."},
                status=422,
            )
        return Response({"ok": True, "horaDaLista": hhmm(minutos)})
