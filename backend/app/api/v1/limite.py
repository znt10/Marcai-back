import math

from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import exception_handler

MUITAS_TENTATIVAS = {"erro": "Muitas tentativas. Tenta de novo daqui a pouco."}


class LimitePorIP(SimpleRateThrottle):
    """Teto POR IP de toda a API, na taxa `geral` do settings — ligado em
    `DEFAULT_THROTTLE_CLASSES`, entao vale para toda view que nao declarar
    `throttle_classes` propria.

    Por IP, e nao por usuario, mesmo com sessao: o `AnonRateThrottle` do DRF
    deixaria passar livre qualquer pedido autenticado, e uma conta de barbeiro
    comprometida seria uma torneira aberta contra o back.

    O contador mora no cache (Redis em producao, ver CACHES no settings), para
    valer o mesmo em todos os workers. O IP sai do `X-Forwarded-For` pelo
    `NUM_PROXIES`, tambem no settings.
    """

    scope = "geral"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LimitaLogin:
    """Teto mais apertado nas rotas de login, na taxa `login`, alem do geral.

    Complementa as travas que ja existem, nao as substitui. A do barbeiro e'
    por CONTA: protege a senha de uma pessoa, mas nao ve quem tenta um numero
    diferente a cada pedido — e cada um desses pedidos roda o argon2, que e'
    caro de proposito. Com 3 workers, uma rajada de logins ocupava o back
    inteiro e ninguem conseguia agendar. Este limite corta a rajada ANTES do
    argon2: o DRF confere o throttle em `initial()`, antes do `post`.

    `LimitePorIP` repetido aqui porque `throttle_classes` na view SUBSTITUI o
    padrao do settings, nao soma a ele.
    """

    throttle_classes = [LimitePorIP, ScopedRateThrottle]
    throttle_scope = "login"


def tratar_excecao(exc, context):
    """O `EXCEPTION_HANDLER` da API. So' muda o 429: o DRF responderia
    `{"detail": "Request was throttled..."}`, em ingles e numa chave que o
    front nao le. Sai no formato de todo erro da API, com o Retry-After que o
    DRF ja calculou. O resto segue o padrao do DRF, sem mudanca."""
    if isinstance(exc, Throttled):
        resposta = Response(MUITAS_TENTATIVAS, status=429)
        if exc.wait is not None:
            resposta["Retry-After"] = str(math.ceil(exc.wait))
        return resposta
    return exception_handler(exc, context)
