import uuid

import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

# O mesmo numero do settings (`DEFAULT_THROTTLE_RATES["login"]`). Escrito aqui
# de proposito: se alguem afrouxar a taxa, este teste avisa.
LIMITE = 10


def _logar(client, xff=None, whatsapp="11900000000"):
    headers = {"host": "brutus.localhost", "x-brutus-cliente": "web"}
    if xff:
        headers["x-forwarded-for"] = xff
    return client.post(
        "/api/auth/login",
        {"whatsapp": whatsapp, "senha": "chute"},
        content_type="application/json",
        headers=headers,
    )


@pytest.fixture
def argon2_contado(monkeypatch):
    """Conta quantas vezes o argon2 rodou. E' ele que o limite protege: o
    pedido que passa do limite nao pode chegar a gastar CPU nele."""
    from app.services import autenticacao

    chamadas = {"n": 0}
    original = autenticacao.confere

    def contando(*args):
        chamadas["n"] += 1
        return original(*args)

    monkeypatch.setattr(autenticacao, "confere", contando)
    return chamadas


def test_passou_do_limite_toma_429_sem_rodar_o_argon2(client, cenario, argon2_contado):
    """Numero inexistente de proposito: e' o caso que a trava por conta nao
    ve (nao ha conta para travar) e que roda o argon2 toda vez."""
    for _ in range(LIMITE):
        assert _logar(client).status_code == 401
    assert argon2_contado["n"] == LIMITE

    r = _logar(client)
    assert r.status_code == 429
    assert r.json() == {"erro": "Muitas tentativas. Tenta de novo daqui a pouco."}
    assert 0 < int(r["Retry-After"]) <= 60
    assert argon2_contado["n"] == LIMITE


def test_forjar_o_primeiro_ip_do_forwarded_for_nao_escapa(client, cenario):
    """O primeiro IP da lista e' o que o cliente escreveu. Se ele contasse,
    bastaria um valor novo por pedido para nunca bater no limite."""
    for _ in range(LIMITE):
        _logar(client, xff=f"{uuid.uuid4().int % 256}.1.1.1, 9.9.9.9")

    r = _logar(client, xff="42.42.42.42, 9.9.9.9")
    assert r.status_code == 429


def test_cada_ip_tem_o_seu_limite(client, cenario):
    for _ in range(LIMITE):
        _logar(client, xff="9.9.9.9")
    assert _logar(client, xff="9.9.9.9").status_code == 429

    assert _logar(client, xff="8.8.8.8").status_code == 401


def test_login_do_admin_tambem_e_limitado(client, monkeypatch):
    """A trava do admin por si so' ja' seguraria este loop (ela espera entre
    tentativas). Desligada aqui para provar que o limite existe por baixo
    dela — e' ele que segura quem distribui as tentativas no tempo."""
    from app.api.v1.views import admin_autenticacao

    monkeypatch.setattr(admin_autenticacao, "espera_de", lambda ip: 0)

    def entrar():
        return client.post(
            "/api/admin/auth/login",
            {"usuario": "kadu", "senha": "errada"},
            content_type="application/json",
            headers={"host": "admin.localhost", "x-brutus-cliente": "web"},
        )

    for _ in range(LIMITE):
        assert entrar().status_code == 401
    r = entrar()
    assert r.status_code == 429
    assert "Muitas tentativas" in r.json()["erro"]


# ------------------------------------------------------- o limite de toda a API

GERAL = 120  # `DEFAULT_THROTTLE_RATES["geral"]` no settings


def test_toda_rota_da_api_tem_limite_por_ip(client, cenario):
    """Uma rota publica qualquer, sem login nenhum no meio."""
    headers = {"host": "brutus.localhost", "x-forwarded-for": "7.7.7.7"}
    for _ in range(GERAL):
        assert client.get("/api/barbearia", headers=headers).status_code == 200

    r = client.get("/api/barbearia", headers=headers)
    assert r.status_code == 429
    assert r.json() == {"erro": "Muitas tentativas. Tenta de novo daqui a pouco."}
    assert "Retry-After" in r


def test_sessao_nao_livra_do_limite(client, cenario):
    """O `AnonRateThrottle` do DRF deixaria pedido autenticado passar livre.
    Aqui o limite e' pelo IP, com ou sem sessao — uma conta comprometida nao
    vira torneira aberta."""
    from app.services.sessao import COOKIE_SESSAO, emitir
    from tenant.models import Barbeiro

    barbeiro = Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=cenario["brutus"].id, nome="Zeca",
        whatsapp="11988887777", ativo=True,
    )
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=cenario["brutus"].id, papel=barbeiro.papel, tv=barbeiro.token_version
    )
    headers = {"host": "brutus.localhost", "x-forwarded-for": "5.5.5.5"}
    for _ in range(GERAL):
        assert client.get("/api/auth/eu", headers=headers).status_code == 200
    assert client.get("/api/auth/eu", headers=headers).status_code == 429


@pytest.mark.parametrize(
    "caminho", ["/api/interno/whatsapp/evento", "/api/cron/lembretes"]
)
def test_webhook_e_cron_ficam_fora_do_limite(client, caminho):
    """Vem de dentro da rede, sempre do mesmo IP, com credencial propria. Um
    429 ali seria mensagem de cliente ou lembrete perdido."""
    headers = {"host": "admin.localhost", "x-brutus-cliente": "web"}
    for _ in range(GERAL + 5):
        r = client.post(caminho, {}, content_type="application/json", headers=headers)
        assert r.status_code != 429
