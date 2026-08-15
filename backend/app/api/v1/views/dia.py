import re
from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeSessao
from app.services.agenda import quadro_do_dia
from app.services.autorizacao import filtro_do_barbeiro
from tenant.datas import dia_de_hoje

_DIA = re.compile(r"\d{4}-\d{2}-\d{2}")


class DiaView(ExigeSessao, APIView):
    """GET /api/painel/dia?dia=YYYY-MM-DD&barbeiroId=… — o quadro do dia,
    uma coluna por barbeiro."""

    def get(self, request):
        pedido = request.query_params.get("dia")
        dia = pedido if pedido and _DIA.fullmatch(pedido) else dia_de_hoje(datetime.now(timezone.utc))

        filtro = filtro_do_barbeiro(self.sessao)
        barbeiro_id = filtro.get("barbeiro_id") or request.query_params.get("barbeiroId") or None

        colunas = quadro_do_dia(self.barbearia_id, dia, barbeiro_id, datetime.now(timezone.utc))
        return Response({"dia": dia, "colunas": colunas})
