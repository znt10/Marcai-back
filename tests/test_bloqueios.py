import uuid
from datetime import datetime, timezone

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0)
    return host


def test_post_bloqueio_semanal(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.post(
        "/api/painel/bloqueios",
        {
            "motivo": "ALMOCO", "repeteSemanalmente": True,
            "diaSemana": 2, "minutosInicio": 720, "minutosFim": 780,
        },
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 201

    from tenant.models import Bloqueio

    bloqueio = Bloqueio.objects.using("owner").get(id=r.json()["id"])
    assert bloqueio.dia_semana == 2 and bloqueio.motivo == "ALMOCO"


def test_post_bloqueio_pontual(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    inicio = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc).isoformat()
    fim = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc).isoformat()

    r = client.post(
        "/api/painel/bloqueios",
        {"motivo": "PESSOAL", "repeteSemanalmente": False, "inicio": inicio, "fim": fim},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 201


def test_post_com_os_dois_formatos_juntos_e_422(client, cenario):
    """O motor le um formato OU o outro — os dois juntos gravariam uma linha
    de interpretacao ambigua."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    inicio = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc).isoformat()
    fim = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc).isoformat()

    r = client.post(
        "/api/painel/bloqueios",
        {
            "motivo": "OUTRO", "repeteSemanalmente": False,
            "diaSemana": 2, "inicio": inicio, "fim": fim,
        },
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422
    assert "Escolhe" in r.json()["erro"]


def test_post_pontual_com_fim_antes_do_inicio_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    inicio = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc).isoformat()
    fim = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc).isoformat()

    r = client.post(
        "/api/painel/bloqueios",
        {"motivo": "OUTRO", "repeteSemanalmente": False, "inicio": inicio, "fim": fim},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 422


def test_delete_apaga(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    from tenant.models import Bloqueio

    bloqueio = Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id,
        motivo="ALMOCO", repete_semanalmente=True, dia_semana=1,
        minutos_inicio=720, minutos_fim=780,
    )

    r = client.delete(
        f"/api/painel/bloqueios/{bloqueio.id}", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200
    assert not Bloqueio.objects.using("owner").filter(id=bloqueio.id).exists()


def test_delete_do_bloqueio_do_colega_e_404(client, cenario):
    """Reconferencia DEPOIS de carregar: forjar o id do bloqueio de um colega
    devolve 404, nao 403 — 403 confirmaria que o registro existe."""
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)

    from tenant.models import Bloqueio

    bloqueio_do_colega = Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=colega.id,
        motivo="ALMOCO", repete_semanalmente=True, dia_semana=1,
        minutos_inicio=720, minutos_fim=780,
    )

    r = client.delete(
        f"/api/painel/bloqueios/{bloqueio_do_colega.id}", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 404
    assert Bloqueio.objects.using("owner").filter(id=bloqueio_do_colega.id).exists()


def test_dono_apaga_bloqueio_de_qualquer_um(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, dono, b.id)

    from tenant.models import Bloqueio

    bloqueio = Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=colega.id,
        motivo="ALMOCO", repete_semanalmente=True, dia_semana=1,
        minutos_inicio=720, minutos_fim=780,
    )

    r = client.delete(f"/api/painel/bloqueios/{bloqueio.id}", headers={"host": host, **CABECALHO})
    assert r.status_code == 200


def test_delete_id_inexistente_e_404(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    r = client.delete("/api/painel/bloqueios/nao-existe", headers={"host": host, **CABECALHO})
    assert r.status_code == 404


# ------------------------- bloqueio por cima de horario ja vendido
#
# Ate aqui bloquear era mudo: o horario continuava marcado, o cliente
# continuava esperando, e o barbeiro tinha que achar cada um na lista de
# conflitos e cancelar na mao. Agora o bloqueio ou avisa o que vai derrubar,
# ou derruba — nunca finge que nao ha ninguem ali.

from datetime import timedelta  # noqa: E402
from unittest.mock import patch  # noqa: E402


def _com_agendamento(barbearia_id, barbeiro, inicio, duracao_min=30, cliente_nome="José Neto"):
    from tenant.models import Agendamento, Cliente, Servico

    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=cliente_nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}",
    )
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=f"Corte {uuid.uuid4().hex[:4]}",
        duracao_minima_min=15, duracao_sugerida_min=duracao_min,
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=duracao_min),
        duracao_min=duracao_min, status="CONFIRMADO",
    )


def _bloqueio_de_uma_vez(inicio, fim):
    return {
        "motivo": "PESSOAL", "repeteSemanalmente": False,
        "inicio": inicio.isoformat(), "fim": fim.isoformat(),
    }


def test_bloquear_por_cima_de_agendamento_recusa_e_lista_quem_cai(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    inicio = datetime.now(timezone.utc) + timedelta(days=1)
    a = _com_agendamento(b.id, barbeiro, inicio)

    r = client.post(
        "/api/painel/bloqueios",
        _bloqueio_de_uma_vez(inicio - timedelta(minutes=30), inicio + timedelta(hours=1)),
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    corpo = r.json()
    assert [c["clienteNome"] for c in corpo["conflitos"]] == ["José Neto"]

    from tenant.models import Agendamento, Bloqueio

    assert Bloqueio.objects.using("owner").count() == 0, "recusou, entao nao pode ter criado"
    assert Agendamento.objects.using("owner").get(id=a.id).status == "CONFIRMADO"


def test_bloquear_confirmando_cancela_e_avisa_o_cliente(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    inicio = datetime.now(timezone.utc) + timedelta(days=1)
    a = _com_agendamento(b.id, barbeiro, inicio)

    corpo = _bloqueio_de_uma_vez(inicio - timedelta(minutes=30), inicio + timedelta(hours=1))
    corpo["cancelarConflitos"] = True
    with patch("app.api.v1.views.bloqueios.enviar_texto") as mock_envia:
        r = client.post(
            "/api/painel/bloqueios", corpo,
            content_type="application/json", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 201
    assert r.json()["cancelados"] == 1

    from tenant.models import Agendamento, Bloqueio

    assert Bloqueio.objects.using("owner").count() == 1
    assert Agendamento.objects.using("owner").get(id=a.id).status == "CANCELADO_BARBEIRO"
    mock_envia.assert_called_once()
    assert "cancelar" in mock_envia.call_args.args[1].lower()


def test_bloqueio_sem_ninguem_dentro_continua_passando_direto(client, cenario):
    """O caminho comum nao pode ganhar uma pergunta que nao precisa."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    inicio = datetime.now(timezone.utc) + timedelta(days=1)
    _com_agendamento(b.id, barbeiro, inicio)

    r = client.post(
        "/api/painel/bloqueios",
        _bloqueio_de_uma_vez(inicio + timedelta(hours=5), inicio + timedelta(hours=6)),
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 201


def test_bloqueio_nao_derruba_horario_que_ja_passou(client, cenario):
    """Cancelar o passado nao muda nada e mandaria WhatsApp para quem ja foi
    atendido."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    passado = datetime.now(timezone.utc) - timedelta(days=2)
    _com_agendamento(b.id, barbeiro, passado)

    r = client.post(
        "/api/painel/bloqueios",
        _bloqueio_de_uma_vez(passado - timedelta(hours=1), passado + timedelta(hours=1)),
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 201


# --------------------------- nao empilhar folga em cima de folga
#
# A tela mostrava "toda semana · seg, ter, ter, qua, qua, qua": o mesmo almoco
# gravado varias vezes no mesmo dia. Nada impedia, e o efeito na agenda e' o
# mesmo de UM bloqueio — sao linhas mortas que so' sujam a lista.


def _almoco(dia_semana, de=720, ate=780, motivo="ALMOCO"):
    return {
        "motivo": motivo, "repeteSemanalmente": True,
        "diaSemana": dia_semana, "minutosInicio": de, "minutosFim": ate,
    }


def test_nao_deixa_repetir_a_mesma_folga_no_mesmo_dia(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    cabecalho = {"host": host, **CABECALHO}

    primeira = client.post("/api/painel/bloqueios", _almoco(1),
                           content_type="application/json", headers=cabecalho)
    assert primeira.status_code == 201

    repetida = client.post("/api/painel/bloqueios", _almoco(1),
                           content_type="application/json", headers=cabecalho)
    assert repetida.status_code == 422

    from tenant.models import Bloqueio

    assert Bloqueio.objects.using("owner").count() == 1


def test_nao_deixa_encostar_folga_por_cima_de_outra_no_mesmo_dia(client, cenario):
    """12:00-13:00 e 12:30-13:30 na segunda nao sao duas pausas, sao uma
    bagunca — o motor le as duas e o efeito e' 12:00-13:30."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    cabecalho = {"host": host, **CABECALHO}

    client.post("/api/painel/bloqueios", _almoco(1, 720, 780),
                content_type="application/json", headers=cabecalho)
    r = client.post("/api/painel/bloqueios", _almoco(1, 750, 810, motivo="PESSOAL"),
                    content_type="application/json", headers=cabecalho)
    assert r.status_code == 422


def test_mesma_hora_em_dia_diferente_continua_valendo(client, cenario):
    """E' o caso NORMAL: almoco de segunda a sabado, mesma hora."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    cabecalho = {"host": host, **CABECALHO}

    for dia in (1, 2, 3):
        r = client.post("/api/painel/bloqueios", _almoco(dia),
                        content_type="application/json", headers=cabecalho)
        assert r.status_code == 201, f"dia {dia} deveria passar"


def test_duas_pausas_separadas_no_mesmo_dia_continuam_valendo(client, cenario):
    """Almoco ao meio-dia e um compromisso as 16h nao se encostam."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    cabecalho = {"host": host, **CABECALHO}

    client.post("/api/painel/bloqueios", _almoco(1, 720, 780),
                content_type="application/json", headers=cabecalho)
    r = client.post("/api/painel/bloqueios", _almoco(1, 960, 1020, motivo="PESSOAL"),
                    content_type="application/json", headers=cabecalho)
    assert r.status_code == 201


def test_a_folga_de_um_barbeiro_nao_bloqueia_a_do_colega(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    colega = _barbeiro(b.id, "Rael")
    host = _logar(client, dono, b.id)
    cabecalho = {"host": host, **CABECALHO}

    client.post("/api/painel/bloqueios", _almoco(1),
                content_type="application/json", headers=cabecalho)
    r = client.post("/api/painel/bloqueios", {**_almoco(1), "barbeiroId": colega.id},
                    content_type="application/json", headers=cabecalho)
    assert r.status_code == 201


# ------------------------- folga de "uma vez" que ja passou some da lista
#
# A semanal se repete e fica para sempre; a pontual e' um evento — depois que
# passa, ela nao diz mais nada sobre a agenda de ninguem e so' empurra as que
# importam para baixo na tela.


def test_folga_de_uma_vez_que_ja_passou_nao_aparece(client, cenario):
    from tenant.models import Bloqueio

    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    agora = datetime.now(timezone.utc)

    Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id, motivo="PESSOAL",
        repete_semanalmente=False,
        inicio=agora - timedelta(days=3), fim=agora - timedelta(days=3, hours=-1),
    )
    futura = Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id, motivo="PESSOAL",
        repete_semanalmente=False,
        inicio=agora + timedelta(days=1), fim=agora + timedelta(days=1, hours=1),
    )

    r = client.get("/api/painel/expediente", headers={"host": host, **CABECALHO})
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["bloqueios"]]
    assert str(futura.id) in ids
    assert len(ids) == 1, "a folga de tres dias atras nao tem mais o que dizer"


def test_folga_de_uma_vez_ainda_correndo_continua_na_tela(client, cenario):
    """No meio dela, ela e' o motivo de a agenda estar fechada agora."""
    from tenant.models import Bloqueio

    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    agora = datetime.now(timezone.utc)

    Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id, motivo="PESSOAL",
        repete_semanalmente=False,
        inicio=agora - timedelta(minutes=30), fim=agora + timedelta(minutes=30),
    )
    r = client.get("/api/painel/expediente", headers={"host": host, **CABECALHO})
    assert len(r.json()["bloqueios"]) == 1


def test_folga_semanal_nunca_some(client, cenario):
    from tenant.models import Bloqueio

    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    Bloqueio.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id, motivo="ALMOCO",
        repete_semanalmente=True, dia_semana=1, minutos_inicio=720, minutos_fim=780,
    )
    r = client.get("/api/painel/expediente", headers={"host": host, **CABECALHO})
    assert len(r.json()["bloqueios"]) == 1
