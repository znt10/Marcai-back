from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeDono
from app.api.v1.serializers.equipe import (
    AtualizarBarbeiroSerializer,
    CriarBarbeiroSerializer,
    EquipeItemSerializer,
)
from app.services.convite import link_do_convite
from app.services.equipe import atualizar, criar, desativar, listar, reativar, reconvidar
from app.services.mensagens import msg_convite
from app.services.whatsapp import enviar_texto
from tenant.telefone import normalizar

MENSAGEM_SO_DONO = "Só o dono mexe na equipe."


def _agora():
    return datetime.now(timezone.utc)


class EquipeView(ExigeDono, APIView):
    """GET,POST /api/painel/equipe — so o dono, nas duas."""

    mensagem_papel_insuficiente = MENSAGEM_SO_DONO

    def get(self, request):
        equipe = listar(self.barbearia_id, _agora())
        return Response({"equipe": EquipeItemSerializer(equipe, many=True).data})

    def post(self, request):
        entrada = CriarBarbeiroSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche nome, celular e papel."}, status=422)
        d = entrada.validated_data

        whatsapp = normalizar(d["whatsapp"])
        if not whatsapp:
            return Response({"erro": "Confere o celular — parece faltar dígito."}, status=422)

        resultado = criar(self.barbearia_id, d["nome"], whatsapp, d["papel"])
        if resultado["tipo"] == "repetido":
            msg = (
                f"Esse celular já é do {resultado['nome']}."
                if resultado["ativo"]
                else (
                    f"Esse celular é do {resultado['nome']}, que está desativado. "
                    "Reativa em vez de cadastrar de novo."
                )
            )
            return Response({"erro": msg}, status=409)

        link = link_do_convite(request.barbearia.slug, resultado["convite"]["token"])
        # Fire-and-forget, depois do commit: WhatsApp fora do ar nao derruba
        # o cadastro. E' por isso que o link tambem volta na resposta.
        enviar_texto(
            whatsapp,
            msg_convite(nome=d["nome"], barbearia_nome=request.barbearia.nome, link=link),
        )
        return Response({"id": resultado["id"], "linkConvite": link}, status=201)


class EquipeDetalheView(ExigeDono, APIView):
    """PATCH /api/painel/equipe/<id>"""

    mensagem_papel_insuficiente = MENSAGEM_SO_DONO

    def patch(self, request, id):
        entrada = AtualizarBarbeiroSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Nada para mudar."}, status=422)
        d = entrada.validated_data

        campos = {}
        if "nome" in d:
            campos["nome"] = d["nome"]
        if "papel" in d:
            campos["papel"] = d["papel"]
        if "whatsapp" in d:
            normalizado = normalizar(d["whatsapp"])
            if not normalizado:
                return Response(
                    {"erro": "Confere o celular — parece faltar dígito."}, status=422,
                )
            campos["whatsapp"] = normalizado

        resultado = atualizar(self.barbearia_id, self.sessao, id, campos)
        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "recusado":
            return Response({"erro": resultado["erro"]}, status=409)
        return Response({"ok": True})


class EquipeDesativarView(ExigeDono, APIView):
    """POST /api/painel/equipe/<id>/desativar"""

    mensagem_papel_insuficiente = MENSAGEM_SO_DONO

    def post(self, request, id):
        resultado = desativar(self.barbearia_id, self.sessao, id, _agora())
        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "recusado":
            return Response({"erro": resultado["erro"]}, status=409)
        return Response({"ok": True})


class EquipeReativarView(ExigeDono, APIView):
    """POST /api/painel/equipe/<id>/reativar"""

    mensagem_papel_insuficiente = MENSAGEM_SO_DONO

    def post(self, request, id):
        resultado = reativar(self.barbearia_id, id)
        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        return Response({"ok": True})


class EquipeConviteView(ExigeDono, APIView):
    """POST /api/painel/equipe/<id>/convite — reemitir e' o reset de senha:
    `senhaHash` volta a nulo, o mesmo desenho da rota do admin."""

    mensagem_papel_insuficiente = MENSAGEM_SO_DONO

    def post(self, request, id):
        resultado = reconvidar(self.barbearia_id, id)
        if resultado["tipo"] == "nao_encontrado":
            return Response(NAO_ENCONTRADO, status=404)
        if resultado["tipo"] == "desativado":
            return Response(
                {"erro": "Esse barbeiro está desativado. Reativa antes de mandar convite."},
                status=409,
            )

        link = link_do_convite(request.barbearia.slug, resultado["convite"]["token"])
        enviar_texto(
            resultado["whatsapp"],
            msg_convite(nome=resultado["nome"], barbearia_nome=request.barbearia.nome, link=link),
        )
        return Response({"linkConvite": link})
