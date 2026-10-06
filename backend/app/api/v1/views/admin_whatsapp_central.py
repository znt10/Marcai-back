from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeAdmin
from app.services.whatsapp_central import ver_central


class AdminWhatsappCentralView(ExigeAdmin, APIView):
    """GET /api/admin/whatsapp-central — estado e QR do numero central."""

    def get(self, request):
        return Response(ver_central())
