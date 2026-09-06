from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeDono
from app.services.resumo import cortes_por_barbeiro, periodo_pedido
from tenant.datas import dia_de_hoje


class ResumoView(ExigeDono, APIView):
    """GET /api/painel/resumo?de=YYYY-MM-DD&ate=YYYY-MM-DD — quantos cortes
    cada barbeiro fez no periodo, e para quantas pessoas diferentes.

    `ExigeDono` e nao `ExigeSessao`: o resumo compara a equipe inteira lado a
    lado, e isso e' informacao de quem administra. Um barbeiro vendo a coluna
    do colega e' uma decisao de produto que ninguem tomou — se um dia for
    tomada, a mudanca e' trocar por `ExigeSessao` e aplicar
    `filtro_do_barbeiro(self.sessao)`, exatamente como `/painel/dia` ja' faz.

    A view nao tem regra nenhuma de proposito: le a query, chama, devolve. O
    que decide o periodo e' `periodo_pedido`, que e' puro e por isso e' o que
    tem teste por combinacao.
    """

    mensagem_papel_insuficiente = "Só o dono vê o resumo."

    def get(self, request):
        agora = datetime.now(timezone.utc)
        de, ate = periodo_pedido(
            request.query_params.get("de"),
            request.query_params.get("ate"),
            dia_de_hoje(agora),
        )
        return Response(cortes_por_barbeiro(self.barbearia_id, de, ate, agora))
