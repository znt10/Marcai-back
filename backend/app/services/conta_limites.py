from django.core.cache import cache

from tenant.config import (
    CONTA_ENVIOS_POR_DIA,
    CONTA_ENVIOS_POR_IP_HORA,
    CONTA_ENVIOS_POR_NUMERO_DIA,
    CONTA_ENVIOS_POR_NUMERO_HORA,
)

# Quantos codigos/links o numero central manda por hora e por dia. Cada
# mensagem e' um envio pelo chip do Marcai, entao sem limite um script poderia
# gastar o chip (e o numero de qualquer vitima) em mensagens de "seu codigo".
#
# RESERVA, e nao "confere e depois conta": quem chama faz
#
#     motivo = reservar_envio(whatsapp, ip)   # None = a vaga ja e' sua
#     if motivo: recusa
#     if not enviar_pelo_central(...): devolver_envio(whatsapp, ip)
#
# Conferir antes e contar depois do envio (que e' uma chamada HTTP lenta) deixa
# N pedidos paralelos verem todos "0 envios" e mandarem todos. Aqui o `incr`
# devolve o valor novo de forma atomica, entao cada pedido concorrente enxerga
# um numero diferente e so' os primeiros ficam abaixo do limite. Quando o envio
# falha, `devolver_envio` devolve a vaga: recusa da Evolution nao gasta cota do
# cliente.
#
# Mora no CACHE (Redis em producao), como `trava_ip`: um dict por processo
# multiplicaria o limite pelos workers do gunicorn. Janela fixa: `cache.add`
# cria o contador com validade igual a janela e `cache.incr` soma.
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


_JANELAS = {"numero_hora": _HORA, "numero_dia": _DIA, "ip_hora": _HORA, "teto": _DIA}


def _somar(chave: str, janela: int) -> int:
    """Soma 1 e devolve o valor novo, que e' o que torna a reserva atomica."""
    cache.add(chave, 0, timeout=janela)
    try:
        return cache.incr(chave)
    except ValueError:
        # A chave venceu entre o add e o incr: recomeca a janela com este envio.
        cache.set(chave, 1, timeout=janela)
        return 1


def _subtrair(chave: str) -> None:
    try:
        cache.decr(chave)
    except ValueError:
        # Contador ja venceu: nao ha o que devolver.
        pass


def reservar_envio(whatsapp: str, ip: str) -> str | None:
    """Reserva uma vaga nas quatro janelas. `None` = reservada (a cota ja foi
    gasta); senao `"numero"`, `"ip"` ou `"teto"`, e nada fica gasto: se qualquer
    janela estourou, as quatro voltam ao que eram."""
    k = _chaves(whatsapp, ip)
    novos = {nome: _somar(chave, _JANELAS[nome]) for nome, chave in k.items()}

    if (novos["numero_hora"] > CONTA_ENVIOS_POR_NUMERO_HORA
            or novos["numero_dia"] > CONTA_ENVIOS_POR_NUMERO_DIA):
        motivo = "numero"
    elif novos["ip_hora"] > CONTA_ENVIOS_POR_IP_HORA:
        motivo = "ip"
    elif novos["teto"] > CONTA_ENVIOS_POR_DIA:
        motivo = "teto"
    else:
        return None

    devolver_envio(whatsapp, ip)
    return motivo


def devolver_envio(whatsapp: str, ip: str) -> None:
    """Devolve a vaga das quatro janelas: o envio reservado nao saiu."""
    for chave in _chaves(whatsapp, ip).values():
        _subtrair(chave)
