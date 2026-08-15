from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeAdmin
from app.api.v1.serializers.admin_barbearias import AtualizarBarbeariaSerializer
from app.services.admin_barbearias import (
    atualizar_ativo,
    criar,
    listar_com_contagem,
    reemitir_convite,
)
from app.services.convite import link_do_convite
from app.services.mensagens import msg_convite
from app.services.whatsapp import enviar_texto

NAO_ENCONTRADA = {"erro": "Barbearia não encontrada."}


class AdminBarbeariasView(ExigeAdmin, APIView):
    """GET,POST /api/admin/barbearias"""

    def get(self, request):
        return Response({"barbearias": listar_com_contagem()})

    def post(self, request):
        resultado = criar(request.data if isinstance(request.data, dict) else {})

        if resultado["tipo"] == "slug_invalido":
            return Response({"erro": "Slug inválido ou reservado."}, status=422)
        if resultado["tipo"] == "faltou_campo":
            return Response({"erro": "Faltou preencher algum campo."}, status=422)
        if resultado["tipo"] == "slug_duplicado":
            # Nao e' evasivo como no login: quem le esta resposta e' o dono
            # do site, nao um estranho tentando descobrir slug alheio.
            return Response(
                {"erro": f'O slug "{resultado["slug"]}" já está em uso.'}, status=409
            )

        link = link_do_convite(resultado["slug"], resultado["convite"]["token"])
        # Fire-and-forget, DEPOIS do commit (a transacao ja fechou dentro de
        # `criar()`). O link tambem volta no corpo porque o banco so guarda o
        # hash — perdido ali, nao ha como recuperar, so' reemitir.
        enviar_texto(
            resultado["contato"],
            msg_convite(
                nome=resultado["dono_nome"], barbearia_nome=resultado["nome"], link=link
            ),
        )
        return Response(
            {"id": resultado["id"], "slug": resultado["slug"], "linkConvite": link},
            status=201,
        )


class AdminBarbeariaDetalheView(ExigeAdmin, APIView):
    """PATCH /api/admin/barbearias/<id>"""

    def patch(self, request, id):
        entrada = AtualizarBarbeariaSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Informe ativo: true ou false."}, status=422)

        if not atualizar_ativo(id, entrada.validated_data["ativo"]):
            return Response(NAO_ENCONTRADA, status=404)
        return Response({"ok": True})


class AdminBarbeariaConviteView(ExigeAdmin, APIView):
    """POST /api/admin/barbearias/<id>/convite"""

    def post(self, request, id):
        resultado = reemitir_convite(id)

        if resultado["tipo"] == "barbearia_nao_encontrada":
            return Response(NAO_ENCONTRADA, status=404)
        if resultado["tipo"] == "sem_dono_ativo":
            return Response({"erro": "Essa barbearia não tem dono ativo."}, status=404)

        link = link_do_convite(resultado["slug"], resultado["convite"]["token"])
        # Reemitir ja apagou a senha do dono neste ponto — se o link so
        # existisse na tela do admin e ela fechasse, o dono ficava de fora
        # sem caminho de volta. Duas vias, como o convite de barbeiro.
        enviar_texto(
            resultado["dono_whatsapp"],
            msg_convite(
                nome=resultado["dono_nome"], barbearia_nome=resultado["nome"], link=link
            ),
        )
        return Response({"linkConvite": link})
