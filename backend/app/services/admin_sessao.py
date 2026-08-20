import os
from datetime import datetime, timedelta, timezone

import jwt

from tenant.config import ADMIN_SESSAO_COOKIE, ADMIN_SESSAO_HORAS
from tenant.identidade import como_uuid

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
            "ADMIN_JWT_SECRET nao definido. Sem ele nao ha como assinar cookie."
        )
    return valor


def emitir(sub) -> str:
    """`sub` de verdade desde a fatia 3 — era o literal `'admin'`, porque a
    conta nao existia em lugar nenhum para ter id.

    Continua sem `bid`, sem `papel` e sem `tv`: nenhum desses tem sentido para
    uma conta que nao pertence a barbearia nenhuma, e o `papel` do admin ja e a
    propria existencia da linha com `barbearia_id IS NULL`.

    `str()` pelo mesmo motivo do `sessao.emitir()`: JWT e um formato de texto e
    o id e um `uuid.UUID`."""
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(sub), "iat": agora, "exp": agora + timedelta(hours=ADMIN_SESSAO_HORAS)},
        _segredo(),
        algorithm=ALGORITMO,
    )


def ler(token: str | None):
    """Devolve o `sub` (um `uuid.UUID`) ou None. Era `bool`, porque o `sub` era
    sempre o mesmo literal e nao carregava informacao nenhuma.

    Continua sem peneira fina no banco, ao contrario da sessao do barbeiro: nao
    ha `tokenVersion` de admin a conferir a cada pedido. Trocar
    ADMIN_JWT_SECRET continua sendo o jeito de derrubar a sessao dele."""
    if not token:
        return None
    try:
        carga = jwt.decode(token, _segredo(), algorithms=[ALGORITMO])
    except jwt.InvalidTokenError:
        return None
    return como_uuid(carga.get("sub"))
