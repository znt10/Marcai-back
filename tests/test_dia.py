import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

DIA = "2026-08-20"  # quinta-feira


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO", ordem=0, ativo=True):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=ativo, ordem=ordem,
    )


def _coluna_de(corpo, barbeiro_id):
    """A fixture `cenario` ja cria um barbeiro padrao por barbearia, entao
    `colunas[0]` nem sempre e' o barbeiro que o teste configurou — os testes
    buscam a coluna certa por id em vez de assumir posicao."""
    return next(c for c in corpo["colunas"] if c["barbeiroId"] == barbeiro_id)


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0)
    return host


def _expediente(barbearia_id, barbeiro, minutos_inicio=540, minutos_fim=1080):
    from tenant.models import HorarioTrabalho

    # 2026-08-20 e' quinta (dia_semana 4, dom=0).
    return HorarioTrabalho.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, barbeiro_id=barbeiro.id,
        dia_semana=4, minutos_inicio=minutos_inicio, minutos_fim=minutos_fim,
    )


def _servico_vinculado(barbearia_id, barbeiro, duracao_min=30, nome="Corte"):
    from tenant.models import BarbeiroServico, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"{nome} {uuid.uuid4().hex[:6]}",
        duracao_minima_min=15, duracao_sugerida_min=duracao_min,
    )
    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id, servico_id=servico.id, barbearia_id=barbearia_id,
        duracao_min=duracao_min, ativo=True,
    )
    return servico


def test_coluna_sem_servico_marcado_mostra_null(client, cenario):
    """Nulo em `servicoMaisCurto` e' o mesmo aviso que a tela de equipe
    denuncia — esse barbeiro nao aparece pra cliente nenhum."""
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)
    _expediente(b.id, dono)

    r = client.get("/api/painel/dia", {"dia": DIA}, headers={"host": host})
    assert r.status_code == 200
    coluna = _coluna_de(r.json(), dono.id)
    assert coluna["servicoMaisCurto"] is None
    assert coluna["proximoLivre"] is None


def test_proximo_livre_usa_o_servico_mais_curto(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)
    _expediente(b.id, dono, minutos_inicio=540, minutos_fim=1080)
    _servico_vinculado(b.id, dono, duracao_min=40, nome="Corte")
    _servico_vinculado(b.id, dono, duracao_min=15, nome="Pezinho")

    r = client.get("/api/painel/dia", {"dia": DIA}, headers={"host": host})
    coluna = _coluna_de(r.json(), dono.id)
    assert coluna["servicoMaisCurto"].startswith("Pezinho")
    assert coluna["proximoLivre"] is not None


def test_itens_misturam_agendamento_e_bloqueio_ordenados(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)
    _expediente(b.id, dono)

    from tenant.models import Agendamento, Bloqueio, Cliente

    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Cliente", whatsapp="11988889999",
    )
    Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=dono.id,
        motivo="ALMOCO", repete_semanalmente=True, dia_semana=4,
        minutos_inicio=720, minutos_fim=780,
    )
    servico = _servico_vinculado(b.id, dono)
    inicio = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=dono.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )

    r = client.get("/api/painel/dia", {"dia": DIA}, headers={"host": host})
    itens = _coluna_de(r.json(), dono.id)["itens"]
    tipos = [i["tipo"] for i in itens]
    assert "AGENDAMENTO" in tipos and "BLOQUEIO" in tipos
    # ordenados por inicio: o agendamento (10h locais) vem antes do almoco (12h).
    assert tipos.index("AGENDAMENTO") < tipos.index("BLOQUEIO")


def test_barbeiro_inativo_sem_agenda_no_dia_nao_aparece(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)
    _barbeiro(b.id, "Saiu", ativo=False)

    r = client.get("/api/painel/dia", {"dia": DIA}, headers={"host": host})
    nomes = [c["barbeiroNome"] for c in r.json()["colunas"]]
    assert "Saiu" not in nomes


def test_barbeiro_so_ve_a_propria_coluna(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)

    r = client.get(
        "/api/painel/dia", {"dia": DIA, "barbeiroId": colega.id}, headers={"host": host},
    )
    colunas = r.json()["colunas"]
    assert len(colunas) == 1
    assert colunas[0]["barbeiroNome"] == "Eu"
