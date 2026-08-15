import logging
import os

import requests

logger = logging.getLogger(__name__)


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
