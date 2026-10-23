from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

BRASILIA = ZoneInfo("America/Sao_Paulo")
IP = {
    "INFINITEPAY_HANDLE": "marcai", "INFINITEPAY_WEBHOOK_SEGREDO": "s3gredo",
    "MENSALIDADE_WHATSAPP_AVISO": "83999990000",
}
AGORA = datetime(2026, 10, 12, 12, 0, tzinfo=BRASILIA)


@pytest.fixture(autouse=True)
def _ip():
    with override_settings(**IP):
        yield


@pytest.fixture
def pagamento(monkeypatch):
    """Troca o `payment_check`. `pagamento.resposta` decide o que ele diz;
    `pagamento.chamadas` guarda o que foi perguntado."""
    from app.services import infinitepay

    class Falso:
        def __call__(self, **kw):
            self.chamadas.append(kw)
            if isinstance(self.resposta, Exception):
                raise self.resposta
            return self.resposta

    falso = Falso()
    falso.chamadas = []
    falso.resposta = {"pago": True, "valor_centavos": 10000, "meio": "pix"}
    monkeypatch.setattr(infinitepay, "conferir", falso)
    return falso


@pytest.fixture
def enviados(monkeypatch):
    from app.services.mensalidade import operacoes

    lista = []
    monkeypatch.setattr(operacoes, "enviar_a_equipe", lambda numero, texto: lista.append((numero, texto)))
    return lista


@pytest.fixture
def cobranca(cenario):
    """Brutus vencendo, com a cobranca da InfinitePay aberta."""
    import uuid

    from tenant.models import Assinatura, Cobranca

    b = cenario["brutus"].id
    Assinatura.objects.using("admin").filter(barbearia_id=b).update(
        isenta=False, valor_centavos=10000, paga_ate=date(2026, 10, 10), dia_de_vencimento=10,
    )
    cid = uuid.uuid4()
    return Cobranca.objects.using("admin").create(
        id=cid, barbearia_id=b, motivo="MENSALIDADE", chave_pix=f"ip:{cid}",
        valor_base_centavos=10000, valor_centavos=10000, copia_e_cola="",
        link_pagamento="https://checkout.infinitepay.io/x",
    )


def _recarregar(c):
    from tenant.models import Cobranca

    return Cobranca.objects.using("admin").get(id=c.id)


def _paga_ate(c):
    from tenant.models import Assinatura

    return Assinatura.objects.using("admin").get(barbearia_id=c.barbearia_id).paga_ate


def _processar(c, transacao="nsu-1"):
    from app.services.mensalidade import infinitepay_retorno

    return infinitepay_retorno.processar(
        referencia=str(c.id), transacao=transacao, slug="fat-1", agora=AGORA,
    )


# --- processar ---
def test_pago_confirma_e_avanca_paga_ate(cobranca, pagamento, enviados):
    assert _processar(cobranca) == "confirmada"
    c = _recarregar(cobranca)
    assert c.status == "PAGA" and c.como_foi_paga == "INFINITEPAY"
    assert c.ip_transacao == "nsu-1"
    assert _paga_ate(cobranca) == date(2026, 11, 10)
    assert pagamento.chamadas == [
        {"referencia": str(cobranca.id), "transacao": "nsu-1", "slug": "fat-1"}
    ]


def test_aviso_repetido_nao_avanca_duas_vezes(cobranca, pagamento, enviados):
    _processar(cobranca)
    assert _processar(cobranca) == "ja_resolvida"
    assert _paga_ate(cobranca) == date(2026, 11, 10)


def test_nao_pago_nao_confirma(cobranca, pagamento):
    pagamento.resposta = {"pago": False, "valor_centavos": 10000, "meio": ""}
    assert _processar(cobranca) == "pendente"
    assert _recarregar(cobranca).status == "ABERTA"
    assert _paga_ate(cobranca) == date(2026, 10, 10)


def test_nao_pago_ainda_guarda_a_transacao(cobranca, pagamento):
    pagamento.resposta = {"pago": False, "valor_centavos": 10000, "meio": ""}
    _processar(cobranca, transacao="nsu-7")
    assert _recarregar(cobranca).ip_transacao == "nsu-7"


def test_valor_diferente_e_ignorado(cobranca, pagamento):
    pagamento.resposta = {"pago": True, "valor_centavos": 100, "meio": "pix"}
    assert _processar(cobranca) == "ignorada"
    assert _recarregar(cobranca).status == "ABERTA"


def test_referencia_desconhecida_e_ignorada(cobranca, pagamento):
    from app.services.mensalidade import infinitepay_retorno

    r = infinitepay_retorno.processar(
        referencia="nao-e-uuid", transacao="nsu-1", slug="fat-1", agora=AGORA,
    )
    assert r == "ignorada"
    assert pagamento.chamadas == []


def test_cobranca_do_pix_estatico_e_ignorada(cobranca, pagamento):
    from tenant.models import Cobranca

    Cobranca.objects.using("admin").filter(id=cobranca.id).update(chave_pix="dono@marcai.com")
    assert _processar(cobranca) == "ignorada"
    assert pagamento.chamadas == []


def test_pago_em_cancelada_avisa_uma_vez(cobranca, pagamento, enviados):
    from tenant.models import Cobranca

    Cobranca.objects.using("admin").filter(id=cobranca.id).update(status="CANCELADA")
    assert _processar(cobranca) == "paga_em_cancelada"
    assert _processar(cobranca) == "paga_em_cancelada"
    assert len(enviados) == 1
    numero, texto = enviados[0]
    assert numero == "83999990000"
    assert "InfinitePay" in texto and "cancelada" in texto and "R$ 100,00" in texto
    c = _recarregar(cobranca)
    assert c.status == "CANCELADA"
    assert c.observacao == "pago na InfinitePay depois de cancelada"
    assert _paga_ate(cobranca) == date(2026, 10, 10)


# --- a rota ---
URL = "/api/interno/infinitepay"


def _aviso(client, c, t="s3gredo", **corpo):
    dados = {
        "order_nsu": str(c.id), "transaction_nsu": "nsu-1", "invoice_slug": "fat-1",
        "amount": 10000, "paid_amount": 10000, "capture_method": "pix", **corpo,
    }
    # Sem `x-brutus-cliente`: a InfinitePay nao manda, e a rota tem que passar.
    return client.post(
        f"{URL}?t={t}", dados, content_type="application/json",
        headers={"host": "brutus.localhost"},
    )


def test_aviso_com_segredo_errado_da_401_e_nao_confere(client, cobranca, pagamento):
    pagamento.resposta = AssertionError("nao devia perguntar")
    r = _aviso(client, cobranca, t="errado")
    assert r.status_code == 401
    assert pagamento.chamadas == []
    assert _recarregar(cobranca).status == "ABERTA"


def test_aviso_certo_confirma(client, cobranca, pagamento, enviados):
    r = _aviso(client, cobranca)
    assert r.status_code == 200
    assert _recarregar(cobranca).status == "PAGA"


def test_aviso_sem_order_nsu_responde_200(client, cobranca, pagamento):
    r = _aviso(client, cobranca, order_nsu="")
    assert r.status_code == 200
    assert pagamento.chamadas == []


def test_infinitepay_fora_do_ar_da_400(client, cobranca, pagamento):
    from app.services.infinitepay import ErroDaInfinitePay

    pagamento.resposta = ErroDaInfinitePay("fora")
    r = _aviso(client, cobranca)
    # 400 e' o que faz a InfinitePay mandar o aviso de novo.
    assert r.status_code == 400
    c = _recarregar(cobranca)
    assert c.status == "ABERTA"
    assert c.ip_transacao == "nsu-1"


# --- a varredura ---
def test_varredura_confirma_o_que_ficou_pendente(cobranca, pagamento, enviados, monkeypatch):
    from app import tasks
    from app.services.mensalidade import infinitepay_retorno

    pagamento.resposta = {"pago": False, "valor_centavos": 10000, "meio": ""}
    _processar(cobranca, transacao="nsu-3")
    assert _recarregar(cobranca).status == "ABERTA"

    pagamento.resposta = {"pago": True, "valor_centavos": 10000, "meio": "pix"}
    monkeypatch.setattr(infinitepay_retorno, "_agora", lambda: AGORA)
    r = tasks.conferir_pagamentos_infinitepay()
    assert r == {"confirmada": 1}
    assert _recarregar(cobranca).status == "PAGA"
    assert pagamento.chamadas[-1] == {
        "referencia": str(cobranca.id), "transacao": "nsu-3", "slug": "fat-1",
    }


def test_varredura_pula_a_que_nunca_recebeu_aviso(cobranca, pagamento):
    from app import tasks

    assert tasks.conferir_pagamentos_infinitepay() == {}
    assert pagamento.chamadas == []
