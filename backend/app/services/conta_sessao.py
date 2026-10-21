from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings

from app.services.sessao import ALGORITMO, _segredo
from tenant.config import CONTA_SESSAO_COOKIE, CONTA_SESSAO_DIAS
from tenant.identidade import como_uuid
from tenant.models import ContaCliente

# A sessao da CONTA do cliente. Mesmo segredo e mesmo algoritmo da do barbeiro
# (`sessao.py`), de proposito: um segredo a menos para guardar. O que impede um
# token de valer no lugar do outro e' a audiencia — este leva `aud="cliente"`, o
# do barbeiro nao leva nenhuma. O PyJWT recusa um token COM `aud` quando o
# decode nao pede audiencia (e vice-versa), entao o cookie da conta nao abre o
# painel e o do painel nao abre a conta. tests/test_conta_sessao.py trava os
# dois sentidos.
AUDIENCIA = "cliente"


def emitir(conta_id, tv: int) -> str:
    """`str()` em `sub` pelo mesmo motivo do `sessao.emitir`: o JWT e' texto, e
    `conta.id` chega aqui como `uuid.UUID`."""
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(conta_id),
            "tv": tv,
            "aud": AUDIENCIA,
            "iat": agora,
            "exp": agora + timedelta(days=CONTA_SESSAO_DIAS),
        },
        _segredo(),
        algorithm=ALGORITMO,
    )


def ler(token: str | None) -> dict | None:
    """A peneira grossa: assinatura, validade e audiencia. Mesma conferencia de
    tipo do `sessao.ler`, pelas mesmas razoes (`tv` como string faria a
    comparacao com o inteiro do banco dar False calado; `tv: true` passaria
    como 1). `algorithms` explicito: sem ele `alg: none` viraria cookie forjado.
    """
    if not token:
        return None
    try:
        carga = jwt.decode(
            token, _segredo(), algorithms=[ALGORITMO], audience=AUDIENCIA
        )
    except jwt.InvalidTokenError:
        return None

    sub, tv = carga.get("sub"), carga.get("tv")
    if not isinstance(sub, str):
        return None
    # UUID para dentro, texto no cookie: a conversao fica aqui para o consumidor
    # nao comparar UUID com str (da' sempre "diferente", sem erro nenhum).
    sub = como_uuid(sub)
    if sub is None:
        return None
    if not isinstance(tv, int) or isinstance(tv, bool):
        return None
    return {"sub": sub, "tv": tv}


def conta_da_requisicao(request) -> ContaCliente | None:
    """A peneira fina: a conta existe, esta CONFIRMADA e `tv` bate com
    `token_version`. Conta nao confirmada nao entra (o cliente nao provou o
    numero), e trocar a senha sobe `token_version` e derruba toda sessao.

    `ContaCliente` e' global, fora do RLS: le direto, sem `com_barbearia`.
    """
    sessao = ler(request.COOKIES.get(CONTA_SESSAO_COOKIE))
    if sessao is None:
        return None
    conta = ContaCliente.objects.filter(id=sessao["sub"]).first()
    if conta is None or conta.confirmada_em is None:
        return None
    if conta.token_version != sessao["tv"]:
        return None
    return conta


def dominio_do_cookie() -> str | None:
    """`.<DOMINIO_BASE>` em producao: o cookie vale em todos os subdominios
    (`brutus.usemarcai.online`, `outra.usemarcai.online`), porque a conta e'
    global e o cliente nao deve logar de novo ao trocar de estabelecimento.

    No dev (`localhost` ou `*.localhost`) devolve None e o cookie fica host-only:
    navegadores nao aceitam `Domain=.localhost` de forma confiavel. O custo e'
    que, no dev, o login NAO atravessa subdominios — cada `x.localhost` tem o
    seu. Em producao isso nao existe.
    """
    base = settings.DOMINIO_BASE
    if base == "localhost" or base.endswith(".localhost"):
        return None
    return f".{base}"


def plantar(resposta, conta):
    resposta.set_cookie(
        CONTA_SESSAO_COOKIE,
        emitir(conta.id, conta.token_version),
        max_age=CONTA_SESSAO_DIAS * 24 * 3600,
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
        path="/",
        domain=dominio_do_cookie(),
    )
    return resposta


def apagar(resposta):
    # `domain` e `path` PRECISAM ser os mesmos do `plantar`: o navegador trata
    # cookie com outro dominio/caminho como outro cookie e nao apaga o certo.
    resposta.delete_cookie(
        CONTA_SESSAO_COOKIE,
        path="/",
        domain=dominio_do_cookie(),
        samesite="Lax",
    )
    return resposta
