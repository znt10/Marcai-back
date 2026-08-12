import re

import pytest
from django.conf import settings

from tenant.config import regex_de_origem

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.mark.parametrize(
    "origem",
    [
        "http://brutus.localhost:3000",
        "http://dontony.localhost:3000",
        # O admin e reservado para o slug, mas e uma origem legitima do front:
        # e de la que o painel da plataforma chama a API.
        "http://admin.localhost:3000",
    ],
)
def test_origens_do_front_sao_aceitas(origem):
    assert re.match(regex_de_origem("localhost"), origem)


@pytest.mark.parametrize(
    "origem,porque",
    [
        ("http://malicioso.com", "dominio alheio"),
        ("http://brutus.localhost.malicioso.com:3000", "sufixo forjado"),
        ("http://www.localhost:3000", "subdominio reservado"),
        ("http://api.localhost:3000", "subdominio reservado"),
        ("http://a.b.localhost:3000", "subdominio de subdominio"),
    ],
)
def test_origens_de_fora_sao_recusadas(origem, porque):
    assert not re.match(regex_de_origem("localhost"), origem)


def test_o_regex_deriva_da_lista_de_reservados():
    # Um subdominio reservado novo em config.py tem que fechar a porta no CORS
    # sozinho. Se estas duas coisas virarem listas separadas, a segunda para de
    # acompanhar a primeira e ninguem percebe ate alguem registrar 'cdn'.
    from tenant.config import SUBDOMINIOS_RESERVADOS

    for reservado in SUBDOMINIOS_RESERVADOS - {"admin"}:
        assert not re.match(regex_de_origem("localhost"), f"http://{reservado}.localhost:3000")


def test_a_biblioteca_esta_ligada_e_credenciada():
    assert "corsheaders.middleware.CorsMiddleware" in settings.MIDDLEWARE
    # `*` e incompativel com credenciais — se isto virar True, o navegador
    # passa a recusar toda resposta com cookie.
    assert settings.CORS_ALLOW_CREDENTIALS is True
    assert getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) is False


def test_ecoa_a_origem_e_permite_credencial(client, cenario):
    r = client.get(
        "/api/saude",
        headers={"host": "brutus.localhost", "origin": "http://brutus.localhost:3000"},
    )
    assert r["Access-Control-Allow-Origin"] == "http://brutus.localhost:3000"
    assert r["Access-Control-Allow-Credentials"] == "true"


def test_origem_recusada_nao_ganha_cabecalho(client, cenario):
    r = client.get(
        "/api/saude",
        headers={"host": "brutus.localhost", "origin": "http://malicioso.com"},
    )
    assert "Access-Control-Allow-Origin" not in r


def test_escrita_sem_o_header_e_recusada(client, cenario):
    r = client.post("/api/saude", headers={"host": "brutus.localhost"})
    # Entre 3000 e 8000 e same-site, e ai o SameSite=Lax nao protege. Quem
    # protege e o preflight que este header obriga.
    assert r.status_code == 403


def test_escrita_com_o_header_passa(client, cenario):
    r = client.post(
        "/api/saude",
        headers={"host": "brutus.localhost", "x-brutus-cliente": "web"},
    )
    assert r.status_code != 403


def test_get_nao_precisa_do_header(client, cenario):
    r = client.get("/api/saude", headers={"host": "brutus.localhost"})
    assert r.status_code == 200
