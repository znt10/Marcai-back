import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import conta_sessao
from app.services.lista_do_dia import SEM_LISTA
from tenant.config import CONTA_SESSAO_COOKIE
from tenant.models import Agendamento, Barbearia, Cliente, ContaCliente
from test_agendamentos import (
    CABECALHO, HOST, _barbeiro, _envios, _proximo_slot_livre,
    _servico_vinculado,
)

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

NUMERO = "83982217869"
HOST_DONTONY = "dontony.localhost"


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setenv("SESSAO_JWT_SECRET", "segredo-so-de-teste")
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


@pytest.fixture(autouse=True)
def lista_refeita():
    with patch("app.services.lista_do_dia.avisar_mudanca", return_value=SEM_LISTA) as avisar:
        yield avisar


def _logar(client, whatsapp=NUMERO):
    conta = ContaCliente.objects.using("owner").create(
        nome="Ana", whatsapp=whatsapp, senha_hash="x", confirmada_em=datetime.now(timezone.utc),
    )
    client.cookies[CONTA_SESSAO_COOKIE] = conta_sessao.emitir(conta.id, conta.token_version)
    return conta


def _marcar_como(barbearia, whatsapp, inicio, status="CONFIRMADO", codigo=None):
    """Um agendamento de um cliente com exatamente este numero gravado.
    Barbeiro, servico e cliente sao reaproveitados por lugar (o servico tem
    nome unico por tenant)."""
    from tenant.models import Barbeiro, Servico

    bid = barbearia.id
    zeca = Barbeiro.objects.using("owner").filter(barbearia_id=bid).first()
    servico = Servico.objects.using("owner").filter(barbearia_id=bid, nome="Corte").first()
    if servico is None:
        servico = Servico.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=bid, nome="Corte",
            duracao_minima_min=15, duracao_sugerida_min=30,
        )
    cliente = Cliente.objects.using("owner").filter(barbearia_id=bid, whatsapp=whatsapp).first()
    if cliente is None:
        cliente = Cliente.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=bid, nome="Cliente", whatsapp=whatsapp,
        )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=bid, codigo=codigo or str(uuid.uuid4())[:10],
        barbeiro_id=zeca.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status=status,
    )


def _historico(client, host=HOST):
    return client.get("/api/conta/historico", headers={"host": host})


def _cancelar(client, codigo, barbearia_id, host=HOST):
    return client.post(
        f"/api/conta/agendamentos/{codigo}/cancelar", {"barbeariaId": str(barbearia_id)},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )


def _em(horas):
    return datetime.now(timezone.utc) + timedelta(hours=horas)


def test_historico_separa_por_lugar_e_atual_primeiro(client, cenario):
    _logar(client)
    # A brutus tem o agendamento mais recente: sem a regra da "atual primeiro",
    # ela abriria a lista.
    _marcar_como(cenario["dontony"], NUMERO, _em(5), codigo="don0000001")
    _marcar_como(cenario["brutus"], NUMERO, _em(30), codigo="bru0000001")

    r = _historico(client, HOST_DONTONY)
    assert r.status_code == 200
    lugares = r.json()["estabelecimentos"]
    assert [l["slug"] for l in lugares] == ["dontony", "brutus"]
    assert lugares[0]["barbeariaId"] == str(cenario["dontony"].id)
    assert lugares[0]["nome"] == "Dom Tony" and lugares[0]["tipo"]
    item = lugares[0]["agendamentos"][0]
    assert item["codigo"] == "don0000001" and item["status"] == "CONFIRMADO"
    assert item["servicoNome"] == "Corte" and item["podeCancelar"] is True
    assert item["inicio"].endswith("Z") and "." in item["inicio"]
    assert [a["codigo"] for a in lugares[1]["agendamentos"]] == ["bru0000001"]


def test_historico_ordena_os_outros_lugares_pelo_mais_recente(client, cenario):
    from tenant.models import Barbeiro

    terceira = Barbearia.objects.using("owner").create(
        id=str(uuid.uuid4()), slug="tercei", plano="SEM_ZAP", nome="Terceira",
        endereco="Rua 3", whatsapp_contato="11999998888", ativo=True,
        criado_em="2026-08-11T12:00:00Z",
    )
    Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=terceira.id, nome="B3", whatsapp="11911112222", ativo=True,
    )
    _logar(client)
    _marcar_como(cenario["brutus"], NUMERO, _em(1))
    _marcar_como(cenario["dontony"], NUMERO, _em(10))
    _marcar_como(terceira, NUMERO, _em(20))
    lugares = _historico(client, HOST_DONTONY).json()["estabelecimentos"]
    assert [l["slug"] for l in lugares] == ["dontony", "tercei", "brutus"]


def test_historico_vem_do_mais_novo_ao_mais_antigo(client, cenario):
    _logar(client)
    _marcar_como(cenario["brutus"], NUMERO, _em(5), codigo="perto00001")
    _marcar_como(cenario["brutus"], NUMERO, _em(50), codigo="longe00001")
    codigos = [a["codigo"] for a in _historico(client).json()["estabelecimentos"][0]["agendamentos"]]
    assert codigos == ["longe00001", "perto00001"]


def test_historico_limita_por_lugar_e_vem_do_mais_novo(client, cenario):
    from tenant.config import CONTA_HISTORICO_POR_LUGAR

    _logar(client)
    for i in range(CONTA_HISTORICO_POR_LUGAR + 1):
        _marcar_como(cenario["brutus"], NUMERO, _em(10 + i), codigo=f"cod{i:07d}")
    ag = _historico(client).json()["estabelecimentos"][0]["agendamentos"]
    assert len(ag) == CONTA_HISTORICO_POR_LUGAR
    assert ag[0]["codigo"] == f"cod{CONTA_HISTORICO_POR_LUGAR:07d}"
    assert "cod0000000" not in [a["codigo"] for a in ag]


def test_historico_acha_cliente_gravado_sem_o_nove(client, cenario):
    _logar(client)  # conta em 83982217869
    _marcar_como(cenario["brutus"], "8382217869", _em(5), codigo="sem9000001")
    lugares = _historico(client).json()["estabelecimentos"]
    assert [a["codigo"] for a in lugares[0]["agendamentos"]] == ["sem9000001"]


def test_historico_inclui_agendamento_de_antes_da_conta(client, cenario):
    antigo = _marcar_como(cenario["brutus"], NUMERO, _em(-72), codigo="antigo0001")
    Agendamento.objects.using("owner").filter(id=antigo.id).update(status="CONCLUIDO")
    _logar(client)  # a conta nasce DEPOIS do agendamento
    ag = _historico(client).json()["estabelecimentos"][0]["agendamentos"]
    assert [a["codigo"] for a in ag] == ["antigo0001"]
    assert ag[0]["podeCancelar"] is False


def test_historico_nao_mostra_agendamento_de_outro_numero(client, cenario):
    _logar(client)
    _marcar_como(cenario["brutus"], NUMERO, _em(5), codigo="meu0000001")
    _marcar_como(cenario["brutus"], "11977778888", _em(6), codigo="alheio0001")
    ag = _historico(client).json()["estabelecimentos"][0]["agendamentos"]
    assert [a["codigo"] for a in ag] == ["meu0000001"]


def test_historico_esconde_barbearia_inativa(client, cenario):
    _logar(client)
    _marcar_como(cenario["brutus"], NUMERO, _em(5))
    _marcar_como(cenario["dontony"], NUMERO, _em(6))
    Barbearia.objects.using("owner").filter(id=cenario["dontony"].id).update(ativo=False)
    lugares = _historico(client).json()["estabelecimentos"]
    assert [l["slug"] for l in lugares] == ["brutus"]


def test_historico_sem_sessao_401(client, cenario):
    r = _historico(client)
    assert r.status_code == 401
    assert r.json() == {"erro": "nao autorizado"}


# ------------------------------------------------------------ cancelar logado


def test_cancelar_logado_cancela_e_avisa_como_o_link(client, cenario, lista_refeita):
    _logar(client)
    a = _marcar_como(cenario["brutus"], NUMERO, _em(3))

    with _envios() as envios:
        r = _cancelar(client, a.codigo, cenario["brutus"].id)

    assert r.status_code == 200 and r.json() == {"ok": True}
    assert Agendamento.objects.using("owner").get(id=a.id).status == "CANCELADO_CLIENTE"
    assert envios.call_count == 1 and "cancel" in envios.pares[0][1].lower()
    assert envios.destinos == [NUMERO]
    lista_refeita.assert_called_once()
    assert lista_refeita.call_args.kwargs["cancelados"][0][0] == str(a.id)


def test_cancelar_logado_ja_cancelado_e_idempotente_e_nao_reavisa(client, cenario, lista_refeita):
    _logar(client)
    a = _marcar_como(cenario["brutus"], NUMERO, _em(3), status="CANCELADO_CLIENTE")
    with _envios() as envios:
        r = _cancelar(client, a.codigo, cenario["brutus"].id)
    assert r.status_code == 200
    envios.assert_not_called()
    lista_refeita.assert_not_called()


def test_cancelar_logado_em_outro_lugar_pelo_host_atual(client, cenario):
    _logar(client)
    a = _marcar_como(cenario["dontony"], NUMERO, _em(3))
    with _envios():
        r = _cancelar(client, a.codigo, cenario["dontony"].id, host=HOST)  # host da brutus
    assert r.status_code == 200
    assert Agendamento.objects.using("owner").get(id=a.id).status == "CANCELADO_CLIENTE"


def test_cancelar_agendamento_de_outro_numero_da_404(client, cenario):
    _logar(client)
    _marcar_como(cenario["brutus"], NUMERO, _em(30))  # a conta tem cadastro aqui
    alheio = _marcar_como(cenario["brutus"], "11977778888", _em(3))
    with _envios() as envios:
        r = _cancelar(client, alheio.codigo, cenario["brutus"].id)
    assert r.status_code == 404
    envios.assert_not_called()
    assert Agendamento.objects.using("owner").get(id=alheio.id).status == "CONFIRMADO"


def test_cancelar_em_barbearia_onde_a_conta_nao_tem_cadastro_da_404(client, cenario):
    _logar(client)
    _marcar_como(cenario["brutus"], NUMERO, _em(30))
    alheio = _marcar_como(cenario["dontony"], "11977778888", _em(3))
    r = _cancelar(client, alheio.codigo, cenario["dontony"].id)
    assert r.status_code == 404
    assert Agendamento.objects.using("owner").get(id=alheio.id).status == "CONFIRMADO"


def test_cancelar_com_codigo_de_outra_barbearia_da_404(client, cenario):
    _logar(client)
    _marcar_como(cenario["brutus"], NUMERO, _em(30))
    outro = _marcar_como(cenario["dontony"], NUMERO, _em(3))
    r = _cancelar(client, outro.codigo, cenario["brutus"].id)  # lugar errado
    assert r.status_code == 404


def test_cancelar_barbearia_inativa_da_404(client, cenario):
    _logar(client)
    a = _marcar_como(cenario["dontony"], NUMERO, _em(3))
    Barbearia.objects.using("owner").filter(id=cenario["dontony"].id).update(ativo=False)
    assert _cancelar(client, a.codigo, cenario["dontony"].id).status_code == 404


@pytest.mark.parametrize("corpo", [{}, {"barbeariaId": "nao-e-uuid"}, {"barbeariaId": 5}, {"barbeariaId": None}])
def test_cancelar_barbearia_id_ruim_da_404(client, cenario, corpo):
    _logar(client)
    a = _marcar_como(cenario["brutus"], NUMERO, _em(3))
    r = client.post(
        f"/api/conta/agendamentos/{a.codigo}/cancelar", corpo,
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 404


def test_cancelar_sem_sessao_401(client, cenario):
    a = _marcar_como(cenario["brutus"], NUMERO, _em(3))
    r = _cancelar(client, a.codigo, cenario["brutus"].id)
    assert r.status_code == 401
    assert Agendamento.objects.using("owner").get(id=a.id).status == "CONFIRMADO"


def test_cancelar_logado_fora_do_prazo_422(client, cenario):
    _logar(client)
    a = _marcar_como(cenario["brutus"], NUMERO, _em(0.5))
    with _envios() as envios:
        r = _cancelar(client, a.codigo, cenario["brutus"].id)
    assert r.status_code == 422
    assert "Passou do prazo de 1h" in r.json()["erro"] and "(11) 9 9999-8888" in r.json()["erro"]
    envios.assert_not_called()
    assert Agendamento.objects.using("owner").get(id=a.id).status == "CONFIRMADO"


def test_bloqueado_logado_continua_recusado_ao_agendar(client, cenario):
    from app.services.clientes_bloqueados import bloquear

    b = cenario["brutus"]
    zeca = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, zeca)
    inicio = _proximo_slot_livre(zeca, servico)
    anterior = _marcar_como(b, NUMERO, _em(40))
    bloquear(b.id, anterior.id, None, zeca.id, datetime.now(timezone.utc))
    _logar(client)

    antes = Agendamento.objects.using("owner").count()
    with _envios() as envios:
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": zeca.id, "servicoId": servico.id, "inicio": inicio.isoformat(),
                "nome": "Ana", "whatsapp": NUMERO,
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 422
    assert r.json()["erro"] == (
        "Não foi possível concluir o agendamento. Chama a barbearia: (11) 9 9999-8888"
    )
    assert Agendamento.objects.using("owner").count() == antes
    envios.assert_not_called()
