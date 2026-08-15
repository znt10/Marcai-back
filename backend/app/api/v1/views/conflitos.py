from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao
from app.services.autorizacao import alvo_do_barbeiro
from app.services.conflitos import listar_conflitos


class ConflitosView(ExigeSessao, APIView):
    """GET /api/painel/conflitos?barbeiroId=…"""

    def get(self, request):
        barbeiro_id = alvo_do_barbeiro(self.sessao, request.query_params.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        conflitos = listar_conflitos(self.barbearia_id, barbeiro_id, datetime.now(timezone.utc))
        return Response({"conflitos": conflitos})
