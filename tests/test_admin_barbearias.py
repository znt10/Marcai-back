import uuid
from unittest.mock import patch

import pytest

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir
from fabricas import criar_admin, criar_barbeiro

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "admin.localhost"


def _logar_admin(client):
    # `emitir()` ganhou `sub` de verdade na fatia 3 — era o literal 'admin',
    # porque a conta nao existia em lugar nenhum para ter id.
    client.cookies[COOKIE_SESSAO_ADMIN] = emitir(criar_admin().id)


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO", ativo=True, **extra):
    from tenant.models import Barbeiro, Usuario

    return criar_barbeiro(
        id=str(uuid.uuid4()), barbearia_id=barbearia_id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=ativo,
        **extra,
    )


@pytest.fixture(autouse=True)
def _sem_whatsapp_de_verdade(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


# --------------------------------------------------------------------- acesso


def test_sem_cookie_da_401(client):
    r = client.get("/api/admin/barbearias", headers={"host": HOST})
    assert r.status_code == 401


def test_fora_do_host_admin_da_404(client):
    _logar_admin(client)
    r = client.get("/api/admin/barbearias", headers={"host": "brutus.localhost"})
    assert r.status_code == 404


# ------------------------------------------------------------------------ GET


def test_lista_barbearias_com_contagem(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]
    _barbeiro(b.id, nome="Segundo")  # cenario ja cria um — este soma dois

    r = client.get("/api/admin/barbearias", headers={"host": HOST})
    assert r.status_code == 200
    achada = next(x for x in r.json()["barbearias"] if x["id"] == b.id)
    assert achada["slug"] == b.slug
    assert achada["ativo"] is True
    assert achada["barbeiros"] == 2
    assert achada["agendamentos"] == 0


# ------------------------------------------------------------------------ POST


def _corpo_valido(slug="nova-barbearia", dono_email=None):
    return {
        "slug": slug,
        "nome": "Barbearia Nova",
        "endereco": "Rua das Flores, 10",
        # O telefone PUBLICO da barbearia, e so' isso desde a fatia 3. Ate a
        # fatia 2 ele era tambem o login do dono, e era esse acoplamento que
        # fazia trocar o contato derrubar o acesso dele.
        "whatsappContato": "11988887777",
        "donoNome": "Fulano",
        # O campo novo. Cada chamada precisa de um email PROPRIO porque
        # `Usuario.login` e unico no sistema inteiro — duas barbearias com o
        # mesmo email de dono nao podem coexistir.
        "donoEmail": dono_email or f"dono-{slug}@exemplo.com",
    }


def test_post_cria_barbearia_e_dono_e_manda_convite(client):
    _logar_admin(client)

    with patch("app.api.v1.views.admin_barbearias.enviar_texto") as mock_envia:
        r = client.post(
            "/api/admin/barbearias", _corpo_valido(),
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["slug"] == "nova-barbearia"
    assert "linkConvite" in corpo
    mock_envia.assert_called_once()

    from tenant.models import Barbearia, Barbeiro

    barbearia = Barbearia.objects.using("owner").get(id=corpo["id"])
    assert barbearia.ativo is True
    assert barbearia.horario_resumo is None

    dono = Barbeiro.objects.using("owner").get(barbearia_id=barbearia.id)
    # Credencial mora na IDENTIDADE desde a fatia 3; o perfil so' guarda quem a
    # pessoa e na agenda.
    assert dono.usuario.papel == "DONO"
    assert dono.usuario.senha_hash is None
    assert dono.usuario.convite_token_hash is not None
    # O que prova a fatia: o login do dono e o EMAIL, e nao o telefone publico
    # da barbearia.
    assert dono.usuario.login == "dono-nova-barbearia@exemplo.com"
    assert dono.whatsapp == "11988887777"


def test_post_slug_invalido_da_422(client):
    _logar_admin(client)
    r = client.post(
        "/api/admin/barbearias", _corpo_valido(slug="a"),
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_post_slug_reservado_da_422(client):
    _logar_admin(client)
    r = client.post(
        "/api/admin/barbearias", _corpo_valido(slug="admin"),
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_post_campo_faltando_da_422(client):
    _logar_admin(client)
    corpo = _corpo_valido()
    del corpo["donoNome"]
    r = client.post(
        "/api/admin/barbearias", corpo,
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_post_slug_duplicado_da_409(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]
    r = client.post(
        "/api/admin/barbearias", _corpo_valido(slug=b.slug),
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 409


def test_post_corpo_malformado_nao_estoura_500(client):
    _logar_admin(client)
    r = client.post(
        "/api/admin/barbearias", data="isto nao e json",
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code in (400, 422)


def test_criar_e_atomica_dono_orfao_nao_sobrevive_a_falha(monkeypatch):
    """A criacao inteira e' UMA transacao: se o INSERT do dono falhar depois
    do INSERT da barbearia, a barbearia nao pode ficar gravada — senao nasce
    orfa, e ninguem entra nela pra cadastrar ninguem. Testado no SERVICO
    direto (nao pela rota) pra' quebrar exatamente o segundo INSERT sem
    depender de mock de HTTP."""
    import app.services.admin_barbearias as modulo
    from tenant.models import Barbearia

    class _ObjectsQuebrado:
        def using(self, alias):
            raise RuntimeError("boom - o INSERT do dono nunca chega a rodar")

    class _BarbeiroQuebrado:
        objects = _ObjectsQuebrado()

    monkeypatch.setattr(modulo, "Barbeiro", _BarbeiroQuebrado())

    with pytest.raises(RuntimeError):
        modulo.criar(_corpo_valido(slug="vai-falhar"))

    assert not Barbearia.objects.using("owner").filter(slug="vai-falhar").exists()


# ----------------------------------------------------------------------- PATCH


def test_patch_desativa_e_reativa(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]

    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"ativo": False},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200

    from tenant.models import Barbearia

    assert Barbearia.objects.using("owner").get(id=b.id).ativo is False

    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"ativo": True},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert Barbearia.objects.using("owner").get(id=b.id).ativo is True


def test_patch_sem_ativo_da_422(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]
    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_patch_ativo_nao_booleano_da_422(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]
    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"ativo": "sim"},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 422


def test_patch_id_inexistente_da_404(client):
    _logar_admin(client)
    r = client.patch(
        "/api/admin/barbearias/nao-existe", {"ativo": True},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 404


# --------------------------------------------------------------------- convite


def test_convite_reseta_senha_e_deriva_o_token_version(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]
    dono = _barbeiro(b.id, papel="DONO", senha_hash="algum-hash")

    with patch("app.api.v1.views.admin_barbearias.enviar_texto") as mock_envia:
        r = client.post(
            f"/api/admin/barbearias/{b.id}/convite", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200
    assert "linkConvite" in r.json()
    mock_envia.assert_called_once()
    assert mock_envia.call_args.args[0] == dono.whatsapp

    from tenant.models import Barbeiro, Usuario

    atualizado = Barbeiro.objects.using("owner").get(id=dono.id)
    assert atualizado.usuario.senha_hash is None
    assert atualizado.usuario.token_version == dono.usuario.token_version + 1
    assert atualizado.usuario.convite_token_hash is not None


def test_convite_escolhe_o_dono_ativo_mais_antigo(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]
    mais_novo = _barbeiro(
        b.id, nome="Dono Novo", papel="DONO", criado_em="2026-08-10T10:00:00Z",
    )
    mais_antigo = _barbeiro(
        b.id, nome="Dono Antigo", papel="DONO", criado_em="2026-08-01T10:00:00Z",
    )

    with patch("app.api.v1.views.admin_barbearias.enviar_texto") as mock_envia:
        r = client.post(
            f"/api/admin/barbearias/{b.id}/convite", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200
    assert mock_envia.call_args.args[0] == mais_antigo.whatsapp

    from tenant.models import Barbeiro, Usuario

    assert Barbeiro.objects.using("owner").get(id=mais_novo.id).usuario.convite_token_hash is None


def test_convite_barbearia_inexistente_da_404(client):
    _logar_admin(client)
    r = client.post(
        "/api/admin/barbearias/nao-existe/convite", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 404
    assert r.json()["erro"] == "Barbearia não encontrada."


def test_convite_sem_dono_ativo_da_404(client, cenario):
    _logar_admin(client)
    b = cenario["brutus"]  # so o barbeiro padrao, papel BARBEIRO — sem DONO
    _barbeiro(b.id, papel="DONO", ativo=False)  # dono existe, mas desativado

    r = client.post(
        f"/api/admin/barbearias/{b.id}/convite", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 404
    assert r.json()["erro"] == "Essa barbearia não tem dono ativo."
