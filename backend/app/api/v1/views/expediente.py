from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao
from app.api.v1.serializers.expediente import BloqueioSerializer, DefinirHorarioSerializer, HorarioSerializer
from app.services.autorizacao import alvo_do_barbeiro
from app.services.horarios import apagar_horario, definir_horario, jornada_valida, listar_expediente


class ExpedienteView(ExigeSessao, APIView):
    """GET,PUT,DELETE /api/painel/expediente

    Alcance de `alvo_do_barbeiro`, igual a barbeiro-servicos: dono mexe no de
    todos, cada um no seu."""

    def get(self, request):
        barbeiro_id = alvo_do_barbeiro(self.sessao, request.query_params.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        dados = listar_expediente(self.barbearia_id, barbeiro_id)
        return Response(
            {
                "barbeiroId": barbeiro_id,
                "expediente": HorarioSerializer(dados["expediente"], many=True).data,
                "bloqueios": BloqueioSerializer(dados["bloqueios"], many=True).data,
            }
        )

    def put(self, request):
        entrada = DefinirHorarioSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Preenche o dia e os horários."}, status=422)
        d = entrada.validated_data

        barbeiro_id = alvo_do_barbeiro(self.sessao, d.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        recusa = jornada_valida(d["diaSemana"], d["minutosInicio"], d["minutosFim"])
        if recusa:
            return Response({"erro": recusa}, status=422)

        definir_horario(
            self.barbearia_id, barbeiro_id, d["diaSemana"], d["minutosInicio"], d["minutosFim"],
        )
        return Response({"ok": True})

    def delete(self, request):
        barbeiro_id = alvo_do_barbeiro(self.sessao, request.query_params.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        try:
            dia_semana = int(request.query_params.get("diaSemana", ""))
        except ValueError:
            dia_semana = -1
        if not 0 <= dia_semana <= 6:
            return Response({"erro": "Dia da semana inválido."}, status=422)

        apagar_horario(self.barbearia_id, barbeiro_id, dia_semana)
        return Response({"ok": True})
