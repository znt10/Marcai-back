import time

from tenant.config import (
    ADMIN_TRAVA_BASE_MS,
    ADMIN_TRAVA_BLOQUEIO_MS,
    ADMIN_TRAVA_TENTATIVAS,
    ADMIN_TRAVA_TETO_MS,
)

# Porte de front/src/lib/trava-ip.ts. Em MEMORIA, e isso e' aceito de
# proposito, nao esquecido — so' vale enquanto o deploy for uma instancia so;
# virando multi-instancia, migra pra tabela. Chave e' o IP, nao a conta:
# so' existe UMA conta de admin, e travar por conta deixaria qualquer um
# trancar o dono do site fora do proprio painel com cinco requisicoes.
_falhas: dict[str, dict] = {}


def ip_de(request) -> str:
    """Porte do `ipDe` do route.ts: primeiro IP de `X-Forwarded-For`, porque
    quem termina a conexao TCP de verdade e' o proxy reverso, nao o
    atacante — `REMOTE_ADDR` seria sempre o mesmo endereco do proxy."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    primeiro = xff.split(",")[0].strip()
    return primeiro or request.META.get("REMOTE_ADDR", "") or "desconhecido"


def _agora_ms() -> float:
    return time.monotonic() * 1000


def espera_de(ip: str) -> float:
    """Quantos ms faltam ate a proxima tentativa poder rodar. Zero = pode
    tentar agora. Conferido ANTES de tocar o argon2 — o argon2 e' caro de
    proposito, e deixar o atacante gastar CPU nele e' o que a trava evita."""
    f = _falhas.get(ip)
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
    f = _falhas.get(ip)
    return f["quantas"] if f else 0


def registrar_falha(ip: str) -> None:
    quantas = _falhas.get(ip, {}).get("quantas", 0) + 1
    _falhas[ip] = {"quantas": quantas, "ultima_em": _agora_ms()}


def limpar_falhas(ip: str) -> None:
    _falhas.pop(ip, None)
