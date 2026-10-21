"""Marcar com Pix: o SITE de um barbeiro que cobra nasce AGUARDANDO_PAGAMENTO
com uma Cobranca aberta; painel, bot e todo caso sem como cobrar nascem
CONFIRMADO como sempre. Roda o fluxo de verdade (banco com RLS, as tres
conexoes); so' o envio do WhatsApp e' simulado."""
import logging
import uuid
from datetime import datetime, timedelta, timezone as fuso
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "brutus.localhost"
CHAVE = "zeca@barbearia.com"
PIX_DO_DONO = {"PIX_CHAVE": "dono@marcai.com", "PIX_NOME_RECEBEDOR": "Marcai", "PIX_CIDADE": "Patos"}


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


@pytest.fixture
def envios():
    """Cliente, equipe e a lista do dia, tudo simulado, do jeito que a view os enxerga."""
    with patch("app.api.v1.views.agendamentos.enviar_ao_cliente") as ao_cliente, patch(
        "app.api.v1.views.agendamentos.enviar_a_equipe_da"
    ) as a_equipe, patch("app.services.lista_do_dia.avisar_mudanca") as lista:

        class Envios:
            def cliente(self):
                return [(c.args[1], c.args[2]) for c in ao_cliente.call_args_list]

            def equipe(self):
                return [(c.args[1], c.args[2]) for c in a_equipe.call_args_list]

        e = Envios()
        e.lista = lista
        yield e


def _dia():
    from tenant.datas import dia_de_hoje, somar_dias

    return somar_dias(dia_de_hoje(timezone.now()), 30)


def _inicio(minutos):
    from tenant.datas import local_para_utc

    return local_para_utc(_dia(), minutos)


def _barbeiro(b, nome="Zeca", *, cobra=True, chave=CHAVE, tipo="EMAIL", preco=3500):
    from tenant.datas import dia_semana_de
    from tenant.models import Barbeiro, BarbeiroServico, HorarioTrabalho, Servico

    servico = Servico.objects.using("owner").get_or_create(
        barbearia_id=b.id, nome="Corte",
        defaults={"duracao_minima_min": 20, "duracao_sugerida_min": 30},
    )[0]
    barbeiro = Barbeiro.objects.using("owner").create(
        barbearia_id=b.id, nome=nome, whatsapp=f"1198{uuid.uuid4().int % 10**7:07d}",
        ativo=True, cobra_no_agendamento=cobra, pix_chave=chave, pix_tipo=tipo,
        pix_titular="Zeca da Silva",
    )
    BarbeiroServico.objects.using("owner").create(
        barbearia_id=b.id, barbeiro=barbeiro, servico=servico, duracao_min=30,
        preco_centavos=preco,
    )
    HorarioTrabalho.objects.using("owner").create(
        barbearia_id=b.id, barbeiro=barbeiro, dia_semana=dia_semana_de(_dia()),
        minutos_inicio=9 * 60, minutos_fim=18 * 60,
    )
    return barbeiro, servico


def _marcar_no_site(client, barbeiro, servico, minutos, whatsapp="11977778888", nome="José Neto"):
    return client.post(
        "/api/agendamentos",
        {
            "barbeiroId": str(barbeiro.id), "servicoId": str(servico.id),
            "inicio": _inicio(minutos).isoformat(), "nome": nome, "whatsapp": whatsapp,
        },
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )


def _agendamento(codigo):
    from tenant.models import Agendamento

    return Agendamento.objects.using("owner").get(codigo=codigo)


def _cobrancas():
    from tenant.models import Cobranca

    return list(Cobranca.objects.using("owner").order_by("criada_em"))


def _chamar_marcar(b, barbeiro, servico, minutos, origem, whatsapp="11977778888"):
    from app.services.agendamentos import marcar

    return marcar(
        barbearia_id=b.id, barbeiro_id=str(barbeiro.id), servico_id=str(servico.id),
        inicio=_inicio(minutos), nome="Maria", whatsapp=whatsapp,
        agora=datetime.now(fuso.utc), origem=origem,
    )


# ---- o caminho certo

def test_site_com_tudo_certo_nasce_aguardando_com_cobranca(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)

    antes = datetime.now(fuso.utc)
    r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert r.status_code == 201

    a = _agendamento(r.json()["codigo"])
    assert a.status == "AGUARDANDO_PAGAMENTO"
    assert a.lembrete_enviado_em is None
    [c] = _cobrancas()
    assert (c.motivo, c.status, c.chave_pix) == ("AGENDAMENTO", "ABERTA", CHAVE)
    assert (c.valor_base_centavos, c.valor_centavos) == (3500, 3501)
    assert c.agendamento_id == a.id and str(c.barbearia_id) == str(b.id)
    assert antes + timedelta(minutes=14) < c.expira_em < antes + timedelta(minutes=16)
    # O copia e cola leva o valor com centavos, a chave e o titular do barbeiro.
    assert "35.01" in c.copia_e_cola and CHAVE in c.copia_e_cola
    assert "ZECA DA SILVA" in c.copia_e_cola


def test_prazo_vem_da_variavel(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    antes = datetime.now(fuso.utc)
    with override_settings(PIX_AGENDAMENTO_PRAZO_MIN=3):
        r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert r.status_code == 201
    [c] = _cobrancas()
    assert antes + timedelta(minutes=2) < c.expira_em < antes + timedelta(minutes=4)
    assert "3 minutos" in envios.cliente()[0][1]


def test_cidade_da_barbearia_vai_no_copia_e_cola(client, cenario, envios):
    from tenant.models import Barbearia

    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(cidade="Patos")
    barbeiro, servico = _barbeiro(b)
    _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert "Patos" in _cobrancas()[0].copia_e_cola


def test_sem_cidade_o_copia_e_cola_leva_brasil(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert "BRASIL" in _cobrancas()[0].copia_e_cola


def test_segunda_reserva_do_mesmo_valor_na_mesma_chave_leva_02(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    assert _marcar_no_site(client, barbeiro, servico, 10 * 60).status_code == 201
    assert _marcar_no_site(client, barbeiro, servico, 11 * 60, whatsapp="11966665555").status_code == 201
    assert [c.valor_centavos for c in _cobrancas()] == [3501, 3502]


def test_dois_barbeiros_com_a_mesma_chave_pagam_centavos_diferentes(client, cenario, envios):
    b = cenario["brutus"]
    ana, servico = _barbeiro(b, "Ana")
    beto, _ = _barbeiro(b, "Beto")
    assert _marcar_no_site(client, ana, servico, 10 * 60).status_code == 201
    assert _marcar_no_site(client, beto, servico, 10 * 60, whatsapp="11966665555").status_code == 201
    assert sorted(c.valor_centavos for c in _cobrancas()) == [3501, 3502]


def test_o_horario_aguardando_nao_e_marcado_de_novo_pelo_site(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    assert _marcar_no_site(client, barbeiro, servico, 10 * 60).status_code == 201
    r = _marcar_no_site(client, barbeiro, servico, 10 * 60, whatsapp="11966665555")
    assert r.status_code == 409
    assert len(_cobrancas()) == 1


# ---- o que o cliente e o barbeiro recebem

def test_aguardando_manda_o_pix_ao_cliente_e_o_aviso_curto_ao_barbeiro(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    codigo = r.json()["codigo"]
    [c] = _cobrancas()

    [(numero, texto)] = envios.cliente()
    assert numero == "11977778888"
    assert "Corte" in texto and "R$ 35,01" in texto and "10:00" in texto
    assert c.copia_e_cola in texto
    assert "15 minutos" in texto
    assert f"/agendamento/{codigo}" in texto
    assert "Fechou" not in texto  # a confirmacao so' sai depois de pago

    [(numero, aviso)] = envios.equipe()
    assert numero == barbeiro.whatsapp
    assert aviso.startswith("José Neto marcou")
    assert "10:00" in aviso and "R$ 35,01" in aviso and "recebi" in aviso
    envios.lista.assert_not_called()


def test_confirmado_segue_igual_ao_de_hoje(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b, cobra=False)
    r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert r.status_code == 201
    assert _agendamento(r.json()["codigo"]).status == "CONFIRMADO"
    assert _cobrancas() == []
    [(_, texto)] = envios.cliente()
    assert texto.startswith("*Brutus*") and "Fechou" in texto
    envios.lista.assert_called_once()


# ---- quando NAO cobra

@pytest.mark.parametrize("ajuste", [
    {"cobra": False},
    {"chave": "", "tipo": ""},
    {"preco": None},
], ids=["desligado", "sem_chave", "sem_preco"])
def test_sem_como_cobrar_nasce_confirmado(client, cenario, envios, ajuste):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b, **ajuste)
    r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert r.status_code == 201
    assert _agendamento(r.json()["codigo"]).status == "CONFIRMADO"
    assert _cobrancas() == []
    assert "Fechou" in envios.cliente()[0][1]


@pytest.mark.parametrize("origem", ["PAINEL", "BOT"])
def test_painel_e_bot_nascem_confirmados_sem_cobranca(cenario, origem):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    criado = _chamar_marcar(b, barbeiro, servico, 10 * 60, origem)
    assert criado["status"] == "CONFIRMADO" and criado["cobranca"] is None
    assert _agendamento(criado["codigo"]).status == "CONFIRMADO"
    assert _cobrancas() == []


def test_origem_desconhecida_e_erro_de_programacao(cenario):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    with pytest.raises(ValueError):
        _chamar_marcar(b, barbeiro, servico, 10 * 60, "TELEFONE")


def test_a_rota_do_painel_nao_cobra(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=b.id, papel="BARBEIRO", tv=0)
    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"):
        r = client.post(
            "/api/painel/agendamentos",
            {
                "barbeiroId": str(barbeiro.id), "servicoId": str(servico.id),
                "inicio": _inicio(10 * 60).isoformat(), "nome": "Maria", "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201
    assert _agendamento(r.json()["codigo"]).status == "CONFIRMADO"
    assert _cobrancas() == []


def test_mensalidade_bloqueada_nasce_confirmado(client, cenario, envios):
    from tenant.models import Assinatura

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    Assinatura.objects.using("owner").filter(barbearia_id=b.id).update(
        isenta=False, valor_centavos=10000, paga_ate=timezone.localdate() - timedelta(days=7),
    )
    with override_settings(**PIX_DO_DONO):
        r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert r.status_code == 201
    assert _agendamento(r.json()["codigo"]).status == "CONFIRMADO"
    assert _cobrancas() == []


def test_mensalidade_em_dia_ainda_cobra(client, cenario, envios):
    from tenant.models import Assinatura

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    Assinatura.objects.using("owner").filter(barbearia_id=b.id).update(
        isenta=False, valor_centavos=10000, paga_ate=timezone.localdate() + timedelta(days=20),
    )
    with override_settings(**PIX_DO_DONO):
        r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert _agendamento(r.json()["codigo"]).status == "AGUARDANDO_PAGAMENTO"


def test_sem_centavo_livre_nasce_confirmado_e_avisa_no_log(client, cenario, envios, caplog):
    from tenant.models import Cobranca

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    for k in range(1, 100):
        Cobranca.objects.using("owner").create(
            barbearia_id=b.id, motivo="AGENDAMENTO", chave_pix=CHAVE,
            valor_base_centavos=3500, valor_centavos=3500 + k, copia_e_cola="x",
        )
    with caplog.at_level(logging.WARNING):
        r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert r.status_code == 201
    assert _agendamento(r.json()["codigo"]).status == "CONFIRMADO"
    assert len(_cobrancas()) == 99
    assert any(x.levelno == logging.WARNING for x in caplog.records)
    assert "Fechou" in envios.cliente()[0][1]


# ---- a ordem do commit

def test_a_cobranca_so_abre_depois_do_agendamento_comitado(cenario):
    """A FK da cobranca e' conferida no commit dela, por outra conexao: o
    agendamento precisa ja' estar visivel la."""
    from app.services import pix_agendamento
    from tenant.models import Agendamento

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    visto = {}
    original = pix_agendamento.abrir

    def espiar(**kw):
        visto["status"] = list(
            Agendamento.objects.using("owner").filter(id=kw["agendamento_id"])
            .values_list("status", flat=True)
        )
        return original(**kw)

    with patch("app.services.agendamentos.pix_agendamento.abrir", side_effect=espiar):
        criado = _chamar_marcar(b, barbeiro, servico, 10 * 60, "SITE")
    assert visto["status"] == ["AGUARDANDO_PAGAMENTO"]
    assert criado["status"] == "AGUARDANDO_PAGAMENTO"
    assert criado["cobranca"]["valor_centavos"] == 3501


def test_se_a_abertura_falha_o_agendamento_vira_confirmado_sem_cobranca(client, cenario, envios, caplog):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    with patch(
        "app.services.agendamentos.pix_agendamento.abrir", side_effect=RuntimeError("banco caiu")
    ), caplog.at_level(logging.ERROR):
        r = _marcar_no_site(client, barbeiro, servico, 10 * 60)
    assert r.status_code == 201
    assert _agendamento(r.json()["codigo"]).status == "CONFIRMADO"
    assert _cobrancas() == []
    assert any(x.levelno == logging.ERROR for x in caplog.records)
    # E o cliente recebe a confirmacao normal, nao um Pix que nao existe.
    assert "Fechou" in envios.cliente()[0][1]


# ---- a consulta pelo codigo

def _detalhe(client, codigo):
    return client.get(f"/api/agendamentos/{codigo}", headers={"host": HOST, **CABECALHO})


def test_detalhe_com_pix(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    [c] = _cobrancas()

    corpo = _detalhe(client, codigo).json()
    assert corpo["status"] == "AGUARDANDO_PAGAMENTO"
    assert corpo["pix"]["copiaECola"] == c.copia_e_cola
    assert corpo["pix"]["valorCentavos"] == 3501
    assert corpo["pix"]["qrSvg"].startswith("data:image/svg+xml")
    assert corpo["expiraEm"].endswith("Z")
    assert datetime.fromisoformat(corpo["expiraEm"].replace("Z", "+00:00")) == c.expira_em.replace(microsecond=(c.expira_em.microsecond // 1000) * 1000)
    assert corpo["barbeiro"] == {"nome": "Zeca", "whatsapp": barbeiro.whatsapp}
    # O WhatsApp do CLIENTE continua fora.
    assert "11977778888" not in str(corpo)


def test_detalhe_sem_pix(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b, cobra=False)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]

    corpo = _detalhe(client, codigo).json()
    assert corpo["status"] == "CONFIRMADO"
    assert corpo["pix"] is None and corpo["expiraEm"] is None
    assert corpo["barbeiro"] == {"nome": "Zeca", "whatsapp": barbeiro.whatsapp}


def test_detalhe_do_aguardando_com_cobranca_vencida_nao_mostra_pix(client, cenario, envios):
    from tenant.models import Cobranca

    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    Cobranca.objects.using("owner").update(status="EXPIRADA")
    corpo = _detalhe(client, codigo).json()
    assert corpo["pix"] is None and corpo["expiraEm"] is None


# ---- cancelar o que esta aguardando

def _cancelar_no_site(client, codigo):
    return client.post(
        f"/api/agendamentos/{codigo}/cancelar",
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )


def test_cliente_cancela_o_aguardando_e_a_cobranca_cai(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    avisos_ao_barbeiro = len(envios.equipe())
    envios.lista.reset_mock()

    assert _detalhe(client, codigo).json()["podeCancelar"] is True

    r = _cancelar_no_site(client, codigo)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert _agendamento(codigo).status == "CANCELADO_CLIENTE"
    assert [c.status for c in _cobrancas()] == ["CANCELADA"]
    # O cliente recebe o mesmo retorno de hoje; o barbeiro nada (nunca entrou na lista).
    assert "Cancelamos" in envios.cliente()[-1][1] or "cancel" in envios.cliente()[-1][1].lower()
    assert len(envios.equipe()) == avisos_ao_barbeiro
    envios.lista.assert_not_called()


def test_o_centavo_volta_a_ficar_livre_depois_de_cancelar(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    _cancelar_no_site(client, codigo)
    _marcar_no_site(client, barbeiro, servico, 10 * 60, whatsapp="11966665555")
    assert [c.valor_centavos for c in _cobrancas()] == [3501, 3501]


def test_barbeiro_cancela_o_aguardando_pelo_painel(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    a = _agendamento(codigo)
    envios.lista.reset_mock()
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=b.id, papel="BARBEIRO", tv=0)

    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente") as ao_cliente:
        r = client.post(
            f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200
    assert _agendamento(codigo).status == "CANCELADO_BARBEIRO"
    assert [c.status for c in _cobrancas()] == ["CANCELADA"]
    ao_cliente.assert_called_once()
    envios.lista.assert_not_called()


def test_bloquear_o_cliente_cancela_o_aguardando_e_a_cobranca(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    codigo = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    a = _agendamento(codigo)
    envios.lista.reset_mock()
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=b.id, papel="BARBEIRO", tv=0)

    r = client.post(
        f"/api/painel/agendamentos/{a.id}/bloquear-cliente", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert _agendamento(codigo).status == "CANCELADO_BARBEIRO"
    assert [c.status for c in _cobrancas()] == ["CANCELADA"]
    envios.lista.assert_not_called()


def test_cancelar_so_mexe_na_cobranca_daquele_agendamento(client, cenario, envios):
    b = cenario["brutus"]
    barbeiro, servico = _barbeiro(b)
    primeiro = _marcar_no_site(client, barbeiro, servico, 10 * 60).json()["codigo"]
    _marcar_no_site(client, barbeiro, servico, 11 * 60, whatsapp="11966665555")
    _cancelar_no_site(client, primeiro)
    assert [c.status for c in _cobrancas()] == ["CANCELADA", "ABERTA"]
