from datetime import timedelta

from django.utils import timezone

from app.services.convite import gerar_convite, link_do_convite
from app.services.senha import hash_de_convite


def test_gerar_convite_guarda_so_o_hash():
    convite = gerar_convite()
    assert convite["hash"] == hash_de_convite(convite["token"])
    assert convite["hash"] != convite["token"]


def test_gerar_convite_vence_em_48_horas():
    antes = timezone.now()
    convite = gerar_convite()
    depois = timezone.now()
    assert antes + timedelta(hours=48) <= convite["expira_em"] <= depois + timedelta(hours=48)


def test_link_do_convite_usa_url_base_do_ambiente(monkeypatch):
    monkeypatch.setenv("URL_BASE", "https://marcai.app")
    link = link_do_convite("brutus", "token-123")
    assert link == "https://brutus.marcai.app/convite/token-123"


def test_link_do_convite_sem_url_base_cai_no_padrao_local(monkeypatch):
    monkeypatch.delenv("URL_BASE", raising=False)
    link = link_do_convite("brutus", "token-123")
    assert link == "http://brutus.localhost:3000/convite/token-123"


def test_link_do_convite_sem_esquema_assume_https(monkeypatch):
    """Quem escreve o dominio nu em producao quer o site de producao, nao
    localhost."""
    monkeypatch.setenv("URL_BASE", "marcai.app")
    link = link_do_convite("brutus", "token-123")
    assert link == "https://brutus.marcai.app/convite/token-123"
