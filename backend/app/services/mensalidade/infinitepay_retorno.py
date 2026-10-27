"""O aviso de pago da InfinitePay, e a varredura que cobre aviso perdido.

O aviso nao e' assinado: quem descobrir a URL (e o `?t=`) consegue mandar um
POST com o `order_nsu` de qualquer cobranca aberta. Por isso nada se confirma
pelo que veio no corpo — so' pelo que o `payment_check` responde, e so' se o
`amount` dele for o valor da cobranca.

Toda escrita pelo alias `admin`, como em `operacoes`."""

import logging
import uuid
from datetime import datetime, timezone

from django.conf import settings
from django.db import transaction

from app.services import infinitepay, mensagens
from tenant.models import Cobranca, ComoFoiPaga, MotivoCobranca, StatusCobranca

from . import operacoes
from .operacoes import ALIAS, RecusaDaMensalidade

logger = logging.getLogger(__name__)

PAGO_EM_CANCELADA = "pago na InfinitePay depois de cancelada"


def _agora():
    return datetime.now(timezone.utc)


def _da_infinitepay(referencia):
    try:
        cobranca_id = uuid.UUID(str(referencia))
    except ValueError:
        return None
    return (
        Cobranca.objects.using(ALIAS)
        .filter(id=cobranca_id, motivo=MotivoCobranca.MENSALIDADE, chave_pix__startswith="ip:")
        .first()
    )


def processar(*, referencia: str, transacao: str, slug: str, agora) -> str:
    """Devolve "confirmada", "ja_resolvida", "paga_em_cancelada", "ignorada"
    ou "pendente". `ErroDaInfinitePay` sobe: a rota responde 400 (a
    InfinitePay manda de novo) e a varredura passa para a proxima."""
    cobranca = _da_infinitepay(referencia)
    if cobranca is None:
        return "ignorada"
    # Guardado antes de perguntar: e' o que deixa a varredura conferir depois
    # se o `payment_check` falhar agora ou ainda disser que nao pagou.
    if not cobranca.ip_transacao and transacao:
        Cobranca.objects.using(ALIAS).filter(id=cobranca.id, ip_transacao="").update(
            ip_transacao=transacao, ip_fatura=slug or "",
        )
    if cobranca.status == StatusCobranca.PAGA:
        return "ja_resolvida"
    if cobranca.status == StatusCobranca.CANCELADA and cobranca.observacao == PAGO_EM_CANCELADA:
        return "paga_em_cancelada"

    resposta = infinitepay.conferir(referencia=str(cobranca.id), transacao=transacao, slug=slug)
    if not resposta["pago"]:
        return "pendente"
    if resposta["valor_centavos"] != cobranca.valor_centavos:
        logger.warning(
            "[infinitepay] valor nao bate (cobranca=%s, esperado=%s, pago=%s)",
            cobranca.id, cobranca.valor_centavos, resposta["valor_centavos"],
        )
        return "ignorada"

    if cobranca.status == StatusCobranca.ABERTA:
        try:
            operacoes.confirmar(cobranca.id, agora=agora, como=ComoFoiPaga.INFINITEPAY)
        except RecusaDaMensalidade:
            # Outro aviso (ou o admin) resolveu entre a leitura e a trava.
            return "ja_resolvida"
        return "confirmada"
    return _pago_em_cancelada(cobranca.id)


def _pago_em_cancelada(cobranca_id) -> str:
    """O link nao expira: o admin registrou na mao, a barbearia ficou isenta,
    e o link velho ainda foi pago. Nao se confirma nada — o Jose confere ou
    devolve —, e o aviso sai uma vez so', marcado na observacao."""
    with transaction.atomic(using=ALIAS):
        cobranca = Cobranca.objects.using(ALIAS).select_for_update().get(pk=cobranca_id)
        if cobranca.observacao == PAGO_EM_CANCELADA:
            return "paga_em_cancelada"
        cobranca.observacao = PAGO_EM_CANCELADA
        cobranca.save(using=ALIAS, update_fields=["observacao"])
        if settings.MENSALIDADE_WHATSAPP_AVISO:
            barbearia_id, valor = cobranca.barbearia_id, cobranca.valor_centavos
            operacoes._avisar_depois_do_commit(lambda: (
                settings.MENSALIDADE_WHATSAPP_AVISO,
                mensagens.msg_infinitepay_pago_em_cancelada(
                    operacoes._nome_da_barbearia(barbearia_id), valor,
                ),
            ))
    return "paga_em_cancelada"


def conferir_pendentes() -> dict:
    """A varredura: cobranca aberta da InfinitePay que ja recebeu ao menos um
    aviso. A que nunca recebeu aviso nao tem como ser conferida — o
    `payment_check` pede o `transaction_nsu` e o `slug`, que so' o aviso
    traz —, e fica para o "registrar na mao" do admin."""
    contagem = {}
    pendentes = (
        Cobranca.objects.using(ALIAS)
        .filter(
            motivo=MotivoCobranca.MENSALIDADE, status=StatusCobranca.ABERTA,
            chave_pix__startswith="ip:",
        )
        .exclude(ip_transacao="")
        .values_list("id", "ip_transacao", "ip_fatura")
    )
    for cobranca_id, transacao, fatura in pendentes:
        try:
            r = processar(referencia=str(cobranca_id), transacao=transacao, slug=fatura, agora=_agora())
        except Exception:
            logger.exception("[infinitepay] varredura falhou na cobranca %s", cobranca_id)
            r = "erro"
        contagem[r] = contagem.get(r, 0) + 1
    return contagem
