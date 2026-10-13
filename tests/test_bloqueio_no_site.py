from unittest.mock import patch

import pytest

from app.services.clientes_bloqueados import bloquear
from app.services.lista_do_dia import SEM_LISTA
from test_agendamentos import (
    CABECALHO, HOST, _barbeiro, _dia_semana, _envios, _expediente_aberto_24h,
    _proximo_slot_livre, _servico_vinculado,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


@pytest.fixture(autouse=True)
def _sem_lista():
    with patch("app.services.lista_do_dia.avisar_mudanca", return_value=SEM_LISTA):
        yield


def _dois_horarios(barbeiro, servico):
    """Dois horarios livres, uma hora um do outro. `_proximo_slot_livre`
    cadastra o expediente do dia, e chama-lo duas vezes no mesmo dia bate em
    `jornada_unica_por_dia`."""
    from datetime import timedelta

    primeiro = _proximo_slot_livre(barbeiro, servico)
    segundo = primeiro + timedelta(hours=1)
    if _dia_semana(segundo) != _dia_semana(primeiro):
        _expediente_aberto_24h(barbeiro.barbearia_id, barbeiro, _dia_semana(segundo))
    return primeiro, segundo


def _marcar(client, barbeiro, servico, inicio, whatsapp):
    with _envios() as envios:
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Maria", "whatsapp": whatsapp,
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    return r, envios


def _bloquear_quem_marcou(barbearia, codigo, por):
    from datetime import datetime, timezone

    from tenant.models import Agendamento

    a = Agendamento.objects.using("owner").get(codigo=codigo)
    bloquear(barbearia.id, a.id, None, por.id, datetime.now(timezone.utc))


def test_primeiro_agendamento_ganha_a_marca_do_aparelho(client, cenario):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico), "11977778888")

    assert r.status_code == 201
    marca = r.cookies["aparelho"]
    assert marca.value and marca["httponly"] and marca["samesite"] == "Lax"
    assert Agendamento.objects.using("owner").get(codigo=r.json()["codigo"]).aparelho == marca.value


def test_aparelho_que_ja_tem_marca_nao_ganha_outra(client, cenario):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    client.cookies["aparelho"] = "marca-antiga"
    r, _ = _marcar(client, zeca, servico, _proximo_slot_livre(zeca, servico), "11977778888")

    assert r.status_code == 201
    assert "aparelho" not in r.cookies
    assert Agendamento.objects.using("owner").get(codigo=r.json()["codigo"]).aparelho == "marca-antiga"


def test_numero_bloqueado_recebe_o_erro_que_manda_chamar_a_barbearia(client, cenario):
    from tenant.models import Agendamento

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    primeiro, segundo = _dois_horarios(zeca, servico)
    r, _ = _marcar(client, zeca, servico, primeiro, "11977778888")
    _bloquear_quem_marcou(b, r.json()["codigo"], zeca)
    client.cookies.clear()  # outro navegador: so' o numero denuncia

    antes = Agendamento.objects.using("owner").count()
    r, envios = _marcar(client, zeca, servico, segundo, "11977778888")

    assert r.status_code == 422
    assert r.json()["erro"] == (
        "Não foi possível concluir o agendamento. Chama a barbearia: (11) 9 9999-8888"
    )
    assert Agendamento.objects.using("owner").count() == antes
    envios.assert_not_called()


def test_numero_novo_no_mesmo_aparelho_tambem_e_recusado(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    primeiro, segundo = _dois_horarios(zeca, servico)
    r, _ = _marcar(client, zeca, servico, primeiro, "11977778888")
    _bloquear_quem_marcou(b, r.json()["codigo"], zeca)

    # O cookie do primeiro agendamento continua no `client`, como no celular.
    r, _ = _marcar(client, zeca, servico, segundo, "11966665555")
    assert r.status_code == 422


def test_o_painel_continua_marcando_para_o_numero_bloqueado(client, cenario):
    from app.services.sessao import COOKIE_SESSAO, emitir

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    primeiro, segundo = _dois_horarios(zeca, servico)
    r, _ = _marcar(client, zeca, servico, primeiro, "11977778888")
    _bloquear_quem_marcou(b, r.json()["codigo"], zeca)

    client.cookies[COOKIE_SESSAO] = emitir(sub=zeca.id, bid=b.id, papel="BARBEIRO", tv=0)
    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"):
        r = client.post(
            "/api/painel/agendamentos",
            {
                "barbeiroId": zeca.id, "servicoId": servico.id,
                "inicio": segundo.isoformat(),
                "nome": "Maria", "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201
