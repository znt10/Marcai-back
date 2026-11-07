"""A tela do admin com os DOIS caminhos lado a lado (06/11): a Meta (API
oficial) na esquerda e o chip da Evolution na direita, cada um dizendo se
esta de pe. Antes ela mostrava um so', e com a Meta ligada o chip sumia —
ninguem via que ele tinha caido."""

from unittest.mock import patch

from app.services import whatsapp_central
from tenant.models import EstadoInstancia

SERVICO = "app.services.whatsapp_central"


def _evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "Marcai")


def _meta(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "meta")
    monkeypatch.setenv("META_WHATSAPP_TOKEN", "token")
    monkeypatch.setenv("META_WHATSAPP_NUMERO_ID", "1411744118692075")


def _ver(*, meta="open", chip=EstadoInstancia.CONECTADO):
    with patch(f"{SERVICO}.whatsapp_meta.estado", return_value=meta), \
         patch(f"{SERVICO}.whatsapp_meta.dados_do_numero", return_value={"display_phone_number": "+55 83 8898-2852"}), \
         patch(f"{SERVICO}.consultar_estado", return_value=chip), \
         patch(f"{SERVICO}.consultar_dono", return_value="5583988010990@s.whatsapp.net"), \
         patch(f"{SERVICO}.pedir_qr", return_value="data:image/png;base64,QR"):
        return whatsapp_central.ver_central()


def test_mostra_os_dois_com_a_meta_ligada_e_o_chip_fora_de_uso(monkeypatch):
    _evolution(monkeypatch)
    _meta(monkeypatch)

    dados = _ver()

    assert dados["meta"] == {"ligada": True, "configurado": True, "conectado": True, "numero": "83988982852"}
    assert dados["evolution"] == {
        "emUso": False, "configurado": True, "conectado": True, "numero": "83988010990", "qrBase64": None,
    }


def test_meta_caida_aparece_mesmo_com_o_chip_em_uso(monkeypatch):
    _evolution(monkeypatch)
    _meta(monkeypatch)
    monkeypatch.setenv("WHATSAPP_EQUIPE_PELA_EVOLUTION", "1")

    dados = _ver(meta="close")

    assert dados["meta"]["conectado"] is False
    assert dados["evolution"]["emUso"] is True
    assert dados["evolution"]["conectado"] is True


def test_chip_caido_traz_o_qr_mesmo_com_a_meta_na_frente(monkeypatch):
    _evolution(monkeypatch)
    _meta(monkeypatch)

    dados = _ver(chip=EstadoInstancia.DESCONECTADO)

    assert dados["evolution"]["conectado"] is False
    assert dados["evolution"]["qrBase64"] == "data:image/png;base64,QR"
    assert dados["meta"]["conectado"] is True


def test_sem_meta_o_chip_leva_tudo(monkeypatch):
    _evolution(monkeypatch)

    dados = _ver()

    assert dados["meta"] == {"ligada": False, "configurado": False, "conectado": False, "numero": None}
    assert dados["evolution"]["emUso"] is True


def test_sem_evolution_o_lado_dela_diz_nao_configurado(monkeypatch):
    _meta(monkeypatch)

    dados = _ver()

    assert dados["evolution"] == {
        "emUso": False, "configurado": False, "conectado": False, "numero": None, "qrBase64": None,
    }
    assert dados["meta"]["conectado"] is True
