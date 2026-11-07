from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeDono
from app.services.barbearia import trocar_paleta
from tenant.models import Paleta


class PaletaView(ExigeDono, APIView):
    """PUT /api/painel/paleta — a tela do cliente clara ou escura.

    So' entre o claro e o escuro da mesma cor; trocar a COR e' do admin."""

    mensagem_papel_insuficiente = "Só o dono muda a tela do cliente."

    def put(self, request):
        paleta = request.data.get("paleta")
        if paleta not in Paleta.values or not trocar_paleta(self.barbearia_id, paleta):
            return Response({"erro": "Essa cor não é desta casa."}, status=422)
        return Response({"ok": True})
