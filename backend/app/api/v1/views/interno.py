import hmac
import logging
import os
from datetime import datetime, timezone

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from app.services.bot_entrada import EVENTO_MENSAGEM, Recebida, ler_mensagem, receber
from app.services.whatsapp_eventos import aplicar_evento

logger = logging.getLogger(__name__)


class WhatsappEventoView(APIView):
    """POST /api/interno/whatsapp/evento — a Evolution avisando que o WhatsApp
    de uma barbearia conectou, caiu ou gerou um QR novo.

    **Como um pedido de fora da aplicacao chega aqui inteiro**, que e a parte
    que custou uma fatia so de investigacao para confirmar: a Evolution bate
    em `http://api:8000` pela rede interna do compose, mandando tres
    cabecalhos configurados na propria instancia (`whatsapp_instancias.py`).
    Cada um passa por uma barreira diferente, e todas as tres ja existiam:

    - `Host: admin.<DOMINIO_BASE>` passa pelo `ALLOWED_HOSTS` (o Host real
      seria `api`, que o Django recusa com 400) e faz o `TenantMiddleware`
      tratar isto como pedido de plataforma, sem tenant. Mesmo truque do
      `/api/cron/lembretes`, e foi medido chegando intacto na 2.3.7.
    - `x-brutus-cliente` passa pelo `ClienteMiddleware`, que recusa todo verbo
      que escreve sem ele.
    - `x-marcai-webhook` e a credencial, conferida aqui.

    Fora de `/painel` e de `/admin`, entao nenhum dos dois crivos posicionais
    toca nesta rota — igual a `LembretesView`, e pela mesma razao: quem chama
    nao tem sessao nenhuma e nao fala de dentro de UMA barbearia.

    **Responde 200 para quase tudo**, e isso e deliberado. A Evolution reenvia
    o que nao foi aceito; um corpo estranho que virasse 404 ou 500 voltaria em
    laco. A UNICA resposta que nao e 200 e o 401 da credencial — a la ela
    nunca vai chegar de verdade, entao nao ha laco a temer.

    Com o bot ligado chegam tambem as mensagens de cliente (messages.upsert):
    o descarte e a fila moram em bot_entrada.py.
    """

    def post(self, request):
        segredo = os.environ.get("WHATSAPP_WEBHOOK_SEGREDO", "")
        recebido = request.headers.get("x-marcai-webhook", "")
        # Segredo vazio NEGA TUDO, igual ao CRON_SECRET: sem segredo
        # configurado a rota fica fechada em vez de virar um jeito publico de
        # mentir sobre o estado do WhatsApp de qualquer barbearia.
        #
        # `compare_digest` em bytes, e nao em str: com texto nao-ASCII a versao
        # de str levanta TypeError, e um cabecalho forjado viraria 500 em vez
        # de 401 — o mesmo cuidado do `HostDoProxyMiddleware`.
        if not segredo or not hmac.compare_digest(recebido.encode(), segredo.encode()):
            return Response({"erro": "não autorizado"}, status=401)

        # O guarda tem que olhar o `Content-Length` ANTES de tocar em
        # `request.data`: no DRF 3.17 a leitura do corpo nao levanta mais
        # `RequestDataTooBig` (o parser le o stream cru), entao o unico jeito
        # de recusar sem estourar e' conferir o tamanho anunciado primeiro.
        # 200 e nao 400: a Evolution reenvia o que nao foi aceito, e uma foto
        # grande demais voltaria para sempre.
        try:
            tamanho = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            tamanho = 0
        if tamanho > settings.DATA_UPLOAD_MAX_MEMORY_SIZE:
            logger.warning("[webhook] evento acima do limite de corpo: descartado")
            return Response({"ok": True, "resultado": "ignorado:grande"})

        corpo = request.data
        corpo = corpo if isinstance(corpo, dict) else {}

        # Mensagem de cliente vai para o bot; conexao e QR seguem o caminho de
        # sempre. As duas coisas chegam pela mesma rota porque a Evolution so'
        # tem UM webhook por instancia.
        if str(corpo.get("event") or "").lower() == EVENTO_MENSAGEM:
            try:
                resultado = receber(corpo, datetime.now(timezone.utc))
            except Exception:
                # Uma queda do broker ou do banco no meio do webhook nao pode
                # virar 500 — mesma razao do corpo grande: a Evolution
                # reenviaria o mesmo evento para sempre. `ler_mensagem` e'
                # pura e nao repete o que ja falhou, so' identifica o evento
                # pro log — sem o numero nem o texto do cliente.
                lida = ler_mensagem(corpo)
                barbearia_id = lida.barbearia_id if isinstance(lida, Recebida) else None
                mensagem_id = lida.mensagem_id if isinstance(lida, Recebida) else None
                logger.exception(
                    "[webhook] falha ao tratar messages.upsert (barbearia=%s, mensagem=%s)",
                    barbearia_id, mensagem_id,
                )
                resultado = "ignorado:erro"
        else:
            resultado = aplicar_evento(corpo)
        return Response({"ok": True, "resultado": resultado})
