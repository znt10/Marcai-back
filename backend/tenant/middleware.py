import time

from django.conf import settings
from django.http import Http404, JsonResponse

from .config import SESSAO_BARBEIRO_COOKIE, TTL_CACHE_TENANT_S
from .models import Barbearia
from .slug import eh_host_admin, extrair_slug

_cache: dict[str, tuple[Barbearia | None, float]] = {}


def _limpar_cache_tenant() -> None:
    """So para teste, igual ao _limparCacheTenant do lado Next: cada caso
    recria a barbearia com um uuid novo, e um slug cacheado do caso anterior
    apontaria para um id que o TRUNCATE ja apagou.
    """
    _cache.clear()


def _buscar_por_slug(slug: str) -> Barbearia | None:
    guardado = _cache.get(slug)
    if guardado and guardado[1] > time.monotonic():
        return guardado[0]

    # Barbearia esta FORA do RLS de proposito: e lida antes de existir tenant.
    valor = Barbearia.objects.filter(slug=slug, ativo=True).first()
    _cache[slug] = (valor, time.monotonic() + TTL_CACHE_TENANT_S)
    return valor


class ClienteMiddleware:
    """Exige `X-Brutus-Cliente` em todo verbo que escreve.

    Front e back dividem o mesmo host e diferem so na porta: e cross-ORIGIN
    (o CORS se aplica, e disso cuida a biblioteca) e same-SITE (o SameSite=Lax
    NAO bloqueia). A segunda metade e o buraco — entre origens same-site o Lax
    nao protege nada.

    Este header e a tampa: ele nao esta na lista de cabecalhos simples de CORS,
    entao exigi-lo obriga preflight, e preflight recusado impede o navegador de
    mandar o pedido com credenciais. O valor nao importa e nao e segredo — o
    que protege e a EXIGENCIA dele, nao o conteudo.
    """

    VERBOS_QUE_ESCREVEM = {"POST", "PATCH", "PUT", "DELETE"}
    HEADER = "HTTP_X_BRUTUS_CLIENTE"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in self.VERBOS_QUE_ESCREVEM and self.HEADER not in request.META:
            return JsonResponse({"erro": "pedido sem cliente"}, status=403)
        return self.get_response(request)


class TenantMiddleware:
    """Resolve Host -> Barbearia e anexa em request.barbearia.

    Le do Host REAL, nunca de cabecalho de upstream. E isso que mantem o back
    deployavel sozinho: um Django que dependesse de um x-barbearia-slug
    injetado pelo Next nao subiria sem o front na frente.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()
        base = settings.DOMINIO_BASE

        request.eh_admin = eh_host_admin(host, base)
        request.barbearia = None

        if not request.eh_admin:
            slug = extrair_slug(host, base)
            if slug is None:
                raise Http404("host sem barbearia")
            barbearia = _buscar_por_slug(slug)
            if barbearia is None:
                raise Http404("barbearia nao encontrada")
            request.barbearia = barbearia

        return self.get_response(request)


class CrivoPainelMiddleware:
    """O gemeo Django do crivo do `proxy.ts`.

    O `proxy.ts` protege `/painel` e `/api/painel/*` por POSICAO, conferindo a
    sessao antes de qualquer rota rodar. Quando um prefixo `/api/painel/*`
    entra no `MIGRADAS`, o navegador passa a falar direto com a porta 8000 e
    nunca mais encosta no `proxy.ts` — sem este middleware, a rota nasceria
    aberta.

    ATE A FATIA 1 ELE NEGAVA TUDO, de proposito: o criterio de verdade exige
    consulta ao banco, e falhar fechado era a unica resposta honesta enquanto
    ela nao existia. Agora ela existe, e a recusa seca deu lugar a leitura do
    cookie. O lugar sempre esteve certo; mudou so o criterio, como estava
    escrito aqui que mudaria.

    A diferenca em relacao ao lado Next e que aqui o crivo faz o exame INTEIRO,
    e nao a peneira grossa. La ele tinha que ser dividido em dois — o
    `proxy.ts` roda em Edge, onde o Prisma nao roda, entao `bid`, `ativo` e
    `tokenVersion` ficaram para as rotas (`sessao-painel.ts`). O Django nao tem
    essa restricao: as tres conferencias cabem aqui, e o resultado fica
    pendurado no request para a view nao repeti-las.

    O caminho fica em `app.services.sessao` e nao aqui dentro porque `/api/auth/eu`
    precisa exatamente do mesmo exame e NAO esta sob estes prefixos. Duas
    copias da regra seriam duas regras.
    """

    PREFIXOS = ("/painel", "/api/painel")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(self.PREFIXOS):
            from app.services.sessao import da_requisicao

            if da_requisicao(request) is None:
                return nao_autorizado()
        return self.get_response(request)


def nao_autorizado() -> JsonResponse:
    """401 com o cookie APAGADO — copia do `naoAutorizado` do sessao-painel.ts,
    e o apagamento e a parte que importa.

    Sessao morta que fica no navegador vira 401 em laco: a tela seguinte pede,
    leva 401, redireciona para o login, o login redireciona de volta porque o
    cookie ainda esta la. O barbeiro liga achando que o sistema caiu.

    A mensagem sai sem acento porque este arquivo e ASCII; o front nunca a
    mostra (ele redireciona no 401), e o corpo existe so para quem depura.
    """
    res = JsonResponse({"erro": "nao autorizado"}, status=401)
    res.delete_cookie(SESSAO_BARBEIRO_COOKIE, path="/")
    return res


class BarreiraAdminMiddleware:
    """Fora do host do admin, o painel da plataforma NAO EXISTE.

    A barreira e POSICIONAL: nenhuma rota de admin precisa lembrar de se
    proteger, porque a partir de qualquer outro host elas nao sao alcancaveis.
    Rota nova sob estes prefixos nasce protegida sem que ninguem decida nada.

    404 e nao 403, de proposito: 403 confirmaria que o recurso existe.

    Durante a travessia esta regra vive dos DOIS lados — aqui e no proxy.ts do
    front. Nao e redundancia acidental: e o que faz uma rota atravessar sem
    ficar desprotegida em nenhum instante.
    """

    PREFIXOS = ("/admin", "/api/admin")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(self.PREFIXOS) and not request.eh_admin:
            # Http404 SEM texto, de proposito: sob DEBUG=True o Django
            # renderiza a mensagem da excecao verbatim na pagina de erro
            # (<pre class="exception_value">), e "nao existe fora do host do
            # admin" explicaria em portugues exatamente o que a barreira
            # existe para esconder — pior que o 403 que a tarefa recusou.
            raise Http404
        return self.get_response(request)
