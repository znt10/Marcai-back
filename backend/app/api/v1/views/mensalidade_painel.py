from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeDono, ExigeSessao
from app.services.mensalidade import operacoes, pix
from app.services.mensalidade.operacoes import RecusaDaMensalidade
from tenant.models import Assinatura


def _data(valor):
    return valor.isoformat() if valor else None


def _corpo(barbearia_id, papel, *, agora):
    """O mesmo corpo do GET e do "Ja paguei". O Pix so' vai para o dono e so'
    quando ha o que cobrar; ver a tela nao pode criar cobranca para barbeiro
    (quem paga e' o dono), por isso a cobranca so' e' pedida a ele."""
    lido = operacoes.leitura(barbearia_id, agora=agora)
    assinatura = Assinatura.objects.using("admin").filter(pk=barbearia_id).first()
    sou_dono = papel == "DONO"
    cobranca, pix_erro = None, None
    if sou_dono:
        try:
            cobranca = operacoes.cobranca_do_ciclo(barbearia_id, agora=agora)
        except RecusaDaMensalidade as recusa:
            # Sem centavo livre agora: o dono bloqueado so' alcanca esta rota,
            # entao ela responde com a situacao e o motivo em vez de 500.
            pix_erro = recusa.mensagem
    return {
        "situacao": str(lido.situacao),
        "dias": lido.dias,
        "bloqueiaEm": _data(lido.bloqueia_em),
        "pagaAte": _data(assinatura.paga_ate) if assinatura and not assinatura.isenta else None,
        "valorCentavos": assinatura.valor_centavos if assinatura and not assinatura.isenta else None,
        "souDono": sou_dono,
        "pixErro": pix_erro,
        "pix": None if cobranca is None else {
            "copiaECola": cobranca.copia_e_cola,
            "qrSvg": pix.qr_svg(cobranca.copia_e_cola),
            "valorCentavos": cobranca.valor_centavos,
        },
    }


class MensalidadePainelView(ExigeSessao, APIView):
    """GET /api/painel/mensalidade — de todo barbeiro logado, e e' a unica
    rota do painel que responde com a barbearia bloqueada."""

    def get(self, request):
        return Response(_corpo(request.barbearia.id, self.papel, agora=timezone.now()))


class MensalidadeJaPagueiView(ExigeDono, APIView):
    """POST /api/painel/mensalidade/ja-paguei — so' o dono avisa que pagou."""

    mensagem_papel_insuficiente = "Só o dono avisa o pagamento da mensalidade."

    def post(self, request):
        agora = timezone.now()
        try:
            operacoes.informar_pagamento(request.barbearia.id, self.barbeiro_id, agora=agora)
        except RecusaDaMensalidade as recusa:
            return Response({"erro": recusa.mensagem}, status=400)
        return Response(_corpo(request.barbearia.id, self.papel, agora=agora))
