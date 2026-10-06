"""O numero central do Marcai, visto do admin.

Desde a etapa 1 (spec 2026-10-06) ele carrega TUDO — equipe e cliente —,
entao o admin precisa ver se ele esta de pe e, quando nao estiver, ler o QR.
Antes disso o unico jeito era o manager da Evolution exposto, e a unica
noticia de queda era uma linha no log do `whatsapp_healthcheck`.
"""

import logging

import requests

from tenant.models import EstadoInstancia

from . import whatsapp
from .whatsapp_eventos import _numero_do_jid
from .whatsapp_instancias import TIMEOUT_CRIACAO_S, consultar_dono, consultar_estado, pedir_qr

logger = logging.getLogger(__name__)


def ver_central() -> dict:
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
