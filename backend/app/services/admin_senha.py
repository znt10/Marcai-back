import base64
import logging
import os
import uuid

from django.conf import settings

from .senha import confere, gerar

# So' existe UMA conta de admin, sem tabela. O usuario e' ADMIN_USUARIO
# (texto puro); a senha entra por UMA de duas variaveis:
#
#   ADMIN_SENHA_HASH_B64  hash argon2id, em BASE64. O base64 existe porque o
#                         hash em claro tem `$` (`$argon2id$v=19$m=...`), que
#                         tanto o dotenv quanto o Docker Compose expandem como
#                         inicio de variavel — o valor chegaria truncado ao
#                         processo sem avisar nada.
#   ADMIN_SENHA           a senha LEGIVEL. Conveniencia de desenvolvimento:
#                         quem sobe o projeto na propria maquina quer ler a
#                         senha no .env e entrar, nao rodar `admin_hash` antes.
#
# O hash TEM PRECEDENCIA. Quem ja' configurou producao com ele nao passa a
# depender de um ADMIN_SENHA esquecido no arquivo — e a ordem torna a
# migracao para o hash uma linha nova, sem apagar nada.
#
# Vale dizer o que se perde com a senha em claro, porque nao e' nada: um
# arquivo com a senha legivel entrega a conta a quem o ler — um backup, um
# `docker inspect`, um log de ambiente. O hash nao entrega. Por isso o aviso
# abaixo quando DEBUG esta desligado.

logger = logging.getLogger(__name__)

_descartavel: str | None = None
# (senha em claro, hash dela). Cacheado porque argon2 custa dezenas de
# milissegundos de proposito, e re-derivar a cada login transformaria a tela
# de entrada num alvo barato. A senha entra na chave para que editar o .env
# passe a valer sem reiniciar — e para o cache nunca responder pelo valor
# velho.
_em_claro: tuple[str, str] | None = None
_avisou = False


def _hash_descartavel() -> str:
    """Proprio do admin, e nao `senha.hash_descartavel()`: sao dois relogios
    diferentes que nao podem vazar um no outro — ver o comentario da versao
    do barbeiro, o motivo e' o mesmo."""
    global _descartavel
    if _descartavel is None:
        _descartavel = gerar(str(uuid.uuid4()))
    return _descartavel


def _hash_da_senha_em_claro() -> str | None:
    """Deriva o mesmo tipo de hash que `admin_hash` geraria, a partir de
    ADMIN_SENHA. Devolver hash — e nao comparar texto com texto — e o que
    mantem `conferir_senha` com UM caminho so': mesmo relogio, mesma
    comparacao, independente de qual das duas variaveis configurou a conta."""
    global _em_claro, _avisou
    senha = os.environ.get("ADMIN_SENHA")
    if not senha:
        return None
    if not settings.DEBUG and not _avisou:
        _avisou = True
        logger.warning(
            "[admin] ADMIN_SENHA (senha em claro) em uso com DEBUG desligado. "
            "Em producao, prefira ADMIN_SENHA_HASH_B64: gere com "
            "`manage.py admin_hash 'a-senha'`."
        )
    if _em_claro is None or _em_claro[0] != senha:
        _em_claro = (senha, gerar(senha))
    return _em_claro[1]


def _hash_esperado() -> str | None:
    bruto = os.environ.get("ADMIN_SENHA_HASH_B64")
    if not bruto:
        return _hash_da_senha_em_claro()
    try:
        return base64.b64decode(bruto).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        # Hash ilegivel e' configuracao QUEBRADA, nao configuracao ausente:
        # cair no ADMIN_SENHA aqui trocaria em silencio a senha de producao
        # pela de desenvolvimento esquecida no arquivo.
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
