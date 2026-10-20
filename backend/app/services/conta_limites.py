from django.core.cache import cache

from tenant.config import (
    CONTA_ENVIOS_POR_DIA,
    CONTA_ENVIOS_POR_IP_HORA,
    CONTA_ENVIOS_POR_NUMERO_DIA,
    CONTA_ENVIOS_POR_NUMERO_HORA,
)

# Quantos codigos/links o numero central manda por dia. Cada mensagem e'
# um envio pelo chip do Marcai, entao sem teto um script poderia gastar o chip
# (e o numero de qualquer vitima) em mensagens de "seu codigo".
#
# Mora no CACHE (Redis em producao), como `trava_ip`: um dict por processo
# multiplicaria o limite pelos workers do gunicorn. Janela fixa: `cache.add`
# cria o contador com validade igual a janela e `cache.incr` soma, ambos
# atomicos. `motivo_para_nao_enviar` so' CONFERE e `registrar_envio` so'
# CONTA — separados porque quem chama so' conta o que de fato mandou (envio
# recusado pela Evolution nao gasta a cota do cliente).
_PREFIXO = "conta-envio:"
_HORA = 3600
_DIA = 86400


def _chaves(whatsapp: str, ip: str) -> dict[str, str]:
    return {
        "numero_hora": f"{_PREFIXO}num-h:{whatsapp}",
        "numero_dia": f"{_PREFIXO}num-d:{whatsapp}",
        "ip_hora": f"{_PREFIXO}ip-h:{ip}",
        "teto": f"{_PREFIXO}teto-d",
    }


def motivo_para_nao_enviar(whatsapp: str, ip: str) -> str | None:
    """`None` se pode mandar; senao `"numero"`, `"ip"` ou `"teto"`. Nao conta."""
    k = _chaves(whatsapp, ip)
    if (cache.get(k["numero_hora"], 0) >= CONTA_ENVIOS_POR_NUMERO_HORA
            or cache.get(k["numero_dia"], 0) >= CONTA_ENVIOS_POR_NUMERO_DIA):
        return "numero"
    if cache.get(k["ip_hora"], 0) >= CONTA_ENVIOS_POR_IP_HORA:
        return "ip"
    if cache.get(k["teto"], 0) >= CONTA_ENVIOS_POR_DIA:
        return "teto"
    return None


def _somar(chave: str, janela: int) -> None:
    cache.add(chave, 0, timeout=janela)
    try:
        cache.incr(chave)
    except ValueError:
        # A chave venceu entre o add e o incr: recomeca a janela com este envio.
        cache.set(chave, 1, timeout=janela)


def registrar_envio(whatsapp: str, ip: str) -> None:
    """Conta um envio nas quatro janelas."""
    k = _chaves(whatsapp, ip)
    _somar(k["numero_hora"], _HORA)
    _somar(k["numero_dia"], _DIA)
    _somar(k["ip_hora"], _HORA)
    _somar(k["teto"], _DIA)
