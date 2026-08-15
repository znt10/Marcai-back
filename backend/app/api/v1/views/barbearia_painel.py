from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeSessao, PapelInsuficiente
from app.api.v1.serializers.barbearia import AtualizarBarbeariaSerializer
from app.services.barbearia import atualizar_horario_resumo, ler


class BarbeariaPainelView(ExigeSessao, APIView):
    """GET,PATCH /api/painel/barbearia

    Leitura para a EQUIPE inteira (quem atende precisa saber o que a home
    promete); escrever continua sendo so do dono, conferido dentro do PATCH."""

    def get(self, request):
        dados = ler(self.barbearia_id)
        return Response(
            {
                "nome": dados["nome"],
                "endereco": dados["endereco"],
                "horarioResumo": dados["horario_resumo"],
                "whatsappContato": dados["whatsapp_contato"],
            }
        )

    def patch(self, request):
        if self.papel != "DONO":
            raise PapelInsuficiente({"erro": "Só o dono muda isso."})

        entrada = AtualizarBarbeariaSerializer(data=request.data)
        if not entrada.is_valid():
            return Response({"erro": "Escreve a frase do horário."}, status=422)

        atualizar_horario_resumo(self.barbearia_id, entrada.validated_data["horarioResumo"])
        return Response({"ok": True})
