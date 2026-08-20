from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeSessao, ExigeTenant
from app.api.v1.serializers.autenticacao import (
    INVALIDO,
    TRAVADO,
    ConviteSerializer,
    EuSerializer,
    LoginSerializer,
)
from app.services.autenticacao import aceitar_convite, autenticar, quem_e
from app.services.sessao import COOKIE_SESSAO, emitir
from tenant.config import SESSAO_BARBEIRO_HORAS


def _plantar_cookie(resposta, jwt: str):
    """Os atributos sao os mesmos do `res.cookies.set` do route.ts, e cada um
    precisa continuar igual porque o cookie e emitido por um lado e lido pelo
    outro durante a travessia.

    O que NAO aparece aqui e o mais importante: nao ha `domain`. Um cookie sem
    `domain` e HOST-ONLY, e e exatamente isso que faz a travessia funcionar —
    ele vale para `brutus.localhost` e para mais nenhum host, o que da o
    isolamento entre barbearias de graca; e cookie IGNORA porta, entao o mesmo
    cookie vale na 3000 (Next) e na 8000 (Django). Acrescentar
    `domain=.localhost` aqui mandaria o cookie do Brutus para o Dom Tony.

    `secure` sai de DEBUG e nao de uma constante: em desenvolvimento o acesso e
    http, e um cookie `Secure` seria descartado pelo navegador em silencio — o
    login responderia 200 e o barbeiro continuaria deslogado.
    """
    resposta.set_cookie(
        COOKIE_SESSAO,
        jwt,
        max_age=SESSAO_BARBEIRO_HORAS * 3600,
        path="/",
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
    )
    return resposta


class LoginView(ExigeTenant, APIView):
    """POST /api/auth/login

    `ExigeTenant` e nao `ExigeSessao`, obviamente — mas a heranca importa por
    outro motivo: e ela que faz um login tentado a partir de `admin.localhost`
    dar 404 em vez de estourar em `request.barbearia.id`.
    """

    def post(self, request):
        entrada = LoginSerializer(data=request.data)
        if not entrada.is_valid():
            # 401 com a mensagem generica, e nao o 400 de validacao: o corpo
            # malformado nao pode ser um desfecho distinguivel dos outros. O
            # route.ts faz o mesmo com o `safeParse`.
            return Response(INVALIDO, status=401)

        resultado = autenticar(
            self.barbearia_id,
            entrada.validated_data["login"],
            entrada.validated_data["senha"],
        )

        if resultado["tipo"] == "travado":
            return Response(TRAVADO, status=429)
        if resultado["tipo"] == "invalido":
            return Response(INVALIDO, status=401)

        # O cookie passa a carregar a IDENTIDADE: `sub` e o id do usuario, e
        # `papel`/`tv` saem dele tambem. O nome continua vindo do PERFIL — e' a
        # divisao que a fatia 2 criou.
        conta = resultado["usuario"]
        jwt = emitir(
            sub=conta.id,
            bid=self.barbearia_id,
            papel=conta.papel,
            tv=conta.token_version,
        )
        # O corpo devolve nome e papel porque a tela pinta o cabecalho do
        # painel com eles sem precisar de uma segunda ida a `/auth/eu`.
        resposta = Response({"nome": conta.perfil.nome, "papel": conta.papel})
        return _plantar_cookie(resposta, jwt)


class LogoutView(APIView):
    """POST /api/auth/logout

    Sem `ExigeTenant` e sem `ExigeSessao`, igual ao route.ts: sair tem que
    funcionar SEMPRE. Exigir sessao valida para poder sair criaria o beco em
    que um cookie corrompido nao pode ser descartado pelo proprio botao de
    sair — o unico caso em que sair realmente importa.
    """

    def post(self, request):
        resposta = Response({"ok": True})
        resposta.delete_cookie(COOKIE_SESSAO, path="/")
        return resposta


class EuView(ExigeSessao, APIView):
    """GET /api/auth/eu — quem esta logado.

    Esta rota NAO esta sob `/api/painel`, entao o `CrivoPainelMiddleware` nao
    passa por ela: quem confere a sessao aqui e o `ExigeSessao`. E o caso que
    justifica o mixin existir alem do middleware.
    """

    def get(self, request):
        barbeiro = quem_e(self.barbearia_id, self.usuario_id)
        # `quem_e` nao volta None na pratica: o `ExigeSessao` acabou de ler
        # este barbeiro ativo, na mesma barbearia. A guarda cobre a corrida em
        # que ele e apagado entre as duas consultas, e responde 401 em vez de
        # 500 — o front sabe o que fazer com 401.
        if barbeiro is None:
            return Response({"erro": "nao autorizado"}, status=401)
        return Response(EuSerializer(barbeiro).data)


class ConviteView(ExigeTenant, APIView):
    """POST /api/auth/convite/<token> — troca o convite pela senha.

    Publica de proposito (nao ha sessao a exigir: quem aceita convite ainda nao
    tem senha para logar). Quem faz as vezes de credencial e o proprio token,
    que tem 32 bytes aleatorios e vence em 48 horas.
    """

    def post(self, request, token: str):
        entrada = ConviteSerializer(data=request.data)
        if not entrada.is_valid():
            return Response(ConviteSerializer.MENSAGEM, status=422)

        if not aceitar_convite(
            self.barbearia_id, token, entrada.validated_data["senha"]
        ):
            # 404 e nao 403: um token invalido nao pode revelar se existe
            # convite algum naquela barbearia.
            return Response({"erro": "Convite inválido ou vencido."}, status=404)
        return Response({"ok": True})
