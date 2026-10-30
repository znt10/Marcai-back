import uuid
from datetime import date, timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir
from app.services.mensalidade.situacao import hoje_em_sao_paulo

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "admin.localhost"
PIX = {"PIX_CHAVE": "dono@marcai.com", "PIX_NOME_RECEBEDOR": "Marcai", "PIX_CIDADE": "Patos"}


@pytest.fixture(autouse=True)
def _pix():
    with override_settings(**PIX):
        yield


def hoje():
    return hoje_em_sao_paulo(timezone.now())


def _logar_admin(client):
    client.cookies[COOKIE_SESSAO_ADMIN] = emitir()


def _nova(slug, *, paga_ate, valor=10000, **extra):
    """Barbearia nova com assinatura propria (o `cenario` nasce isento)."""
    from tenant.models import Assinatura, Barbearia

    b = Barbearia.objects.using("owner").create(
        id=str(uuid.uuid4()), slug=slug, plano="SEM_ZAP", nome=slug.capitalize(),
        endereco="Rua A, 1", whatsapp_contato="11999998888", ativo=True,
        criado_em="2026-08-11T12:00:00Z",
    )
    if paga_ate is not None:
        Assinatura.objects.using("owner").create(
            barbearia_id=b.id, valor_centavos=valor, dia_de_vencimento=10,
            paga_ate=paga_ate, **extra,
        )
    return b


def _assinatura(bid):
    from tenant.models import Assinatura

    return Assinatura.objects.using("admin").get(barbearia_id=bid)


def _aberta(bid, **extra):
    from tenant.models import Cobranca

    return Cobranca.objects.using("admin").create(
        barbearia_id=bid, motivo="MENSALIDADE", chave_pix="dono@marcai.com",
        valor_base_centavos=10000, valor_centavos=10001, copia_e_cola="x",
        **extra,
    )


def _status(c):
    from tenant.models import Cobranca

    return Cobranca.objects.using("admin").get(id=c.id).status


def _get(client, url="/api/admin/mensalidades"):
    return client.get(url, headers={**CABECALHO, "host": HOST})


def _patch(client, bid, corpo):
    return client.patch(
        f"/api/admin/mensalidades/{bid}", corpo, content_type="application/json",
        headers={**CABECALHO, "host": HOST},
    )


def _post(client, url, corpo=None):
    return client.post(
        url, corpo or {}, content_type="application/json", headers={**CABECALHO, "host": HOST},
    )


# --------------------------------------------------------------------- acesso


@pytest.mark.parametrize("metodo,url", [
    ("get", "/api/admin/mensalidades"),
    ("patch", f"/api/admin/mensalidades/{uuid.uuid4()}"),
    ("post", f"/api/admin/mensalidades/{uuid.uuid4()}/registrar"),
    ("post", f"/api/admin/cobrancas/{uuid.uuid4()}/confirmar"),
    ("post", f"/api/admin/cobrancas/{uuid.uuid4()}/recusar"),
    ("get", f"/api/admin/mensalidades/{uuid.uuid4()}/historico"),
    ("post", f"/api/admin/cobrancas/{uuid.uuid4()}/remover"),
])
def test_sem_cookie_da_401(client, metodo, url):
    r = getattr(client, metodo)(url, headers={**CABECALHO, "host": HOST})
    assert r.status_code == 401


def test_fora_do_host_admin_da_404(client):
    _logar_admin(client)
    r = client.get("/api/admin/mensalidades", headers={"host": "brutus.localhost"})
    assert r.status_code == 404


# ------------------------------------------------------------------------ GET


def test_lista_com_contadores(client, cenario):
    _logar_admin(client)
    h = hoje()
    avisada = _nova("avisada", paga_ate=h - timedelta(days=2))
    cobranca = _aberta(avisada.id, informada_em=timezone.now())
    atrasada = _nova("atrasada", paga_ate=h - timedelta(days=2))
    bloqueada = _nova("bloqueada", paga_ate=h - timedelta(days=30))
    sem_linha = _nova("semlinha", paga_ate=None)
    paga = _nova("paga", paga_ate=h + timedelta(days=20))

    r = _get(client)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["contadores"] == {"informadas": 1, "atrasadas": 1, "bloqueadas": 1}
    por_id = {x["barbeariaId"]: x for x in corpo["barbearias"]}

    a = por_id[str(avisada.id)]
    assert a["situacao"] == "AGUARDANDO"
    assert a["informada"]["cobrancaId"] == str(cobranca.id)
    assert a["informada"]["valorCentavos"] == 10001
    assert a["informada"]["porNome"] is None
    assert a["informada"]["em"].startswith(str(h.year))
    assert a["ultimaPaga"] is None

    t = por_id[str(atrasada.id)]
    assert (t["situacao"], t["dias"], t["informada"]) == ("ATRASADA", 2, None)
    assert t["pagaAte"] == (h - timedelta(days=2)).isoformat()
    assert t["bloqueiaEm"] == (h - timedelta(days=2) + timedelta(days=6)).isoformat()
    assert t["valorCentavos"] == 10000 and t["isenta"] is False
    assert t["nuncaBloquear"] is False and t["tipo"] and t["nome"] == "Atrasada"

    assert por_id[str(bloqueada.id)]["situacao"] == "BLOQUEADA"
    assert por_id[str(paga.id)]["situacao"] == "EM_DIA"
    assert por_id[str(cenario["brutus"].id)]["situacao"] == "ISENTA"

    s = por_id[str(sem_linha.id)]
    assert s["situacao"] == "ISENTA" and s["isenta"] is True
    assert s["valorCentavos"] is None and s["pagaAte"] is None and s["informada"] is None


def test_lista_traz_o_nome_de_quem_avisou_e_a_ultima_paga(client, cenario):
    from tenant.models import Barbeiro

    _logar_admin(client)
    b = cenario["brutus"]
    barbeiro = Barbeiro.objects.using("owner").get(barbearia_id=b.id)
    c = _aberta(b.id, informada_em=timezone.now(), informada_por_id=barbeiro.id)
    from tenant.models import Cobranca

    Cobranca.objects.using("admin").create(
        barbearia_id=b.id, motivo="MENSALIDADE", chave_pix="x", valor_base_centavos=5000,
        valor_centavos=5000, copia_e_cola="", status="PAGA", paga_em=timezone.now(),
        como_foi_paga="REGISTRO", paga_ate_depois=hoje(),
    )
    linha = next(x for x in _get(client).json()["barbearias"] if x["barbeariaId"] == str(b.id))
    assert linha["informada"]["porNome"] == barbeiro.nome
    assert linha["ultimaPaga"]["valorCentavos"] == 5000
    assert linha["ultimaPaga"]["como"] == "REGISTRO"


# ---------------------------------------------------------------------- PATCH


def test_patch_cada_campo(client):
    _logar_admin(client)
    b = _nova("alvo", paga_ate=date(2026, 1, 10))
    r = _patch(client, b.id, {"valorCentavos": 7500})
    assert r.status_code == 200 and r.json()["valorCentavos"] == 7500
    r = _patch(client, b.id, {"isenta": True})
    assert r.json()["isenta"] is True and r.json()["situacao"] == "ISENTA"
    r = _patch(client, b.id, {"nuncaBloquear": True})
    assert r.json()["nuncaBloquear"] is True
    r = _patch(client, b.id, {"pagaAte": "2026-03-31"})
    assert r.json()["pagaAte"] == "2026-03-31"
    a = _assinatura(b.id)
    assert a.dia_de_vencimento == 28 and a.paga_ate == date(2026, 3, 31)
    assert (a.valor_centavos, a.isenta, a.nunca_bloquear) == (7500, True, True)


def test_patch_varios_campos_de_uma_vez(client):
    _logar_admin(client)
    b = _nova("varios", paga_ate=date(2026, 1, 10))
    r = _patch(client, b.id, {"valorCentavos": 100, "nuncaBloquear": True})
    assert r.status_code == 200
    a = _assinatura(b.id)
    assert (a.valor_centavos, a.nunca_bloquear) == (100, True)


@pytest.mark.parametrize("corpo", [
    {"valorCentavos": -1}, {"valorCentavos": "100"}, {"valorCentavos": 1.5},
    {"valorCentavos": True}, {"valorCentavos": None},
    {"isenta": "sim"}, {"isenta": 1}, {"nuncaBloquear": None},
    {"pagaAte": "10/10/2026"}, {"pagaAte": "2026-02-30"}, {"pagaAte": 20261010},
    {"pagaAte": "20261010"}, {},
])
def test_patch_com_entrada_ruim_da_400_e_nao_muda_nada(client, corpo):
    _logar_admin(client)
    b = _nova("ruim", paga_ate=date(2026, 1, 10))
    r = _patch(client, b.id, corpo)
    assert r.status_code == 400 and r.json()["erro"]
    a = _assinatura(b.id)
    assert (a.valor_centavos, a.paga_ate, a.isenta) == (10000, date(2026, 1, 10), False)


def test_patch_corpo_que_nao_e_objeto_da_400(client):
    _logar_admin(client)
    b = _nova("lista", paga_ate=date(2026, 1, 10))
    r = client.patch(
        f"/api/admin/mensalidades/{b.id}", [1], content_type="application/json",
        headers={**CABECALHO, "host": HOST},
    )
    assert r.status_code == 400


def test_patch_barbearia_inexistente_da_404(client):
    _logar_admin(client)
    assert _patch(client, uuid.uuid4(), {"valorCentavos": 1}).status_code == 404
    assert _patch(client, "nao-e-uuid", {"valorCentavos": 1}).status_code == 404


def test_patch_cria_a_assinatura_que_faltava(client):
    _logar_admin(client)
    b = _nova("semlinha", paga_ate=None)
    r = _patch(client, b.id, {"valorCentavos": 9000, "isenta": False})
    assert r.status_code == 200
    a = _assinatura(b.id)
    assert (a.valor_centavos, a.isenta) == (9000, False)
    assert r.json()["valorCentavos"] == 9000


def test_mudar_valor_cancela_a_cobranca_ainda_nao_avisada(client):
    _logar_admin(client)
    b = _nova("troca", paga_ate=hoje())
    c = _aberta(b.id)
    r = _patch(client, b.id, {"valorCentavos": 12000})
    assert r.status_code == 200
    assert _status(c) == "CANCELADA"


def test_mudar_isenta_cancela_a_cobranca_ainda_nao_avisada(client):
    _logar_admin(client)
    b = _nova("isenta", paga_ate=hoje())
    c = _aberta(b.id)
    _patch(client, b.id, {"isenta": True})
    assert _status(c) == "CANCELADA"


def test_mudar_valor_mantem_a_cobranca_ja_avisada(client):
    _logar_admin(client)
    b = _nova("avisou", paga_ate=hoje())
    c = _aberta(b.id, informada_em=timezone.now())
    _patch(client, b.id, {"valorCentavos": 12000})
    assert _status(c) == "ABERTA"


def test_patch_que_nao_muda_valor_nem_isenta_mantem_a_cobranca(client):
    _logar_admin(client)
    b = _nova("igual", paga_ate=hoje())
    c = _aberta(b.id)
    _patch(client, b.id, {"valorCentavos": 10000, "isenta": False, "nuncaBloquear": True})
    assert _status(c) == "ABERTA"


# ------------------------------------------------------------------- registrar


def test_registrar_avanca_um_mes_e_devolve_a_linha(client):
    from app.services.mensalidade.datas import mes_seguinte

    _logar_admin(client)
    vence = hoje() + timedelta(days=2)
    b = _nova("reg", paga_ate=vence)
    from tenant.models import Assinatura
    Assinatura.objects.using("owner").filter(barbearia_id=b.id).update(dia_de_vencimento=vence.day)
    c = _aberta(b.id)
    r = _post(client, f"/api/admin/mensalidades/{b.id}/registrar", {
        "valorCentavos": 9000, "observacao": " dinheiro ",
    })
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["pagaAte"] == mes_seguinte(vence, vence.day).isoformat()
    assert corpo["situacao"] == "EM_DIA"
    assert corpo["ultimaPaga"]["como"] == "REGISTRO"
    assert corpo["ultimaPaga"]["valorCentavos"] == 9000
    # sem `pagoEm`, pagou hoje
    from datetime import datetime
    pago = datetime.fromisoformat(corpo["ultimaPaga"]["pagaEm"])
    assert hoje_em_sao_paulo(pago) == hoje()
    assert _status(c) == "CANCELADA"


def test_registrar_guarda_o_dia_que_pagou(client):
    _logar_admin(client)
    vence = hoje() + timedelta(days=2)
    b = _nova("regdia", paga_ate=vence)
    ontem = hoje() - timedelta(days=1)
    r = _post(client, f"/api/admin/mensalidades/{b.id}/registrar", {
        "valorCentavos": 10000, "pagoEm": ontem.isoformat(),
    })
    assert r.status_code == 200
    from datetime import datetime
    assert hoje_em_sao_paulo(datetime.fromisoformat(r.json()["ultimaPaga"]["pagaEm"])) == ontem


def test_registrar_bloqueada_conta_o_mes_do_dia_que_pagou(client):
    from app.services.mensalidade.datas import dia_de_vencimento_para, mes_seguinte

    _logar_admin(client)
    b = _nova("regblq", paga_ate=hoje() - timedelta(days=20))
    pagou = hoje() - timedelta(days=1)
    r = _post(client, f"/api/admin/mensalidades/{b.id}/registrar", {
        "valorCentavos": 10000, "pagoEm": pagou.isoformat(),
    })
    assert r.status_code == 200
    assert r.json()["pagaAte"] == mes_seguinte(pagou, dia_de_vencimento_para(pagou)).isoformat()


def test_registrar_com_dia_no_futuro_da_400(client):
    _logar_admin(client)
    b = _nova("regfut", paga_ate=date(2026, 1, 10))
    r = _post(client, f"/api/admin/mensalidades/{b.id}/registrar", {
        "valorCentavos": 10000, "pagoEm": (hoje() + timedelta(days=1)).isoformat(),
    })
    assert r.status_code == 400
    assert _assinatura(b.id).paga_ate == date(2026, 1, 10)


@pytest.mark.parametrize("corpo", [
    {}, {"pagoEm": "2026-01-05"},
    {"pagoEm": "2026-13-01", "valorCentavos": 9000},
    {"valorCentavos": 0},
    {"valorCentavos": "9000"},
    {"valorCentavos": True},
    {"valorCentavos": 9000, "observacao": 5},
])
def test_registrar_com_entrada_ruim_da_400(client, corpo):
    _logar_admin(client)
    b = _nova("regruim", paga_ate=date(2026, 1, 10))
    r = _post(client, f"/api/admin/mensalidades/{b.id}/registrar", corpo)
    assert r.status_code == 400 and r.json()["erro"]
    assert _assinatura(b.id).paga_ate == date(2026, 1, 10)


def test_registrar_em_barbearia_inexistente_da_404(client):
    _logar_admin(client)
    r = _post(client, f"/api/admin/mensalidades/{uuid.uuid4()}/registrar", {
        "valorCentavos": 9000,
    })
    assert r.status_code == 404


def test_registrar_sem_assinatura_da_400(client):
    _logar_admin(client)
    b = _nova("regsem", paga_ate=None)
    r = _post(client, f"/api/admin/mensalidades/{b.id}/registrar", {
        "valorCentavos": 9000,
    })
    assert r.status_code == 400


# ------------------------------------------------------- confirmar e recusar


def test_confirmar_avanca_o_paga_ate(client):
    _logar_admin(client)
    paga_ate = hoje() + timedelta(days=2)
    b = _nova("conf", paga_ate=paga_ate)
    c = _aberta(b.id, informada_em=timezone.now())
    r = _post(client, f"/api/admin/cobrancas/{c.id}/confirmar")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["barbeariaId"] == str(b.id)
    assert corpo["informada"] is None
    assert corpo["pagaAte"] > paga_ate.isoformat()
    assert corpo["ultimaPaga"]["como"] == "MANUAL"
    assert _status(c) == "PAGA"


def test_confirmar_duas_vezes_da_400(client):
    _logar_admin(client)
    b = _nova("conf2", paga_ate=hoje())
    c = _aberta(b.id, informada_em=timezone.now())
    assert _post(client, f"/api/admin/cobrancas/{c.id}/confirmar").status_code == 200
    r = _post(client, f"/api/admin/cobrancas/{c.id}/confirmar")
    assert r.status_code == 400
    assert r.json() == {"erro": "Este pagamento já foi resolvido."}


def test_cobranca_desconhecida_da_400_de_ja_resolvido(client):
    _logar_admin(client)
    for acao in ("confirmar", "recusar"):
        r = _post(client, f"/api/admin/cobrancas/{uuid.uuid4()}/{acao}")
        assert r.status_code == 400
        assert r.json() == {"erro": "Este pagamento já foi resolvido."}
    assert _post(client, "/api/admin/cobrancas/xx/confirmar").status_code == 400


def test_recusar_limpa_o_aviso_e_mantem_a_cobranca_aberta(client):
    _logar_admin(client)
    b = _nova("rec", paga_ate=hoje() - timedelta(days=2))
    c = _aberta(b.id, informada_em=timezone.now())
    assert _get(client).json()["contadores"]["informadas"] == 1
    r = _post(client, f"/api/admin/cobrancas/{c.id}/recusar")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["informada"] is None and corpo["situacao"] == "ATRASADA"
    assert _status(c) == "ABERTA"
    assert _get(client).json()["contadores"]["informadas"] == 0


def test_recusar_sem_aviso_da_400(client):
    _logar_admin(client)
    b = _nova("recsem", paga_ate=hoje())
    c = _aberta(b.id)
    r = _post(client, f"/api/admin/cobrancas/{c.id}/recusar")
    assert r.status_code == 400 and r.json()["erro"]


# ------------------------------------------- ligar a cobranca e o "nao cobravel"


def test_tirar_a_isencao_comeca_um_ciclo_novo_e_nao_tranca(client):
    """Isenta ha tempo, o `paga_ate` ficou para tras: ligar a cobranca sem
    dizer ate quando esta pago comeca do zero, como barbearia nova."""
    from app.services.mensalidade.datas import dia_de_vencimento_para, mes_seguinte

    _logar_admin(client)
    h = hoje()
    b = _nova("volta", paga_ate=h - timedelta(days=30), isenta=True)
    r = _patch(client, b.id, {"isenta": False})
    assert r.status_code == 200
    assert r.json()["situacao"] == "EM_DIA"
    a = _assinatura(b.id)
    dia = dia_de_vencimento_para(h)
    assert (a.paga_ate, a.dia_de_vencimento, a.isenta) == (mes_seguinte(h, dia), dia, False)


def test_tirar_a_isencao_com_paga_ate_usa_a_data_dada(client):
    _logar_admin(client)
    b = _nova("voltadata", paga_ate=hoje() - timedelta(days=30), isenta=True)
    r = _patch(client, b.id, {"isenta": False, "pagaAte": "2027-02-14"})
    assert r.status_code == 200
    a = _assinatura(b.id)
    assert (a.paga_ate, a.dia_de_vencimento) == (date(2027, 2, 14), 14)


def test_cobrar_com_valor_zero_da_400_e_nao_muda_nada(client):
    _logar_admin(client)
    b = _nova("zero", paga_ate=hoje() - timedelta(days=30), valor=0, isenta=True)
    r = _patch(client, b.id, {"isenta": False})
    assert r.status_code == 400
    assert r.json() == {"erro": "Defina o valor da mensalidade antes de cobrar."}
    assert _assinatura(b.id).isenta is True
    r = _patch(client, b.id, {"isenta": False, "valorCentavos": 0})
    assert r.status_code == 400


def test_lista_le_como_isenta_quem_nao_tem_o_que_pagar(client):
    """Valor zero ou Pix sem configurar: nao ha como pagar, entao a lista diz
    ISENTA, igual a trava (que nao tranca) e aos avisos (que nao saem)."""
    _logar_admin(client)
    b = _nova("semvalor", paga_ate=hoje() - timedelta(days=30), valor=0)
    linha = next(x for x in _get(client).json()["barbearias"] if x["barbeariaId"] == str(b.id))
    assert linha["situacao"] == "ISENTA"
    _patch(client, b.id, {"valorCentavos": 5000})
    with override_settings(PIX_CIDADE=""):
        linha = next(x for x in _get(client).json()["barbearias"] if x["barbeariaId"] == str(b.id))
    assert linha["situacao"] == "ISENTA"
    assert _get(client).json()["contadores"]["bloqueadas"] == 1


def test_isentar_cancela_ate_a_cobranca_ja_avisada(client):
    _logar_admin(client)
    b = _nova("isentaavisada", paga_ate=hoje())
    c = _aberta(b.id, informada_em=timezone.now())
    _patch(client, b.id, {"isenta": True})
    assert _status(c) == "CANCELADA"


def test_mover_o_paga_ate_cancela_a_cobranca_aberta(client):
    _logar_admin(client)
    b = _nova("move", paga_ate=hoje())
    c = _aberta(b.id, informada_em=timezone.now())
    _patch(client, b.id, {"pagaAte": (hoje() + timedelta(days=40)).isoformat()})
    assert _status(c) == "CANCELADA"


def test_desativar_a_barbearia_cancela_a_cobranca_aberta(client):
    from app.services.admin_barbearias import atualizar_ativo

    b = _nova("desliga", paga_ate=hoje())
    c = _aberta(b.id, informada_em=timezone.now())
    assert atualizar_ativo(str(b.id), False)
    assert _status(c) == "CANCELADA"


# ------------------------------------------------------------------ historico


def _paga(bid, *, como, paga_em, valor=10000, status="PAGA", **extra):
    from tenant.models import Cobranca

    return Cobranca.objects.using("admin").create(
        barbearia_id=bid, motivo="MENSALIDADE", chave_pix=f"h:{uuid.uuid4()}",
        valor_base_centavos=valor, valor_centavos=valor, copia_e_cola="",
        status=status, como_foi_paga=como, paga_em=paga_em,
        paga_ate_depois=date(2026, 11, 10), **extra,
    )


def _historico(client, bid):
    return _get(client, f"/api/admin/mensalidades/{bid}/historico")


def test_historico_lista_os_pagamentos_do_mais_novo_ao_mais_velho(client):
    from datetime import datetime, timezone as fuso

    _logar_admin(client)
    b = _nova("hist", paga_ate=hoje())
    velho = _paga(b.id, como="MANUAL", paga_em=datetime(2026, 8, 10, 15, 0, tzinfo=fuso.utc))
    meio = _paga(b.id, como="REGISTRO", paga_em=datetime(2026, 9, 10, 15, 0, tzinfo=fuso.utc),
                 observacao="dinheiro")
    novo = _paga(b.id, como="INFINITEPAY", paga_em=datetime(2026, 10, 10, 15, 30, tzinfo=fuso.utc),
                 valor=4990)
    _aberta(b.id)
    _paga(b.id, como="MANUAL", paga_em=datetime(2026, 7, 1, tzinfo=fuso.utc), status="CANCELADA")

    r = _historico(client, b.id)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["barbearia"] == {"id": str(b.id), "nome": "Hist", "tipo": b.tipo}
    assert [p["id"] for p in corpo["pagamentos"]] == [str(novo.id), str(meio.id), str(velho.id)]
    p = corpo["pagamentos"][0]
    assert p["como"] == "INFINITEPAY" and p["valorCentavos"] == 4990
    assert p["pagaEm"].startswith("2026-10-10T15:30")
    assert p["registradaEm"] and p["pagaAteDepois"] == "2026-11-10"
    assert corpo["pagamentos"][1]["observacao"] == "dinheiro"


def test_historico_diz_quem_avisou(client):
    from datetime import datetime, timezone as fuso

    from tenant.models import Barbeiro

    _logar_admin(client)
    b = _nova("histav", paga_ate=hoje())
    zeca = Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Zeca", whatsapp="11988880001",
        papel="DONO", ativo=True,
    )
    _paga(b.id, como="MANUAL", paga_em=datetime(2026, 10, 10, tzinfo=fuso.utc),
          informada_em=datetime(2026, 10, 9, tzinfo=fuso.utc), informada_por_id=zeca.id)
    assert _historico(client, b.id).json()["pagamentos"][0]["avisadoPor"] == "Zeca"


def test_historico_de_barbearia_inexistente_da_404(client):
    _logar_admin(client)
    assert _historico(client, uuid.uuid4()).status_code == 404


def test_remover_tira_do_historico_e_da_ultima_paga_sem_mexer_no_paga_ate(client):
    from datetime import datetime, timezone as fuso

    _logar_admin(client)
    b = _nova("histrm", paga_ate=date(2026, 11, 10))
    fica = _paga(b.id, como="MANUAL", paga_em=datetime(2026, 9, 10, tzinfo=fuso.utc))
    sai = _paga(b.id, como="REGISTRO", paga_em=datetime(2026, 10, 10, tzinfo=fuso.utc))

    r = _post(client, f"/api/admin/cobrancas/{sai.id}/remover")
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["pagamentos"]] == [str(fica.id)]
    assert _assinatura(b.id).paga_ate == date(2026, 11, 10)
    linha = next(x for x in _get(client).json()["barbearias"] if x["barbeariaId"] == str(b.id))
    assert linha["ultimaPaga"]["como"] == "MANUAL"


def test_remover_duas_vezes_da_400(client):
    from datetime import datetime, timezone as fuso

    _logar_admin(client)
    b = _nova("histrm2", paga_ate=hoje())
    c = _paga(b.id, como="MANUAL", paga_em=datetime(2026, 10, 10, tzinfo=fuso.utc))
    assert _post(client, f"/api/admin/cobrancas/{c.id}/remover").status_code == 200
    r = _post(client, f"/api/admin/cobrancas/{c.id}/remover")
    assert r.status_code == 400 and r.json()["erro"] == "Este pagamento já foi removido."


def test_remover_aberta_ou_inexistente_da_400(client):
    _logar_admin(client)
    b = _nova("histrm3", paga_ate=hoje())
    aberta = _aberta(b.id)
    assert _post(client, f"/api/admin/cobrancas/{aberta.id}/remover").status_code == 400
    assert _status(aberta) == "ABERTA"
    assert _post(client, f"/api/admin/cobrancas/{uuid.uuid4()}/remover").status_code == 400
