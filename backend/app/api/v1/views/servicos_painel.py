from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeDono, ExigeSessao, PapelInsuficiente
from app.api.v1.serializers.servicos import (
    AtualizarGrupoSerializer,
    AtualizarServicoSerializer,
    CriarGrupoSerializer,
    CriarServicoSerializer,
    GrupoSerializer,
    ServicoPainelSerializer,
)
from app.services import grupos
from app.services.servicos import (
    MENSAGEM_FALTA_GRUPO,
    atualizar,
    criar,
    limites_do_servico,
    listar_para_painel,
)

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
        return Response({
            "servicos": ServicoPainelSerializer(servicos, many=True).data,
            "grupos": GrupoSerializer(grupos.listar(self.barbearia_id), many=True).data,
        })

    def post(self, request):
        if self.papel != "DONO":
            raise PapelInsuficiente({"erro": MENSAGEM_SO_DONO})

        entrada = CriarServicoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche o nome do serviço."}, status=422)
        d = entrada.validated_data

        recusa = limites_do_servico(d["duracaoMinimaMin"], d["duracaoSugeridaMin"])
        if recusa:
            return Response({"erro": recusa}, status=422)

        resultado = criar(
            self.barbearia_id, d["nome"], d["duracaoMinimaMin"], d["duracaoSugeridaMin"],
            d.get("grupoId"),
        )
        if resultado["tipo"] == "falta_grupo":
            return Response({"erro": MENSAGEM_FALTA_GRUPO}, status=422)
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
    "grupoId": "grupo_id",
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


MENSAGEM_GRUPO_REPETIDO = "Já existe um grupo com esse nome."


class GruposPainelView(ExigeDono, APIView):
    """POST /api/painel/grupos — o primeiro grupo puxa o catalogo inteiro
    para dentro dele (ver `app.services.grupos`). A lista sai junto do GET
    de servicos, que e' quem a tela ja chama."""

    def post(self, request):
        entrada = CriarGrupoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche o nome do grupo."}, status=422)
        d = entrada.validated_data
        if not grupos.icone_valido(d["icone"]):
            return Response({"erro": "Ícone desconhecido."}, status=422)

        resultado = grupos.criar(self.barbearia_id, d["nome"], d["icone"])
        if resultado["tipo"] == "repetido":
            return Response({"erro": MENSAGEM_GRUPO_REPETIDO}, status=409)
        return Response({"id": resultado["id"]}, status=201)


class GrupoPainelDetalheView(ExigeDono, APIView):
    """PATCH,DELETE /api/painel/grupos/<id>

    O DELETE leva `?moverPara=<id>` quando o grupo tem servicos e nao e' o
    ultimo: os servicos nunca ficam sem grupo enquanto a casa tiver grupos.
    """

    def patch(self, request, id):
        entrada = AtualizarGrupoSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Nada para mudar."}, status=422)
        campos = dict(entrada.validated_data)
        if "icone" in campos and not grupos.icone_valido(campos["icone"]):
            return Response({"erro": "Ícone desconhecido."}, status=422)

        resultado = grupos.atualizar(self.barbearia_id, id, campos)
        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "repetido":
            return Response({"erro": MENSAGEM_GRUPO_REPETIDO}, status=409)
        return Response({"ok": True})

    def delete(self, request, id):
        resultado = grupos.apagar(self.barbearia_id, id, request.query_params.get("moverPara"))
        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "falta_destino":
            return Response({"erro": "Escolhe para qual grupo os serviços vão."}, status=422)
        return Response({"ok": True})
