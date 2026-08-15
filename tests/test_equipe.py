import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO", ativo=True, **extra):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=ativo,
        **extra,
    )


def _logar(client, barbeiro, barbearia_id, host="brutus.localhost"):
    """Le o `token_version` ATUAL do banco, nao um `tv=0` fixo: uma acao
    anterior no mesmo teste (desativar, reconvidar, trocar papel/celular)
    pode ter incrementado o token_version daquele barbeiro, e logar com um
    valor desatualizado forjaria uma sessao invalida (401) sem que o teste
    tenha nada a ver com isso."""
    from tenant.models import Barbeiro

    tv = Barbeiro.objects.using("owner").get(id=barbeiro.id).token_version
    client.cookies[COOKIE_SESSAO] = emitir(sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=tv)
    return host


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    """Nenhum teste deste arquivo deve tentar falar com a Evolution — so
    confere que `enviar_texto` foi chamado, via mock."""
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


# ---------------------------------------------------------------- GET


def test_get_exige_ser_dono(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="BARBEIRO")
    host = _logar(client, barbeiro, b.id)

    r = client.get("/api/painel/equipe", headers={"host": host})
    assert r.status_code == 403
    assert r.json()["erro"] == "Só o dono mexe na equipe."


def test_get_lista_ordenada_ativos_primeiro(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO")
    host = _logar(client, dono, b.id)
    _barbeiro(b.id, "Inativo", ativo=False)

    corpo = client.get("/api/painel/equipe", headers={"host": host}).json()
    nomes = [x["nome"] for x in corpo["equipe"]]
    assert nomes[0] == "Dono"
    assert nomes[-1] == "Inativo"


def test_get_marca_tem_senha_e_convite_expirado(client, cenario):
    from app.services.senha import gerar

    b = cenario["brutus"]
    dono = _barbeiro(b.id, "Dono", papel="DONO", senha_hash=gerar("x"))
    host = _logar(client, dono, b.id)

    vencido = datetime.now(timezone.utc) - timedelta(hours=1)
    _barbeiro(b.id, "Convite vencido", convite_expira_em=vencido)

    corpo = client.get("/api/painel/equipe", headers={"host": host}).json()
    por_nome = {x["nome"]: x for x in corpo["equipe"]}
    assert por_nome["Dono"]["temSenha"] is True
    assert por_nome["Convite vencido"]["temSenha"] is False
    assert por_nome["Convite vencido"]["conviteExpirado"] is True


# ---------------------------------------------------------------- POST (criar)


def test_post_cria_e_manda_convite(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    with patch("app.api.v1.views.equipe.enviar_texto") as mock_envia:
        r = client.post(
            "/api/painel/equipe",
            {"nome": "Novo Barbeiro", "whatsapp": "11977776666", "papel": "BARBEIRO"},
            content_type="application/json", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 201
    assert "linkConvite" in r.json()
    mock_envia.assert_called_once()

    from tenant.models import Barbeiro

    criado = Barbeiro.objects.using("owner").get(id=r.json()["id"])
    assert criado.senha_hash is None
    assert criado.convite_token_hash is not None


def test_post_celular_repetido_ativo_da_409(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    existente = _barbeiro(b.id, "Existente")

    r = client.post(
        "/api/painel/equipe",
        {"nome": "Outro", "whatsapp": existente.whatsapp, "papel": "BARBEIRO"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "Existente" in r.json()["erro"]
    assert "desativado" not in r.json()["erro"]


# ---------------------------------------------------------------- PATCH


def test_patch_rebaixar_o_unico_dono_ativo_e_recusado(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.patch(
        f"/api/painel/equipe/{dono.id}",
        {"papel": "BARBEIRO"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "único dono" in r.json()["erro"]


def test_patch_rebaixar_com_outro_dono_ativo_funciona_e_derruba_sessao(client, cenario):
    b = cenario["brutus"]
    dono1 = _barbeiro(b.id, "Dono Um", papel="DONO")
    dono2 = _barbeiro(b.id, "Dono Dois", papel="DONO")
    host = _logar(client, dono1, b.id)

    r = client.patch(
        f"/api/painel/equipe/{dono2.id}",
        {"papel": "BARBEIRO"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import Barbeiro

    atualizado = Barbeiro.objects.using("owner").get(id=dono2.id)
    assert atualizado.papel == "BARBEIRO"
    assert atualizado.token_version == 1


def test_patch_so_o_nome_nao_derruba_sessao(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    alvo = _barbeiro(b.id, "Nome Velho")

    r = client.patch(
        f"/api/painel/equipe/{alvo.id}",
        {"nome": "Nome Novo"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import Barbeiro

    atualizado = Barbeiro.objects.using("owner").get(id=alvo.id)
    assert atualizado.nome == "Nome Novo"
    assert atualizado.token_version == 0


def test_patch_whatsapp_repetido_e_recusado(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    existente = _barbeiro(b.id, "Existente")
    alvo = _barbeiro(b.id, "Alvo")

    r = client.patch(
        f"/api/painel/equipe/{alvo.id}",
        {"whatsapp": existente.whatsapp},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409


def test_patch_id_inexistente_e_404(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.patch(
        "/api/painel/equipe/nao-existe",
        {"nome": "Nome Novo"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 404


def test_patch_barbeiro_comum_recebe_403(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id, papel="BARBEIRO")
    host = _logar(client, barbeiro, b.id)

    r = client.patch(
        f"/api/painel/equipe/{barbeiro.id}",
        {"nome": "X"},
        content_type="application/json", headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------- desativar


def test_desativar_a_si_mesmo_e_recusado(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)

    r = client.post(
        f"/api/painel/equipe/{dono.id}/desativar",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "se desativar" in r.json()["erro"]


def test_desativar_um_dono_quando_so_resta_um_ativo_e_recusado(client, cenario):
    """Isola a recusa de `donos_ativos <= 1` da de `eh_eu_mesmo`: o alvo NAO
    e' quem esta logado, e' um segundo dono (aqui, ja inativo) — a contagem
    de donos ATIVOS e' 1 (so o proprio dono1) independente do estado do
    alvo, e e' isso que a recusa confere."""
    b = cenario["brutus"]
    dono1 = _barbeiro(b.id, "Dono Ativo", papel="DONO")
    dono2 = _barbeiro(b.id, "Dono Inativo", papel="DONO", ativo=False)
    host = _logar(client, dono1, b.id)

    r = client.post(
        f"/api/painel/equipe/{dono2.id}/desativar",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "único dono" in r.json()["erro"]


def test_desativar_com_agenda_futura_e_recusado_com_contagem(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    alvo = _barbeiro(b.id, "Com agenda")

    from tenant.models import Agendamento, Cliente, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=20, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Cliente", whatsapp="11988889999",
    )
    futuro = datetime.now(timezone.utc) + timedelta(days=1)
    Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=alvo.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=futuro, fim=futuro + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )

    r = client.post(
        f"/api/painel/equipe/{alvo.id}/desativar",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "1 horário" in r.json()["erro"]


def test_desativar_com_sucesso_derruba_sessao(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    alvo = _barbeiro(b.id, "Alvo")

    r = client.post(
        f"/api/painel/equipe/{alvo.id}/desativar",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import Barbeiro

    atualizado = Barbeiro.objects.using("owner").get(id=alvo.id)
    assert atualizado.ativo is False
    assert atualizado.desativado_em is not None
    assert atualizado.token_version == 1


# ---------------------------------------------------------------- reativar


def test_reativar_nao_derruba_sessao(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    alvo = _barbeiro(b.id, "Desativado", ativo=False)

    r = client.post(
        f"/api/painel/equipe/{alvo.id}/reativar",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import Barbeiro

    atualizado = Barbeiro.objects.using("owner").get(id=alvo.id)
    assert atualizado.ativo is True
    assert atualizado.desativado_em is None
    assert atualizado.token_version == 0


# ---------------------------------------------------------------- convite


def test_reconvidar_reseta_a_senha_e_manda_whatsapp(client, cenario):
    from app.services.senha import gerar

    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    alvo = _barbeiro(b.id, "Alvo", senha_hash=gerar("velha"))

    with patch("app.api.v1.views.equipe.enviar_texto") as mock_envia:
        r = client.post(
            f"/api/painel/equipe/{alvo.id}/convite",
            headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 200
    assert "linkConvite" in r.json()
    mock_envia.assert_called_once()

    from tenant.models import Barbeiro

    atualizado = Barbeiro.objects.using("owner").get(id=alvo.id)
    assert atualizado.senha_hash is None
    assert atualizado.token_version == 1


def test_reconvidar_barbeiro_desativado_e_recusado(client, cenario):
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO")
    host = _logar(client, dono, b.id)
    alvo = _barbeiro(b.id, "Desativado", ativo=False)

    r = client.post(
        f"/api/painel/equipe/{alvo.id}/convite",
        headers={"host": host, **CABECALHO},
    )
    assert r.status_code == 409
    assert "desativado" in r.json()["erro"]


# ---------------------------------------------------------------- isolamento


def test_o_rls_isola_a_equipe(client, cenario):
    for slug, nome in (("brutus", "Da Brutus"), ("dontony", "Da Dontony")):
        b = cenario[slug]
        dono = _barbeiro(b.id, f"Dono {nome}", papel="DONO")
        _barbeiro(b.id, nome)

    dono_brutus = None
    from tenant.models import Barbeiro

    dono_brutus = Barbeiro.objects.using("owner").filter(
        barbearia_id=cenario["brutus"].id, papel="DONO"
    ).first()
    host = _logar(client, dono_brutus, cenario["brutus"].id)

    nomes = [x["nome"] for x in client.get("/api/painel/equipe", headers={"host": host}).json()["equipe"]]
    assert "Da Dontony" not in nomes
