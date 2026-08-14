from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeTenant
from app.api.v1.serializers.servicos import ServicoParaAgendamentoSerializer
from app.services.servicos import QUALQUER, listar_para_agendamento


class ServicosView(ExigeTenant, APIView):
    """GET /api/servicos?barbeiroId=…

    O `barbeiroId` ausente vira "qualquer" AQUI, e nao no servico: quem decide
    o que um parametro faltando significa e a camada que fala HTTP. O servico
    recebe sempre um valor e nao precisa saber que existe query string.

    Sem validacao do id: um `barbeiroId` que nao existe (ou de outra
    barbearia, que o RLS torna a mesma coisa) devolve lista vazia, e nao erro.
    E o mesmo do route.ts, e e o certo — a alternativa diria a quem chuta ids
    quais barbeiros existem naquela barbearia.
    """

    def get(self, request):
        barbeiro_id = request.query_params.get("barbeiroId") or QUALQUER
        servicos = listar_para_agendamento(self.barbearia_id, barbeiro_id)
        return Response(
            {"servicos": ServicoParaAgendamentoSerializer(servicos, many=True).data}
        )
