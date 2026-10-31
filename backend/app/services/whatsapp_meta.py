"""O numero central pela API oficial da Meta (WhatsApp Cloud API).

Liga com `WHATSAPP_PROVEDOR=meta`; sem isso tudo continua pela Evolution, e
voltar atras e' so' apagar a variavel. Quem chama nao muda: `whatsapp.py`
pergunta `ligado()` e desvia para ca' — os avisos, a lista do dia e o codigo
da conta nao sabem qual dos dois mandou.

**A regra que a Meta impoe e a Evolution nao:** texto livre so' sai para
quem falou com o numero nas ultimas 24 horas. Fora disso — que e' o caso de
quase tudo que o Marcai manda (lembrete, lista do dia, aviso de horario) — a
Meta so' entrega um TEMPLATE aprovado. E ela NAO recusa o texto na hora:
aceita com 200 e so' depois avisa a falha (131047) pelo webhook — medido em
30/10, quando nenhum outro numero recebia. Por isso, com
`META_WHATSAPP_TEMPLATE` configurado, TUDO sai pelo template, com a mensagem
inteira no `{{1}}`. Sem template, sai como texto (so' chega a quem falou com
o numero nas ultimas 24h).

Nunca levanta, mesmo contrato do `_enviar_aceita`: falha de WhatsApp nao
derruba agendamento.
"""

import hashlib
import hmac
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

# Limite do corpo de um template: 1024 caracteres no total, e o texto fixo
# do template come uma parte. Folga para um cabecalho curto.
_LIMITE_PARAMETRO = 900


def ligado() -> bool:
    return os.environ.get("WHATSAPP_PROVEDOR", "").strip().lower() == "meta"


def _config() -> dict[str, str]:
    """Lida a cada chamada pelo mesmo motivo do `whatsapp._config`."""
    return {
        "token": os.environ.get("META_WHATSAPP_TOKEN", ""),
        "numero_id": os.environ.get("META_WHATSAPP_NUMERO_ID", ""),
        "versao": os.environ.get("META_GRAPH_VERSAO", "") or "v21.0",
        "template": os.environ.get("META_WHATSAPP_TEMPLATE", ""),
        "idioma": os.environ.get("META_WHATSAPP_TEMPLATE_IDIOMA", "") or "pt_BR",
    }


def _template_do_modelo(chave: str) -> str:
    """O template proprio de uma mensagem ao cliente, quando configurado:
    `META_TEMPLATE_CONFIRMACAO`, `META_TEMPLATE_LEMBRETE`,
    `META_TEMPLATE_CANCELAMENTO`. Vazio = cai no generico."""
    return os.environ.get(f"META_TEMPLATE_{chave.upper()}", "").strip()


def configurado() -> bool:
    cfg = _config()
    return bool(cfg["token"] and cfg["numero_id"])


def _url(cfg: dict, caminho: str) -> str:
    return f"https://graph.facebook.com/{cfg['versao']}/{cfg['numero_id']}{caminho}"


def _cabecalhos(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['token']}"}


def achatar(mensagem: str) -> str:
    """O parametro de template nao aceita quebra de linha, tab nem mais de
    quatro espacos seguidos (erro 132018). A lista do dia e' feita de linhas:
    viram " · ", que ainda se le como lista numa linha so'."""
    linhas = [linha.strip() for linha in mensagem.splitlines() if linha.strip()]
    texto = " · ".join(linhas)
    texto = re.sub(r"\s{4,}", "   ", texto.replace("\t", " "))
    if len(texto) > _LIMITE_PARAMETRO:
        texto = texto[: _LIMITE_PARAMETRO - 1].rstrip() + "…"
    return texto


def _post(cfg: dict, corpo: dict) -> requests.Response | None:
    try:
        return requests.post(
            _url(cfg, "/messages"), json=corpo, headers=_cabecalhos(cfg), timeout=5,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-meta] falha ao enviar: %s", e)
        return None


def _id_aceito(r: requests.Response) -> str | None:
    try:
        mensagens = (r.json() or {}).get("messages") or []
        return mensagens[0].get("id") if mensagens else None
    except (ValueError, AttributeError, IndexError):
        return None


def enviar(
    whatsapp_digitos: str, mensagem: str, *, modelo: tuple[str, list[str]] | None = None,
) -> str | None:
    """O `wamid` da mensagem aceita, ou None quando nao saiu.

    Aceita, nao entregue — igual a Evolution. Entrega e leitura chegam
    depois, pelo webhook (`statuses`), e so' viram log.
    """
    cfg = _config()
    if not cfg["token"] or not cfg["numero_id"]:
        logger.info("[whatsapp-meta] sem META_WHATSAPP_TOKEN/NUMERO_ID: %s %s", whatsapp_digitos, mensagem)
        return None

    destino = f"55{whatsapp_digitos}"
    proprio = _template_do_modelo(modelo[0]) if modelo else ""
    if proprio:
        como = proprio
        corpo = {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "template",
            "template": {
                "name": proprio,
                "language": {"code": cfg["idioma"]},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": achatar(c)} for c in modelo[1]],
                }],
            },
        }
    elif cfg["template"]:
        como = "template"
        corpo = {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "template",
            "template": {
                "name": cfg["template"],
                "language": {"code": cfg["idioma"]},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": achatar(mensagem)}],
                }],
            },
        }
    else:
        como = "texto"
        corpo = {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "text",
            "text": {"body": mensagem, "preview_url": False},
        }
    r = _post(cfg, corpo)
    if r is None:
        return None
    if r.ok:
        return _registrar_aceita(r, whatsapp_digitos, como)

    # O corpo e' onde a Meta diz o motivo: token vencido (190), numero nao
    # registrado (133010), sem cartao (131042), template nao aprovado (132001).
    logger.error(
        "[whatsapp-meta] envio recusado (%s) para %s: %s",
        r.status_code, whatsapp_digitos, r.text[:300],
    )
    return None


def _registrar_aceita(r: requests.Response, whatsapp_digitos: str, como: str) -> str | None:
    mensagem_id = _id_aceito(r)
    logger.info("[whatsapp-meta] aceito para %s por %s (%s)", whatsapp_digitos, como, mensagem_id or "?")
    # Sem id ainda e' aceita: devolve algo nao vazio para quem testa "saiu?".
    return mensagem_id or "aceita"


def dados_do_numero() -> dict | None:
    """O que a Meta sabe do numero: `display_phone_number`, `verified_name`,
    `code_verification_status`, `quality_rating`. None quando nao respondeu."""
    cfg = _config()
    if not cfg["token"] or not cfg["numero_id"]:
        return None
    try:
        r = requests.get(
            _url(cfg, ""),
            params={"fields": "display_phone_number,verified_name,code_verification_status,quality_rating"},
            headers=_cabecalhos(cfg),
            timeout=3,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-meta] falha ao consultar o numero: %s", e)
        return None
    if not r.ok:
        logger.error("[whatsapp-meta] consulta do numero recusada (%s): %s", r.status_code, r.text[:300])
        return None
    try:
        return r.json()
    except ValueError:
        return None


def estado() -> str:
    """Mesmo contrato do `whatsapp.estado_da_instancia`: "open" quando da'
    para mandar, senao um texto curto que o healthcheck loga."""
    if not configurado():
        return "sem-configuracao"
    dados = dados_do_numero()
    if dados is None:
        return "erro"
    # Numero ainda nao verificado por SMS/ligacao nao manda nada.
    if dados.get("code_verification_status") not in (None, "VERIFIED"):
        return f"numero nao verificado ({dados.get('code_verification_status')})"
    return "open"


def assinatura_confere(corpo_cru: bytes, cabecalho: str) -> bool:
    """`X-Hub-Signature-256: sha256=<hmac do corpo com o App Secret>`. Sem
    `META_APP_SECRET` nega tudo, igual ao `WHATSAPP_WEBHOOK_SEGREDO`."""
    segredo = os.environ.get("META_APP_SECRET", "")
    if not segredo or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(segredo.encode(), corpo_cru, hashlib.sha256).hexdigest()
    return hmac.compare_digest(cabecalho[len("sha256="):].encode(), esperado.encode())


def token_de_verificacao_confere(recebido: str) -> bool:
    esperado = os.environ.get("META_WEBHOOK_TOKEN", "")
    return bool(esperado) and hmac.compare_digest(recebido.encode(), esperado.encode())


def registrar_evento(corpo) -> str:
    """O que o webhook faz com o corpo. Por enquanto so' LOGA: falha de
    entrega (a unica noticia de que um lembrete nao chegou) e mensagem de
    cliente. Responder cliente pelo numero central ainda nao existe — o bot e'
    por barbearia, e uma mensagem no central nao diz de qual barbearia ela e'.
    """
    if not isinstance(corpo, dict) or corpo.get("object") != "whatsapp_business_account":
        return "ignorado"
    falhas = recebidas = 0
    for entrada in corpo.get("entry") or []:
        for mudanca in (entrada or {}).get("changes") or []:
            valor = (mudanca or {}).get("value") or {}
            for status in valor.get("statuses") or []:
                if status.get("status") == "failed":
                    falhas += 1
                    logger.error(
                        "[whatsapp-meta] entrega falhou para %s: %s",
                        status.get("recipient_id"), (status.get("errors") or [{}])[0],
                    )
            for _ in valor.get("messages") or []:
                recebidas += 1
    if recebidas:
        logger.info("[whatsapp-meta] %s mensagem(ns) de cliente no central (sem bot por aqui)", recebidas)
    return f"falhas={falhas} recebidas={recebidas}"
