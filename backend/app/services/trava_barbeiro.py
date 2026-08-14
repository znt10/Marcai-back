from datetime import datetime, timedelta, timezone

from tenant.config import BARBEIRO_TRAVA_MIN, BARBEIRO_TRAVA_TENTATIVAS
from tenant.datas import como_utc

# Porte literal de front/src/lib/trava-barbeiro.ts, e o comentario de la vale
# inteiro aqui: a trava do BARBEIRO e POR CONTA e mora no BANCO — o oposto da
# trava do admin, que e por IP e vive em memoria.
#
# Os dois motivos, que sao o que impede alguem de "simplificar" isto depois:
#
# - a barbearia inteira sai do mesmo IP, e travar o IP derrubaria a equipe
#   toda por causa de um funcionario desmemoriado;
# - sao muitas contas, entao um atacante que espere o processo reciclar
#   zeraria um contador em memoria de graca.
#
# Funcoes PURAS: quem aplica o resultado e a rota, com um update. E assim que
# a regra fica testavel sem cenario e sem Postgres.

LIMPO = {"tentativas_login": 0, "bloqueado_ate": None}


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def esta_travado(bloqueado_ate: datetime | None, agora: datetime | None = None) -> bool:
    bloqueado_ate = como_utc(bloqueado_ate)
    if bloqueado_ate is None:
        return False
    return bloqueado_ate > (agora or agora_utc())


def apos_falha(tentativas: int, agora: datetime | None = None) -> dict:
    """A trava so nasce NA falha que atinge o limite, e some no primeiro
    acerto. Nao ha decaimento por tempo do contador de proposito: quem errou
    quatro vezes e acertou na quinta zera tudo (o `LIMPO` da rota), e quem
    errou cinco espera os 15 minutos inteiros.
    """
    agora = agora or agora_utc()
    tentativas_login = tentativas + 1
    return {
        "tentativas_login": tentativas_login,
        "bloqueado_ate": (
            agora + timedelta(minutes=BARBEIRO_TRAVA_MIN)
            if tentativas_login >= BARBEIRO_TRAVA_TENTATIVAS
            else None
        ),
    }
