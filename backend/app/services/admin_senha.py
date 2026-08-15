import base64
import os
import uuid

from .senha import confere, gerar

# So' existe UMA conta de admin, sem tabela — dois env vars: ADMIN_USUARIO
# (texto puro) e ADMIN_SENHA_HASH_B64 (hash argon2id, em BASE64). O base64
# existe porque o hash em claro tem `$` (`$argon2id$v=19$m=...`), que tanto
# o dotenv do front quanto o Docker Compose expandem como inicio de
# variavel — o valor chegaria truncado ao processo sem avisar nada.

_descartavel: str | None = None


def _hash_descartavel() -> str:
    """Proprio do admin, e nao `senha.hash_descartavel()`: sao dois relogios
    diferentes que nao podem vazar um no outro — ver o comentario da versao
    do barbeiro, o motivo e' o mesmo."""
    global _descartavel
    if _descartavel is None:
        _descartavel = gerar(str(uuid.uuid4()))
    return _descartavel


def _hash_esperado() -> str | None:
    bruto = os.environ.get("ADMIN_SENHA_HASH_B64")
    if not bruto:
        return None
    try:
        return base64.b64decode(bruto).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def conferir_senha(usuario: str, senha: str) -> bool:
    """Resposta UNICA pra usuario errado e senha errada — e o RELOGIO
    tambem precisa ser unico, por isso `confere()` roda SEMPRE, mesmo
    quando o usuario ja esta errado (contra um hash descartavel real)."""
    usuario_bate = usuario == os.environ.get("ADMIN_USUARIO")
    esperado = _hash_esperado()
    hash_alvo = esperado if (usuario_bate and esperado) else _hash_descartavel()
    senha_bate = confere(hash_alvo, senha)
    return usuario_bate and senha_bate
