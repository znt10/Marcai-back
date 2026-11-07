"""Grupos do catalogo: a regra "tudo ou nada" (06/11/2026).

Ou a casa nao tem grupo nenhum e a lista e' solta, ou tem ao menos um e
todo servico esta dentro de algum — nunca uns dentro e outros espalhados.
"""

import uuid

import pytest

from app.services.sessao import COOKIE_SESSAO, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
JSON = "application/json"


def _servico(barbearia_id, nome="Corte", ativo=True, ordem=0, grupo=None):
    from tenant.models import Servico

    return Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        duracao_minima_min=20, duracao_sugerida_min=30, ativo=ativo, ordem=ordem,
        grupo_id=grupo.id if grupo else None,
    )


def _grupo(barbearia_id, nome="Cabelo", ordem=0, icone=None):
    from tenant.models import GrupoServico

    return GrupoServico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome, ordem=ordem, icone=icone,
    )


def _barbeiro(barbearia_id, nome="Dono", papel="DONO"):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _vinculo(barbearia_id, barbeiro, servico):
    from tenant.models import BarbeiroServico

    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id, servico_id=servico.id, barbearia_id=barbearia_id,
        duracao_min=30, ativo=True,
    )


def _logar(client, barbeiro, barbearia_id):
    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia_id, papel=barbeiro.papel, tv=0,
    )
    return {"host": "brutus.localhost", **CABECALHO}


def _grupo_de(servico):
    from tenant.models import Servico

    g = Servico.objects.using("owner").get(id=servico.id).grupo_id
    return str(g) if g else None


def _post(client, url, corpo, h):
    return client.post(url, corpo, content_type=JSON, headers=h)


def _patch(client, url, corpo, h):
    return client.patch(url, corpo, content_type=JSON, headers=h)


# ---------------------------------------------------------------- criar grupo


def test_o_primeiro_grupo_puxa_o_catalogo_inteiro_ate_o_desativado(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    corte = _servico(b.id, "Corte")
    velho = _servico(b.id, "Luzes", ativo=False)

    r = _post(client, "/api/painel/grupos", {"nome": "Cabelo", "icone": "tesoura"}, h)
    assert r.status_code == 201
    gid = r.json()["id"]
    assert _grupo_de(corte) == gid
    assert _grupo_de(velho) == gid


def test_o_segundo_grupo_nasce_vazio_e_no_fim(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    cabelo = _grupo(b.id, "Cabelo", ordem=0)
    corte = _servico(b.id, "Corte", grupo=cabelo)

    r = _post(client, "/api/painel/grupos", {"nome": "Barba"}, h)
    assert r.status_code == 201
    assert _grupo_de(corte) == str(cabelo.id)

    grupos = client.get("/api/painel/servicos", headers=h).json()["grupos"]
    assert [g["nome"] for g in grupos] == ["Cabelo", "Barba"]
    assert grupos[1]["icone"] is None


def test_nome_repetido_e_409_e_icone_desconhecido_e_422(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    _grupo(b.id, "Cabelo")

    assert _post(client, "/api/painel/grupos", {"nome": "Cabelo"}, h).status_code == 409
    assert _post(client, "/api/painel/grupos", {"nome": "Barba", "icone": "foguete"}, h).status_code == 422


def test_barbeiro_comum_nao_mexe_em_grupo(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id, "Zeca", papel="BARBEIRO"), b.id)
    assert _post(client, "/api/painel/grupos", {"nome": "Cabelo"}, h).status_code == 403


# ---------------------------------------------------------------- servico


def test_casa_com_grupos_exige_grupo_ao_criar_servico(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    cabelo = _grupo(b.id, "Cabelo")

    r = _post(client, "/api/painel/servicos", {"nome": "Corte"}, h)
    assert r.status_code == 422
    assert r.json()["erro"] == "Escolhe o grupo do serviço."

    r = _post(client, "/api/painel/servicos", {"nome": "Corte", "grupoId": str(cabelo.id)}, h)
    assert r.status_code == 201
    servicos = client.get("/api/painel/servicos", headers=h).json()["servicos"]
    assert servicos[0]["grupoId"] == str(cabelo.id)


def test_casa_sem_grupos_cria_servico_solto(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)

    r = _post(client, "/api/painel/servicos", {"nome": "Corte"}, h)
    assert r.status_code == 201
    assert client.get("/api/painel/servicos", headers=h).json()["servicos"][0]["grupoId"] is None


def test_servico_nao_sai_do_grupo_nem_vai_para_grupo_de_outra_casa(client, cenario):
    b, outra = cenario["brutus"], cenario["dontony"]
    h = _logar(client, _barbeiro(b.id), b.id)
    cabelo = _grupo(b.id, "Cabelo")
    barba = _grupo(b.id, "Barba", ordem=1)
    alheio = _grupo(outra.id, "Cabelo")
    corte = _servico(b.id, "Corte", grupo=cabelo)
    url = f"/api/painel/servicos/{corte.id}"

    assert _patch(client, url, {"grupoId": None}, h).status_code == 422
    assert _patch(client, url, {"grupoId": str(alheio.id)}, h).status_code == 422
    assert _grupo_de(corte) == str(cabelo.id)

    assert _patch(client, url, {"grupoId": str(barba.id)}, h).status_code == 200
    assert _grupo_de(corte) == str(barba.id)


# ---------------------------------------------------------------- apagar


def test_apagar_grupo_com_servicos_pede_destino(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    cabelo = _grupo(b.id, "Cabelo")
    barba = _grupo(b.id, "Barba", ordem=1)
    corte = _servico(b.id, "Corte", grupo=cabelo)

    r = client.delete(f"/api/painel/grupos/{cabelo.id}", headers=h)
    assert r.status_code == 422
    r = client.delete(f"/api/painel/grupos/{cabelo.id}?moverPara={cabelo.id}", headers=h)
    assert r.status_code == 422

    r = client.delete(f"/api/painel/grupos/{cabelo.id}?moverPara={barba.id}", headers=h)
    assert r.status_code == 200
    assert _grupo_de(corte) == str(barba.id)


def test_apagar_grupo_vazio_nao_pede_destino(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    _grupo(b.id, "Cabelo")
    vazio = _grupo(b.id, "Barba", ordem=1)

    assert client.delete(f"/api/painel/grupos/{vazio.id}", headers=h).status_code == 200


def test_apagar_o_ultimo_grupo_solta_a_lista(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    cabelo = _grupo(b.id, "Cabelo")
    corte = _servico(b.id, "Corte", grupo=cabelo)

    assert client.delete(f"/api/painel/grupos/{cabelo.id}", headers=h).status_code == 200
    assert _grupo_de(corte) is None


def test_grupo_de_outra_casa_e_404(client, cenario):
    b, outra = cenario["brutus"], cenario["dontony"]
    h = _logar(client, _barbeiro(b.id), b.id)
    alheio = _grupo(outra.id, "Cabelo")

    assert client.delete(f"/api/painel/grupos/{alheio.id}", headers=h).status_code == 404
    assert _patch(client, f"/api/painel/grupos/{alheio.id}", {"nome": "Xis"}, h).status_code == 404
    assert client.get("/api/painel/servicos", headers=h).json()["grupos"] == []


def test_renomear_e_reordenar_grupo(client, cenario):
    b = cenario["brutus"]
    h = _logar(client, _barbeiro(b.id), b.id)
    cabelo = _grupo(b.id, "Cabelo")

    r = _patch(client, f"/api/painel/grupos/{cabelo.id}", {"nome": "Cortes", "icone": "pente", "ordem": 3}, h)
    assert r.status_code == 200
    g = client.get("/api/painel/servicos", headers=h).json()["grupos"][0]
    assert (g["nome"], g["icone"], g["ordem"]) == ("Cortes", "pente", 3)


# ---------------------------------------------------------------- cliente


def test_cliente_recebe_o_grupo_e_so_os_grupos_com_servico(client, cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b.id, "Zeca", papel="BARBEIRO")
    cabelo = _grupo(b.id, "Cabelo", ordem=0, icone="tesoura")
    _grupo(b.id, "Vazio", ordem=1)
    corte = _servico(b.id, "Corte", grupo=cabelo)
    _vinculo(b.id, zeca, corte)

    corpo = client.get("/api/servicos", headers={"host": "brutus.localhost"}).json()
    assert corpo["servicos"][0]["grupoId"] == str(cabelo.id)
    assert [g["nome"] for g in corpo["grupos"]] == ["Cabelo"]
    assert corpo["grupos"][0]["icone"] == "tesoura"
