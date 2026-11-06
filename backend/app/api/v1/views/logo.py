from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeDono
from app.services.logo import definir_logo, logo_invalida


class LogoView(ExigeDono, APIView):
    """PUT /api/painel/logo — a logo da casa.

    So' do dono: a logo e' da CASA, ao contrario da foto, que e' de cada um.
    `PUT` com `logo: null` tira a logo, como o `FotoView` — "sem logo" e' um
    valor, nao um recurso ausente.
    """

    mensagem_papel_insuficiente = "Só o dono muda a logo."

    def put(self, request):
        logo = request.data.get("logo")
        if logo is not None:
            if not isinstance(logo, str):
                return Response({"erro": "Manda a logo pelo botão da tela."}, status=422)
            problema = logo_invalida(logo)
            if problema:
                return Response({"erro": problema}, status=422)
            logo = logo.strip()

        definir_logo(self.barbearia_id, logo)
        return Response({"ok": True})
