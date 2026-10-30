"""O Checkout Integrado da InfinitePay, para a mensalidade do Marcai.

Duas chamadas: `criar_link` (a cobranca vira um link de Pix ou cartao) e
`conferir` (o `payment_check`). A conta e' identificada pelo `handle` no
corpo; a documentacao (10/2026) nao tem chave de API, e a `X-Api-Key` so' sai
se um dia `INFINITEPAY_API_KEY` for preenchida.

O aviso de pago que a InfinitePay manda para a `webhook_url` NAO e' assinado.
Por isso a URL leva o segredo (`?t=`) e, mesmo com ele certo, nada se
confirma sem perguntar de volta pelo `payment_check` (ver
`mensalidade/infinitepay_retorno.py`)."""

import hmac
import logging

import requests
from django.conf import settings

from .convite import link_da_vitrine

logger = logging.getLogger(__name__)

API = "https://api.checkout.infinitepay.io"
TIMEOUT_S = 10


class ErroDaInfinitePay(Exception):
    """A InfinitePay nao respondeu, respondeu erro ou respondeu sem o campo
    que importa."""


def configurada() -> bool:
    return bool(settings.INFINITEPAY_HANDLE) and bool(settings.INFINITEPAY_WEBHOOK_SEGREDO)


def segredo_confere(t: str) -> bool:
    """`compare_digest` em bytes, como no webhook do WhatsApp: texto
    nao-ASCII em str levantaria TypeError e viraria 500 em vez de 401.
    Segredo vazio nega tudo."""
    segredo = settings.INFINITEPAY_WEBHOOK_SEGREDO
    if not segredo:
        return False
    return hmac.compare_digest((t or "").encode(), segredo.encode())


def _post(caminho: str, corpo: dict) -> dict:
    headers = {}
    if settings.INFINITEPAY_API_KEY:
        headers["X-Api-Key"] = settings.INFINITEPAY_API_KEY
    try:
        r = requests.post(f"{API}{caminho}", json=corpo, headers=headers, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise ErroDaInfinitePay(f"{caminho}: {e}") from e
    if not r.ok:
        raise ErroDaInfinitePay(f"{caminho}: {r.status_code} {r.text[:300]}")
    try:
        dados = r.json()
    except ValueError as e:
        raise ErroDaInfinitePay(f"{caminho}: resposta sem JSON") from e
    if not isinstance(dados, dict):
        raise ErroDaInfinitePay(f"{caminho}: resposta inesperada")
    return dados


def criar_link(*, valor_centavos: int, descricao: str, referencia: str, barbearia_slug: str) -> str:
    """O link de pagamento da cobranca `referencia` (o `order_nsu`). Aviso e
    volta passam pelo subdominio da propria barbearia: o host do admin pede a
    sessao da plataforma ate em `/api/`, e o da barbearia deixa
    `/api/interno/` chegar ao Django sem sessao nenhuma."""
    vitrine = link_da_vitrine(barbearia_slug)
    dados = _post("/links", {
        "handle": settings.INFINITEPAY_HANDLE,
        "items": [{"quantity": 1, "price": valor_centavos, "description": descricao}],
        "order_nsu": referencia,
        "redirect_url": f"{vitrine}/painel",
        "webhook_url": (
            f"{vitrine}/api/interno/infinitepay?t={settings.INFINITEPAY_WEBHOOK_SEGREDO}"
        ),
    })
    # A documentacao nao mostra a resposta; `url` e' o que se espera, `link`
    # fica de reserva ate o primeiro teste de verdade dizer qual e'.
    link = dados.get("url") or dados.get("link")
    if not isinstance(link, str) or not link:
        logger.error("[infinitepay] link sem url na resposta: %s", str(dados)[:300])
        raise ErroDaInfinitePay("/links: resposta sem link")
    return link


def conferir(*, referencia: str, transacao: str, slug: str) -> dict:
    """O `payment_check`. `slug` e' o `invoice_slug` do aviso, nao o da
    barbearia. Vale o `amount` (o preco do link): o `paid_amount` pode vir
    maior no cartao parcelado."""
    dados = _post("/payment_check", {
        "handle": settings.INFINITEPAY_HANDLE,
        "order_nsu": referencia,
        "transaction_nsu": transacao,
        "slug": slug,
    })
    if not isinstance(dados.get("paid"), bool):
        raise ErroDaInfinitePay("/payment_check: resposta sem `paid`")
    try:
        valor = int(dados.get("amount") or 0)
    except (TypeError, ValueError) as e:
        raise ErroDaInfinitePay("/payment_check: `amount` invalido") from e
    return {"pago": dados["paid"], "valor_centavos": valor, "meio": str(dados.get("capture_method") or "")}
