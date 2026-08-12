from django.conf import settings

from corsheaders.signals import check_request_enabled

from .config import origem_e_permitida


def permitir_por_par_origem_host(sender, request, **kwargs):
    """Receiver de `corsheaders.signals.check_request_enabled` — conectado em
    `TenantConfig.ready()` (tenant/apps.py).

    LEIA `corsheaders.middleware.CorsMiddleware.add_response_headers` (4.9.0,
    instalado em .venv) antes de mexer aqui. A linha que importa e:

        if (
            not conf.CORS_ALLOW_ALL_ORIGINS
            and not self.origin_found_in_white_lists(origin, url)
            and not self.check_signal(request)
        ):
            return response  # sem cabecalho

    O retorno deste receiver entra OR'd com `origin_found_in_white_lists`,
    NUNCA AND'd — ou seja, a biblioteca usa o sinal so pra ACRESCENTAR origem
    permitida, nunca pra RETIRAR uma que a lista estatica ja aceitou. Por
    isso `CORS_ALLOWED_ORIGIN_REGEXES` SAIU de settings.py: se o regex
    continuasse la, `origin_found_in_white_lists` sozinho já bastaria para
    liberar o cabeçalho pra qualquer origem de forma valida — o cross-tenant
    que este receiver existe pra fechar (`dontony.localhost:3000` lendo
    `brutus.localhost:8000`) voltaria a passar batido, porque o regex por si
    so nunca soube contra qual Host a origem chegou. Com a lista estatica
    vazia, este receiver e a UNICA porta, e por isso ele mesmo aplica o
    filtro de forma (via `origem_e_permitida`, que chama `regex_de_origem`)
    antes do filtro de par — o papel que a config antiga cumpria sozinha
    continua cumprido, so que dentro da mesma funcao que agora tambem compara
    host.
    """
    origem = request.headers.get("origin")
    if not origem:
        return False
    return origem_e_permitida(origem, request.get_host(), settings.DOMINIO_BASE)


check_request_enabled.connect(permitir_por_par_origem_host)
