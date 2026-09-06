"""A saida de dev para testar pelo celular sem DNS curinga.

O endereco E a barbearia neste produto, e isso cobra um preco em dev: o
celular nao alcanca `localhost` (la' `localhost` e' o proprio celular) e um IP
nu nao tem onde por subdominio. `TENANT_PADRAO` resolve mandando todo host SEM
subdominio para uma barbearia escolhida.

O que estes testes guardam nao e' a conveniencia — e' o RECORTE dela. Um
fallback na resolucao de tenant e' a coisa mais perigosa que se pode
acrescentar a um multi-tenant, entao o que mais importa aqui e' tudo aquilo em
que ele NAO pega.
"""

import pytest
from django.test import override_settings

from tenant.config import origem_e_permitida, sem_subdominio, tenant_padrao

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

# `*` porque em uso real o host e' o IP da maquina na rede — o mesmo que o
# settings.py faz quando o modo esta ligado.
padrao = lambda slug: override_settings(TENANT_PADRAO=slug, ALLOWED_HOSTS=["*"])


# ---- A trava: fora de DEBUG a variavel nao liga nada ----------------------


def test_producao_ignora_a_variavel():
    """A garantia que sustenta o resto. Sem ela, um TENANT_PADRAO esquecido
    num .env de servidor faria TODO host desconhecido servir a mesma
    barbearia — inclusive o dominio nu, que e' a pagina institucional.
    """
    assert tenant_padrao("brutus", debug=False) == ""


def test_em_dev_a_variavel_vale():
    assert tenant_padrao("brutus", debug=True) == "brutus"


def test_variavel_ausente_deixa_o_modo_desligado():
    assert tenant_padrao("", debug=True) == ""


def test_o_slug_e_normalizado():
    # O usuario digita isto a mao num .env; " Brutus " nao pode virar 404 mudo.
    assert tenant_padrao("  BRUTUS  ", debug=True) == "brutus"


# ---- O recorte: onde o fallback pega, e onde nao pega --------------------


@pytest.mark.parametrize(
    "host,porque",
    [
        ("10.220.0.207:8000", "o IP da maquina na rede — o caso de uso"),
        ("localhost", "o dominio nu, para o mesmo teste valer no PC"),
        ("192.168.0.15", "outra faixa de rede domestica"),
    ],
)
def test_host_sem_subdominio_cai_no_padrao(host, porque):
    assert sem_subdominio(host, "localhost") is True


@pytest.mark.parametrize(
    "host,porque",
    [
        ("brutus.localhost", "tem subdominio, e ele manda"),
        ("www.localhost", "reservado: nao e' barbearia, e nao vira uma"),
        ("a.b.localhost", "subdominio de subdominio"),
        ("naoexiste.localhost", "slug sem dono continua 404"),
        ("admin.localhost", "o painel da plataforma nao e' barbearia"),
    ],
)
def test_host_com_subdominio_nunca_cai_no_padrao(host, porque):
    """O recorte que evita o acidente: um erro de digitacao no subdominio tem
    que dar 404, nunca abrir a barbearia errada em silencio.
    """
    assert sem_subdominio(host, "localhost") is False


# ---- Ponta a ponta, pelo middleware --------------------------------------


def test_ip_nu_serve_a_barbearia_padrao(client, cenario):
    with padrao("brutus"):
        r = client.get("/api/saude", headers={"host": "10.220.0.207:8000"})
    assert r.status_code == 200
    assert r.json()["barbearia"] == "Brutus"


def test_sem_o_modo_o_ip_nu_da_404(client, cenario):
    with override_settings(TENANT_PADRAO="", ALLOWED_HOSTS=["*"]):
        r = client.get("/api/saude", headers={"host": "10.220.0.207:8000"})
    assert r.status_code == 404


def test_o_subdominio_continua_mandando(client, cenario):
    """O padrao e' fallback, nunca override: com `dontony.localhost` na barra,
    e' Dom Tony que aparece, mesmo com brutus como padrao.
    """
    with padrao("brutus"):
        r = client.get("/api/saude", headers={"host": "dontony.localhost"})
    assert r.json()["barbearia"] == "Dom Tony"


def test_subdominio_desconhecido_nao_vira_o_padrao(client, cenario):
    with padrao("brutus"):
        r = client.get("/api/saude", headers={"host": "naoexiste.localhost"})
    assert r.status_code == 404


def test_o_host_do_admin_nao_vira_barbearia(client, cenario):
    with padrao("brutus"):
        r = client.get("/api/saude", headers={"host": "admin.localhost"})
    assert r.json()["barbearia"] is None
    assert r.json()["admin"] is True


def test_padrao_apontando_para_barbearia_inexistente_da_404(client, cenario):
    with padrao("fantasma"):
        r = client.get("/api/saude", headers={"host": "10.220.0.207:8000"})
    assert r.status_code == 404


# ---- CORS: o filtro de PAR continua sendo o que protege -------------------


def test_cors_aceita_a_origem_do_mesmo_ip():
    assert origem_e_permitida(
        "http://10.220.0.207:3000", "10.220.0.207:8000", "localhost", "brutus"
    )


def test_cors_recusa_origem_de_outra_maquina_da_rede():
    """O filtro de FORMA nao sabe julgar IP, entao neste modo quem protege e'
    o PAR: so' a propria pagina servida por aquele host pode ler a API dele.
    """
    assert not origem_e_permitida(
        "http://10.220.0.99:3000", "10.220.0.207:8000", "localhost", "brutus"
    )


def test_cors_recusa_dominio_alheio_mesmo_no_modo_padrao():
    assert not origem_e_permitida(
        "http://malicioso.com", "10.220.0.207:8000", "localhost", "brutus"
    )


def test_cors_sem_o_modo_recusa_o_ip():
    assert not origem_e_permitida(
        "http://10.220.0.207:3000", "10.220.0.207:8000", "localhost", ""
    )


def test_o_cruzado_entre_tenants_continua_recusado():
    """A regressao que a revisao final pegou uma vez; o modo novo nao pode
    reabri-la — `sem_subdominio` e' falso para os dois lados aqui.
    """
    assert not origem_e_permitida(
        "http://dontony.localhost:3000", "brutus.localhost:8000", "localhost", "brutus"
    )
