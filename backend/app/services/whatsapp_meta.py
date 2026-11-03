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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Modelo:
    """Um template proprio da Meta para UMA mensagem (03/11): as quebras de
    linha ficam no texto fixo, e cada pedaco vai numa variavel.

    `variavel` e' o NOME da variavel de ambiente com o nome do template
    (ex.: `META_TEMPLATE_LEMBRETE=marcai_lembrete_1h`): vazia, a mensagem
    segue pelo `marcai_aviso`. `payload` vai no botao de resposta rapida
    (indice 0) e volta no webhook quando o cliente toca."""

    variavel: str
    parametros: list
    payload: str | None = None

    def nome(self) -> str:
        return os.environ.get(self.variavel, "").strip()

    def parametros_prontos(self) -> list[str]:
        # Vazio e quebra de linha a Meta recusa (132000/132018).
        return [achatar(str(p or "")) or "—" for p in self.parametros]


def _corpo_texto(destino: str, mensagem: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "text",
        "text": {"body": mensagem, "preview_url": False},
    }


def _corpo_template(destino: str, nome: str, idioma: str, parametros: list[str], payload=None) -> dict:
    componentes = [{
        "type": "body",
        "parameters": [{"type": "text", "text": p} for p in parametros],
    }]
    if payload:
        componentes.append({
            "type": "button", "sub_type": "quick_reply", "index": "0",
            "parameters": [{"type": "payload", "payload": payload}],
        })
    return {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "template",
        "template": {"name": nome, "language": {"code": idioma}, "components": componentes},
    }


def _tentar(cfg: dict, corpo: dict, whatsapp_digitos: str, como: str) -> str | None:
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


def enviar(
    whatsapp_digitos: str, mensagem: str, *, modelo: Modelo | None = None, na_janela: bool = False,
) -> str | None:
    """O `wamid` da mensagem aceita, ou None quando nao saiu.

    Aceita, nao entregue — igual a Evolution. Entrega e leitura chegam
    depois, pelo webhook (`statuses`), e so' viram log.

    A ordem:
    - `na_janela`: quem chama SABE que o cliente escreveu ha pouco (o toque
      do lembrete). Sai texto normal, com as quebras de linha. So' com
      certeza: fora da janela a Meta aceita o texto com 200 e ele some
      depois, pelo webhook.
    - `modelo` com o template preenchido: o template proprio da mensagem.
      Recusado (ainda nao aprovado, pausado), cai no `marcai_aviso` — a
      mensagem nao some por causa do modelo novo.
    - o `marcai_aviso` (`META_WHATSAPP_TEMPLATE`), com a mensagem achatada.
    - sem template nenhum: texto.
    """
    cfg = _config()
    if not cfg["token"] or not cfg["numero_id"]:
        logger.info("[whatsapp-meta] sem META_WHATSAPP_TOKEN/NUMERO_ID: %s %s", whatsapp_digitos, mensagem)
        return None

    destino = f"55{whatsapp_digitos}"
    if na_janela or not cfg["template"]:
        return _tentar(cfg, _corpo_texto(destino, mensagem), whatsapp_digitos, "texto")

    if modelo is not None and modelo.nome():
        aceita = _tentar(
            cfg,
            _corpo_template(destino, modelo.nome(), cfg["idioma"], modelo.parametros_prontos(), modelo.payload),
            whatsapp_digitos, f"modelo {modelo.nome()}",
        )
        if aceita is not None:
            return aceita
        logger.error("[whatsapp-meta] modelo %s recusado: vai pelo %s", modelo.nome(), cfg["template"])

    return _tentar(
        cfg, _corpo_template(destino, cfg["template"], cfg["idioma"], [achatar(mensagem)]),
        whatsapp_digitos, "template",
    )


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
    """O que o webhook faz com o corpo: LOGA falha de entrega (a unica
    noticia de que um lembrete nao chegou) e, com o lembrete por toque
    ligado, procura o codigo de agendamento no texto de cada mensagem de
    cliente (`lembrete_por_toque.registrar_pedido`). Fora isso o central nao
    responde ninguem — uma mensagem sem codigo nao diz de qual barbearia e'.
    """
    if not isinstance(corpo, dict) or corpo.get("object") != "whatsapp_business_account":
        return "ignorado"
    # Import tardio: lembrete_por_toque importa este modulo.
    from datetime import datetime, timezone

    from . import lembrete_por_toque

    pelo_toque = lembrete_por_toque.ligado()
    agora = datetime.now(timezone.utc)
    falhas = recebidas = pedidos = 0
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
            for msg in valor.get("messages") or []:
                recebidas += 1
                # O texto que o cliente mandou pelo `wa.me`, ou o toque no
                # botao do `marcai_confirmado` (o payload traz o codigo).
                tipo = (msg or {}).get("type")
                if tipo == "text":
                    texto = (msg.get("text") or {}).get("body")
                elif tipo == "button":
                    texto = (msg.get("button") or {}).get("payload")
                else:
                    texto = None
                if pelo_toque and texto:
                    # Uma falha aqui nao pode virar 500: a Meta reenviaria o
                    # webhook inteiro, com os status junto.
                    try:
                        if lembrete_por_toque.registrar_pedido(
                            texto, msg.get("from") or "", agora,
                        ) != "ignorado":
                            pedidos += 1
                    except Exception:
                        logger.exception("[whatsapp-meta] lembrete por toque nao registrou")
    if recebidas:
        logger.info(
            "[whatsapp-meta] %s mensagem(ns) de cliente no central, %s pedido(s) de lembrete",
            recebidas, pedidos,
        )
    return f"falhas={falhas} recebidas={recebidas} pedidos={pedidos}"
