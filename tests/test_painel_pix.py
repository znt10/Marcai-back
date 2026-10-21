"""P5: a agenda e o quadro do painel mostram o Pix dos agendamentos.

O bloco `pix` e' aditivo: CONFIRMADO sem cobranca segue com `pix: null`. So
aguardando, expirado que ainda nao comecou (onde o "recebi" atrasado mora) e
confirmado ja pago ganham o bloco. Lista do dia, resumo e afins seguem so
CONFIRMADO."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.test.utils import CaptureQueriesContext

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

# Uma quinta futura fixa em relacao ao relogio: o expediente do quadro e' dia 4.
_hoje = datetime.now(timezone.utc).date()
DIA = (_hoje + timedelta(days=(3 - _hoje.weekday()) % 7 or 7)).isoformat()
CHAVE = "zeca@exemplo.com"


def _barbeiro(bid, nome="Zeca", papel="BARBEIRO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=bid, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, bid):
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=bid, papel=barbeiro.papel, tv=0)
    return "brutus.localhost"


def _expediente(bid, barbeiro):
    from tenant.models import HorarioTrabalho

    HorarioTrabalho.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=bid, barbeiro_id=barbeiro.id,
        dia_semana=4, minutos_inicio=0, minutos_fim=1439,
    )


def _servico(bid, barbeiro, duracao=30):
    from tenant.models import BarbeiroServico, Servico

    s = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=bid, nome=f"Corte {uuid.uuid4().hex[:6]}",
        duracao_minima_min=15, duracao_sugerida_min=duracao,
    )
    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id, servico_id=s.id, barbearia_id=bid, duracao_min=duracao, ativo=True,
    )
    return s


def _ag(bid, barbeiro, inicio, status="CONFIRMADO", nome="Cliente"):
    from tenant.models import Agendamento, Cliente, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=bid, nome=f"S {uuid.uuid4().hex[:6]}",
        duracao_minima_min=20, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=bid, nome=nome,
        whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
    )
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=bid, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status=status,
    )


def _cobranca(bid, ag, status, centavos=3501, expira_em=None):
    from tenant.models import Cobranca

    return Cobranca.objects.using("admin").create(
        id=uuid.uuid4(), barbearia_id=bid, motivo="AGENDAMENTO", chave_pix=CHAVE,
        valor_base_centavos=3500, valor_centavos=centavos,
        copia_e_cola="00020126SEGREDO", status=status, agendamento_id=ag.id,
        expira_em=expira_em or datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def _inicio(h):
    return datetime.fromisoformat(f"{DIA}T{h:02d}:00:00+00:00")


def _meia_noite():
    from tenant.datas import local_para_utc

    return local_para_utc(DIA, 0)


def _agenda(client, host, **q):
    r = client.get("/api/painel/agenda", {"dia": DIA, **q}, headers={"host": host})
    assert r.status_code == 200
    return {i["id"]: i for i in r.json()["itens"]}


def _quadro(client, host, **q):
    r = client.get("/api/painel/dia", {"dia": DIA, **q}, headers={"host": host})
    assert r.status_code == 200
    return r.json()["colunas"]


def test_agenda_traz_aguardando_expirado_futuro_e_pago_com_o_bloco_pix(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    sem = _ag(b.id, dono, _inicio(10))
    ag = _ag(b.id, dono, _inicio(11), "AGUARDANDO_PAGAMENTO")
    ex = _ag(b.id, dono, _inicio(12), "EXPIRADO")
    pago = _ag(b.id, dono, _inicio(13))
    _cobranca(b.id, ag, "ABERTA", 3501)
    _cobranca(b.id, ex, "EXPIRADA", 3502)
    _cobranca(b.id, pago, "PAGA", 3503)
    _ag(b.id, dono, _inicio(14), "CANCELADO")

    itens = _agenda(client, host)
    assert set(itens) == {sem.id, ag.id, ex.id, pago.id}
    assert itens[sem.id]["pix"] is None
    assert itens[ag.id]["pix"]["estado"] == "aguardando"
    assert itens[ag.id]["pix"]["valorCentavos"] == 3501
    assert itens[ag.id]["pix"]["expiraEm"]
    assert itens[ex.id]["pix"]["estado"] == "expirado"
    assert itens[ex.id]["pix"]["valorCentavos"] == 3502
    assert itens[pago.id]["pix"]["estado"] == "pago"
    assert itens[pago.id]["pix"]["valorCentavos"] == 3503


def test_o_bloco_pix_nao_vaza_chave_nem_copia_e_cola(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    ag = _ag(b.id, dono, _inicio(11), "AGUARDANDO_PAGAMENTO")
    _cobranca(b.id, ag, "ABERTA")

    r = client.get("/api/painel/agenda", {"dia": DIA}, headers={"host": host})
    assert set(r.json()["itens"][0]["pix"]) == {"estado", "valorCentavos", "expiraEm"}
    assert CHAVE not in r.content.decode() and "SEGREDO" not in r.content.decode()


def test_expirado_cujo_horario_ja_comecou_nao_aparece(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(minutes=10)
    ex = _ag(b.id, dono, inicio, "EXPIRADO")
    _cobranca(b.id, ex, "EXPIRADA")
    # O dia local de "agora - 10 min" pode cair em qualquer um dos tres.
    for d in ((agora - timedelta(days=1)), agora, (agora + timedelta(days=1))):
        r = client.get("/api/painel/agenda", {"dia": d.date().isoformat()}, headers={"host": host})
        assert ex.id not in [i["id"] for i in r.json()["itens"]]


def test_uma_consulta_extra_por_dia_nao_uma_por_item(client, cenario):
    from django.db import connections

    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    def consultas_em_cobranca():
        with CaptureQueriesContext(connections["admin"]) as q:
            _agenda(client, host)
        return len([x for x in q.captured_queries if "tenant_cobranca" in x["sql"]])

    for h in range(8, 10):
        ag = _ag(b.id, dono, _inicio(h), "AGUARDANDO_PAGAMENTO")
        _cobranca(b.id, ag, "ABERTA", 3500 + h)
    duas = consultas_em_cobranca()
    for h in range(10, 16):
        ag = _ag(b.id, dono, _inicio(h), "AGUARDANDO_PAGAMENTO")
        _cobranca(b.id, ag, "ABERTA", 3500 + h)
    assert consultas_em_cobranca() == duas == 1


def test_outro_barbeiro_so_ve_a_propria_agenda_com_pix(client, cenario):
    b = cenario["brutus"]
    eu = _barbeiro(b.id, "Eu")
    colega = _barbeiro(b.id, "Colega")
    host = _logar(client, eu, b.id)
    ag = _ag(b.id, colega, _inicio(11), "AGUARDANDO_PAGAMENTO")
    _cobranca(b.id, ag, "ABERTA")
    assert _agenda(client, host, barbeiroId=colega.id) == {}


def test_quadro_traz_o_bloco_pix_nos_itens(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    _expediente(b.id, dono)
    _servico(b.id, dono)
    sem = _ag(b.id, dono, _inicio(10))
    ag = _ag(b.id, dono, _inicio(11), "AGUARDANDO_PAGAMENTO")
    ex = _ag(b.id, dono, _inicio(12), "EXPIRADO")
    pago = _ag(b.id, dono, _inicio(13))
    _ag(b.id, dono, _inicio(14), "CANCELADO")
    _cobranca(b.id, ag, "ABERTA", 3501)
    _cobranca(b.id, ex, "EXPIRADA", 3502)
    _cobranca(b.id, pago, "PAGA", 3503)

    col = next(c for c in _quadro(client, host) if c["barbeiroId"] == dono.id)
    itens = {i["id"]: i for i in col["itens"] if i["tipo"] == "AGENDAMENTO"}
    assert set(itens) == {sem.id, ag.id, ex.id, pago.id}
    assert itens[sem.id]["pix"] is None
    assert itens[ag.id]["pix"]["estado"] == "aguardando"
    assert itens[ex.id]["pix"]["estado"] == "expirado"
    assert itens[pago.id]["pix"] == {
        "estado": "pago", "valorCentavos": 3503, "expiraEm": itens[pago.id]["pix"]["expiraEm"],
    }


def test_quadro_conta_aguardando_como_ocupado_e_expirado_como_livre(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    _expediente(b.id, dono)
    _servico(b.id, dono)

    vazio = next(c for c in _quadro(client, host) if c["barbeiroId"] == dono.id)
    assert vazio["ocupacaoPct"] == 0
    primeiro = vazio["proximoLivre"]

    _ag(b.id, dono, _meia_noite(), "EXPIRADO")
    col = next(c for c in _quadro(client, host) if c["barbeiroId"] == dono.id)
    assert col["ocupacaoPct"] == 0 and col["proximoLivre"] == primeiro

    ag = _ag(b.id, dono, _meia_noite(), "AGUARDANDO_PAGAMENTO")
    _cobranca(b.id, ag, "ABERTA")
    col = next(c for c in _quadro(client, host) if c["barbeiroId"] == dono.id)
    assert col["ocupacaoPct"] > 0
    assert col["proximoLivre"] != primeiro


def test_resumo_e_lista_do_dia_nao_contam_aguardando_nem_expirado(cenario):
    from app.services import lista_do_dia
    from app.services.resumo import cortes_por_barbeiro

    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    agora = datetime.now(timezone.utc)
    ontem = agora - timedelta(days=1)
    _ag(b.id, dono, ontem, "AGUARDANDO_PAGAMENTO")
    _ag(b.id, dono, ontem, "EXPIRADO")
    r = cortes_por_barbeiro(
        b.id, (ontem - timedelta(days=1)).date().isoformat(), agora.date().isoformat(), agora,
    )
    assert r["totais"]["cortes"] == 0

    # 06:30 de Sao Paulo (09:30 UTC), meio da manha de um dia fixo: o relogio
    # real faria o teste passar vazio (fora da meia hora da lista nada sai).
    lista = datetime(2026, 3, 10, 9, 30, tzinfo=timezone.utc)
    _ag(b.id, dono, lista.replace(hour=12), "AGUARDANDO_PAGAMENTO", nome="Aguardando")
    _ag(b.id, dono, lista.replace(hour=13), "EXPIRADO", nome="Expirado")
    _ag(b.id, dono, lista.replace(hour=14), "CONFIRMADO", nome="Controle")
    with patch.object(lista_do_dia, "enviar_a_equipe_aceita", return_value=None) as envio:
        assert lista_do_dia.enviar(lista) == 1
    assert envio.call_count == 1
    texto = envio.call_args.args[1]
    assert "Controle" in texto
    assert "Aguardando" not in texto and "Expirado" not in texto
