from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeSessao
from app.services import pix_do_barbeiro

CAMPOS_TEXTO = ("pixTipo", "pixChave", "pixTitular")


class MeuPixView(ExigeSessao, APIView):
    """GET,PUT /api/painel/meu-pix — o Pix de quem esta logado, e so' dele.

    Sem id na URL de proposito: o barbeiro vem da SESSAO, entao nao ha o que
    trocar para chegar na chave de outro — nem sendo o dono."""

    def get(self, request):
        return Response(pix_do_barbeiro.ver(self.barbearia_id, self.barbeiro_id))

    def put(self, request):
        dados = request.data
        if not isinstance(dados, dict):
            return Response({"erro": "Corpo inválido."}, status=400)
        # `isinstance(..., bool)` e nao truthiness, como no bot: "sim" e 1
        # ligariam a cobranca por acidente de um cliente de API mal escrito.
        if "cobraNoAgendamento" in dados and not isinstance(dados["cobraNoAgendamento"], bool):
            return Response({"erro": "Diga se cobra no agendamento: true ou false."}, status=400)
        for campo in CAMPOS_TEXTO:
            if campo in dados and not isinstance(dados[campo], str):
                return Response({"erro": f"{campo} tem que ser texto."}, status=400)

        status, corpo = pix_do_barbeiro.mudar(self.barbearia_id, self.barbeiro_id, dados)
        return Response(corpo, status=status)
