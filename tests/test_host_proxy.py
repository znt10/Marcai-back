import pytest
from django.test import RequestFactory

from app.services.trava_ip import ip_de
from tenant.middleware import HostDoProxyMiddleware

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

# O Host com que a Vercel entrega o pedido ao Django em producao.
RAILWAY = "marcai-back-production.up.railway.app"
SEGREDO = "segredo-do-proxy-so-de-teste"


@pytest.fixture
def com_segredo(settings):
    settings.PROXY_SEGREDO = SEGREDO


def _pelo_proxy(client, host, segredo=SEGREDO, **extra):
    cabecalhos = {"host": RAILWAY, "x-marcai-host": host, "x-marcai-proxy": segredo}
    cabecalhos.update(extra)
    return client.get("/api/saude", headers=cabecalhos)


def test_host_repassado_vira_barbearia(client, cenario, com_segredo):
    r = _pelo_proxy(client, "brutus.localhost")
    assert r.status_code == 200
    assert r.json()["barbearia"] == "Brutus"


def test_cada_host_repassado_vira_a_sua_barbearia(client, cenario, com_segredo):
    assert _pelo_proxy(client, "dontony.localhost").json()["barbearia"] == "Dom Tony"


def test_host_do_admin_repassado(client, cenario, com_segredo):
    r = _pelo_proxy(client, "admin.localhost")
    assert r.status_code == 200
    assert r.json()["admin"] is True


def test_segredo_errado_nao_troca_o_host(client, cenario, com_segredo):
    # Sem a troca sobra o Host do Railway, que ALLOWED_HOSTS recusa.
    assert _pelo_proxy(client, "brutus.localhost", segredo="chute").status_code == 400


def test_sem_segredo_no_pedido_nao_troca_o_host(client, cenario, com_segredo):
    assert _pelo_proxy(client, "brutus.localhost", segredo="").status_code == 400


def test_segredo_desligado_ignora_os_cabecalhos(client, cenario, settings):
    # Vazio e' o estado de dev: nem um pedido com segredo vazio casando com
    # a configuracao vazia pode trocar o host.
    settings.PROXY_SEGREDO = ""
    assert _pelo_proxy(client, "brutus.localhost", segredo="").status_code == 400


def test_segredo_nao_abre_dominio_de_fora(client, cenario, com_segredo):
    assert _pelo_proxy(client, "brutus.malicioso.com").status_code == 400


def test_segredo_com_texto_nao_ascii_e_ignorado_sem_500(client, cenario, com_segredo):
    assert _pelo_proxy(client, "brutus.localhost", segredo="çãé").status_code == 400


def test_sem_os_cabecalhos_o_host_real_segue_valendo(client, cenario, com_segredo):
    r = client.get("/api/saude", headers={"host": "dontony.localhost"})
    assert r.json()["barbearia"] == "Dom Tony"


def test_cors_pareia_a_origem_com_o_host_repassado(client, cenario, com_segredo):
    origem = "https://brutus.localhost"
    r = _pelo_proxy(client, "brutus.localhost", origin=origem)
    assert r.headers.get("access-control-allow-origin") == origem


def test_cors_nao_deixa_outra_barbearia_ler_pelo_proxy(client, cenario, com_segredo):
    r = _pelo_proxy(client, "brutus.localhost", origin="https://dontony.localhost")
    assert "access-control-allow-origin" not in r.headers


# O X-Forwarded-For que chega do salto Vercel -> Railway, conferido em
# producao: o IP da Vercel na frente, o do cliente em lugar nenhum.
XFF_DA_VERCEL = "18.228.6.216, 152.233.23.194"
CLIENTE = "167.249.51.42"
CABECALHOS_DO_PROXY = ("HTTP_X_MARCAI_HOST", "HTTP_X_MARCAI_PROXY", "HTTP_X_MARCAI_IP")


def _depois_do_middleware(settings, segredo_no_pedido):
    settings.PROXY_SEGREDO = SEGREDO
    visto = {}

    def adiante(request):
        visto["request"] = request
        return None

    request = RequestFactory().get(
        "/api/saude",
        HTTP_HOST=RAILWAY,
        HTTP_X_MARCAI_HOST="admin.localhost",
        HTTP_X_MARCAI_PROXY=segredo_no_pedido,
        HTTP_X_MARCAI_IP=CLIENTE,
        HTTP_X_FORWARDED_FOR=XFF_DA_VERCEL,
    )
    HostDoProxyMiddleware(adiante)(request)
    return visto["request"]


def test_trava_de_login_ve_o_ip_do_cliente_e_nao_o_da_vercel(settings):
    request = _depois_do_middleware(settings, SEGREDO)
    assert ip_de(request) == CLIENTE


def test_ip_repassado_sem_o_segredo_e_ignorado(settings):
    request = _depois_do_middleware(settings, "chute")
    assert request.META["HTTP_X_FORWARDED_FOR"] == XFF_DA_VERCEL


@pytest.mark.parametrize("segredo_no_pedido", [SEGREDO, "chute"])
def test_cabecalhos_do_proxy_nao_seguem_adiante(settings, segredo_no_pedido):
    request = _depois_do_middleware(settings, segredo_no_pedido)
    assert not [k for k in CABECALHOS_DO_PROXY if k in request.META]
