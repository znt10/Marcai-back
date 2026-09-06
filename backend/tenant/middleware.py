import time

from django.conf import settings
from django.http import Http404, JsonResponse

from .config import SESSAO_BARBEIRO_COOKIE, TTL_CACHE_TENANT_S, sem_subdominio
from .models import Barbearia
from .rls import com_barbearia_por_requisicao
from .slug import eh_host_admin, extrair_slug

# Import de `app` dentro de `tenant`: inverte a direcao habitual das
# dependencias deste projeto (`app` costuma importar de `tenant`, nunca o
# contrario). Deliberado — a sessao do admin e' um servico de aplicacao, e
# este middleware e' quem a consome. Se algum dia isso fechar um ciclo
# (`app` importando `tenant.models`), o precedente e' `CrivoPainelMiddleware`
# logo abaixo: ele importa `app.services.sessao` de DENTRO do `__call__`,
# exatamente para quebrar o ciclo.
from app.services.admin_sessao import COOKIE_SESSAO_ADMIN
from app.services.admin_sessao import ler as ler_sessao_admin

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
        # O admin do Django e' isento: o formulario dele e' servido pela MESMA
        # origem que o recebe, e ali quem protege e' o token CSRF do Django
        # (ligado na etapa do admin), nao este header. O header existe para o
        # arranjo da API — cross-origin e same-site ao mesmo tempo, onde o
        # SameSite=Lax nao protege nada e so' o preflight obrigatorio protege.
        if request.path.startswith(AdminDjangoMiddleware.PREFIXO):
            return self.get_response(request)
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
            # A saida de dev para testar no celular: um host SEM subdominio
            # (IP nu na rede, ou o dominio nu) cai na barbearia de
            # TENANT_PADRAO. Fica FORA de `extrair_slug` de proposito — aquela
            # e' a funcao pura espelhada no front, e o contrato dela e' "este
            # host nomeia esta barbearia", sem excecao. A conveniencia mora
            # aqui, no chamador, onde da' para ver que ela depende de settings.
            #
            # `settings.TENANT_PADRAO` ja' nasce "" fora de DEBUG (settings.py
            # o passa por `tenant_padrao`), entao em producao esta linha e'
            # inerte.
            if slug is None and settings.TENANT_PADRAO and sem_subdominio(host, base):
                slug = settings.TENANT_PADRAO
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


class AdminDjangoMiddleware:
    """A porta e o escopo do admin do Django (spec de 06/09/2026).

    Faz duas coisas, e as duas so' sob `/admin/django`:

    1. **A porta.** Exige o cookie da plataforma. O `BarreiraAdminMiddleware`
       ja garante que so' se chega aqui do host do admin; esta camada e' o que
       torna o admin do Django SEU, e nao de quem alcancar aquele host. 404 e
       nao 403 pelo mesmo motivo de sempre: 403 confirmaria que existe.

    2. **O escopo.** Define `app.barbearia_id` com a barbearia escolhida na
       sessao. Sem isso, TODA listagem de model de tenant viria vazia — a
       politica de RLS compara `barbearia_id` com `current_setting(...)`, que
       sem valor devolve NULL, e `x = NULL` nao e' verdadeiro.

    O ponto que faz este desenho valer a pena: quem filtra e' o POSTGRES, nao
    um `get_queryset().filter(...)`. Um ModelAdmin que alguem registre amanha
    sem pensar em tenant ja nasce enxergando so' a barbearia escolhida.

    `atomic()` SEM `durable=True`, ao contrario de `com_barbearia`: aquele usa
    durabilidade para estourar alto quando alguem aninha wrapper de tenant, e
    aqui a transacao envolve a REQUISICAO inteira do admin, que pode passar por
    caminhos que abram os seus proprios blocos.

    Sem barbearia escolhida a variavel nao e' definida, e o admin mostra listas
    vazias. E' o comportamento certo e legivel: "voce nao disse de quem esta
    falando".

    **Limite deste `with`, que nao e' obvio:** ele garante UMA CONEXAO e UMA
    VARIAVEL DE RLS por requisicao, nao atomicidade da requisicao inteira.
    Uma excecao levantada dentro da VIEW vira resposta 500 ainda DENTRO do
    `get_response` (o `convert_exception_to_response` do Django embrulha cada
    middleware), entao este `with` sai sem excecao e COMMITA o que a view ja
    tiver escrito — ao contrario de `ATOMIC_REQUESTS`, que embrulha a view por
    FORA e por isso pega a excecao dela. Uma view custom sob este prefixo que
    escreva em tabela de tenant e precise desfazer em erro precisa do proprio
    `atomic()`; ver o docstring de `com_barbearia_por_requisicao` em `rls.py`.
    """

    # SEM barra final de proposito: `startswith` tambem casaria vizinhos como
    # `/admin/djangox/` ou `/admin/django-relatorios/`, mas isso NAO e' um
    # buraco hoje porque `ClienteMiddleware` isenta o mesmo header usando
    # ESTA MESMA constante — os dois conjuntos (quem passa a porta, quem fica
    # isento do header) casam exatamente, entao uma rota futura sob
    # `/admin/django-algo/` nasceria isenta do header MAS tambem atras da
    # porta. Trocar para `"/admin/django/"` pareceria mais preciso e seria
    # PIOR: desalinharia os dois conjuntos e abriria o buraco que este
    # comentario descreve. A garantia vem de as duas classes lerem a MESMA
    # constante, nao da forma dela.
    PREFIXO = "/admin/django"
    CHAVE_SESSAO = "barbearia_escolhida"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(self.PREFIXO):
            return self.get_response(request)

        if not ler_sessao_admin(request.COOKIES.get(COOKIE_SESSAO_ADMIN)):
            # Http404 SEM texto, igual a BarreiraAdminMiddleware: sob DEBUG o
            # Django renderiza a mensagem da excecao na pagina de erro, e
            # explicar a barreira em portugues seria pior que o 403 recusado.
            raise Http404

        escolhida = request.session.get(self.CHAVE_SESSAO)
        if not escolhida:
            return self.get_response(request)

        with com_barbearia_por_requisicao(escolhida):
            return self.get_response(request)
