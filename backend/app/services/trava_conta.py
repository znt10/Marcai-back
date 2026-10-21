import time

from django.core.cache import cache

from tenant.config import CONTA_TRAVA_BASE_MS, CONTA_TRAVA_TETO_MS

# Copia enxuta de `trava_ip.py` para o login da CONTA. Mesmas razoes: mora no
# cache (Redis, compartilhado entre os workers) e conta pelo relogio de parede.
#
# Diferencas, de proposito:
# - a chave e' o NUMERO, nao o IP: o que se protege e' a senha de uma conta, e
#   quem tenta de varios IPs continua batendo na mesma espera;
# - NAO ha bloqueio longo. So' uma espera que dobra a cada erro (BASE, 2*BASE,
#   4*BASE...) ate o TETO. Um bloqueio de minutos permitiria a qualquer um
#   trancar a conta alheia so' errando a senha dela; com o teto de 30s o pior
#   que o atacante faz e' atrasar o dono em meio minuto, e ele mesmo fica
#   limitado a duas tentativas por minuto.
_PREFIXO = "trava-conta:"
# Quanto tempo o contador sobrevive sem novas falhas. Mais que o teto, senao
# esperar o teto zerava a escada e o atacante voltava a 1s por tentativa.
_VALIDADE_S = 15 * 60


def _agora_ms() -> float:
    return time.time() * 1000


def espera_de(whatsapp: str) -> float:
    """Quantos ms faltam ate a proxima tentativa poder rodar (0 = pode agora).
    Conferido ANTES de tocar o argon2, que e' caro de proposito."""
    f = cache.get(_PREFIXO + whatsapp)
    if not f:
        return 0
    # O expoente tem folga de sobra: o teto ja' e' atingido em ~5 erros, o `min`
    # so' evita calcular uma potencia gigante se o contador crescer muito.
    atraso = min(
        CONTA_TRAVA_BASE_MS * 2 ** min(f["quantas"] - 1, 30), CONTA_TRAVA_TETO_MS
    )
    return max(0.0, atraso - (_agora_ms() - f["ultima_em"]))


def registrar_falha(whatsapp: str) -> None:
    # Ler e gravar nao e' atomico, e aqui nao precisa: duas falhas simultaneas
    # contarem como uma adia a escada em um degrau.
    f = cache.get(_PREFIXO + whatsapp)
    quantas = (f["quantas"] if f else 0) + 1
    cache.set(
        _PREFIXO + whatsapp,
        {"quantas": quantas, "ultima_em": _agora_ms()},
        timeout=_VALIDADE_S,
    )


def limpar(whatsapp: str) -> None:
    cache.delete(_PREFIXO + whatsapp)
