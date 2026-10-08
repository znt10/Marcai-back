"""Dois barbeiros na mesma barbearia: nenhuma mensagem vai para o numero errado.

Pedido do Jose em 07/10/2026, com o Marcai ja em uso: "o cliente do barbeiro
A nao pode receber coisa do barbeiro B, nem o B receber o aviso do A".

Os outros testes de mensagem simulam o envio na VIEW, com um barbeiro so'.
Aqui so' a Evolution e' de mentira: tudo o que sai para ela e' guardado como
`(numero, texto)`, e o caminho inteiro e' o de verdade — site, painel, lista
do dia das 07:00 e lembrete. Os dois horarios sao no MESMO instante, em
barbeiros diferentes, que e' onde uma troca de barbeiro passaria despercebida.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import lembrete, lista_do_dia
from app.services.sessao import COOKIE_SESSAO, emitir
from app.services.whatsapp import limpar_caches_numero
from tenant.datas import dia_de_hoje, dia_semana_de, local_para_utc, somar_dias

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}

ANA, BETO = "83911110001", "83922220002"          # os dois barbeiros
XAVIER, YARA = "83933330003", "83944440004"       # cliente da Ana, cliente do Beto
ZE_DA_OUTRA = "83955550005"                       # cliente da outra barbearia
TONY = "83966660006"                              # barbeiro da outra barbearia


class _Resposta:
    def __init__(self, status, corpo):
        self.status_code, self._corpo = status, corpo
        self.ok = 200 <= status < 300
        self.text = str(corpo)

    def json(self):
        return self._corpo


class EvolutionDeMentira:
    """Guarda cada mensagem que sairia, e diz que todo numero tem WhatsApp."""

    def __init__(self):
        self.enviadas: list[tuple[str, str]] = []

    def post(self, url, json=None, headers=None, timeout=None):
        if "/chat/whatsappNumbers/" in url:
            return _Resposta(200, [{"exists": True, "number": json["numbers"][0]}])
        if "/message/sendText/" in url:
            numero = json["number"].removeprefix("55")
            self.enviadas.append((numero, json["text"]))
            return _Resposta(201, {
                "key": {"id": f"MSG{len(self.enviadas)}", "remoteJid": f"55{numero}@s.whatsapp.net"},
                "status": "PENDING",
            })
        raise AssertionError(f"chamada inesperada a Evolution: {url}")

    def para(self, numero) -> list[str]:
        return [texto for n, texto in self.enviadas if n == numero]

    def esquecer(self):
        self.enviadas.clear()


@pytest.fixture
def evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution-de-mentira")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "central")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    limpar_caches_numero()
    falsa = EvolutionDeMentira()
    with patch("app.services.whatsapp.requests.post", side_effect=falsa.post):
        yield falsa
    limpar_caches_numero()


def _montar_barbearia(barbearia, barbeiros, dia):
    """Com zap, um servico, e cada barbeiro com o servico e o dia aberto."""
    from tenant.models import Barbearia, Barbeiro, BarbeiroServico, HorarioTrabalho, Servico

    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    servico = Servico.objects.using("owner").create(
        barbearia_id=barbearia.id, nome="Corte", duracao_minima_min=10, duracao_sugerida_min=30,
    )
    criados = {}
    for nome, numero in barbeiros:
        barbeiro = Barbeiro.objects.using("owner").create(
            barbearia_id=barbearia.id, nome=nome, whatsapp=numero, papel="BARBEIRO", ativo=True,
        )
        BarbeiroServico.objects.using("owner").create(
            barbearia_id=barbearia.id, barbeiro=barbeiro, servico=servico, duracao_min=30,
        )
        HorarioTrabalho.objects.using("owner").create(
            barbearia_id=barbearia.id, barbeiro=barbeiro, dia_semana=dia_semana_de(dia),
            minutos_inicio=0, minutos_fim=1440,
        )
        criados[nome] = barbeiro
    return servico, criados


def _marcar(client, slug, barbeiro, servico, inicio, nome, numero):
    r = client.post(
        "/api/agendamentos",
        {"barbeiroId": str(barbeiro.id), "servicoId": str(servico.id),
         "inicio": inicio.isoformat(), "nome": nome, "whatsapp": numero},
        content_type="application/json", headers={"host": f"{slug}.localhost", **CABECALHO},
    )
    assert r.status_code == 201, r.content
    return r.json()["codigo"]


@pytest.fixture
def cena(client, cenario, evolution):
    """Ana e Beto no Brutus, o Xavier marcado com a Ana e a Yara com o Beto,
    os dois as 10:00 do mesmo dia. No Dom Tony, o Tony com o Ze, tambem as
    10:00. Mais o barbeiro que o `cenario` ja cria no Brutus, sem horario."""
    dia = somar_dias(dia_de_hoje(datetime.now(timezone.utc)), 3)
    inicio = local_para_utc(dia, 10 * 60)

    servico, b = _montar_barbearia(cenario["brutus"], [("Ana Lima", ANA), ("Beto Souza", BETO)], dia)
    servico_d, d = _montar_barbearia(cenario["dontony"], [("Tony Reis", TONY)], dia)

    codigos = {
        "xavier": _marcar(client, "brutus", b["Ana Lima"], servico, inicio, "Xavier Prado", XAVIER),
        "yara": _marcar(client, "brutus", b["Beto Souza"], servico, inicio, "Yara Melo", YARA),
        "ze": _marcar(client, "dontony", d["Tony Reis"], servico_d, inicio, "Ze Campos", ZE_DA_OUTRA),
    }
    return {"dia": dia, "inicio": inicio, "codigos": codigos, "ana": b["Ana Lima"],
            "beto": b["Beto Souza"], "brutus": cenario["brutus"]}


def _sessao(client, barbeiro, papel="BARBEIRO"):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=str(barbeiro.id), bid=str(barbeiro.barbearia_id), papel=papel, tv=0,
    )


def _id_do(codigo):
    from tenant.models import Agendamento

    return Agendamento.objects.using("owner").get(codigo=codigo).id


# --------------------------------------------------------------- marcar


def test_a_confirmacao_vai_ao_cliente_certo_com_o_barbeiro_certo(cena, evolution):
    (do_xavier,) = evolution.para(XAVIER)
    (da_yara,) = evolution.para(YARA)

    assert "Ana Lima" in do_xavier and "Beto" not in do_xavier
    assert "Beto Souza" in da_yara and "Ana" not in da_yara
    assert do_xavier.startswith("*Brutus*") and da_yara.startswith("*Brutus*")
    assert evolution.para(ZE_DA_OUTRA)[0].startswith("*Dom Tony*")


def test_marcar_nao_leva_nada_do_cliente_ao_barbeiro_do_colega(cena, evolution):
    """SE o barbeiro e' avisado de um horario de outro dia e' regra de outro
    lugar (o PR do "so' o que e' de hoje" a muda); aqui o que se prende e' que
    nada de um cliente chega ao barbeiro de outro."""
    assert all("Yara" not in t for t in evolution.para(ANA))
    assert all("Xavier" not in t for t in evolution.para(BETO))
    assert all("Xavier" not in t and "Yara" not in t for t in evolution.para(TONY))
    # O barbeiro sem horario nenhum nao recebe nada, e numero de fora tambem nao.
    assert evolution.para("11911112222") == []
    assert {n for n, _ in evolution.enviadas} <= {XAVIER, YARA, ZE_DA_OUTRA, ANA, BETO, TONY}


# --------------------------------------------------------- lista do dia


def test_a_lista_da_manha_cada_um_recebe_so_os_seus(cena, evolution):
    evolution.esquecer()

    lista_do_dia.enviar(local_para_utc(cena["dia"], lista_do_dia.HORA_PADRAO_MIN))

    (da_ana,) = evolution.para(ANA)
    (do_beto,) = evolution.para(BETO)
    (do_tony,) = evolution.para(TONY)
    assert da_ana.startswith("Bom dia, Ana!") and "Xavier Prado" in da_ana and "Yara" not in da_ana
    assert do_beto.startswith("Bom dia, Beto!") and "Yara Melo" in do_beto and "Xavier" not in do_beto
    assert "Ze Campos" in do_tony and "Xavier" not in do_tony and "Yara" not in do_tony
    # Lista e' de barbeiro: cliente nenhum recebe, e quem nao tem horario tambem nao.
    assert {n for n, _ in evolution.enviadas} == {ANA, BETO, TONY}


# ------------------------------------------------------------- lembrete


def test_o_lembrete_vai_a_cada_cliente_com_o_barbeiro_dele(cena, evolution):
    evolution.esquecer()

    lembrete.enviar_pendentes(cena["inicio"] - timedelta(minutes=50))

    (do_xavier,) = evolution.para(XAVIER)
    (da_yara,) = evolution.para(YARA)
    assert "Ana Lima" in do_xavier and "Beto" not in do_xavier
    assert "Beto Souza" in da_yara and "Ana" not in da_yara
    # Lembrete e' de cliente: barbeiro nenhum recebe.
    assert {n for n, _ in evolution.enviadas} == {XAVIER, YARA, ZE_DA_OUTRA}


# ------------------------------------------------------------ cancelar


def test_o_cliente_cancelando_avisa_so_o_barbeiro_dele(client, cena, evolution):
    evolution.esquecer()

    r = client.post(f"/api/agendamentos/{cena['codigos']['yara']}/cancelar",
                    content_type="application/json", headers={"host": "brutus.localhost", **CABECALHO})
    assert r.status_code == 200

    (da_yara,) = evolution.para(YARA)
    assert "Beto Souza" in da_yara
    # Se o Beto e' avisado de um cancelamento de outro dia e' a mesma regra
    # de fora do teste de marcar; a Ana, de todo jeito, nao fica sabendo.
    assert all("Yara Melo" in t for t in evolution.para(BETO))
    assert {n for n, _ in evolution.enviadas} <= {YARA, BETO}


def test_o_barbeiro_nao_cancela_o_horario_do_colega(client, cena, evolution):
    from tenant.models import Agendamento

    evolution.esquecer()
    _sessao(client, cena["beto"])

    r = client.post(f"/api/painel/agendamentos/{_id_do(cena['codigos']['xavier'])}/cancelar",
                    content_type="application/json", headers={"host": "brutus.localhost", **CABECALHO})

    assert r.status_code == 404
    assert evolution.enviadas == []
    assert Agendamento.objects.using("owner").get(codigo=cena["codigos"]["xavier"]).status == "CONFIRMADO"


def test_a_barbearia_cancelando_avisa_so_o_cliente_do_horario(client, cena, evolution):
    evolution.esquecer()
    _sessao(client, cena["ana"])

    r = client.post(f"/api/painel/agendamentos/{_id_do(cena['codigos']['xavier'])}/cancelar",
                    content_type="application/json", headers={"host": "brutus.localhost", **CABECALHO})
    assert r.status_code == 200

    # Este texto nao cita o barbeiro: o que importa e' ir so' ao Xavier.
    (do_xavier,) = evolution.para(XAVIER)
    assert do_xavier.startswith("*Brutus*") and "Oi, Xavier." in do_xavier
    assert {n for n, _ in evolution.enviadas} == {XAVIER}
