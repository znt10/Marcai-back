import uuid
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
        whatsapp.enviar_a_equipe("11977771234", "Lembrete: corte hoje")
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
            whatsapp.enviar_a_equipe("11977771234", "oi")
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
            whatsapp.enviar_a_equipe("11977771234", "oi")
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
            whatsapp.enviar_a_equipe("11977771234", "oi")
    assert "aceito" in caplog.text
    assert "5511977771234@s.whatsapp.net" in caplog.text


# ------------------------------------------------------------- numero_existe
#
# Desde a etapa 1 a pergunta e' feita pela instancia CENTRAL. O plano ainda
# importa: sem zap, a pergunta nem e' feita.

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _config_evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "brutus")


@pytest.fixture
def com_zap(cenario):
    from tenant.models import Barbearia

    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    b.plano = "COM_ZAP"
    return b


def test_numero_existe_sem_url_e_indeterminado(com_zap, monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "indeterminado"


def test_numero_existe_true(com_zap, monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True, "jid": "5511977771234@s.whatsapp.net"}]
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "existe"


def test_numero_existe_false_bloqueia(com_zap, monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": False}]
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "nao_existe"


def test_numero_existe_falha_de_rede_e_indeterminado(com_zap, monkeypatch, caplog):
    _config_evolution(monkeypatch)
    import requests

    with patch.object(whatsapp.requests, "post", side_effect=requests.ConnectionError("boom")):
        with caplog.at_level("ERROR"):
            assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "indeterminado"
    assert "falha ao verificar numero" in caplog.text


def test_numero_existe_resposta_recusada_e_indeterminado(com_zap, monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=False, status_code=401)
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "indeterminado"


def test_numero_existe_usa_cache_dentro_do_ttl(com_zap, monkeypatch):
    """Uma consulta so' por numero dentro do TTL — a segunda chamada nao
    bate na Evolution de novo."""
    _config_evolution(monkeypatch)
    relogio = {"agora": 0.0}
    monkeypatch.setattr(whatsapp, "_agora_ms", lambda: relogio["agora"])

    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as mock_post:
        assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "existe"
        relogio["agora"] += 1_000  # bem dentro do TTL de 24h
        assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "existe"
    mock_post.assert_called_once()


def test_numero_existe_expira_apos_o_ttl(com_zap, monkeypatch):
    _config_evolution(monkeypatch)
    relogio = {"agora": 0.0}
    monkeypatch.setattr(whatsapp, "_agora_ms", lambda: relogio["agora"])

    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as mock_post:
        assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "existe"
        relogio["agora"] += whatsapp.CHECK_NUMERO_TTL_MS + 1
        assert whatsapp.numero_existe(com_zap, "11977771234", "1.1.1.1") == "existe"
    assert mock_post.call_count == 2


def test_numero_existe_limite_por_ip_por_hora(com_zap, monkeypatch):
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
            whatsapp.numero_existe(com_zap, f"1197777000{i}", "2.2.2.2")
        assert mock_post.call_count == whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA

        # a proxima, do MESMO ip, estoura o limite — nem bate na Evolution.
        resultado = whatsapp.numero_existe(com_zap, "11977779999", "2.2.2.2")
    assert resultado == "indeterminado"
    assert mock_post.call_count == whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA


def test_numero_existe_ip_diferente_tem_janela_propria(com_zap, monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True)
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as mock_post:
        for i in range(whatsapp.CHECK_NUMERO_LIMITE_POR_IP_HORA):
            whatsapp.numero_existe(com_zap, f"1197777000{i}", "3.3.3.3")
        assert whatsapp.numero_existe(com_zap, "11977779999", "4.4.4.4") == "existe"
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


# ------------------------------------------------------------------ _enviar


def test_enviar_devolve_o_id_que_a_evolution_deu(monkeypatch):
    """O bot guarda este id para reconhecer o eco da propria resposta quando
    ele volta pelo webhook como `fromMe`."""
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {
        "key": {"id": "3EB0ABC123", "remoteJid": "5583988887777@s.whatsapp.net"},
        "status": "PENDING",
    }
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp._enviar("marcai-x", "83988887777", "oi") == "3EB0ABC123"


def test_enviar_recusado_devolve_none(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    with patch.object(whatsapp.requests, "post", return_value=Mock(ok=False, status_code=400, text="x")):
        assert whatsapp._enviar("marcai-x", "83988887777", "oi") is None


def test_enviar_com_digitando_manda_o_delay_e_espera_por_ele(monkeypatch):
    """A Evolution mostra "digitando..." durante o `delay` e so' responde o
    POST depois de enviar: o timeout tem que cobrir a pausa, ou toda resposta
    do bot viraria "falha ao enviar" com a mensagem saindo mesmo assim."""
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {"key": {"id": "3EB0X"}}
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        whatsapp._enviar("marcai-x", "83988887777", "oi", digitando_ms=3000)
    assert post.call_args.kwargs["json"]["delay"] == 3000
    assert post.call_args.kwargs["timeout"] >= 3 + 3


def test_enviar_sem_digitando_nao_manda_delay(monkeypatch):
    """Confirmacao do site e avisos da equipe saem na hora: o POST deles roda
    dentro do pedido HTTP do cliente."""
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {"key": {"id": "3EB0X"}}
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        whatsapp._enviar("marcai-x", "83988887777", "oi")
    assert "delay" not in post.call_args.kwargs["json"]
    assert post.call_args.kwargs["timeout"] == 3


# ------------------------------------------------ _enviar_aceita / apagar


def test_enviar_aceita_devolve_id_e_jid(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {
        "key": {"id": "3EB0ABC", "remoteJid": "5583988887777@s.whatsapp.net"},
    }
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        aceita = whatsapp._enviar_aceita("brutus", "83988887777", "oi")
    assert aceita == whatsapp.Aceita("3EB0ABC", "5583988887777@s.whatsapp.net")


def test_enviar_aceita_sem_key_ainda_e_aceita(monkeypatch):
    """Aceita sem id e' aceita: o cliente recebe. So' nao da para apagar
    depois — quem guarda (a lista do dia) confere o id."""
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {}
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp._enviar_aceita("brutus", "83988887777", "oi") == whatsapp.Aceita(None, None)


def test_enviar_a_equipe_aceita_vai_pelo_central(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {"key": {"id": "X", "remoteJid": "J"}}
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        assert whatsapp.enviar_a_equipe_aceita("83988887777", "oi") == whatsapp.Aceita("X", "J")
    assert post.call_args.args[0] == "http://evolution:8080/message/sendText/brutus"


def test_apagar_para_todos_manda_id_jid_e_fromme(monkeypatch):
    _config_evolution(monkeypatch)
    with patch.object(whatsapp.requests, "delete", return_value=Mock(ok=True)) as delete:
        assert whatsapp.apagar_para_todos("5583988887777@s.whatsapp.net", "3EB0X") is True
    assert delete.call_args.args[0] == "http://evolution:8080/chat/deleteMessageForEveryone/brutus"
    assert delete.call_args.kwargs["json"] == {
        "id": "3EB0X", "remoteJid": "5583988887777@s.whatsapp.net", "fromMe": True,
    }


def test_apagar_recusado_devolve_false_e_loga(monkeypatch, caplog):
    _config_evolution(monkeypatch)
    with patch.object(
        whatsapp.requests, "delete", return_value=Mock(ok=False, status_code=400, text="nao achei")
    ):
        with caplog.at_level("ERROR"):
            assert whatsapp.apagar_para_todos("j", "i") is False
    assert "nao achei" in caplog.text


def test_apagar_falha_de_rede_devolve_false(monkeypatch):
    _config_evolution(monkeypatch)
    import requests

    with patch.object(whatsapp.requests, "delete", side_effect=requests.ConnectionError("x")):
        assert whatsapp.apagar_para_todos("j", "i") is False


def test_apagar_sem_url_ou_sem_id_nao_chama_nada(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    with patch.object(whatsapp.requests, "delete") as delete:
        assert whatsapp.apagar_para_todos("j", "i") is False
    _config_evolution(monkeypatch)
    with patch.object(whatsapp.requests, "delete") as delete:
        assert whatsapp.apagar_para_todos(None, "i") is False
        assert whatsapp.apagar_para_todos("j", None) is False
    delete.assert_not_called()
