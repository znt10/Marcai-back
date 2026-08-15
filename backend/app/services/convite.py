import os
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.utils import timezone

from tenant.config import CONVITE_VALIDADE_HORAS

from .senha import hash_de_convite

_PADRAO = "http://localhost:3000"


def gerar_convite() -> dict:
    """Porte fiel de `gerarConvite` (front/src/lib/convite.ts). Guardar so o
    hash pelo mesmo motivo da senha: quem ler o banco nao ganha acesso a
    conta nenhuma.

    `secrets.token_urlsafe(32)` gera os mesmos 32 bytes aleatorios em
    base64url que o `randomBytes(32).toString('base64url')` do lado Node —
    nao ha o que combinar entre os dois, e o token nunca e comparado entre
    linguagens (a busca no banco e sempre pelo hash).
    """
    token = secrets.token_urlsafe(32)
    return {
        "token": token,
        "hash": hash_de_convite(token),
        "expira_em": timezone.now() + timedelta(hours=CONVITE_VALIDADE_HORAS),
    }


def _base_valida() -> tuple[str, str]:
    """`(esquema, host)` da URL base do FRONT — o convite abre no Next, nunca
    no Django, entao a variavel e URL_BASE (espelha NEXT_PUBLIC_URL_BASE), nao
    DOMINIO_BASE (que e so o dominio, sem porta, usado para resolver tenant).

    Roda depois do commit (o barbeiro/barbearia ja esta gravado quando o erro
    subiria) — igual ao original, uma variavel mal preenchida no deploy nao
    pode custar o link em claro, que so existe uma vez.
    """
    bruta = (os.environ.get("URL_BASE") or "").strip()
    if not bruta:
        base = urlsplit(_PADRAO)
        return base.scheme, base.netloc
    com_esquema = bruta if bruta.startswith(("http://", "https://")) else f"https://{bruta}"
    try:
        base = urlsplit(com_esquema)
        if not base.netloc:
            raise ValueError
        return base.scheme, base.netloc
    except ValueError:
        base = urlsplit(_PADRAO)
        return base.scheme, base.netloc


def link_do_convite(slug: str, token: str) -> str:
    esquema, host = _base_valida()
    return f"{esquema}://{slug}.{host}/convite/{token}"
