from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeTenant
from app.api.v1.serializers.barbeiros import BarbeiroPublicoSerializer
from app.services.barbeiros import listar_para_agendamento


class BarbeirosView(ExigeTenant, APIView):
    """GET /api/barbeiros — a primeira rota a atravessar.

    A view nao tem regra: quem decide quem aparece e
    `app/services/barbeiros.py`, e quem decide o que sai e o serializer. O que
    sobra aqui e o HTTP, e e para sobrar pouco — foi assim que a regra do
    servico inativo ficou testavel sem subir pedido.

    O envelope `{"barbeiros": [...]}` repete o do Next ao pe da letra. A tela
    ja le `r.barbeiros`, e a travessia nao pode mudar contrato: se mudasse, o
    `MIGRADAS` deixaria de ser um interruptor reversivel e viraria uma mudanca
    de front acoplada.
    """

    def get(self, request):
        barbeiros = listar_para_agendamento(self.barbearia_id)
        return Response({"barbeiros": BarbeiroPublicoSerializer(barbeiros, many=True).data})
