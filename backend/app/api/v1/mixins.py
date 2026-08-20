from rest_framework.exceptions import APIException, NotFound

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN
from app.services.admin_sessao import ler as ler_sessao_admin
from app.services.sessao import COOKIE_SESSAO, da_requisicao

# Corpo do 404 do painel, repetido em toda rota que carrega um registro por
# id dentro do tenant (bloqueio, agendamento, barbeiro da equipe, ...). Um so
# lugar para o texto, porque a mensagem generica ("Não encontrado.") e' o que
# faz o 404 nao revelar se o registro alheio existe.
NAO_ENCONTRADO = {"erro": "Não encontrado."}


class ExigeTenant:
    """A regra do item 3 do card da fatia 1, e ela precisa existir ANTES da
    primeira rota de tenant, nao depois.

    O `TenantMiddleware` poe `request.barbearia = None` quando o host e o do
    admin. Uma view de tenant alcancada de `admin.localhost` iria direto para
    `request.barbearia.id` e levantaria `AttributeError` — 500, stack trace, e
    um erro de servidor para o que na verdade e um pedido sem sentido.

    404 e nao 400, pelo mesmo motivo que a BarreiraAdminMiddleware usa 404:
    do host do admin, uma rota de barbearia nao existe. 400 admitiria que ela
    existe e que faltou algo.

    Herdar do mixin e a forma de OPTAR por exigir tenant. Nao ha automatismo
    por prefixo aqui de proposito: o prefixo publico (`/api/barbeiros`) e o do
    painel compartilham a mesma raiz `/api`, entao uma regra posicional teria
    que listar excecoes, e uma lista de excecoes e onde a proxima rota vai ser
    esquecida. Herdar e explicito e aparece na definicao da classe.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if getattr(request, "barbearia", None) is None:
            raise NotFound()

    @property
    def barbearia_id(self):
        return self.request.barbearia.id


class SessaoInvalida(APIException):
    """401, e NAO a `NotAuthenticated` do proprio DRF.

    A `NotAuthenticated` parece a escolha obvia e daria 403 aqui. O
    `APIView.handle_exception` pergunta a `get_authenticate_header()` qual
    desafio mandar no `WWW-Authenticate`; sem nenhuma classe de autenticacao
    configurada (e nao ha nenhuma de proposito — settings.py explica) a
    resposta e None, e o DRF entao REBAIXA o 401 para 403, porque um 401 sem
    desafio viola a RFC.

    Só que o front nao trata 403: `pedir()` redireciona para o login no 401 e
    so no 401 (client.ts). Um 403 viraria "Nao deu certo. Tenta de novo?" numa
    tela que nunca mais carrega. O contrato manda 401, entao 401.
    """

    status_code = 401
    default_detail = {"erro": "nao autorizado"}


class ExigeSessao(ExigeTenant):
    """Herdar disto e o jeito de dizer "esta rota e de barbeiro logado".

    Herda de `ExigeTenant` porque nao existe sessao sem barbearia: o host do
    admin nao tem tenant, e conferir cookie antes de saber contra QUAL
    barbearia conferir e a origem do pior bug do multi-tenant.

    O exame em si nao esta aqui — esta em `app.services.sessao.da_requisicao`,
    o mesmo que o `CrivoPainelMiddleware` chama. Para toda rota sob
    `/api/painel/*` o middleware ja passou e o resultado esta memorizado no
    request, entao esta chamada nao custa consulta nova. Para `/api/auth/eu`,
    que nao esta sob aquele prefixo, esta e a unica chamada. Ter os dois nao e
    redundancia: o middleware protege por POSICAO (rota nova sob /api/painel
    nasce protegida sem ninguem decidir nada) e o mixin protege por DECLARACAO
    (rota fora daquele prefixo pede explicitamente).
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # `request._request`: o DRF embrulha o HttpRequest, e o middleware
        # pendurou a memoria no de dentro. Passar o de fora faria a memoria
        # nunca ser encontrada e a consulta rodar duas vezes por pedido.
        self.sessao = da_requisicao(getattr(request, "_request", request))
        if self.sessao is None:
            raise SessaoInvalida()

    @property
    def barbeiro_id(self):
        """O id do PERFIL, resolvido por `sessao.da_requisicao` — nao o `sub`,
        que desde a fatia 3 e o id do usuario."""
        return self.sessao["barbeiro_id"]

    @property
    def usuario_id(self):
        return self.sessao["sub"]

    @property
    def papel(self):
        return self.sessao["papel"]

    def finalize_response(self, request, response, *args, **kwargs):
        """Apaga o cookie em toda resposta 401, igual ao `naoAutorizado` do
        sessao-painel.ts. Sem isso, uma sessao morta que ficou no navegador
        vira 401 em laco — a tela redireciona para o login, o login redireciona
        de volta, e ninguem entra.
        """
        resposta = super().finalize_response(request, response, *args, **kwargs)
        if resposta.status_code == 401:
            resposta.delete_cookie(COOKIE_SESSAO, path="/")
        return resposta


class PapelInsuficiente(APIException):
    """403, nao 404: quem falha aqui ja sabe que nao e dono (tem sessao
    valida), entao dizer "isso e so do dono" nao conta nada que ele nao
    soubesse — diferente do 404 do painel, que existe para nao revelar que um
    REGISTRO alheio existe. Mesma distincao de `ehDono`/`filtroDoBarbeiro` no
    front (src/lib/autorizacao.ts).
    """

    status_code = 403
    default_detail = {"erro": "Só o dono mexe nisso."}


class ExigeDono(ExigeSessao):
    """Herdar disto e o jeito de dizer "esta rota e so do dono" — irma de
    `ExigeSessao`, com uma pergunta a mais depois da sessao valida: o papel.

    Nao ha automatismo por prefixo pelo mesmo motivo de `ExigeTenant`: nem
    toda rota de `/api/painel` e dono-only (horarios e barbeiro-servicos sao
    do proprio barbeiro), entao a lista de excecoes seria o lugar errado para
    a proxima rota ser esquecida. Herdar e' explicito.

    `mensagem_papel_insuficiente` e OVERRIDABLE por view: o front tinha uma
    frase por rota ("Só o dono mexe no catálogo.", "...na equipe.", "Só o
    dono muda isso.") — texto que a tela mostra direto, entao migrar a rota
    sem preservar a frase seria uma regressao de UX que nenhum teste de status
    HTTP pegaria.
    """

    mensagem_papel_insuficiente = "Só o dono mexe nisso."

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.papel != "DONO":
            raise PapelInsuficiente({"erro": self.mensagem_papel_insuficiente})


class SessaoAdminInvalida(APIException):
    """401, mesma razao de `SessaoInvalida` acima (o front so trata 401 no
    redirecionamento de login — `pedir()` em client.ts). Classe separada e
    nao reuso de `SessaoInvalida` porque o cookie que ela apaga em
    `finalize_response` e' outro."""

    status_code = 401
    default_detail = {"erro": "nao autorizado"}


class ExigeAdmin:
    """Herdar disto e o jeito de dizer "esta rota e do admin da plataforma".

    NAO herda de `ExigeSessao`/`ExigeTenant`: o admin nao pertence a
    barbearia nenhuma (nao ha `request.barbearia` do lado do host admin), e
    as claims/segredo do cookie sao outro par por completo (spec do admin,
    §4) — misturar as duas cadeias de heranca so' criaria um jeito de um
    cookie de barbeiro ser lido onde se espera um de admin, ou vice-versa.

    A conferencia em si continua sendo so' a assinatura. Desde a fatia 3 o
    admin EXISTE como linha (`Usuario` com `barbearia_id` NULL), mas nao ha
    `token_version` de admin a conferir a cada pedido — trocar
    ADMIN_JWT_SECRET segue sendo o jeito de derrubar a sessao dele.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        token = request.COOKIES.get(COOKIE_SESSAO_ADMIN)
        self.admin_id = ler_sessao_admin(token)
        if self.admin_id is None:
            raise SessaoAdminInvalida()

    def finalize_response(self, request, response, *args, **kwargs):
        """Mesma razao de `ExigeSessao.finalize_response`: apaga o cookie
        morto em todo 401, pra nao deixar o navegador preso num laco de
        redirecionamento pro login do admin."""
        resposta = super().finalize_response(request, response, *args, **kwargs)
        if resposta.status_code == 401:
            resposta.delete_cookie(COOKIE_SESSAO_ADMIN, path="/")
        return resposta
