import time

from django.core.cache import cache

from tenant.config import (
    ADMIN_TRAVA_BASE_MS,
    ADMIN_TRAVA_BLOQUEIO_MS,
    ADMIN_TRAVA_TENTATIVAS,
    ADMIN_TRAVA_TETO_MS,
)

# Porte de front/src/lib/trava-ip.ts. Mora no CACHE (Redis em producao, ver
# CACHES no settings), e nao num dict do modulo: um dict e' por processo, e
# com os 3 workers do gunicorn cada IP tinha tres contadores, e ate o triplo
# de tentativas antes do bloqueio, dependendo de qual worker atendia. Chave e' o IP, nao a
# conta: so' existe UMA conta de admin, e travar por conta deixaria qualquer um
# trancar o dono do site fora do proprio painel com cinco requisicoes.
_PREFIXO = "trava-admin:"


def ip_de(request) -> str:
    """O IP do cliente: o ULTIMO de `X-Forwarded-For`, o mesmo que o DRF le
    com `NUM_PROXIES = 1` (settings) — a trava e o limite de login contam o
    mesmo endereco.

    O ultimo, e nao o primeiro, porque o primeiro e' o que o cliente quiser
    escrever: cada proxy ACRESCENTA ao fim da lista, entao so' o fim foi
    escrito por quem a gente confia. Em producao o `HostDoProxyMiddleware` ja
    trocou a lista inteira pelo IP que o proxy.ts mandou, e ela tem um valor
    so'. `REMOTE_ADDR` sozinho seria sempre o endereco do proxy."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ultimo = xff.split(",")[-1].strip()
    return ultimo or request.META.get("REMOTE_ADDR", "") or "desconhecido"


def _agora_ms() -> float:
    # Relogio de parede, e nao `monotonic`: o registro e' lido por outro
    # processo, e o `monotonic` de cada processo conta de um zero diferente.
    return time.time() * 1000


def espera_de(ip: str) -> float:
    """Quantos ms faltam ate a proxima tentativa poder rodar. Zero = pode
    tentar agora. Conferido ANTES de tocar o argon2 — o argon2 e' caro de
    proposito, e deixar o atacante gastar CPU nele e' o que a trava evita."""
    f = cache.get(_PREFIXO + ip)
    if not f:
        return 0

    atraso = (
        ADMIN_TRAVA_BLOQUEIO_MS
        if f["quantas"] >= ADMIN_TRAVA_TENTATIVAS
        else min(ADMIN_TRAVA_BASE_MS * 2 ** (f["quantas"] - 1), ADMIN_TRAVA_TETO_MS)
    )
    decorrido = _agora_ms() - f["ultima_em"]
    return max(0.0, atraso - decorrido)


def falhas_de(ip: str) -> int:
    """So' usada pra' escolher o texto do erro (bloqueado vs. espera um
    pouco) — a decisao de deixar passar e' toda de `espera_de`."""
    f = cache.get(_PREFIXO + ip)
    return f["quantas"] if f else 0


def registrar_falha(ip: str) -> None:
    # Ler e gravar nao e' atomico, e aqui nao precisa: duas falhas simultaneas
    # contarem como uma so' adia a trava em uma tentativa, e o limite de login
    # por IP (app/api/v1/limite.py) ja segura a rajada antes daqui.
    quantas = falhas_de(ip) + 1
    # Expira sozinho depois do bloqueio mais longo: um registro velho nao
    # serve para nada e ficaria no Redis para sempre.
    cache.set(
        _PREFIXO + ip,
        {"quantas": quantas, "ultima_em": _agora_ms()},
        timeout=ADMIN_TRAVA_BLOQUEIO_MS // 1000,
    )


def limpar_falhas(ip: str) -> None:
    cache.delete(_PREFIXO + ip)
