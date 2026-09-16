import uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from tenant.datas import dia_semana_de, utc_para_local


def _dia_semana(momento):
    """O dia da semana que o MOTOR vai procurar para este instante.

    Pelas funcoes do proprio motor, e nao por `momento.date()`, porque as
    duas coisas nao sao a mesma: `marcar()` faz `utc_para_local(inicio)`
    antes de olhar o expediente, entao quem manda e' o calendario de SAO
    PAULO, nao o de UTC. Entre 00:00 e 03:00 UTC os dois calendarios estao
    em dias diferentes — e era exatamente ali que estes testes caiam,
    cadastrando jornada numa quinta que o motor procurava na quarta.

    Derivar daqui garante que teste e motor nao possam divergir de novo:
    se a regra de fuso mudar, muda para os dois no mesmo commit.
    """
    dia, _ = utc_para_local(momento)
    return dia_semana_de(dia)


pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


@contextmanager
def _envios():
    """Os DOIS caminhos de envio de uma vez, normalizados em pares
    `(numero, texto)`.

    Um mock so' deixou de contar a historia quando cliente e equipe passaram a
    sair por numeros diferentes: `enviar_ao_cliente` recebe a barbearia na
    frente e `enviar_a_equipe` nao, entao `c.args[0]` quer dizer coisas
    diferentes nos dois. Estes casos sempre leram envio como "para quem, o
    que" — o ajudante preserva essa leitura.

    O que ele NAO prova, e nao deve provar: que a mensagem saiu de verdade.
    Com o envio simulado, `enviar_ao_cliente` e' chamado ate numa barbearia
    sem zap. Quem cobre isso e' `test_envio_por_plano.py`, que exercita a
    funcao de verdade.
    """
    with patch("app.api.v1.views.agendamentos.enviar_ao_cliente") as ao_cliente, patch(
        "app.api.v1.views.agendamentos.enviar_a_equipe"
    ) as a_equipe:

        class Envios:
            @property
            def pares(self):
                return [(c.args[1], c.args[2]) for c in ao_cliente.call_args_list] + [
                    (c.args[0], c.args[1]) for c in a_equipe.call_args_list
                ]

            @property
            def destinos(self):
                return [numero for numero, _ in self.pares]

            @property
            def call_count(self):
                return ao_cliente.call_count + a_equipe.call_count

            def texto_para(self, numero):
                return next(texto for n, texto in self.pares if n == numero)

            def assert_not_called(self):
                assert self.call_count == 0, self.pares

        yield Envios()


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
    _expediente_aberto_24h(barbeiro.barbearia_id, barbeiro, _dia_semana(base))
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
    # Sem EVOLUTION_API_URL, `numero_existe` devolve 'indeterminado' — deixa
    # passar, e' o comportamento correto pra' testes que nao sao SOBRE o
    # oraculo (§10.5: indisponibilidade nao e' resposta).
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


# ------------------------------------------------------------- POST (marcar)


def test_marca_sem_sessao_e_manda_confirmacao(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with _envios() as mock_envia:
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
    confirmacao = mock_envia.texto_para("11977778888")
    assert confirmacao.startswith("Fechou,")

    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    assert criado.status == "CONFIRMADO"


def test_marcar_com_preco_definido_grava_o_snapshot(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro, preco_centavos=4500)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with _envios():
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

    with _envios():
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
        "app.api.v1.views.agendamentos.numero_existe", lambda barbearia, whatsapp, ip: "nao_existe"
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


def test_numero_indeterminado_deixa_passar(client, cenario, monkeypatch):
    """§10.5: indisponibilidade do oraculo NAO e' resposta — so' 'nao_existe'
    de verdade bloqueia."""
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    monkeypatch.setattr(
        "app.api.v1.views.agendamentos.numero_existe", lambda barbearia, whatsapp, ip: "indeterminado"
    )

    with _envios():
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Cliente Novo", "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201


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

    with _envios() as mock_envia:
        r = client.post(
            f"/api/agendamentos/{a.codigo}/cancelar", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # Idem: o cliente e o barbeiro. Aqui interessa o aviso do CLIENTE.
    assert mock_envia.call_count == 2
    do_cliente = next(
        texto for numero, texto in mock_envia.pares if numero != barbeiro.whatsapp
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

    with _envios() as mock_envia:
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

    with _envios() as mock_envia:
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

    destinos = mock_envia.destinos
    assert "11977778888" in destinos, "o cliente continua recebendo a confirmacao"
    assert barbeiro.whatsapp in destinos, "o barbeiro precisa saber que entrou horario"

    aviso = mock_envia.texto_para(barbeiro.whatsapp)
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

    with _envios() as mock_envia:
        r = client.post(
            f"/api/agendamentos/{a.codigo}/cancelar",
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200

    destinos = mock_envia.destinos
    assert barbeiro.whatsapp in destinos, "a vaga abriu e o barbeiro nao ficou sabendo"
    aviso = mock_envia.texto_para(barbeiro.whatsapp)
    assert aviso.startswith("Cancelou")
