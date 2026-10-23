import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "brutus.localhost"
PIX = {"PIX_CHAVE": "dono@marcai.com", "PIX_NOME_RECEBEDOR": "Marcai", "PIX_CIDADE": "Patos"}


@pytest.fixture(autouse=True)
def _pix():
    with override_settings(**PIX):
        yield


def _barbeiro(barbearia_id, papel="DONO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Zeca",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )


def _paga_ate(barbearia_id, dias_a_frente, valor=10000):
    from tenant.models import Assinatura

    paga_ate = timezone.localdate() + timedelta(days=dias_a_frente)
    Assinatura.objects.using("owner").filter(barbearia_id=barbearia_id).update(
        isenta=False, valor_centavos=valor, paga_ate=paga_ate, dia_de_vencimento=10,
    )
    return paga_ate


def _ver(client):
    return client.get("/api/painel/mensalidade", headers={"host": HOST})


def _ja_paguei(client):
    return client.post("/api/painel/mensalidade/ja-paguei", headers={"host": HOST, **CABECALHO})


def test_isenta_volta_nulos(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)

    r = _ver(client)
    assert r.status_code == 200
    assert r.json() == {
        "situacao": "ISENTA", "dias": None, "bloqueiaEm": None, "pagaAte": None,
        "valorCentavos": None, "souDono": True, "pix": None, "pixErro": None,
    }


def test_sem_assinatura_vale_como_isenta(client, cenario):
    from tenant.models import Assinatura

    b = cenario["brutus"]
    Assinatura.objects.using("admin").filter(barbearia_id=b.id).delete()
    _logar(client, _barbeiro(b.id), b.id)

    assert _ver(client).json()["situacao"] == "ISENTA"


def test_sem_sessao_401(client, cenario):
    assert _ver(client).status_code == 401


def test_dono_ve_situacao_e_pix_com_centavos(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    paga_ate = _paga_ate(b.id, 2)

    corpo = _ver(client).json()
    assert corpo["situacao"] == "VENCENDO"
    assert corpo["dias"] == 2
    assert corpo["pagaAte"] == paga_ate.isoformat()
    assert corpo["bloqueiaEm"] is not None and len(corpo["bloqueiaEm"]) == 10
    assert corpo["valorCentavos"] == 10000
    assert corpo["souDono"] is True
    pix = corpo["pix"]
    assert 10001 <= pix["valorCentavos"] <= 10099
    assert pix["copiaECola"].startswith("000201")
    assert pix["qrSvg"].startswith("data:image/svg+xml")


def test_dono_pega_sempre_o_mesmo_pix(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _paga_ate(b.id, 2)

    assert _ver(client).json()["pix"] == _ver(client).json()["pix"]


def test_barbeiro_ve_a_situacao_sem_o_pix(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id, papel="BARBEIRO"), b.id)
    _paga_ate(b.id, 2)

    corpo = _ver(client).json()
    assert corpo["situacao"] == "VENCENDO"
    assert corpo["souDono"] is False
    assert corpo["pix"] is None


def test_barbeiro_nao_gera_cobranca_ao_ver(client, cenario):
    from tenant.models import Cobranca

    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id, papel="BARBEIRO"), b.id)
    _paga_ate(b.id, 2)
    _ver(client)

    assert not Cobranca.objects.using("admin").filter(barbearia_id=b.id).exists()


def test_barbeiro_recebe_403_no_ja_paguei(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id, papel="BARBEIRO"), b.id)
    _paga_ate(b.id, 2)

    assert _ja_paguei(client).status_code == 403


def test_dono_avisa_e_a_situacao_vira_aguardando(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _paga_ate(b.id, -7)

    r = _ja_paguei(client)
    assert r.status_code == 200
    assert r.json()["situacao"] == "AGUARDANDO"
    assert r.json()["pix"]["valorCentavos"] > 10000


def test_segundo_ja_paguei_e_400(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _paga_ate(b.id, 2)

    assert _ja_paguei(client).status_code == 200
    r = _ja_paguei(client)
    assert r.status_code == 400
    assert "aguardando confirmação" in r.json()["erro"]


def test_ja_paguei_de_isenta_e_400(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)

    r = _ja_paguei(client)
    assert r.status_code == 400
    assert r.json() == {"erro": "Esta barbearia não tem mensalidade a pagar."}


def test_sem_centavo_livre_responde_200_com_pix_erro(client, cenario):
    from unittest.mock import patch

    from app.services.mensalidade.centavos import SemCentavoLivre

    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _paga_ate(b.id, -7)

    with patch("app.services.mensalidade.operacoes.centavos.escolher", side_effect=SemCentavoLivre):
        r = _ver(client)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["situacao"] == "BLOQUEADA"
    assert corpo["pix"] is None
    assert "Não foi possível gerar o Pix" in corpo["pixErro"]


def test_em_dia_nao_tem_pix(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _paga_ate(b.id, 20)

    corpo = _ver(client).json()
    assert corpo["situacao"] == "EM_DIA"
    assert corpo["pix"] is None and corpo["pixErro"] is None


def test_portao_manda_o_link_e_diz_que_e_automatico(client, cenario, monkeypatch):
    from app.services import infinitepay

    monkeypatch.setattr(infinitepay, "criar_link", lambda **kw: "https://checkout.infinitepay.io/x")
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _paga_ate(b.id, 2)

    with override_settings(INFINITEPAY_HANDLE="marcai", INFINITEPAY_WEBHOOK_SEGREDO="s3gredo"):
        pix = _ver(client).json()["pix"]
    assert pix == {
        "copiaECola": None, "qrSvg": None, "valorCentavos": 10000,
        "link": "https://checkout.infinitepay.io/x", "automatico": True,
    }


def test_portao_sem_infinitepay_manda_link_nulo(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _paga_ate(b.id, 2)

    pix = _ver(client).json()["pix"]
    assert pix["link"] is None and pix["automatico"] is False
