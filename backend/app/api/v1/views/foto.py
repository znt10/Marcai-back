from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import NAO_ENCONTRADO, ExigeSessao
from app.services.autorizacao import alvo_do_barbeiro
from app.services.foto import definir_foto, foto_invalida


class FotoView(ExigeSessao, APIView):
    """PUT /api/painel/foto — a foto do barbeiro.

    `PUT` e nao `POST`: mandar a mesma foto duas vezes tem que dar no mesmo, e
    `foto: null` e' o jeito de apagar. Nao ha rota de DELETE separada porque
    "sem foto" nao e' um recurso ausente, e' um valor.
    """

    def put(self, request):
        # Mesma regra de horarios e servicos: dono mexe no de todos, barbeiro
        # no seu. Um barbeiro pedindo o id do colega recebe 404, nunca 403 —
        # 403 confirmaria que aquele colega existe.
        barbeiro_id = alvo_do_barbeiro(self.sessao, request.data.get("barbeiroId"))
        if not barbeiro_id:
            return Response(NAO_ENCONTRADO, status=404)

        foto = request.data.get("foto")
        if foto is not None:
            if not isinstance(foto, str):
                return Response({"erro": "Manda a foto pelo botão da tela."}, status=422)
            problema = foto_invalida(foto)
            if problema:
                return Response({"erro": problema}, status=422)
            foto = foto.strip()

        if not definir_foto(self.barbearia_id, barbeiro_id, foto):
            return Response(NAO_ENCONTRADO, status=404)
        return Response({"ok": True})
