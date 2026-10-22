from datetime import datetime, timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.limite import LimitaConta
from app.api.v1.mixins import ExigeTenant
from app.api.v1.serializers.conta import (
    CENTRAL_FORA,
    ERRO_CODIGO,
    ERRO_ENTRAR,
    ERRO_LINK,
    JA_TEM_CONTA,
    MUITOS_CODIGOS,
    NUMERO_INVALIDO,
    SEM_WHATSAPP,
    TRAVADO,
    ConfirmarSerializer,
    CriarSerializer,
    EntrarSerializer,
    NovaSenhaSerializer,
    WhatsappSerializer,
)
from app.api.v1.views.agendamentos import NAO_ENCONTRADO, resposta_do_cancelamento
from app.services import conta as servico
from app.services.agendamentos import cancelar_publico
from app.services.conta_historico import barbearia_ativa_da_conta, historico
from app.services import conta_sessao
from app.services.trava_ip import ip_de
from tenant.config import CONTA_SESSAO_COOKIE
from tenant.telefone import formas_gravadas, formatar

# Os desfechos de quem MANDA mensagem (criar, reenviar, esqueci) e o que cada
# um vira na resposta.
_ENVIO = {
    servico.ENVIADO: (202, {"ok": True}),
    servico.NUMERO_INVALIDO: (422, NUMERO_INVALIDO),
    servico.SEM_WHATSAPP: (422, SEM_WHATSAPP),
    servico.JA_TEM_CONTA: (409, JA_TEM_CONTA),
    servico.LIMITE: (429, MUITOS_CODIGOS),
    servico.FORA: (503, CENTRAL_FORA),
}


def _responder_envio(desfecho: str) -> Response:
    status, corpo = _ENVIO[desfecho]
    return Response(corpo, status=status)


def _corpo_da_conta(conta) -> dict:
    """Os campos que a tela le, e so eles: `ContaCliente` carrega o hash da
    senha e a versao do token. O numero sai formatado, como a tela o mostra."""
    return {"nome": conta.nome, "whatsapp": formatar(conta.whatsapp)}


def _logada(conta) -> Response:
    return conta_sessao.plantar(Response(_corpo_da_conta(conta)), conta)


# Cada rota de conta herda `ExigeTenant`: o host do admin nao tem
# estabelecimento, e um pedido de la' seria 500 em `request.barbearia`. As que
# mandam mensagem ou conferem segredo herdam tambem `LimitaConta`, que corta a
# rajada ANTES do argon2 e do envio.


class CriarView(LimitaConta, ExigeTenant, APIView):
    """POST /api/conta/criar"""

    def post(self, request):
        entrada = CriarSerializer(data=request.data)
        if not entrada.is_valid():
            return Response(entrada.recusa(), status=422)
        d = entrada.validated_data
        return _responder_envio(
            servico.criar(request.barbearia, ip_de(request), d["nome"], d["whatsapp"], d["senha"])
        )


class ReenviarView(LimitaConta, ExigeTenant, APIView):
    """POST /api/conta/reenviar"""

    def post(self, request):
        entrada = WhatsappSerializer(data=request.data)
        if not entrada.is_valid():
            return Response(entrada.recusa(), status=422)
        return _responder_envio(servico.reenviar(ip_de(request), entrada.validated_data["whatsapp"]))


class ConfirmarView(LimitaConta, ExigeTenant, APIView):
    """POST /api/conta/confirmar — o codigo certo vira conta e sessao."""

    def post(self, request):
        entrada = ConfirmarSerializer(data=request.data)
        if not entrada.is_valid():
            return Response(ERRO_CODIGO, status=400)
        d = entrada.validated_data
        conta = servico.confirmar(d["whatsapp"], d["codigo"], d["senha"])
        if conta is None:
            return Response(ERRO_CODIGO, status=400)
        return _logada(conta)


class EntrarView(LimitaConta, ExigeTenant, APIView):
    """POST /api/conta/entrar"""

    def post(self, request):
        entrada = EntrarSerializer(data=request.data)
        if not entrada.is_valid():
            # 401 generico, como o login do painel: corpo malformado nao pode
            # ser um desfecho distinguivel dos outros.
            return Response(ERRO_ENTRAR, status=401)
        d = entrada.validated_data
        desfecho, conta = servico.entrar(d["whatsapp"], d["senha"])
        if desfecho == servico.TRAVADO:
            return Response(TRAVADO, status=429)
        if desfecho != servico.OK:
            return Response(ERRO_ENTRAR, status=401)
        return _logada(conta)


class SairView(APIView):
    """POST /api/conta/sair

    Sem `ExigeTenant`, como o `LogoutView`: sair tem que funcionar SEMPRE, ate
    com o cookie corrompido ou de um host sem estabelecimento."""

    def post(self, request):
        return conta_sessao.apagar(Response({"ok": True}))


class EuView(ExigeTenant, APIView):
    """GET /api/conta/eu — quem esta logado. Sem conta, 401 e o cookie morto
    (assinatura vencida, senha trocada, conta pendente) e apagado, para a tela
    nao ficar em laco com ele."""

    def get(self, request):
        conta = conta_sessao.conta_da_requisicao(request)
        if conta is None:
            resposta = Response({"erro": "nao autorizado"}, status=401)
            return conta_sessao.apagar(resposta) if CONTA_SESSAO_COOKIE in request.COOKIES else resposta
        return Response(_corpo_da_conta(conta))


class EsqueciView(LimitaConta, ExigeTenant, APIView):
    """POST /api/conta/esqueci — a mesma resposta com e sem conta."""

    def post(self, request):
        entrada = WhatsappSerializer(data=request.data)
        if not entrada.is_valid():
            return Response(entrada.recusa(), status=422)
        return _responder_envio(
            servico.esqueci(request.barbearia, ip_de(request), entrada.validated_data["whatsapp"])
        )


class NovaSenhaView(LimitaConta, ExigeTenant, APIView):
    """POST /api/conta/nova-senha/<token>"""

    def post(self, request, token: str):
        # O tamanho da senha ANTES de consumir o link: a recusa por senha curta
        # nao pode gastar o unico link que a pessoa tem.
        entrada = NovaSenhaSerializer(data=request.data)
        if not entrada.is_valid():
            return Response(entrada.recusa(), status=422)
        conta = servico.nova_senha(token, entrada.validated_data["senha"])
        if conta is None:
            # 404 e nao 403: um link invalido nao revela se existe link algum.
            return Response(ERRO_LINK, status=404)
        return _logada(conta)


class HistoricoView(ExigeTenant, APIView):
    """GET /api/conta/historico — os agendamentos da conta, um bloco por
    estabelecimento, o do host atual primeiro."""

    def get(self, request):
        conta = conta_sessao.conta_da_requisicao(request)
        if conta is None:
            return Response({"erro": "nao autorizado"}, status=401)
        agora = datetime.now(timezone.utc)
        return Response({"estabelecimentos": historico(conta, self.barbearia_id, agora)})


class CancelarLogadoView(ExigeTenant, APIView):
    """POST /api/conta/agendamentos/<codigo>/cancelar, corpo `{barbeariaId}`:
    cancela em QUALQUER estabelecimento da conta,
    nao so' no do host. As mesmas respostas da rota pelo link. Tudo que nao e'
    da conta (lugar, codigo, numero do cliente) e' 404."""

    def post(self, request, codigo):
        conta = conta_sessao.conta_da_requisicao(request)
        if conta is None:
            return Response({"erro": "nao autorizado"}, status=401)
        corpo = request.data if isinstance(request.data, dict) else {}
        barbearia = barbearia_ativa_da_conta(conta, corpo.get("barbeariaId"))
        if barbearia is None:
            return Response(NAO_ENCONTRADO, status=404)

        agora = datetime.now(timezone.utc)
        resultado = cancelar_publico(
            str(barbearia.id), codigo, agora, whatsapps=formas_gravadas(conta.whatsapp),
        )
        return resposta_do_cancelamento(barbearia, resultado, agora)
