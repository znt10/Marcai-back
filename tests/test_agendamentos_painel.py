import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir
from fabricas import criar_barbeiro

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return criar_barbeiro(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.usuario_id, bid=barbearia_id, papel=barbeiro.usuario.papel, tv=0)
    return host


def _servico_vinculado(barbearia_id, barbeiro, duracao_min=30, preco_centavos=None):
    from tenant.models import BarbeiroServico, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"Corte {uuid.uuid4().hex[:6]}",
        duracao_minima_min=15, duracao_sugerida_min=duracao_min,
    )
    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id, servico_id=servico.id, barbearia_id=barbearia_id,
        duracao_min=duracao_min, preco_centavos=preco_centavos, ativo=True,
    )
    return servico


def _expediente_aberto_24h(barbearia_id, barbeiro, dia_semana):
    from tenant.models import HorarioTrabalho

    HorarioTrabalho.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, barbeiro_id=barbeiro.id,
        dia_semana=dia_semana, minutos_inicio=0, minutos_fim=1440,
    )


def _proximo_slot_livre(barbeiro, servico):
    """Um horario livre daqui a pouco, na grade de 30 em 30 minutos, com
    jornada aberta o dia inteiro — evita depender de qual dia da semana e'
    'agora' no momento em que o teste roda."""
    agora = datetime.now(timezone.utc)
    minuto = (agora.minute // 30 + 1) * 30
    base = agora.replace(second=0, microsecond=0, minute=0) + timedelta(minutes=minuto)
    _expediente_aberto_24h(barbeiro.barbearia_id, barbeiro, ((base.date().isoweekday()) % 7))
    return base


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


def test_marca_e_manda_confirmacao(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico_vinculado(b.id, barbeiro, duracao_min=30)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with patch("app.api.v1.views.agendamentos_painel.enviar_texto") as mock_envia:
        r = client.post(
            "/api/painel/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Cliente Novo",
                "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 201
    assert "codigo" in r.json()
    mock_envia.assert_called_once()

    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    assert criado.status == "CONFIRMADO"
    # Dentro da janela do lembrete (< 60 min de agora): nasce ja avisado.
    assert criado.lembrete_enviado_em is not None


def test_marcar_no_balcao_tambem_snapshota_o_preco(client, cenario):
    """`marcar()` e' compartilhado entre painel e publico — este teste so'
    confirma que o balcao herda o mesmo snapshot, sem repetir toda a
    cobertura ja feita em test_agendamentos.py."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico_vinculado(b.id, barbeiro, preco_centavos=3500)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with patch("app.api.v1.views.agendamentos_painel.enviar_texto"):
        r = client.post(
            "/api/painel/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Cliente Novo",
                "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 201

    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    assert criado.preco_centavos == 3500


def test_marcar_no_passado_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico_vinculado(b.id, barbeiro)

    passado = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = client.post(
        "/api/painel/agendamentos",
        {
            "barbeiroId": barbeiro.id, "servicoId": servico.id, "inicio": passado,
            "nome": "Cliente", "whatsapp": "11977778888",
        },
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_marcar_na_agenda_do_colega_e_404(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)
    servico = _servico_vinculado(b.id, colega)
    inicio = _proximo_slot_livre(colega, servico)

    r = client.post(
        "/api/painel/agendamentos",
        {
            "barbeiroId": colega.id, "servicoId": servico.id, "inicio": inicio.isoformat(),
            "nome": "Cliente", "whatsapp": "11977778888",
        },
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 404


def test_servico_nao_vinculado_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    from tenant.models import Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Sem vinculo",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    inicio = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    r = client.post(
        "/api/painel/agendamentos",
        {
            "barbeiroId": barbeiro.id, "servicoId": servico.id, "inicio": inicio,
            "nome": "Cliente", "whatsapp": "11977778888",
        },
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_cancelar_muda_status_e_avisa_o_cliente(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    from tenant.models import Agendamento, Cliente, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=20, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Cliente", whatsapp="11988889999",
    )
    futuro = datetime.now(timezone.utc) + timedelta(hours=3)
    a = Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=futuro, fim=futuro + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )

    with patch("app.api.v1.views.agendamentos_painel.enviar_texto") as mock_envia:
        r = client.post(
            f"/api/painel/agendamentos/{a.id}/cancelar",
            headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 200
    mock_envia.assert_called_once()

    atualizado = Agendamento.objects.using("owner").get(id=a.id)
    assert atualizado.status == "CANCELADO_BARBEIRO"
    assert atualizado.cancelado_em is not None


def test_cancelar_agendamento_do_colega_e_404_para_barbeiro_comum(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)

    from tenant.models import Agendamento, Cliente, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=20, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Cliente", whatsapp="11988889999",
    )
    futuro = datetime.now(timezone.utc) + timedelta(hours=3)
    a = Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=colega.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=futuro, fim=futuro + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )

    r = client.post(f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": host, **CABECALHO})
    assert r.status_code == 404

    ainda_confirmado = Agendamento.objects.using("owner").get(id=a.id)
    assert ainda_confirmado.status == "CONFIRMADO"


def test_cancelar_id_inexistente_e_404(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.post(
        "/api/painel/agendamentos/nao-existe/cancelar", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 404
