import base64

import pytest

# O modulo inteiro ganha `django_db`, mesmo os testes unitarios que nao tocam
# `Barbearia`/`Barbeiro` (a sessao do admin nao tem tenant nenhum por baixo —
# so' existe UMA conta, fora do banco): as rotas HTTP de login/logout passam
# pelo `TenantMiddleware`, que consulta `Barbearia` MESMO quando o host e' o
# do admin fora do caminho feliz (host errado, ex.: `brutus.localhost`), e a
# marca precisa estar de pe ANTES desse caminho ser exercitado.
pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


# ------------------------------------------------------------ admin_sessao.py


def test_emitir_e_ler_roda_por_dentro():
    from app.services.admin_sessao import emitir, ler

    token = emitir()
    assert ler(token) is True


def test_ler_recusa_none_ou_vazio():
    from app.services.admin_sessao import ler

    assert ler(None) is False
    assert ler("") is False


def test_ler_recusa_lixo():
    from app.services.admin_sessao import ler

    assert ler("nao-e-um-jwt") is False


def test_ler_recusa_assinado_com_outro_segredo(monkeypatch):
    import jwt as pyjwt

    from app.services.admin_sessao import ALGORITMO, ler

    token = pyjwt.encode({"sub": "admin"}, "segredo-errado", algorithm=ALGORITMO)
    assert ler(token) is False


def test_ler_recusa_sub_diferente_de_admin():
    import jwt as pyjwt

    from app.services.admin_sessao import ALGORITMO, _segredo, ler

    token = pyjwt.encode({"sub": "outra-coisa"}, _segredo(), algorithm=ALGORITMO)
    assert ler(token) is False


def test_emitir_sem_segredo_no_ambiente_estoura(monkeypatch):
    monkeypatch.delenv("ADMIN_JWT_SECRET", raising=False)
    from app.services.admin_sessao import emitir

    with pytest.raises(RuntimeError):
        emitir()


# --------------------------------------------------------------- trava_ip.py


@pytest.fixture(autouse=True)
def _limpar_trava_ip():
    from app.services import trava_ip

    trava_ip._falhas.clear()
    yield
    trava_ip._falhas.clear()


def test_ip_de_le_o_primeiro_da_lista_de_x_forwarded_for():
    from django.test import RequestFactory

    from app.services.trava_ip import ip_de

    req = RequestFactory().post("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8")
    assert ip_de(req) == "1.2.3.4"


def test_ip_de_cai_pro_remote_addr_sem_forwarded_for():
    from django.test import RequestFactory

    from app.services.trava_ip import ip_de

    req = RequestFactory().post("/")
    assert ip_de(req) == req.META["REMOTE_ADDR"]


def test_espera_de_zero_sem_falha_nenhuma():
    from app.services.trava_ip import espera_de

    assert espera_de("1.2.3.4") == 0


def test_espera_de_cresce_exponencial_antes_do_limite(monkeypatch):
    """1s, 2s, 4s, 8s — dobra a cada falha, ate a falha ANTERIOR ao limite de
    tentativas (a que atinge o limite vira bloqueio fixo, testado a parte).
    Mesma progressao do trava-ip.ts do front."""
    from app.services import trava_ip
    from tenant.config import ADMIN_TRAVA_TENTATIVAS

    relogio = {"agora": 0.0}
    monkeypatch.setattr(trava_ip, "_agora_ms", lambda: relogio["agora"])

    esperadas = [1_000 * 2**i for i in range(ADMIN_TRAVA_TENTATIVAS - 1)]
    for esperada in esperadas:
        trava_ip.registrar_falha("9.9.9.9")
        # logo apos a falha, a espera cheia ainda deve faltar inteira
        assert trava_ip.espera_de("9.9.9.9") == esperada
        relogio["agora"] += esperada  # avanca o relogio ate a janela abrir


def test_espera_de_bloqueia_fixo_apos_o_limite_de_tentativas(monkeypatch):
    from app.services import trava_ip
    from tenant.config import ADMIN_TRAVA_BLOQUEIO_MS, ADMIN_TRAVA_TENTATIVAS

    relogio = {"agora": 0.0}
    monkeypatch.setattr(trava_ip, "_agora_ms", lambda: relogio["agora"])

    for _ in range(ADMIN_TRAVA_TENTATIVAS):
        trava_ip.registrar_falha("8.8.8.8")

    assert trava_ip.falhas_de("8.8.8.8") == ADMIN_TRAVA_TENTATIVAS
    assert trava_ip.espera_de("8.8.8.8") == ADMIN_TRAVA_BLOQUEIO_MS


def test_limpar_falhas_reseta_a_progressao():
    from app.services import trava_ip

    trava_ip.registrar_falha("7.7.7.7")
    trava_ip.limpar_falhas("7.7.7.7")
    assert trava_ip.falhas_de("7.7.7.7") == 0
    assert trava_ip.espera_de("7.7.7.7") == 0


# ------------------------------------------------------------- admin_senha.py


def test_conferir_senha_aceita_usuario_e_senha_certos(monkeypatch):
    from app.services.admin_senha import conferir_senha
    from app.services.senha import gerar

    hash_b64 = base64.b64encode(gerar("senha-do-dono-123").encode()).decode()
    monkeypatch.setenv("ADMIN_USUARIO", "kadu")
    monkeypatch.setenv("ADMIN_SENHA_HASH_B64", hash_b64)

    assert conferir_senha("kadu", "senha-do-dono-123") is True


def test_conferir_senha_recusa_senha_errada(monkeypatch):
    from app.services.admin_senha import conferir_senha
    from app.services.senha import gerar

    hash_b64 = base64.b64encode(gerar("senha-certa").encode()).decode()
    monkeypatch.setenv("ADMIN_USUARIO", "kadu")
    monkeypatch.setenv("ADMIN_SENHA_HASH_B64", hash_b64)

    assert conferir_senha("kadu", "senha-errada") is False


def test_conferir_senha_recusa_usuario_errado(monkeypatch):
    from app.services.admin_senha import conferir_senha
    from app.services.senha import gerar

    hash_b64 = base64.b64encode(gerar("senha-certa").encode()).decode()
    monkeypatch.setenv("ADMIN_USUARIO", "kadu")
    monkeypatch.setenv("ADMIN_SENHA_HASH_B64", hash_b64)

    assert conferir_senha("outro-usuario", "senha-certa") is False


def test_conferir_senha_sem_env_recusa_tudo(monkeypatch):
    monkeypatch.delenv("ADMIN_USUARIO", raising=False)
    monkeypatch.delenv("ADMIN_SENHA_HASH_B64", raising=False)
    from app.services.admin_senha import conferir_senha

    assert conferir_senha("qualquer", "qualquer") is False


# ---------------------------------------------------------------- ExigeAdmin


def test_exige_admin_recusa_sem_cookie():
    from django.test import RequestFactory
    from rest_framework.views import APIView

    from app.api.v1.mixins import ExigeAdmin, SessaoAdminInvalida

    class _View(ExigeAdmin, APIView):
        def get(self, request):
            return None

    req = _View.as_view()(RequestFactory().get("/"))
    assert req.status_code == 401


def test_exige_admin_deixa_passar_com_cookie_valido():
    from django.test import RequestFactory
    from rest_framework.response import Response
    from rest_framework.views import APIView

    from app.api.v1.mixins import ExigeAdmin
    from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir

    class _View(ExigeAdmin, APIView):
        def get(self, request):
            return Response({"ok": True})

    req = RequestFactory().get("/")
    req.COOKIES[COOKIE_SESSAO_ADMIN] = emitir()
    resposta = _View.as_view()(req)
    assert resposta.status_code == 200


# ------------------------------------------------------------- rotas de login


def _login(client, usuario="kadu", senha="senha-do-dono-123", host="admin.localhost"):
    return client.post(
        "/api/admin/auth/login",
        {"usuario": usuario, "senha": senha},
        content_type="application/json",
        headers={"host": host, "x-brutus-cliente": "web"},
    )


@pytest.fixture(autouse=True)
def _admin_de_teste(monkeypatch):
    from app.services.senha import gerar

    hash_b64 = base64.b64encode(gerar("senha-do-dono-123").encode()).decode()
    monkeypatch.setenv("ADMIN_USUARIO", "kadu")
    monkeypatch.setenv("ADMIN_SENHA_HASH_B64", hash_b64)


def test_login_admin_certo_planta_cookie(client):
    from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, ler

    r = _login(client)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert ler(r.cookies[COOKIE_SESSAO_ADMIN].value) is True


def test_login_admin_fora_do_host_admin_da_404(client):
    r = _login(client, host="brutus.localhost")
    assert r.status_code == 404


def test_login_admin_senha_errada_401_generico(client):
    r = _login(client, senha="senha-errada")
    assert r.status_code == 401
    assert r.json() == {"erro": "usuário ou senha inválidos"}


def test_login_admin_corpo_malformado_conta_como_tentativa_falha(client):
    r = client.post(
        "/api/admin/auth/login",
        data="isto nao e json",
        content_type="application/json",
        headers={"host": "admin.localhost", "x-brutus-cliente": "web"},
    )
    assert r.status_code == 401


def test_login_admin_trava_apos_tentativas_repetidas(client, monkeypatch):
    """O relogio e' mockado pra' avancar exatamente o que falta a cada volta —
    sem isso, a SEGUNDA tentativa em sequencia real ja cairia no backoff
    (1s) e devolveria 429 antes de completar as `ADMIN_TRAVA_TENTATIVAS`
    tentativas de senha errada que este teste quer exercitar."""
    from app.services import trava_ip
    from tenant.config import ADMIN_TRAVA_TENTATIVAS

    relogio = {"agora": 0.0}
    monkeypatch.setattr(trava_ip, "_agora_ms", lambda: relogio["agora"])
    ip = "127.0.0.1"  # REMOTE_ADDR padrao do client de teste do Django

    for i in range(ADMIN_TRAVA_TENTATIVAS):
        r = _login(client, senha="errada")
        assert r.status_code == 401
        # so avanca o relogio ENTRE tentativas, nunca depois da ultima: a
        # verificacao do bloqueio abaixo precisa acontecer com o relogio
        # parado, senao os 10 minutos de bloqueio ja teriam decorrido.
        if i < ADMIN_TRAVA_TENTATIVAS - 1:
            relogio["agora"] += trava_ip.espera_de(ip) + 1

    r = _login(client, senha="errada")
    assert r.status_code == 429
    assert "Bloqueado" in r.json()["erro"]


def test_logout_admin_sempre_200_e_apaga_cookie(client):
    r = client.post(
        "/api/admin/auth/logout",
        headers={"host": "admin.localhost", "x-brutus-cliente": "web"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
