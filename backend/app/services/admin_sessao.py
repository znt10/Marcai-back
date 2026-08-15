import os
from datetime import datetime, timedelta, timezone

import jwt

from tenant.config import ADMIN_SESSAO_COOKIE, ADMIN_SESSAO_HORAS

COOKIE_SESSAO_ADMIN = ADMIN_SESSAO_COOKIE

# Contrato do cookie do ADMIN — outro segredo, outras claims, outro cookie do
# que o do barbeiro (app.services.sessao). Divergir aqui e' o objetivo, nao
# um risco: "se fosse o mesmo segredo, vazar um vazaria os dois" (spec do
# admin, §4). Por isso este modulo NAO reusa nada de sessao.py alem do
# desenho geral (PyJWT, HS256, segredo lido a cada chamada).
ALGORITMO = "HS256"


def _segredo() -> str:
    """Lido a cada uso, nao capturado numa constante de modulo — mesma regra
    de `sessao._segredo()`: trocar ADMIN_JWT_SECRET tem que derrubar a
    sessao na hora.

    Sem default: um fallback aceitaria cookie assinado com segredo publico
    se alguem esquecesse a variavel no deploy, sem nada quebrar visivelmente.
    """
    valor = os.environ.get("ADMIN_JWT_SECRET")
    if not valor:
        raise RuntimeError(
            "ADMIN_JWT_SECRET nao definido. Precisa ser IGUAL ao do .env do "
            "front: o cookie e' emitido por um lado e lido pelo outro."
        )
    return valor


def emitir() -> str:
    """So' existe UMA conta de admin — nao ha `sub` de verdade pra carregar,
    so' o literal `'admin'`. Sem `bid`, sem `papel`, sem `tv`: nenhum desses
    tem sentido pra uma conta que nao pertence a barbearia nenhuma."""
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "admin", "iat": agora, "exp": agora + timedelta(hours=ADMIN_SESSAO_HORAS)},
        _segredo(),
        algorithm=ALGORITMO,
    )


def ler(token: str | None) -> bool:
    """A peneira inteira: pra' o admin nao ha peneira fina no banco, porque
    nao ha conta pra conferir alem da assinatura — e' por isso que esta
    funcao devolve `bool`, nao um dict de claims como a do barbeiro."""
    if not token:
        return False
    try:
        carga = jwt.decode(token, _segredo(), algorithms=[ALGORITMO])
    except jwt.InvalidTokenError:
        return False
    return carga.get("sub") == "admin"
