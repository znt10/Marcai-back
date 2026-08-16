from unittest.mock import Mock, patch

import pytest

from app.services import whatsapp


@pytest.fixture(autouse=True)
def _caches_limpas():
    whatsapp.limpar_caches_numero()
    yield
    whatsapp.limpar_caches_numero()


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


# ------------------------------------------------------------- numero_existe


def _config_evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "brutus")


def test_numero_existe_sem_url_e_indeterminado(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "indeterminado"


def test_numero_existe_true(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True, "jid": "5511977771234@s.whatsapp.net"}]
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "existe"


def test_numero_existe_false_bloqueia(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": False}]
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "nao_existe"


def test_numero_existe_falha_de_rede_e_indeterminado(monkeypatch, caplog):
    _config_evolution(monkeypatch)
    import requests

    with patch.object(whatsapp.requests, "post", side_effect=requests.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "indeterminado"
    assert "falha ao verificar numero" in caplog.text


def test_numero_existe_resposta_recusada_e_indeterminado(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=False, status_code=401)
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "indeterminado"


def test_numero_existe_usa_cache_dentro_do_ttl(monkeypatch):
    """Uma consulta so' por numero dentro do TTL — a segunda chamada nao
    bate na Evolution de novo."""
    _config_evolution(monkeypatch)
    relogio = {"agora": 0.0}
    monkeypatch.setattr(whatsapp, "_agora_ms", lambda: relogio["agora"])

    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as mock_post:
        assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "existe"
        relogio["agora"] += 1_000  # bem dentro do TTL de 24h
        assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "existe"
    mock_post.assert_called_once()


def test_numero_existe_expira_apos_o_ttl(monkeypatch):
    _config_evolution(monkeypatch)
    relogio = {"agora": 0.0}
    monkeypatch.setattr(whatsapp, "_agora_ms", lambda: relogio["agora"])

    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as mock_post:
        assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "existe"
        relogio["agora"] += whatsapp.CHECK_NUMERO_TTL_MS + 1
        assert whatsapp.numero_existe("11977771234", "1.1.1.1") == "existe"
    assert mock_post.call_count == 2


def test_numero_existe_limite_por_ip_por_hora(monkeypatch):
    """Um formulario publico que responde 'esse numero tem WhatsApp' e' uma
    ferramenta de varredura — por isso o limite e' por IP, nao por numero."""
    _config_evolution(monkeypatch)
    relogio = {"agora": 0.0}
    monkeypatch.setattr(whatsapp, "_agora_ms", lambda: relogio["agora"])

    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as mock_post:
        for i in range(whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA):
            # numero DIFERENTE a cada volta, senao o cache do numero (nao o
            # limite de IP) que evitaria a segunda consulta.
            whatsapp.numero_existe(f"1197777000{i}", "2.2.2.2")
        assert mock_post.call_count == whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA

        # a proxima, do MESMO ip, estoura o limite — nem bate na Evolution.
        resultado = whatsapp.numero_existe("11977779999", "2.2.2.2")
    assert resultado == "indeterminado"
    assert mock_post.call_count == whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA


def test_numero_existe_ip_diferente_tem_janela_propria(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as mock_post:
        for i in range(whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA):
            whatsapp.numero_existe(f"1197777000{i}", "3.3.3.3")
        assert whatsapp.numero_existe("11977779999", "4.4.4.4") == "existe"
    assert mock_post.call_count == whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA + 1


# ------------------------------------------------------------ estado_da_instancia


def test_estado_da_instancia_sem_url_e_sem_configuracao(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    assert whatsapp.estado_da_instancia() == "sem-configuracao"


def test_estado_da_instancia_open(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, text='{"instance":{"state":"open"}}')
    with patch.object(whatsapp.requests, "get", return_value=resposta) as mock_get:
        assert whatsapp.estado_da_instancia() == "open"
    mock_get.assert_called_once()
    url_chamada = mock_get.call_args.args[0]
    assert url_chamada == "http://evolution:8080/instance/connectionState/brutus"


def test_estado_da_instancia_close_devolve_o_corpo_cru(monkeypatch):
    """Casamento por SUBSTRING, igual ao `case` do compose antigo — nao por
    chave de JSON, porque a forma exata do corpo nunca foi documentada aqui."""
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, text='{"instance":{"state":"close"}}')
    with patch.object(whatsapp.requests, "get", return_value=resposta):
        assert whatsapp.estado_da_instancia() == '{"instance":{"state":"close"}}'


def test_estado_da_instancia_falha_de_rede_e_erro(monkeypatch, caplog):
    _config_evolution(monkeypatch)
    import requests

    with patch.object(whatsapp.requests, "get", side_effect=requests.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            assert whatsapp.estado_da_instancia() == "erro"
    assert "falha ao consultar estado" in caplog.text


def test_estado_da_instancia_resposta_recusada_e_erro(monkeypatch, caplog):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=False, status_code=401, text="Unauthorized")
    with patch.object(whatsapp.requests, "get", return_value=resposta):
        with caplog.at_level("ERROR"):
            assert whatsapp.estado_da_instancia() == "erro"
    assert "401" in caplog.text
