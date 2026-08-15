import logging
import os
import time

import requests

from tenant.config import (
    CHECK_NUMERO_LIMITE_POR_IP_HORA,
    CHECK_NUMERO_TIMEOUT_MS,
    CHECK_NUMERO_TTL_MS,
)

logger = logging.getLogger(__name__)

_HORA_MS = 3_600_000
_cache_numero: dict[str, dict] = {}
_uso_por_ip: dict[str, dict] = {}


def _agora_ms() -> float:
    return time.time() * 1000


def limpar_caches_numero() -> None:
    """So para teste — porte do `_limparCaches` do whatsapp.ts."""
    _cache_numero.clear()
    _uso_por_ip.clear()


def _config() -> dict[str, str]:
    """Lida a cada chamada, nao no topo do modulo: o teste troca as variaveis
    entre casos, e uma constante de modulo congelaria o primeiro valor —
    mesma razao do `config()` de whatsapp.ts.
    """
    return {
        "url": os.environ.get("EVOLUTION_API_URL", ""),
        "instancia": os.environ.get("EVOLUTION_INSTANCE", ""),
        "chave": os.environ.get("EVOLUTION_API_KEY", ""),
    }


def enviar_texto(whatsapp_digitos: str, mensagem: str) -> None:
    """Fire-and-forget. Falha de WhatsApp NUNCA derruba um agendamento (§10.2).

    Porte fiel de `enviarTexto` (marcai-front/src/lib/whatsapp.ts): loga e
    NUNCA lanca. `r.ok` e conferido e o corpo da resposta e logado no erro —
    numero desconectado devolve 400, chave errada devolve 401, e sem essa
    checagem os dois passavam sem uma linha de log, com o unico sintoma sendo
    o cliente nao receber nada.
    """
    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp] sem EVOLUTION_API_URL: %s %s", whatsapp_digitos, mensagem)
        return

    try:
        r = requests.post(
            f"{cfg['url']}/message/sendText/{cfg['instancia']}",
            json={"number": f"55{whatsapp_digitos}", "text": mensagem},
            headers={"apikey": cfg["chave"]},
            timeout=3,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp] falha ao enviar: %s", e)
        return

    if not r.ok:
        # O corpo e onde a Evolution diz o motivo — o que separa "instancia
        # desconectada" de "chave errada", as duas causas mais comuns.
        logger.error(
            "[whatsapp] envio recusado (%s) para %s: %s",
            r.status_code, whatsapp_digitos, r.text[:300],
        )
        return

    # ACEITO, nao "enviado": a Evolution devolve 201 com status PENDING mesmo
    # quando o vinculo esta morto e nada sai do lugar de verdade. Quem sabe
    # sobre entrega e o healthcheck do agendador, nao este log.
    corpo = None
    try:
        corpo = r.json()
    except ValueError:
        pass
    jid = (corpo or {}).get("key", {}).get("remoteJid", "?")
    status = (corpo or {}).get("status", "?")
    logger.info("[whatsapp] aceito para %s (jid %s, status %s)", whatsapp_digitos, jid, status)


def numero_existe(whatsapp_digitos: str, ip: str) -> str:
    """'existe' | 'nao_existe' | 'indeterminado'. Porte fiel de `numeroExiste`
    (whatsapp.ts). 'nao_existe' bloqueia o agendamento; 'indeterminado' deixa
    passar — indisponibilidade nao e' resposta (§10.5), entao SEM_URL, limite
    de IP estourado e falha de rede caem todos aqui, nunca em 'nao_existe'.

    So o fluxo PUBLICO chama isto — o painel nao, porque o barbeiro esta com
    o cliente na frente e o balcao e' um IP so, que o limite por hora
    morderia o uso legitimo.
    """
    cfg = _config()
    if not cfg["url"]:
        return "indeterminado"

    guardado = _cache_numero.get(whatsapp_digitos)
    if guardado and guardado["expira_em"] > _agora_ms():
        return "existe" if guardado["existe"] else "nao_existe"

    # Um formulario publico que responde "esse numero tem WhatsApp" e' uma
    # ferramenta de varredura. Sem limite, viram milhares de consultas.
    uso = _uso_por_ip.get(ip)
    if not uso or uso["janela_ate"] < _agora_ms():
        _uso_por_ip[ip] = {"contador": 1, "janela_ate": _agora_ms() + _HORA_MS}
    elif uso["contador"] >= CHECK_NUMERO_LIMITE_POR_IP_HORA:
        return "indeterminado"
    else:
        uso["contador"] += 1

    try:
        r = requests.post(
            f"{cfg['url']}/chat/whatsappNumbers/{cfg['instancia']}",
            json={"numbers": [f"55{whatsapp_digitos}"]},
            headers={"apikey": cfg["chave"]},
            timeout=CHECK_NUMERO_TIMEOUT_MS / 1000,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp] falha ao verificar numero: %s", e)
        return "indeterminado"

    if not r.ok:
        return "indeterminado"

    try:
        dados = r.json()
    except ValueError:
        return "indeterminado"

    existe = isinstance(dados, list) and len(dados) > 0 and dados[0].get("exists") is True
    _cache_numero[whatsapp_digitos] = {"existe": existe, "expira_em": _agora_ms() + CHECK_NUMERO_TTL_MS}
    return "existe" if existe else "nao_existe"
