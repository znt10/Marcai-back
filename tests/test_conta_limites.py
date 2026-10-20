from app.services import conta_limites
from app.services.conta_limites import motivo_para_nao_enviar, registrar_envio


def _envia(whatsapp, ip, vezes=1):
    for _ in range(vezes):
        registrar_envio(whatsapp, ip)


def test_sem_envio_nenhum_pode():
    assert motivo_para_nao_enviar("5511999990001", "1.1.1.1") is None


def test_limite_por_numero_3_por_hora():
    _envia("5511999990001", "1.1.1.1", 3)
    assert motivo_para_nao_enviar("5511999990001", "2.2.2.2") == "numero"


def test_dois_envios_ainda_passam():
    _envia("5511999990001", "1.1.1.1", 2)
    assert motivo_para_nao_enviar("5511999990001", "1.1.1.1") is None


def test_limite_por_numero_10_por_dia(monkeypatch):
    # A janela da hora nao segura aqui (3/h): isola a do dia.
    monkeypatch.setattr(conta_limites, "CONTA_ENVIOS_POR_NUMERO_HORA", 100)
    monkeypatch.setattr(conta_limites, "CONTA_ENVIOS_POR_IP_HORA", 100)
    _envia("5511999990001", "1.1.1.1", 10)
    assert motivo_para_nao_enviar("5511999990001", "1.1.1.1") == "numero"


def test_limite_por_ip_10_por_hora():
    for i in range(10):
        registrar_envio(f"55119999900{i:02d}", "1.1.1.1")
    assert motivo_para_nao_enviar("5511999991111", "1.1.1.1") == "ip"
    assert motivo_para_nao_enviar("5511999991111", "9.9.9.9") is None


def test_teto_geral(monkeypatch):
    monkeypatch.setattr(conta_limites, "CONTA_ENVIOS_POR_DIA", 2)
    registrar_envio("5511999990001", "1.1.1.1")
    registrar_envio("5511999990002", "2.2.2.2")
    assert motivo_para_nao_enviar("5511999990003", "3.3.3.3") == "teto"


def test_conferir_nao_conta():
    for _ in range(10):
        assert motivo_para_nao_enviar("5511999990001", "1.1.1.1") is None
