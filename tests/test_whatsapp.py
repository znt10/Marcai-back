from unittest.mock import Mock, patch

from app.services import whatsapp


def test_sem_evolution_api_url_cai_no_log_e_nao_lanca(monkeypatch, caplog):
    """O modo de desenvolver sem numero de verdade — mesmo contrato do
    `enviarTexto` do front."""
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    with caplog.at_level("INFO"):
        whatsapp.enviar_texto("11977771234", "Lembrete: corte hoje")
    assert "sem EVOLUTION_API_URL" in caplog.text
    assert "11977771234" in caplog.text


def test_falha_de_rede_nao_lanca(monkeypatch, caplog):
    """Fire-and-forget e sobre nao desfazer o agendamento — falha de rede tem
    que ser registrada, nunca propagada."""
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "brutus")

    import requests

    with patch.object(whatsapp.requests, "post", side_effect=requests.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            whatsapp.enviar_texto("11977771234", "oi")
    assert "falha ao enviar" in caplog.text


def test_resposta_recusada_e_logada_com_status_e_motivo(monkeypatch, caplog):
    """Numero desconectado (400) ou chave errada (401): os dois sao 'nao
    ok' e os dois tem que aparecer no log, com o corpo que a Evolution manda —
    e' o que separa as duas causas mais comuns sem precisar reproduzir."""
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave-errada")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "brutus")

    resposta = Mock(ok=False, status_code=401, text="Unauthorized")
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        with caplog.at_level("ERROR"):
            whatsapp.enviar_texto("11977771234", "oi")
    assert "401" in caplog.text
    assert "Unauthorized" in caplog.text


def test_sucesso_e_registrado_com_jid_e_status(monkeypatch, caplog):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "brutus")

    resposta = Mock(ok=True)
    resposta.json.return_value = {
        "key": {"remoteJid": "5511977771234@s.whatsapp.net"},
        "status": "PENDING",
    }
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        with caplog.at_level("INFO"):
            whatsapp.enviar_texto("11977771234", "oi")
    assert "aceito" in caplog.text
    assert "5511977771234@s.whatsapp.net" in caplog.text
