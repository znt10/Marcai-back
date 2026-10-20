import uuid

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from app.services import conta_sessao, sessao, trava_conta
from tenant.config import (
    CONTA_SESSAO_COOKIE,
    CONTA_TRAVA_BASE_MS,
    CONTA_TRAVA_TETO_MS,
)
from tenant.models import ContaCliente


@pytest.fixture(autouse=True)
def _segredo(monkeypatch):
    monkeypatch.setenv("SESSAO_JWT_SECRET", "segredo-so-de-teste")


def _conta(confirmada=True, tv=0):
    return ContaCliente.objects.using("owner").create(
        id=uuid.uuid4(),
        nome="Ana",
        whatsapp=f"5511{uuid.uuid4().int % 10**9:09d}",
        senha_hash="x",
        confirmada_em=timezone.now() if confirmada else None,
        token_version=tv,
    )


def _pedido(token):
    req = RequestFactory().get("/")
    if token is not None:
        req.COOKIES[CONTA_SESSAO_COOKIE] = token
    return req


# ------------------------------------------------------------------ o token


def test_emitir_e_ler_ida_e_volta():
    conta_id = uuid.uuid4()
    lido = conta_sessao.ler(conta_sessao.emitir(conta_id, 3))
    assert lido == {"sub": conta_id, "tv": 3}


def test_token_de_barbeiro_nao_vale_como_conta():
    token = sessao.emitir(sub=str(uuid.uuid4()), bid=str(uuid.uuid4()), papel="DONO", tv=0)
    assert conta_sessao.ler(token) is None


def test_token_de_conta_nao_vale_no_painel():
    # Mesmo segredo dos dois lados: quem separa e' a audiencia. O PyJWT recusa
    # um token com `aud` quando o decode nao pede audiencia nenhuma, e este
    # teste trava esse comportamento.
    assert sessao.ler(conta_sessao.emitir(uuid.uuid4(), 0)) is None


def test_ler_recusa_lixo_e_tipos_tortos():
    import jwt

    assert conta_sessao.ler(None) is None
    assert conta_sessao.ler("") is None
    assert conta_sessao.ler("nao-e-jwt") is None

    def tokeniza(**carga):
        base = {"aud": "cliente", "sub": str(uuid.uuid4()), "tv": 0}
        base.update(carga)
        return jwt.encode(base, "segredo-so-de-teste", algorithm="HS256")

    assert conta_sessao.ler(tokeniza()) is not None
    assert conta_sessao.ler(tokeniza(tv=True)) is None
    assert conta_sessao.ler(tokeniza(tv="0")) is None
    assert conta_sessao.ler(tokeniza(sub="nao-uuid")) is None
    assert conta_sessao.ler(tokeniza(sub=123)) is None
    assert conta_sessao.ler(tokeniza(aud="outra")) is None


def test_token_expirado_e_recusado():
    import jwt

    token = jwt.encode(
        {"aud": "cliente", "sub": str(uuid.uuid4()), "tv": 0, "exp": 1},
        "segredo-so-de-teste",
        algorithm="HS256",
    )
    assert conta_sessao.ler(token) is None


# ------------------------------------------------------- conta_da_requisicao

db = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@db
def test_conta_da_requisicao_devolve_a_conta():
    conta = _conta()
    achada = conta_sessao.conta_da_requisicao(
        _pedido(conta_sessao.emitir(conta.id, conta.token_version))
    )
    assert achada is not None and achada.id == conta.id


@db
def test_sem_cookie_nao_ha_conta():
    assert conta_sessao.conta_da_requisicao(_pedido(None)) is None


@db
def test_tv_diferente_derruba():
    conta = _conta(tv=2)
    assert conta_sessao.conta_da_requisicao(_pedido(conta_sessao.emitir(conta.id, 1))) is None
    assert conta_sessao.conta_da_requisicao(_pedido(conta_sessao.emitir(conta.id, 2))) is not None


@db
def test_conta_nao_confirmada_nao_entra():
    conta = _conta(confirmada=False)
    assert conta_sessao.conta_da_requisicao(_pedido(conta_sessao.emitir(conta.id, 0))) is None


@db
def test_conta_que_nao_existe_mais_nao_entra():
    assert conta_sessao.conta_da_requisicao(_pedido(conta_sessao.emitir(uuid.uuid4(), 0))) is None


# ------------------------------------------------------------------- o cookie


def test_dominio_do_cookie(settings):
    settings.DOMINIO_BASE = "localhost"
    assert conta_sessao.dominio_do_cookie() is None
    settings.DOMINIO_BASE = "brutus.localhost"
    assert conta_sessao.dominio_do_cookie() is None
    settings.DOMINIO_BASE = "usemarcai.online"
    assert conta_sessao.dominio_do_cookie() == ".usemarcai.online"


def test_plantar_e_apagar_usam_o_mesmo_dominio_e_caminho(settings):
    settings.DOMINIO_BASE = "usemarcai.online"
    settings.DEBUG = False
    conta = ContaCliente(id=uuid.uuid4(), token_version=4)

    plantado = conta_sessao.plantar(HttpResponse(), conta).cookies[CONTA_SESSAO_COOKIE]
    assert conta_sessao.ler(plantado.value) == {"sub": conta.id, "tv": 4}
    assert plantado["httponly"] is True
    assert plantado["samesite"] == "Lax"
    assert plantado["secure"] is True
    assert plantado["path"] == "/"
    assert plantado["domain"] == ".usemarcai.online"
    assert plantado["max-age"] == 30 * 24 * 3600

    apagado = conta_sessao.apagar(HttpResponse()).cookies[CONTA_SESSAO_COOKIE]
    # Sem o mesmo dominio e caminho o navegador nao apaga.
    assert apagado["domain"] == ".usemarcai.online"
    assert apagado["path"] == "/"
    assert apagado["max-age"] == 0


def test_cookie_no_dev_fica_sem_dominio_e_sem_secure(settings):
    settings.DOMINIO_BASE = "localhost"
    settings.DEBUG = True
    plantado = conta_sessao.plantar(
        HttpResponse(), ContaCliente(id=uuid.uuid4())
    ).cookies[CONTA_SESSAO_COOKIE]
    assert plantado["domain"] == ""
    assert plantado["secure"] == ""


# ------------------------------------------------------------------ a trava


def test_trava_cresce_e_tem_teto(monkeypatch):
    agora = [1_000_000.0]
    monkeypatch.setattr(trava_conta, "_agora_ms", lambda: agora[0])
    numero = "5511999990001"

    assert trava_conta.espera_de(numero) == 0

    esperas = []
    for _ in range(8):
        trava_conta.registrar_falha(numero)
        esperas.append(trava_conta.espera_de(numero))

    # Dobra a cada erro a partir da base, e para no teto.
    assert esperas[:5] == [1_000, 2_000, 4_000, 8_000, 16_000]
    assert esperas[5:] == [CONTA_TRAVA_TETO_MS] * 3
    assert CONTA_TRAVA_BASE_MS == esperas[0]

    # Sem bloqueio longo: passado o teto, pode tentar de novo.
    agora[0] += CONTA_TRAVA_TETO_MS
    assert trava_conta.espera_de(numero) == 0


def test_trava_conta_o_tempo_decorrido(monkeypatch):
    agora = [1_000_000.0]
    monkeypatch.setattr(trava_conta, "_agora_ms", lambda: agora[0])
    trava_conta.registrar_falha("5511999990001")
    trava_conta.registrar_falha("5511999990001")
    agora[0] += 500
    assert trava_conta.espera_de("5511999990001") == 1_500


def test_trava_e_por_numero_e_limpar_zera():
    trava_conta.registrar_falha("5511999990001")
    assert trava_conta.espera_de("5511999990001") > 0
    assert trava_conta.espera_de("5511999990002") == 0
    trava_conta.limpar("5511999990001")
    assert trava_conta.espera_de("5511999990001") == 0
