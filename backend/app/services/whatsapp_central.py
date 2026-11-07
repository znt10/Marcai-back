"""O numero central do Marcai, visto do admin.

Desde a etapa 1 (spec 2026-10-06) ele carrega TUDO — equipe e cliente —,
entao o admin precisa ver se ele esta de pe e, quando nao estiver, ler o QR.
Antes disso o unico jeito era o manager da Evolution exposto, e a unica
noticia de queda era uma linha no log do `whatsapp_healthcheck`.
"""

import logging

import requests

from tenant.models import EstadoInstancia

from . import whatsapp, whatsapp_meta
from .whatsapp_eventos import _numero_do_jid
from .whatsapp_instancias import (
    TIMEOUT_CRIACAO_S, _aplicar_webhook, consultar_dono, consultar_estado, pedir_qr,
)
from .whatsapp_instancias import _config as _config_instancias

logger = logging.getLogger(__name__)


def chip_em_uso() -> bool:
    """Com a Meta ligada, o admin mostra o CHIP (e o QR dele) quando ele
    carrega alguma coisa: a equipe (#67) ou o toque dos clientes."""
    from . import lembrete_por_toque

    return whatsapp.equipe_pela_evolution() or lembrete_por_toque.pela_evolution()


def ligar_escuta_do_chip() -> bool:
    """O chip so' mandava; com o toque pela Evolution ele precisa OUVIR o
    cliente. Aplica o webhook com `MESSAGES_UPSERT` na instancia central.
    Idempotente: o healthcheck chama a cada tique."""
    cfg = whatsapp._config()
    if not cfg["url"] or not cfg["instancia"]:
        return False
    return _aplicar_webhook(_config_instancias(), cfg["instancia"], bot=True)


def ver_central() -> dict:
    if whatsapp_meta.ligado() and not chip_em_uso():
        return _ver_pela_meta()
    cfg = whatsapp._config()
    if not cfg["url"] or not cfg["instancia"]:
        return {"configurado": False, "conectado": False, "numero": None, "qrBase64": None}

    nome = cfg["instancia"]
    estado = consultar_estado(nome)
    if estado == EstadoInstancia.CONECTADO:
        return {
            "configurado": True, "conectado": True,
            "numero": _numero_do_jid(consultar_dono(nome)), "qrBase64": None,
        }
    # 404 na Evolution vira PENDENTE: a instancia central nao existe la
    # (volume novo, apagada a mao). Cria, e o QR sai na mesma visita.
    if estado == EstadoInstancia.PENDENTE:
        _criar(cfg, nome)
    return {"configurado": True, "conectado": False, "numero": None, "qrBase64": pedir_qr(nome)}


def _ver_pela_meta() -> dict:
    """Pela API oficial nao ha QR: o numero se verifica uma vez no WhatsApp
    Manager. A tela so' mostra se esta de pe e qual numero e'."""
    if not whatsapp_meta.configurado():
        return {"configurado": False, "conectado": False, "numero": None, "qrBase64": None}
    dados = whatsapp_meta.dados_do_numero() or {}
    return {
        "configurado": True,
        "conectado": whatsapp_meta.estado() == "open",
        # A Meta devolve "+55 83 8898-2852": sem o nono digito e com
        # espacos. Pelo mesmo caminho do JID vira "83988982852".
        "numero": _numero_do_jid("".join(c for c in dados.get("display_phone_number") or "" if c.isdigit())),
        "qrBase64": None,
    }


def _criar(cfg: dict, nome: str) -> None:
    """Sem webhook: o central so' manda. 403 "already in use" e' sucesso
    disfarcado (medido na 2.3.7, mesmo caso de `garantir_instancia`)."""
    try:
        r = requests.post(
            f"{cfg['url']}/instance/create",
            json={"instanceName": nome, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            headers={"apikey": cfg["chave"]},
            timeout=TIMEOUT_CRIACAO_S,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-central] falha ao criar %s: %s", nome, e)
        return
    if not r.ok and not (r.status_code == 403 and "already in use" in r.text):
        logger.error(
            "[whatsapp-central] criacao recusada (%s) para %s: %s",
            r.status_code, nome, r.text[:300],
        )
