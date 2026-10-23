import uuid
from datetime import date, datetime, timezone as fuso
from unittest.mock import patch

import pytest
from django.db import IntegrityError, ProgrammingError, connections, transaction
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


def _dados(slug="nova"):
    return {
        "slug": slug, "nome": "Nova", "donoNome": "Zeca",
        "endereco": "Rua A, 1", "whatsappContato": "11988887777",
        "plano": "SEM_ZAP",
    }


def _criar(slug="nova"):
    from app.services.admin_barbearias import criar
    from tenant.models import Assinatura

    r = criar(_dados(slug))
    assert r["tipo"] == "ok"
    return Assinatura.objects.using("admin").get(barbearia_id=r["id"]), r["id"]


def _cobranca(barbearia_id, valor, status="ABERTA", chave="a@b.com"):
    from tenant.models import Cobranca

    return Cobranca.objects.using("owner").create(
        barbearia_id=barbearia_id, motivo="MENSALIDADE", chave_pix=chave,
        valor_base_centavos=5000, valor_centavos=valor, copia_e_cola="x",
        status=status,
    )


@override_settings(MENSALIDADE_VALOR_PADRAO_CENTAVOS=4990)
def test_barbearia_do_admin_nasce_com_o_primeiro_mes_gratis():
    agora = datetime(2026, 10, 20, 15, 0, tzinfo=fuso.utc)
    with patch("app.services.admin_barbearias.timezone.now", return_value=agora):
        a, _ = _criar()
    assert a.isenta is False
    assert a.valor_centavos == 4990
    assert a.dia_de_vencimento == 20
    assert a.paga_ate == date(2026, 11, 20)


@override_settings(MENSALIDADE_VALOR_PADRAO_CENTAVOS=0)
def test_sem_valor_padrao_a_barbearia_nasce_isenta():
    a, _ = _criar()
    assert a.isenta is True
    assert a.valor_centavos == 0


def test_o_cenario_tem_assinatura_isenta(cenario):
    from tenant.models import Assinatura

    assert Assinatura.objects.using("admin").filter(isenta=True).count() == 2


def test_indice_recusa_duas_abertas_com_mesma_chave_e_valor(cenario):
    b = cenario["brutus"].id
    _cobranca(b, 5001)
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _cobranca(cenario["dontony"].id, 5001)
    # outro valor, ou outra chave, passa
    _cobranca(b, 5002)
    _cobranca(b, 5001, chave="c@d.com")


def test_indice_aceita_de_novo_depois_que_a_primeira_e_paga(cenario):
    b = cenario["brutus"].id
    c = _cobranca(b, 5001)
    c.status = "PAGA"
    c.save(using="owner")
    _cobranca(cenario["dontony"].id, 5001)


@pytest.mark.parametrize("tabela", ["tenant_assinatura", "tenant_cobranca"])
@pytest.mark.parametrize("sql", [
    "INSERT INTO {t} DEFAULT VALUES",
    "UPDATE {t} SET observacao = 'x'",
    "DELETE FROM {t}",
])
def test_brutus_app_nao_escreve(cenario, tabela, sql):
    if tabela == "tenant_assinatura":
        sql = sql.replace("SET observacao = 'x'", "SET isenta = false")
    with pytest.raises(ProgrammingError, match="permission denied"):
        with connections["default"].cursor() as cur:
            cur.execute(sql.format(t=tabela))


def test_brutus_app_ainda_le(cenario):
    with connections["default"].cursor() as cur:
        cur.execute("SELECT count(*) FROM tenant_assinatura")
        assert cur.fetchone()[0] == 2


def test_apagar_barbearia_leva_assinatura_e_cobranca_so_dela(cenario):
    from app.services.admin_barbearias import apagar_barbearia
    from tenant.models import Assinatura, Cobranca

    a, b = cenario["brutus"].id, cenario["dontony"].id
    _cobranca(a, 5001)
    _cobranca(b, 5002)
    apagar_barbearia(a)
    assert not Assinatura.objects.using("admin").filter(barbearia_id=a).exists()
    assert not Cobranca.objects.using("admin").filter(barbearia_id=a).exists()
    assert Assinatura.objects.using("admin").filter(barbearia_id=b).exists()
    assert Cobranca.objects.using("admin").filter(barbearia_id=b).exists()


def test_apagar_barbeiro_zera_informada_por_e_guarda_a_cobranca(cenario):
    from tenant.models import Barbeiro, Cobranca
    from tenant.rls import com_barbearia_admin

    b = cenario["brutus"].id
    barbeiro = Barbeiro.objects.using("owner").get(barbearia_id=b)
    c = _cobranca(b, 5001)
    c.informada_por_id = barbeiro.id
    c.save(using="owner")
    with com_barbearia_admin(b):
        Barbeiro.objects.using("admin").filter(id=barbeiro.id).delete()
    c = Cobranca.objects.using("admin").get(id=c.id)
    assert c.informada_por_id is None


def test_cobranca_guarda_o_link_da_infinitepay():
    from tenant.models import Cobranca, ComoFoiPaga

    _, barbearia_id = _criar()
    c = _cobranca(barbearia_id, 5000, chave="ip:x")
    c.link_pagamento = "https://checkout.infinitepay.io/marcai/abc"
    c.ip_transacao = "nsu-123"
    c.como_foi_paga = ComoFoiPaga.INFINITEPAY
    c.save(using="owner")
    relida = Cobranca.objects.using("owner").get(pk=c.pk)
    assert relida.link_pagamento == "https://checkout.infinitepay.io/marcai/abc"
    assert relida.ip_transacao == "nsu-123"
    assert relida.como_foi_paga == "INFINITEPAY"
