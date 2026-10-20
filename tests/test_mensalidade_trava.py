import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "brutus.localhost"
CORPO_402 = {
    "erro": "O painel está bloqueado pela mensalidade.",
    "code": "mensalidade_bloqueada",
}


def _barbeiro(barbearia_id, papel="DONO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Zeca",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )


def _atrasar(barbearia_id, dias):
    """Paga ate `dias` atras (data de Sao Paulo, como a trava le), com valor."""
    from tenant.models import Assinatura

    Assinatura.objects.using("owner").filter(barbearia_id=barbearia_id).update(
        isenta=False, valor_centavos=10000,
        paga_ate=timezone.localdate() - timedelta(days=dias),
    )


def _agenda(client, host=HOST):
    return client.get("/api/painel/agenda", {"dia": "2026-08-20"}, headers={"host": host})


def test_bloqueada_recebe_402_no_painel(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _atrasar(b.id, 7)

    r = _agenda(client)
    assert r.status_code == 402
    assert r.json() == CORPO_402


def test_bloqueada_ainda_alcanca_a_rota_da_mensalidade(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _atrasar(b.id, 7)

    r = client.get("/api/painel/mensalidade", headers={"host": HOST})
    assert r.status_code == 200
    assert r.json()["situacao"] == "BLOQUEADA"


def test_vizinho_do_prefixo_nao_e_rota_livre(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _atrasar(b.id, 7)

    r = client.get("/api/painel/mensalidadeX", headers={"host": HOST})
    assert r.status_code == 402


def test_bloqueada_ainda_tem_eu_e_logout(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _atrasar(b.id, 7)

    assert client.get("/api/auth/eu", headers={"host": HOST}).status_code == 200
    r = client.post("/api/auth/logout", headers={"host": HOST, **CABECALHO})
    assert r.status_code == 200


def test_bloqueada_ainda_aceita_agendamento_do_site(client, cenario, monkeypatch):
    from app.services.lista_do_dia import SEM_LISTA
    from test_agendamentos import (
        _proximo_slot_livre,
        _servico_vinculado,
    )

    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="BARBEIRO")
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)
    _atrasar(b.id, 7)

    with patch("app.api.v1.views.agendamentos.enviar_ao_cliente"), patch(
        "app.api.v1.views.agendamentos.enviar_a_equipe_da"
    ), patch("app.services.lista_do_dia.avisar_mudanca", return_value=SEM_LISTA):
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Cliente Novo",
                "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201


def test_atrasada_dentro_da_tolerancia_nao_trava(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)
    _atrasar(b.id, 3)

    assert _agenda(client).status_code == 200


def test_isenta_nao_trava(client, cenario):
    b = cenario["brutus"]
    _logar(client, _barbeiro(b.id), b.id)

    assert _agenda(client).status_code == 200


def test_a_outra_barbearia_nao_e_afetada(client, cenario):
    b, outra = cenario["brutus"], cenario["dontony"]
    _logar(client, _barbeiro(outra.id), outra.id)
    _atrasar(b.id, 7)

    assert _agenda(client, host="dontony.localhost").status_code == 200
