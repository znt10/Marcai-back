import re
from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeSessao
from app.services.agenda import agenda_do_dia
from app.services.autorizacao import filtro_do_barbeiro
from tenant.datas import dia_de_hoje

_DIA = re.compile(r"\d{4}-\d{2}-\d{2}")


class AgendaPainelView(ExigeSessao, APIView):
    """GET /api/painel/agenda?dia=YYYY-MM-DD&barbeiroId=…"""

    def get(self, request):
        pedido = request.query_params.get("dia")
        dia = pedido if pedido and _DIA.fullmatch(pedido) else dia_de_hoje(datetime.now(timezone.utc))

        # O filtro da sessao vence o da query, SEMPRE: o parametro so e'
        # honrado quando o filtro da sessao e' vazio, o caso do dono.
        filtro = filtro_do_barbeiro(self.sessao)
        barbeiro_id = filtro.get("barbeiro_id") or request.query_params.get("barbeiroId") or None

        itens = agenda_do_dia(self.barbearia_id, dia, barbeiro_id)
        return Response({"dia": dia, "itens": itens})
