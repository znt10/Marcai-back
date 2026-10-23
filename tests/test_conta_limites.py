from django.core.cache import cache

from app.services import conta_limites
from app.services.conta_limites import devolver_envio, reservar_envio


def _reserva(whatsapp, ip, vezes=1):
    for _ in range(vezes):
        assert reservar_envio(whatsapp, ip) is None


def test_primeira_reserva_passa():
    assert reservar_envio("5511999990001", "1.1.1.1") is None


def test_limite_por_numero_3_por_hora():
    _reserva("5511999990001", "1.1.1.1", 3)
    assert reservar_envio("5511999990001", "2.2.2.2") == "numero"


def test_limite_por_numero_10_por_dia(monkeypatch):
    # A janela da hora nao segura aqui (3/h): isola a do dia.
    monkeypatch.setattr(conta_limites, "CONTA_ENVIOS_POR_NUMERO_HORA", 100)
    monkeypatch.setattr(conta_limites, "CONTA_ENVIOS_POR_IP_HORA", 100)
    _reserva("5511999990001", "1.1.1.1", 10)
    assert reservar_envio("5511999990001", "1.1.1.1") == "numero"


def test_limite_por_ip_10_por_hora():
    for i in range(10):
        assert reservar_envio(f"55119999900{i:02d}", "1.1.1.1") is None
    assert reservar_envio("5511999991111", "1.1.1.1") == "ip"
    assert reservar_envio("5511999991111", "9.9.9.9") is None


def test_teto_geral(monkeypatch):
    monkeypatch.setattr(conta_limites, "CONTA_ENVIOS_POR_DIA", 2)
    _reserva("5511999990001", "1.1.1.1")
    _reserva("5511999990002", "2.2.2.2")
    assert reservar_envio("5511999990003", "3.3.3.3") == "teto"


def test_recusa_nao_consome_cota():
    _reserva("5511999990001", "1.1.1.1", 3)
    k = conta_limites._chaves("5511999990001", "1.1.1.1")
    antes = {nome: cache.get(chave) for nome, chave in k.items()}

    # Varias recusas seguidas: nenhuma deixa rastro nos quatro contadores.
    for _ in range(5):
        assert reservar_envio("5511999990001", "1.1.1.1") == "numero"
    assert {nome: cache.get(chave) for nome, chave in k.items()} == antes

    # Janela da hora livre de novo (vence no relogio): a proxima passa, e o dia
    # e o IP nao foram inflados pelas recusas.
    cache.delete(k["numero_hora"])
    assert reservar_envio("5511999990001", "1.1.1.1") is None


def test_devolver_libera_a_vaga():
    _reserva("5511999990001", "1.1.1.1", 3)
    assert reservar_envio("5511999990001", "1.1.1.1") == "numero"
    devolver_envio("5511999990001", "1.1.1.1")
    assert reservar_envio("5511999990001", "1.1.1.1") is None


def test_devolver_desfaz_as_quatro_janelas():
    _reserva("5511999990001", "1.1.1.1")
    devolver_envio("5511999990001", "1.1.1.1")
    k = conta_limites._chaves("5511999990001", "1.1.1.1")
    assert [cache.get(chave) for chave in k.values()] == [0, 0, 0, 0]


def test_devolver_sem_reserva_nao_quebra():
    devolver_envio("5511999990001", "1.1.1.1")
