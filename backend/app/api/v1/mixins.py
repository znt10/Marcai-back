from rest_framework.exceptions import APIException, NotFound

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
