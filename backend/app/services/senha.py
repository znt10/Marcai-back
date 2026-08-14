import hashlib
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

# Os parametros sao os do `@node-rs/argon2` do outro lado, CONFERIDOS no fio e
# nao supostos: um `hash('teste')` la produz `$argon2id$v=19$m=19456,t=2,p=1$`.
#
# Para CONFERIR uma senha eles nem seriam necessarios — o formato codificado
# carrega os proprios parametros, e por isso cada lado le o hash do outro sem
# combinar nada. Eles existem porque o convite ESCREVE hash: sem fixa-los, o
# Python usaria os proprios defaults (m=65536, t=3, p=4) e o banco passaria a
# ter duas familias de hash, com custos diferentes, dependendo de qual lado
# atendeu o convite naquele dia. Nada quebraria — e por isso ninguem notaria.
_hasher = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1)


def gerar(senha: str) -> str:
    return _hasher.hash(senha)


def confere(hash_guardado: str, senha: str) -> bool:
    try:
        return _hasher.verify(hash_guardado, senha)
    except (Argon2Error, ValueError, TypeError):
        # ValueError/TypeError cobrem hash corrompido ou nao-argon2 na coluna:
        # e recusa, nao erro de servidor. Um 500 aqui diria ao atacante que
        # aquele numero tem conta com hash estranho.
        return False


_descartavel: str | None = None


def hash_descartavel() -> str:
    """Um hash real de uma senha que ninguem sabe, para conferir contra quando
    NAO EXISTE barbeiro.

    Sem isto a resposta generica do login vira teatro: `/api/auth/login` sempre
    responde a mesma coisa para numero inexistente e senha errada, mas o
    RELOGIO nao — o caso sem barbeiro voltaria em microssegundos e o caso com
    barbeiro gastaria os ~50ms do argon2. A diferenca e medivel de fora e
    enumera a equipe inteira, que e exatamente o que a resposta unica existe
    para impedir.

    Calculado uma vez por processo e guardado: e caro de proposito, e paga-lo
    a cada tentativa daria ao atacante um jeito barato de ocupar a CPU.
    """
    global _descartavel
    if _descartavel is None:
        _descartavel = gerar(str(uuid.uuid4()))
    return _descartavel


def hash_de_convite(token: str) -> str:
    """SHA-256 hex, e NAO argon2 — a mesma escolha do `hashDe` do convite.ts, e
    ela e deliberada dos dois lados: o token tem 32 bytes aleatorios, entao nao
    ha o que adivinhar por forca bruta. O alongamento de chave do argon2 existe
    para senha escolhida por gente, que tem pouca entropia; gasta-lo num token
    aleatorio e custo sem defesa correspondente.

    Trocar isto por argon2 aqui nao seria "mais seguro": tornaria todo convite
    ja emitido invalido, porque a busca e feita PELO HASH e o valor mudaria.
    """
    return hashlib.sha256(token.encode()).hexdigest()
