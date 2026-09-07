import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "brutus.localhost"


def _barbeiro(barbearia_id, nome="Zeca"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel="BARBEIRO", ativo=True,
    )


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


def _proximo_slot_livre(barbeiro, servico, daqui_a_min=30):
    """Um horario livre daqui a pouco, na grade de 30 em 30 minutos, com
    jornada aberta o dia inteiro."""
    agora = datetime.now(timezone.utc)
    passo = 30
    minuto = ((agora.minute + daqui_a_min) // passo + 1) * passo
    base = agora.replace(second=0, microsecond=0, minute=0) + timedelta(minutes=minuto)
    _expediente_aberto_24h(barbeiro.barbearia_id, barbeiro, (base.date().isoweekday() % 7))
    return base


def _agendamento(
    barbearia_id, barbeiro, inicio, duracao_min=30, status="CONFIRMADO", codigo=None,
    preco_centavos=None,
):
    from tenant.models import Agendamento, Cliente, Servico

    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Cliente",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}",
    )
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome="Corte",
        duracao_minima_min=15, duracao_sugerida_min=duracao_min,
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id,
        codigo=codigo or str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=duracao_min),
        duracao_min=duracao_min, preco_centavos=preco_centavos, status=status,
    )


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    # O oraculo passa a ser OBRIGATORIO: 'indeterminado' bloqueia, nao deixa
    # mais passar. Entao apagar EVOLUTION_API_URL (que era o que esta fixture
    # fazia) deixaria de ser "nao testar o oraculo" e viraria "reprovar todo
    # agendamento" — cada teste desta suite falharia por um motivo que nao e'
    # o dele. Fingir 'existe' e' o equivalente novo da intencao antiga.
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    monkeypatch.setattr(
        "app.api.v1.views.agendamentos.numero_existe", lambda whatsapp, ip: "existe"
    )


# ------------------------------------------------------------- POST (marcar)


def test_marca_sem_sessao_e_manda_confirmacao(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with patch("app.api.v1.views.agendamentos.enviar_texto") as mock_envia:
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
    assert "codigo" in r.json()
    # Dois envios desde que o barbeiro passou a ser avisado
    # (`test_marcar_avisa_o_barbeiro_alem_do_cliente`). O que ESTE teste
    # garante e' que o do cliente continua saindo.
    assert mock_envia.call_count == 2
    confirmacao = next(c.args[1] for c in mock_envia.call_args_list if c.args[0] == "11977778888")
    assert confirmacao.startswith("Fechou,")

    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    assert criado.status == "CONFIRMADO"


def test_marcar_com_preco_definido_grava_o_snapshot(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro, preco_centavos=4500)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with patch("app.api.v1.views.agendamentos.enviar_texto"):
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

    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    assert criado.preco_centavos == 4500


def test_marcar_sem_preco_definido_continua_funcionando(client, cenario):
    """A barbearia funciona sem preco nenhum ha muito tempo — esta fatia nao
    pode passar a bloquear quem ainda nao precificou."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)  # preco_centavos=None
    inicio = _proximo_slot_livre(barbeiro, servico)

    with patch("app.api.v1.views.agendamentos.enviar_texto"):
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

    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    assert criado.preco_centavos is None


def test_numero_sem_whatsapp_e_recusado_antes_da_transacao(client, cenario, monkeypatch):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    monkeypatch.setattr(
        "app.api.v1.views.agendamentos.numero_existe", lambda whatsapp, ip: "nao_existe"
    )

    r = client.post(
        "/api/agendamentos",
        {
            "barbeiroId": barbeiro.id, "servicoId": servico.id,
            "inicio": inicio.isoformat(), "nome": "Cliente Novo", "whatsapp": "11977778888",
        },
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422
    assert "WhatsApp" in r.json()["erro"]

    from tenant.models import Agendamento

    assert not Agendamento.objects.using("owner").filter(barbeiro_id=barbeiro.id).exists()


def test_numero_indeterminado_BLOQUEIA_e_manda_chamar_no_zap(client, cenario, monkeypatch):
    """REVERTE o §10.5. A regra era "indisponibilidade nao e' resposta", e o
    oraculo so' bloqueava com um 'nao_existe' de verdade; agendamento com
    numero nao confirmado passava.

    O dono pediu o contrario, sabendo o preco: se a Evolution cair, ninguem
    marca sozinho. O que torna isso aceitavel e' a mensagem — ela manda a
    pessoa para o WhatsApp da barbearia, entao o cliente nao some, ele muda de
    canal. Recusar em silencio seria perder a venda.

    503 e nao 422: nao e' erro de quem digitou. O 422 diria "seu numero esta
    errado" para alguem cujo numero pode estar perfeito.
    """
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    monkeypatch.setattr(
        "app.api.v1.views.agendamentos.numero_existe", lambda whatsapp, ip: "indeterminado"
    )

    with patch("app.api.v1.views.agendamentos.enviar_texto"):
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Cliente Novo", "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 503
    # O numero da barbearia tem de estar no texto: sem ele a mensagem manda
    # "chama a gente" sem dizer onde.
    assert b.whatsapp_contato[-4:] in r.json()["erro"].replace(" ", "").replace("-", "")


def test_fixo_e_recusado_sem_nem_consultar_o_oraculo(client, cenario, monkeypatch):
    """O ganho de validar antes: fixo nao tem WhatsApp, e reconhecer isso nao
    custa chamada de rede, nao depende da Evolution estar de pe e nao gasta
    consulta do limite por IP.

    O controle negativo esta em `tests/test_celular.py`: `normalizar` ACEITA
    este mesmo numero. Sem ele, este teste nao distinguiria a regra nova da
    validacao que ja existia.
    """
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    consultas = []
    monkeypatch.setattr(
        "app.api.v1.views.agendamentos.numero_existe",
        lambda whatsapp, ip: consultas.append(whatsapp) or "existe",
    )

    r = client.post(
        "/api/agendamentos",
        {
            "barbeiroId": barbeiro.id, "servicoId": servico.id,
            "inicio": inicio.isoformat(), "nome": "Cliente Novo",
            "whatsapp": "1132217869",
        },
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )

    assert r.status_code == 422
    assert consultas == [], "o oraculo foi consultado para um fixo"


def test_ddd_que_nao_existe_e_recusado(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    r = client.post(
        "/api/agendamentos",
        {
            "barbeiroId": barbeiro.id, "servicoId": servico.id,
            "inicio": inicio.isoformat(), "nome": "Cliente Novo",
            "whatsapp": "20982217869",
        },
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_marcar_no_passado_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    passado = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    r = client.post(
        "/api/agendamentos",
        {
            "barbeiroId": barbeiro.id, "servicoId": servico.id, "inicio": passado,
            "nome": "Cliente", "whatsapp": "11977778888",
        },
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_servico_nao_vinculado_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)

    from tenant.models import Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Sem vinculo",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    inicio = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    r = client.post(
        "/api/agendamentos",
        {
            "barbeiroId": barbeiro.id, "servicoId": servico.id, "inicio": inicio,
            "nome": "Cliente", "whatsapp": "11977778888",
        },
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_corpo_sem_nome_ou_whatsapp_e_422(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)

    r = client.post(
        "/api/agendamentos",
        {"barbeiroId": barbeiro.id, "servicoId": servico.id, "inicio": "2026-08-20T10:00:00Z"},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_fora_do_host_da_barbearia_e_404(client, cenario):
    r = client.post(
        "/api/agendamentos", {}, content_type="application/json",
        headers={"host": "admin.localhost", **CABECALHO},
    )
    assert r.status_code == 404


# ----------------------------------------------------------------- GET detalhe


def test_detalhe_dentro_do_prazo_pode_cancelar(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=3)
    a = _agendamento(b.id, barbeiro, inicio)

    r = client.get(f"/api/agendamentos/{a.codigo}", headers={"host": HOST})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["codigo"] == a.codigo
    assert corpo["status"] == "CONFIRMADO"
    assert corpo["podeCancelar"] is True
    # O nome do cliente sai; o WhatsApp dele, nunca (§9.1).
    assert "clienteWhatsapp" not in corpo
    assert "whatsapp" not in corpo


def test_detalhe_devolve_o_preco_snapshotado(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=3)
    a = _agendamento(b.id, barbeiro, inicio, preco_centavos=4500)

    r = client.get(f"/api/agendamentos/{a.codigo}", headers={"host": HOST})
    assert r.status_code == 200
    assert r.json()["precoCentavos"] == 4500


def test_detalhe_sem_preco_snapshotado_devolve_nulo(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=3)
    a = _agendamento(b.id, barbeiro, inicio)  # preco_centavos=None

    r = client.get(f"/api/agendamentos/{a.codigo}", headers={"host": HOST})
    assert r.status_code == 200
    assert r.json()["precoCentavos"] is None


def test_detalhe_dentro_do_prazo_de_cancelamento_nao_pode_cancelar(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(minutes=30)  # < PRAZO_CANCELAMENTO_MIN
    a = _agendamento(b.id, barbeiro, inicio)

    r = client.get(f"/api/agendamentos/{a.codigo}", headers={"host": HOST})
    assert r.status_code == 200
    assert r.json()["podeCancelar"] is False


def test_detalhe_nao_confirmado_nao_pode_cancelar(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=3)
    a = _agendamento(b.id, barbeiro, inicio, status="CANCELADO_CLIENTE")

    r = client.get(f"/api/agendamentos/{a.codigo}", headers={"host": HOST})
    assert r.status_code == 200
    assert r.json()["podeCancelar"] is False


def test_detalhe_codigo_inexistente_e_404(client, cenario):
    r = client.get("/api/agendamentos/naoexisteai", headers={"host": HOST})
    assert r.status_code == 404


def test_detalhe_codigo_de_outra_barbearia_e_404(client, cenario):
    """O RLS garante isso — nao um filtro explicito na query."""
    b = cenario["brutus"]
    outra = cenario["dontony"]
    barbeiro = _barbeiro(outra.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=3)
    a = _agendamento(outra.id, barbeiro, inicio)

    r = client.get(f"/api/agendamentos/{a.codigo}", headers={"host": "brutus.localhost"})
    assert r.status_code == 404
    assert b.id != outra.id


# --------------------------------------------------------------------- cancelar


def test_cancelar_dentro_do_prazo_ok_e_avisa(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=3)
    a = _agendamento(b.id, barbeiro, inicio)

    with patch("app.api.v1.views.agendamentos.enviar_texto") as mock_envia:
        r = client.post(
            f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # Idem: o cliente e o barbeiro. Aqui interessa o aviso do CLIENTE.
    assert mock_envia.call_count == 2
    do_cliente = next(
        c.args[1] for c in mock_envia.call_args_list if c.args[0] != barbeiro.whatsapp
    )
    assert "cancel" in do_cliente.lower()

    from tenant.models import Agendamento

    atualizado = Agendamento.objects.using("owner").get(id=a.id)
    assert atualizado.status == "CANCELADO_CLIENTE"
    assert atualizado.cancelado_em is not None


def test_cancelar_fora_do_prazo_da_422_com_o_zap_da_barbearia(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(minutes=30)
    a = _agendamento(b.id, barbeiro, inicio)

    r = client.post(f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO})
    assert r.status_code == 422
    assert "Passou do prazo de 1h" in r.json()["erro"]

    from tenant.models import Agendamento

    assert Agendamento.objects.using("owner").get(id=a.id).status == "CONFIRMADO"


def test_cancelar_ja_cancelado_e_idempotente(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    inicio = datetime.now(timezone.utc) + timedelta(hours=3)
    a = _agendamento(b.id, barbeiro, inicio, status="CANCELADO_CLIENTE")

    with patch("app.api.v1.views.agendamentos.enviar_texto") as mock_envia:
        r = client.post(
            f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # Ja' estava cancelado — reenviar o aviso seria mandar de novo pro
    # cliente que ja' recebeu.
    mock_envia.assert_not_called()


def test_cancelar_codigo_inexistente_e_404(client, cenario):
    r = client.post(
        "/api/agendamentos/naoexisteai/cancelar", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 404


# ------------------------------------------------- o barbeiro tambem e' avisado
#
# Ate aqui o WhatsApp so falava com o CLIENTE. Alguem marcava as 22h de domingo
# e o barbeiro so descobria abrindo o painel na segunda.


def test_marcar_avisa_o_barbeiro_alem_do_cliente(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with patch("app.api.v1.views.agendamentos.enviar_texto") as mock_envia:
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "José Neto",
                "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201

    destinos = [c.args[0] for c in mock_envia.call_args_list]
    assert "11977778888" in destinos, "o cliente continua recebendo a confirmacao"
    assert barbeiro.whatsapp in destinos, "o barbeiro precisa saber que entrou horario"

    aviso = next(c.args[1] for c in mock_envia.call_args_list if c.args[0] == barbeiro.whatsapp)
    assert aviso.startswith("Novo horário")
    assert "José Neto" in aviso
    # Endereco e' coisa do cliente: o barbeiro trabalha la.
    assert b.endereco not in aviso


def test_cliente_cancelando_avisa_o_barbeiro(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico, daqui_a_min=180)
    a = _agendamento(b.id, barbeiro, inicio)  # noqa: F841 — o codigo dele e' o alvo

    with patch("app.api.v1.views.agendamentos.enviar_texto") as mock_envia:
        r = client.post(
            f"/api/agendamentos/{a.codigo}/cancelar",
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200

    destinos = [c.args[0] for c in mock_envia.call_args_list]
    assert barbeiro.whatsapp in destinos, "a vaga abriu e o barbeiro nao ficou sabendo"
    aviso = next(c.args[1] for c in mock_envia.call_args_list if c.args[0] == barbeiro.whatsapp)
    assert aviso.startswith("Cancelou")
