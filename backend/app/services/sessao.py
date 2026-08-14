import os
from datetime import datetime, timedelta, timezone

import jwt

from tenant.config import SESSAO_BARBEIRO_COOKIE, SESSAO_BARBEIRO_HORAS
from tenant.models import Barbeiro
from tenant.rls import com_barbearia

COOKIE_SESSAO = SESSAO_BARBEIRO_COOKIE

# O contrato do cookie NAO E ESCOLHA DESTE MODULO. Ele ja existe em
# front/src/lib/auth.ts e ja esta no navegador de quem usa o sistema: HS256,
# segredo SESSAO_JWT_SECRET em utf-8 cru, claims `sub` (barbeiroId), `bid`
# (barbeariaId), `papel` e `tv` (tokenVersion).
#
# Durante a travessia os DOIS lados emitem e os DOIS leem — quem serve cada
# rota depende do MIGRADAS, e o barbeiro nao faz login de novo ao trocar de
# tela. Qualquer divergencia aqui (algoritmo, nome de claim, tipo de `tv`)
# aparece como "deslogado do nada" numa rota so, que e o tipo de defeito que
# se persegue por dias. Este modulo copia o outro lado ao pe da letra.
ALGORITMO = "HS256"


def _segredo() -> str:
    """Lido a cada uso, nao capturado numa constante de modulo — mesma regra do
    `segredo()` do auth.ts: trocar SESSAO_JWT_SECRET tem que derrubar toda
    sessao na hora, e uma constante de modulo so mudaria no proximo restart.

    Sem default. Um fallback aqui faria o Django aceitar cookies assinados com
    um segredo publico se alguem esquecesse a variavel no deploy — e nada
    quebraria, que e exatamente o perigo.
    """
    valor = os.environ.get("SESSAO_JWT_SECRET")
    if not valor:
        raise RuntimeError(
            "SESSAO_JWT_SECRET nao definido. Ele precisa ser IGUAL ao do .env "
            "do front: o cookie e emitido por um lado e lido pelo outro."
        )
    return valor


def emitir(*, sub: str, bid: str, papel: str, tv: int) -> str:
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": sub,
            "bid": bid,
            "papel": papel,
            "tv": tv,
            "iat": agora,
            "exp": agora + timedelta(hours=SESSAO_BARBEIRO_HORAS),
        },
        _segredo(),
        algorithm=ALGORITMO,
    )


def ler(token: str | None) -> dict | None:
    """A peneira GROSSA: assinatura e validade, e mais nada.

    Espelha `lerSessao` do auth.ts, inclusive na conferencia de tipo de cada
    claim. Isso nao e paranoia com o proprio token: um cookie de ADMIN
    apresentado aqui ja falha na assinatura (os dois segredos sao diferentes de
    proposito), mas um token legitimo de uma versao futura do formato passaria
    pela assinatura e chegaria torto — e `tv` chegando como string faria a
    comparacao com o inteiro do banco dar False calado, deslogando todo mundo.

    `algorithms` explicito e obrigatorio: sem ele o PyJWT aceitaria o algoritmo
    que o proprio token declara no cabecalho, e `alg: none` viraria um cookie
    que qualquer um forja.
    """
    if not token:
        return None
    try:
        carga = jwt.decode(token, _segredo(), algorithms=[ALGORITMO])
    except jwt.InvalidTokenError:
        return None

    sub, bid, papel, tv = (carga.get(k) for k in ("sub", "bid", "papel", "tv"))
    if not isinstance(sub, str) or not isinstance(bid, str):
        return None
    if papel not in ("DONO", "BARBEIRO"):
        return None
    # `isinstance(True, int)` e True em Python, e um `tv: true` no token
    # passaria e depois compararia igual a 1 no banco. bool sai fora na mao.
    if not isinstance(tv, int) or isinstance(tv, bool):
        return None
    return {"sub": sub, "bid": bid, "papel": papel, "tv": tv}


def da_requisicao(request) -> dict | None:
    """A peneira FINA: as tres conferencias que exigem banco.

    Espelha `sessaoDaRequisicao` do sessao-painel.ts. Do lado Next essas tres
    NAO podiam morar no proxy.ts porque ele roda em Edge e o Prisma nao roda
    la. Aqui nao ha essa restricao, e por isso elas moram no middleware — mas
    continuam sendo as mesmas tres, e cada uma responde a uma pergunta que a
    assinatura sozinha nao responde:

    1. `bid` == a barbearia DESTE host. O pior bug possivel do multi-tenant:
       token valido, barbeiro existente, e mesmo assim de outra barbearia. Sem
       esta linha, um dono de barbearia logado abre `outra.localhost` e entra
       no painel dela com o proprio cookie.
    2. o barbeiro continua ATIVO. Desligar alguem tem que valer agora, nao
       daqui a 12 horas.
    3. `tv` == tokenVersion do banco. E o que faz "derrubar as sessoes" ser
       possivel sem existir lista de sessao para varrer.

    O resultado fica pendurado no request porque middleware e view perguntam a
    mesma coisa: sem a memoria, todo pedido de painel faria a consulta duas
    vezes, e as duas dentro de transacoes diferentes.
    """
    if hasattr(request, "_sessao"):
        return request._sessao

    request._sessao = _resolver(request)
    return request._sessao


def _resolver(request) -> dict | None:
    barbearia = getattr(request, "barbearia", None)
    if barbearia is None:
        # Host do admin (ou host sem barbearia): nao ha sessao de barbeiro a
        # ter. Recusar aqui, e nao deixar o `bid` decidir, evita depender de
        # `barbearia.id` numa linha onde `barbearia` e None.
        return None

    sessao = ler(request.COOKIES.get(COOKIE_SESSAO))
    if sessao is None:
        return None
    if sessao["bid"] != barbearia.id:
        return None

    with com_barbearia(barbearia.id):
        barbeiro = (
            Barbeiro.objects.filter(id=sessao["sub"])
            .values("ativo", "token_version")
            .first()
        )

    if not barbeiro or not barbeiro["ativo"]:
        return None
    if barbeiro["token_version"] != sessao["tv"]:
        return None
    return sessao
