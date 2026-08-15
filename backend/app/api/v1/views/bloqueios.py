from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao
from app.api.v1.serializers.expediente import CriarBloqueioSerializer
from app.services.autorizacao import alvo_do_barbeiro, filtro_do_barbeiro
from app.services.bloqueios import apagar_bloqueio, criar_bloqueio
from app.services.horarios import bloqueio_valido


class BloqueiosView(ExigeSessao, APIView):
    """POST /api/painel/bloqueios"""

    def post(self, request):
        entrada = CriarBloqueioSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche o bloqueio."}, status=422)
        d = entrada.validated_data

        barbeiro_id = alvo_do_barbeiro(self.sessao, d.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        campos = {
            "motivo": d["motivo"],
            "observacao": d.get("observacao"),
            "repete_semanalmente": d["repeteSemanalmente"],
            "dia_semana": d.get("diaSemana"),
            "minutos_inicio": d.get("minutosInicio"),
            "minutos_fim": d.get("minutosFim"),
            "inicio": d.get("inicio"),
            "fim": d.get("fim"),
        }
        recusa = bloqueio_valido(
            repete_semanalmente=campos["repete_semanalmente"],
            dia_semana=campos["dia_semana"],
            minutos_inicio=campos["minutos_inicio"],
            minutos_fim=campos["minutos_fim"],
            inicio=campos["inicio"],
            fim=campos["fim"],
        )
        if recusa:
            return Response({"erro": recusa}, status=422)

        novo_id = criar_bloqueio(self.barbearia_id, barbeiro_id, campos)
        return Response({"id": novo_id}, status=201)


class BloqueioDetalheView(ExigeSessao, APIView):
    """DELETE /api/painel/bloqueios/<id>"""

    def delete(self, request, id):
        filtro = filtro_do_barbeiro(self.sessao)
        apagado = apagar_bloqueio(self.barbearia_id, id, filtro.get("barbeiro_id"))
        if not apagado:
            return Response(NAO_ENCONTRADO, status=404)
        return Response({"ok": True})
