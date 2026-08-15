import os
from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.services.lembrete import enviar_pendentes


class LembretesView(APIView):
    """POST /api/cron/lembretes — chamado pelo `agendador` do docker-compose
    a cada tique, nunca por navegador.

    Sem `ExigeTenant`/`ExigeSessao`/`ExigeAdmin`: quem chama nao tem sessao
    nenhuma nem fala de dentro de UMA barbearia (o motor itera TODAS as
    ativas) — a credencial e' so' o bearer contra `CRON_SECRET`. O pedido
    ainda passa pelo `TenantMiddleware` global antes de chegar aqui, por
    isso o `agendador` bate com `Host: admin.<DOMINIO_BASE>` (docker-compose)
    — sem host valido em `ALLOWED_HOSTS` o pedido nem chegaria a esta view.
    """

    def post(self, request):
        segredo = os.environ.get("CRON_SECRET", "")
        esperado = f"Bearer {segredo}"
        recebido = request.headers.get("Authorization", "")
        # CRON_SECRET vazio nega tudo: sem segredo configurado, a rota fica
        # fechada em vez de virar um disparador publico de mensagens.
        if not segredo or recebido != esperado:
            return Response({"erro": "não autorizado"}, status=401)

        enviados = enviar_pendentes(datetime.now(timezone.utc))
        return Response({"enviados": enviados})
