import time

from django.conf import settings
from django.http import Http404

from .config import TTL_CACHE_TENANT_S
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
            raise Http404("nao existe fora do host do admin")
        return self.get_response(request)
