from datetime import date

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeAdmin
from app.services import admin_mensalidades as servico
from app.services.mensalidade.operacoes import RecusaDaMensalidade

NAO_ENCONTRADA = {"erro": "Barbearia não encontrada."}


def _dict(request):
    return request.data if isinstance(request.data, dict) else {}


def _inteiro(valor, minimo):
    """int de verdade: bool e' int em Python, mas aqui `true` nao e' valor."""
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= minimo


def _data(valor):
    if not isinstance(valor, str):
        return None
    try:
        return date.fromisoformat(valor) if len(valor) == 10 else None
    except ValueError:
        return None


def _erro(frase):
    return Response({"erro": frase}, status=400)


class AdminMensalidadesView(ExigeAdmin, APIView):
    """GET /api/admin/mensalidades"""

    def get(self, request):
        return Response(servico.listar())


class AdminMensalidadeDetalheView(ExigeAdmin, APIView):
    """PATCH /api/admin/mensalidades/<id>"""

    def patch(self, request, id):
        corpo = _dict(request)
        campos = {}
        if "valorCentavos" in corpo:
            if not _inteiro(corpo["valorCentavos"], 0):
                return _erro("Informe o valor em centavos, zero ou mais.")
            campos["valorCentavos"] = corpo["valorCentavos"]
        for nome in ("isenta", "nuncaBloquear"):
            if nome in corpo:
                if not isinstance(corpo[nome], bool):
                    return _erro(f"{nome} deve ser true ou false.")
                campos[nome] = corpo[nome]
        if "pagaAte" in corpo:
            data = _data(corpo["pagaAte"])
            if data is None:
                return _erro("Informe pagaAte como AAAA-MM-DD.")
            campos["pagaAte"] = data
        if not campos:
            return _erro("Nada para alterar.")

        try:
            achou = id is not None and servico.atualizar(id, campos)
        except RecusaDaMensalidade as recusa:
            return _erro(recusa.mensagem)
        if not achou:
            return Response(NAO_ENCONTRADA, status=404)
        return Response(servico.linha(id))


class AdminMensalidadeRegistrarView(ExigeAdmin, APIView):
    """POST /api/admin/mensalidades/<id>/registrar"""

    def post(self, request, id):
        corpo = _dict(request)
        data = _data(corpo.get("pagaAte"))
        if data is None:
            return _erro("Informe pagaAte como AAAA-MM-DD.")
        if not _inteiro(corpo.get("valorCentavos"), 1):
            return _erro("Informe o valor pago, em centavos.")
        observacao = corpo.get("observacao", "")
        if not isinstance(observacao, str):
            return _erro("A observação deve ser um texto.")

        try:
            existe = id is not None and servico.registrar(
                id, paga_ate=data, valor_centavos=corpo["valorCentavos"],
                observacao=observacao.strip(),
            )
        except RecusaDaMensalidade as e:
            return _erro(e.mensagem)
        if not existe:
            return Response(NAO_ENCONTRADA, status=404)
        return Response(servico.linha(id))


class _DecisaoView(ExigeAdmin, APIView):
    decidir = None

    def post(self, request, id):
        # Id malformado cai no mesmo "ja resolvido" do id que nao existe.
        try:
            if id is None:
                raise RecusaDaMensalidade("Este pagamento já foi resolvido.")
            barbearia_id = type(self).decidir(id)
        except RecusaDaMensalidade as e:
            return _erro(e.mensagem)
        return Response(servico.linha(barbearia_id))


class AdminCobrancaConfirmarView(_DecisaoView):
    """POST /api/admin/cobrancas/<id>/confirmar"""

    decidir = staticmethod(servico.confirmar)


class AdminCobrancaRecusarView(_DecisaoView):
    """POST /api/admin/cobrancas/<id>/recusar"""

    decidir = staticmethod(servico.recusar)
