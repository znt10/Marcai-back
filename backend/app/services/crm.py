"""O aviso ao CRM pessoal do Jose: cada mensalidade paga (e cada pagamento
tirado do historico) vira uma linha la', sem lancar na mao.

E' so' saida, e nao manda em nada aqui: o aviso e' agendado DEPOIS do commit
e vai pelo Celery, entao o CRM fora do ar nunca desfaz uma confirmacao nem
atrasa a tela. Sem `CRM_WEBHOOK_URL` e `CRM_WEBHOOK_SEGREDO`, nada sai.

O id da cobranca vai como `external_id`: o CRM ignora o mesmo pagamento
mandado duas vezes, que e' o que deixa a tarefa tentar de novo sem medo."""

import logging

import requests
from django.conf import settings
from django.db import transaction

from tenant.models import Cobranca, ComoFoiPaga

logger = logging.getLogger(__name__)

ALIAS = "admin"
TIMEOUT_S = 10
PAGO = "pago"
REMOVIDO = "removido"

# O "como" do Marcai no vocabulario do CRM. O REGISTRO e' o que chegou fora
# do sistema (dinheiro, Pix sem aviso).
MEIO = {
    ComoFoiPaga.INFINITEPAY: "infinitepay",
    ComoFoiPaga.VIGIA: "pix",
    ComoFoiPaga.MANUAL: "pix",
    ComoFoiPaga.REGISTRO: "outro",
}


class ErroDoCrm(Exception):
    """O CRM nao respondeu ou respondeu erro. A tarefa tenta de novo."""


def configurado() -> bool:
    return bool(settings.CRM_WEBHOOK_URL) and bool(settings.CRM_WEBHOOK_SEGREDO)


def avisar_depois_do_commit(cobranca_id, acao):
    """Chamado de dentro da transacao que mudou a cobranca."""
    if not configurado():
        return

    def agendar():
        from app.tasks import avisar_crm  # tasks importa os servicos

        try:
            avisar_crm.delay(str(cobranca_id), acao)
        except Exception:
            logger.exception("[crm] aviso nao foi agendado (cobranca=%s)", cobranca_id)

    transaction.on_commit(agendar, using=ALIAS)


def corpo(cobranca, acao) -> dict:
    from app.services.mensalidade.operacoes import _nome_da_barbearia

    return {
        "acao": acao,
        "external_id": str(cobranca.id),
        "valor_centavos": cobranca.valor_centavos,
        "pago_em": cobranca.paga_em.isoformat() if cobranca.paga_em else None,
        "meio": MEIO.get(cobranca.como_foi_paga, "outro"),
        "descricao": f"Mensalidade · {_nome_da_barbearia(cobranca.barbearia_id)}",
    }


def enviar(cobranca_id, acao):
    cobranca = Cobranca.objects.using(ALIAS).filter(id=cobranca_id).first()
    if cobranca is None or not configurado():
        return
    try:
        r = requests.post(
            settings.CRM_WEBHOOK_URL,
            json=corpo(cobranca, acao),
            headers={"X-CRM-Segredo": settings.CRM_WEBHOOK_SEGREDO},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise ErroDoCrm(str(e)) from e
    if not r.ok:
        raise ErroDoCrm(f"{r.status_code} {r.text[:300]}")
