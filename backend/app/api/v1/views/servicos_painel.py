from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao, PapelInsuficiente
from app.api.v1.serializers.servicos import (
    AtualizarServicoSerializer,
    CriarServicoSerializer,
    ServicoPainelSerializer,
)
from app.services.servicos import atualizar, criar, limites_do_servico, listar_para_painel

MENSAGEM_SO_DONO = "Só o dono mexe no catálogo."


class ServicosPainelView(ExigeSessao, APIView):
    """GET,POST /api/painel/servicos

    O catalogo e' decisao da CASA (o que a barbearia vende), entao escrever e'
    so do dono — mas o GET e' para a equipe inteira, quem atende precisa ver o
    que existe. Por isso a guarda de papel mora dentro do POST, e nao na
    classe (`ExigeDono` bloquearia o GET tambem).
    """

    def get(self, request):
        servicos = listar_para_painel(self.barbearia_id)
        return Response({"servicos": ServicoPainelSerializer(servicos, many=True).data})

    def post(self, request):
        if self.papel != "DONO":
            raise PapelInsuficiente({"erro": MENSAGEM_SO_DONO})

        entrada = CriarServicoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche nome e durações."}, status=422)
        d = entrada.validated_data

        recusa = limites_do_servico(d["duracaoMinimaMin"], d["duracaoSugeridaMin"])
        if recusa:
            return Response({"erro": recusa}, status=422)

        resultado = criar(
            self.barbearia_id, d["nome"], d["duracaoMinimaMin"], d["duracaoSugeridaMin"],
        )
        if resultado["tipo"] == "repetido":
            msg = (
                "Já existe um serviço com esse nome."
                if resultado["ativo"]
                else "Já existe um serviço com esse nome, desativado. Reativa em vez de criar outro."
            )
            return Response({"erro": msg}, status=409)
        return Response({"id": resultado["id"]}, status=201)


_CAMPO_PARA_MODELO = {
    "nome": "nome",
    "duracaoMinimaMin": "duracao_minima_min",
    "duracaoSugeridaMin": "duracao_sugerida_min",
    "ordem": "ordem",
    "ativo": "ativo",
}


class ServicoPainelDetalheView(ExigeSessao, APIView):
    """PATCH /api/painel/servicos/<id> — so o dono."""

    def patch(self, request, id):
        if self.papel != "DONO":
            raise PapelInsuficiente({"erro": MENSAGEM_SO_DONO})

        entrada = AtualizarServicoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Nada para mudar."}, status=422)

        campos = {_CAMPO_PARA_MODELO[k]: v for k, v in entrada.validated_data.items()}
        resultado = atualizar(self.barbearia_id, id, campos)

        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "recusado":
            return Response({"erro": resultado["erro"]}, status=resultado["status"])
        return Response({"ok": True})
