"""AGUARDANDO_PAGAMENTO segura o horario como CONFIRMADO; EXPIRADO e cancelado nao.

Os dois lugares que seguram vaga (a grade de `slots_do_dia` e o EXCLUDE do
banco) precisam dizer a mesma coisa, senao a tela oferece um horario que o
banco recusa — ou o contrario. Ninguem cria AGUARDANDO pelo fluxo ainda; aqui
ele nasce direto no banco.
"""
import uuid
from datetime import datetime, timedelta, timezone as fuso
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


def _dia():
    from tenant.datas import dia_de_hoje, somar_dias

    return somar_dias(dia_de_hoje(timezone.now()), 30)


@pytest.fixture
def pronto(cenario):
    from tenant.datas import dia_semana_de
    from tenant.models import Barbeiro, BarbeiroServico, HorarioTrabalho, Servico

    b = cenario["brutus"].id
    servico = Servico.objects.using("owner").create(
        barbearia_id=b, nome="Corte", duracao_minima_min=20, duracao_sugerida_min=30,
    )
    barbeiro = Barbeiro.objects.using("owner").create(
        barbearia_id=b, nome="Zeca", whatsapp="83911110001", ativo=True,
    )
    BarbeiroServico.objects.using("owner").create(
        barbearia_id=b, barbeiro=barbeiro, servico=servico, duracao_min=30,
    )
    HorarioTrabalho.objects.using("owner").create(
        barbearia_id=b, barbeiro=barbeiro, dia_semana=dia_semana_de(_dia()),
        minutos_inicio=9 * 60, minutos_fim=18 * 60,
    )
    return {"barbearia": b, "servico": servico, "barbeiro": barbeiro}


def _agendamento(p, minutos, status, alias="owner"):
    from tenant.datas import local_para_utc
    from tenant.models import Agendamento, Cliente

    cliente = Cliente.objects.using("owner").create(
        barbearia_id=p["barbearia"], nome="Fulano",
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )
    inicio = local_para_utc(_dia(), minutos)
    return Agendamento.objects.using(alias).create(
        barbearia_id=p["barbearia"], codigo=uuid.uuid4().hex[:10],
        barbeiro_id=p["barbeiro"].id, cliente_id=cliente.id,
        servico_id=p["servico"].id, servico_nome="Corte",
        inicio=inicio, fim=inicio + timedelta(minutes=30), duracao_min=30,
        status=status,
    )


def _slots(p):
    from app.services.agenda import slots_do_dia
    from tenant.rls import com_barbearia

    with com_barbearia(p["barbearia"]):
        livres = slots_do_dia(
            str(p["barbeiro"].id), str(p["servico"].id), _dia(), datetime.now(fuso.utc),
        )
    return {s.inicio for s in livres}


def _inicio(minutos):
    from tenant.datas import local_para_utc

    return local_para_utc(_dia(), minutos)


# ---- a grade

def test_aguardando_pagamento_tira_o_horario_da_grade(pronto):
    assert _inicio(10 * 60) in _slots(pronto)
    _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")
    assert _inicio(10 * 60) not in _slots(pronto)


@pytest.mark.parametrize("status", ["EXPIRADO", "CANCELADO_CLIENTE", "CANCELADO_BARBEIRO"])
def test_expirado_e_cancelado_liberam_o_horario(pronto, status):
    _agendamento(pronto, 10 * 60, status)
    assert _inicio(10 * 60) in _slots(pronto)


def test_marcar_em_cima_de_aguardando_recusa_com_409(pronto):
    from app.services.agendamentos import ErroCliente, marcar

    _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")
    with pytest.raises(ErroCliente) as e:
        marcar(
            barbearia_id=pronto["barbearia"], barbeiro_id=str(pronto["barbeiro"].id),
            servico_id=str(pronto["servico"].id), inicio=_inicio(10 * 60),
            nome="Maria", whatsapp="83933330003", agora=datetime.now(fuso.utc),
        )
    assert (e.value.status, e.value.mensagem) == (409, "Esse horário não está mais disponível.")


# ---- o banco

def test_banco_recusa_confirmado_em_cima_de_aguardando(pronto):
    from app.services.agendamentos import eh_sobreposicao

    _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")
    with pytest.raises(IntegrityError) as e, transaction.atomic(using="owner"):
        _agendamento(pronto, 10 * 60 + 15, "CONFIRMADO")
    assert eh_sobreposicao(e.value)


def test_banco_recusa_dois_aguardando_no_mesmo_horario(pronto):
    _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")


def test_banco_deixa_expirado_e_cancelado_ao_lado_de_confirmado(pronto):
    _agendamento(pronto, 10 * 60, "CONFIRMADO")
    _agendamento(pronto, 10 * 60, "EXPIRADO")
    _agendamento(pronto, 10 * 60, "CANCELADO_CLIENTE")


def test_banco_deixa_confirmar_o_aguardando_so_se_a_vaga_segue_livre(pronto):
    """O 'recebi' tardio de um EXPIRADO vira CONFIRMADO por UPDATE: se outro
    pegou o horario nesse meio tempo, a restricao e' a palavra final."""
    from tenant.models import Agendamento

    velho = _agendamento(pronto, 10 * 60, "EXPIRADO")
    _agendamento(pronto, 10 * 60, "CONFIRMADO")
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        Agendamento.objects.using("owner").filter(id=velho.id).update(status="CONFIRMADO")


# ---- Cobranca.agendamento

def _cobranca(p, agendamento, valor=3501):
    from tenant.models import Cobranca

    return Cobranca.objects.using("owner").create(
        barbearia_id=p["barbearia"], motivo="AGENDAMENTO", chave_pix="a@b.com",
        valor_base_centavos=3500, valor_centavos=valor, copia_e_cola="x",
        agendamento=agendamento,
    )


def test_uma_cobranca_por_agendamento(pronto):
    a = _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")
    _cobranca(pronto, a, 3501)
    with pytest.raises(IntegrityError), transaction.atomic(using="owner"):
        _cobranca(pronto, a, 3502)


def test_apagar_o_agendamento_zera_a_ligacao_e_guarda_a_cobranca(pronto):
    """Pelo `brutus_app`, que nao pode dar UPDATE em `tenant_cobranca`: quem
    zera a coluna e' o banco (ON DELETE SET NULL feito a mao na 0015)."""
    from tenant.models import Agendamento, Cobranca
    from tenant.rls import com_barbearia

    a = _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")
    c = _cobranca(pronto, a)
    with com_barbearia(pronto["barbearia"]):
        Agendamento.objects.filter(id=a.id).delete()
    c = Cobranca.objects.using("owner").get(id=c.id)
    assert c.agendamento_id is None


def test_apagar_barbearia_com_cobranca_ligada_a_agendamento(cenario, pronto):
    from app.services.admin_barbearias import apagar_barbearia
    from tenant.models import Agendamento, Cobranca

    a = _agendamento(pronto, 10 * 60, "AGUARDANDO_PAGAMENTO")
    _cobranca(pronto, a)
    apagar_barbearia(pronto["barbearia"])
    assert not Agendamento.objects.using("owner").filter(barbearia_id=pronto["barbearia"]).exists()
    assert not Cobranca.objects.using("owner").filter(barbearia_id=pronto["barbearia"]).exists()


def test_apagar_barbearia_com_cobranca_ligada_na_ordem_inversa(cenario, pronto):
    """Se a ordem de apagar um dia mudar (agendamento antes da cobranca), o
    SET NULL do banco ainda tem de segurar."""
    from app.services import admin_barbearias as ab

    a = _agendamento(pronto, 10 * 60, "CONFIRMADO")
    _cobranca(pronto, a)
    antes = ab.ORDEM_DE_APAGAR
    ordem = tuple(m for m in antes if m is not ab.Agendamento)
    i = ordem.index(ab.Cobranca)
    with patch.object(ab, "ORDEM_DE_APAGAR", ordem[:i] + (ab.Agendamento,) + ordem[i:]):
        ab.apagar_barbearia(pronto["barbearia"])
    from tenant.models import Cobranca

    assert not Cobranca.objects.using("owner").filter(barbearia_id=pronto["barbearia"]).exists()


# ---- deadlock vira 409

# O `_gerar_codigo` roda dentro da transacao de `marcar()`, logo antes do
# INSERT: e' onde o deadlock real aparece (o INSERT espera o do outro).
def _deadlock():
    import psycopg
    from django.db.utils import OperationalError

    erro = OperationalError("deadlock detected")
    erro.__cause__ = psycopg.errors.DeadlockDetected("deadlock detected")
    return erro


def test_deadlock_no_insert_vira_409_igual_a_sobreposicao(pronto):
    from app.services.agendamentos import ErroCliente, marcar
    with patch("app.services.agendamentos._gerar_codigo", side_effect=_deadlock()):
        with pytest.raises(ErroCliente) as e:
            marcar(
                barbearia_id=pronto["barbearia"], barbeiro_id=str(pronto["barbeiro"].id),
                servico_id=str(pronto["servico"].id), inicio=_inicio(10 * 60),
                nome="Maria", whatsapp="83933330003", agora=datetime.now(fuso.utc),
            )
    assert (e.value.status, e.value.mensagem) == (409, "Esse horário não está mais disponível.")


def test_outro_erro_de_banco_continua_estourando(pronto):
    from app.services.agendamentos import marcar
    from django.db.utils import OperationalError
    with patch("app.services.agendamentos._gerar_codigo", side_effect=OperationalError("caiu")):
        with pytest.raises(OperationalError):
            marcar(
                barbearia_id=pronto["barbearia"], barbeiro_id=str(pronto["barbeiro"].id),
                servico_id=str(pronto["servico"].id), inicio=_inicio(10 * 60),
                nome="Maria", whatsapp="83933330003", agora=datetime.now(fuso.utc),
            )


def test_deadlock_na_rota_publica_responde_409_com_a_frase_do_horario(pronto):
    from django.test import Client
    corpo = {
        "barbeiroId": str(pronto["barbeiro"].id), "servicoId": str(pronto["servico"].id),
        "inicio": _inicio(10 * 60).isoformat(), "nome": "Maria Teste", "whatsapp": "83933330003",
    }
    with patch("app.services.agendamentos._gerar_codigo", side_effect=_deadlock()):
        r = Client().post(
            "/api/agendamentos", corpo, content_type="application/json",
            headers={"host": "brutus.localhost", **CABECALHO},
        )
    assert r.status_code == 409
    assert r.json() == {"erro": "Esse horário não está mais disponível."}
