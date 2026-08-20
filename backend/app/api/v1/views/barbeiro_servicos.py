from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao
from app.api.v1.serializers.servicos import (
    BarbeiroServicoPainelSerializer,
    DefinirVinculoSerializer,
)
from app.services.autorizacao import alvo_do_barbeiro
from app.services.barbeiro_servicos import definir_vinculo, listar_vinculos
from tenant.identidade import como_uuid


class BarbeiroServicosView(ExigeSessao, APIView):
    """GET,PUT /api/painel/barbeiro-servicos

    Quem faz o que e em quanto tempo comeca na PESSOA, entao o alcance e'
    `alvo_do_barbeiro` (dono mexe no de todos, barbeiro so no seu) — diferente
    do catalogo em si, que e' `ehDono` puro."""

    def get(self, request):
        barbeiro_id = alvo_do_barbeiro(self.sessao, request.query_params.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        vinculos = listar_vinculos(self.barbearia_id, barbeiro_id)
        return Response(
            {
                "barbeiroId": barbeiro_id,
                "vinculos": BarbeiroServicoPainelSerializer(vinculos, many=True).data,
            }
        )

    def put(self, request):
        entrada = DefinirVinculoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche o serviço."}, status=422)
        d = entrada.validated_data

        barbeiro_id = alvo_do_barbeiro(self.sessao, d.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        # `servicoId` vem do CORPO, entao chega como texto de fonte externa. Sem
        # a conversao, um id malformado nao vira o 404 que esta escrito logo
        # abaixo: ele estoura ValidationError la dentro, no `filter()`, e a
        # rota responde 500. `None` cai no mesmo "nao encontrado" de um id que
        # simplesmente nao existe — os dois merecem a mesma resposta.
        servico_id = como_uuid(d["servicoId"])
        if servico_id is None:
            return Response(NAO_ENCONTRADO, status=404)

        resultado = definir_vinculo(
            self.barbearia_id, barbeiro_id, servico_id, d["faz"], d.get("duracaoMin"),
            d.get("precoCentavos"),
        )
        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "recusado":
            return Response({"erro": resultado["erro"]}, status=422)
        return Response({"ok": True})
