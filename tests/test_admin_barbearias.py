import uuid
from unittest.mock import patch

import pytest

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

CABECALHO = {"x-brutus-cliente": "web"}
HOST = "admin.localhost"


def _logar_admin(client):
    client.cookies[COOKIE_SESSAO_ADMIN] = emitir()


def _barbeiro(barbearia_id, nome="Zeca", papel="BARBEIRO", ativo=True, **extra):
    from tenant.models import Barbeiro

    return Barbeiro.objects.using("owner").create(
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


def _corpo_valido(slug="nova-barbearia"):
    return {
        "slug": slug,
        "nome": "Barbearia Nova",
        "endereco": "Rua das Flores, 10",
        "whatsappContato": "11988887777",
        "donoNome": "Fulano",
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
    assert dono.papel == "DONO"
    assert dono.senha_hash is None
    assert dono.convite_token_hash is not None


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

    from tenant.models import Barbeiro

    atualizado = Barbeiro.objects.using("owner").get(id=dono.id)
    assert atualizado.senha_hash is None
    assert atualizado.token_version == dono.token_version + 1
    assert atualizado.convite_token_hash is not None


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

    from tenant.models import Barbeiro

    assert Barbeiro.objects.using("owner").get(id=mais_novo.id).convite_token_hash is None


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


# ------------------------------------------------------- plano com/sem zap
#
# A instancia da Evolution e' simulada nos DOIS pontos de entrada
# (`garantir_instancia`, `apagar_instancia`) porque o que esta sob teste aqui
# nao e' a conversa com a Evolution — essa e' de `test_whatsapp_instancias.py`
# — e sim QUANDO cada uma delas e' chamada. Sao gatilhos: cadastrar, trocar de
# plano, desativar, reativar. Errar um deles nao quebra nada visivelmente; so'
# deixa uma barbearia pagando por um numero que nunca foi criado, ou um numero
# vivo de uma barbearia que saiu.


@pytest.fixture
def evolution_simulada():
    with patch("app.services.admin_barbearias.garantir_instancia") as garantir, patch(
        "app.services.admin_barbearias.apagar_instancia"
    ) as apagar:
        yield {"garantir": garantir, "apagar": apagar}


def _criar_barbearia(client, slug="nova", **extra):
    corpo = {
        "slug": slug, "nome": "Nova", "endereco": "Rua A, 1",
        "whatsappContato": "11999990000", "donoNome": "Dona",
        **extra,
    }
    return client.post(
        "/api/admin/barbearias", corpo,
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )


def _instancia_de(barbearia_id):
    from tenant.models import WhatsappInstancia

    return WhatsappInstancia.objects.using("owner").filter(barbearia_id=barbearia_id).first()


def test_criar_com_zap_deixa_a_instancia_pendente_e_chama_a_evolution(client, evolution_simulada):
    from tenant.models import Barbearia, EstadoInstancia

    _logar_admin(client)
    r = _criar_barbearia(client, plano="COM_ZAP")
    assert r.status_code == 201

    b = Barbearia.objects.using("owner").get(id=r.json()["id"])
    assert b.plano == "COM_ZAP"

    linha = _instancia_de(b.id)
    # A LINHA nasce na transacao do cadastro; a instancia na Evolution nasce
    # depois do commit. E' por isso que ela comeca `PENDENTE`: se a Evolution
    # estiver fora do ar, a barbearia existe do mesmo jeito e a conferencia
    # periodica termina o servico depois.
    assert linha is not None
    assert linha.estado == EstadoInstancia.PENDENTE
    assert linha.nome == f"marcai-{b.id}"
    assert evolution_simulada["garantir"].call_count == 1


def test_criar_sem_plano_nasce_sem_zap_e_nao_fala_com_a_evolution(client, evolution_simulada):
    from tenant.models import Barbearia

    _logar_admin(client)
    r = _criar_barbearia(client)
    assert r.status_code == 201

    b = Barbearia.objects.using("owner").get(id=r.json()["id"])
    assert b.plano == "SEM_ZAP"
    assert _instancia_de(b.id) is None
    assert evolution_simulada["garantir"].call_count == 0


def test_criar_com_plano_inventado_da_422(client, evolution_simulada):
    """Plano vem do corpo JSON do admin, como o resto: valor fora da lista e'
    recusado aqui, e nao guardado para virar um `if` perdido mais tarde."""
    _logar_admin(client)
    r = _criar_barbearia(client, plano="COM_POMBO_CORREIO")
    assert r.status_code == 422
    assert evolution_simulada["garantir"].call_count == 0


def test_patch_sobe_para_com_zap(client, cenario, evolution_simulada):
    from tenant.models import Barbearia, EstadoInstancia

    _logar_admin(client)
    b = cenario["brutus"]
    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"plano": "COM_ZAP"},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert Barbearia.objects.using("owner").get(id=b.id).plano == "COM_ZAP"
    assert _instancia_de(b.id).estado == EstadoInstancia.PENDENTE
    assert evolution_simulada["garantir"].call_count == 1


def test_patch_desce_para_sem_zap_apaga_a_instancia(client, cenario, evolution_simulada):
    from tenant.models import Barbearia

    _logar_admin(client)
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")

    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"plano": "SEM_ZAP"},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert Barbearia.objects.using("owner").get(id=b.id).plano == "SEM_ZAP"
    assert evolution_simulada["apagar"].call_count == 1


def test_patch_para_o_mesmo_plano_nao_mexe_na_evolution(client, cenario, evolution_simulada):
    """Repetir o plano que ja vale nao pode derrubar e recriar o vinculo: o
    dono teria que escanear o QR de novo porque alguem clicou duas vezes."""
    _logar_admin(client)
    b = cenario["brutus"]
    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"plano": "SEM_ZAP"},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert evolution_simulada["garantir"].call_count == 0
    assert evolution_simulada["apagar"].call_count == 0


def test_desativar_barbearia_com_zap_desliga_o_numero(client, cenario, evolution_simulada):
    """Barbearia desativada com o WhatsApp de pe continuaria respondendo por um
    numero que o Marcai ainda paga — e pior, continuaria conectada ao celular
    de um ex-cliente."""
    from tenant.models import Barbearia

    _logar_admin(client)
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")

    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"ativo": False},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert evolution_simulada["apagar"].call_count == 1


def test_reativar_barbearia_com_zap_recria_o_numero(client, cenario, evolution_simulada):
    from tenant.models import Barbearia, EstadoInstancia

    _logar_admin(client)
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP", ativo=False)

    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"ativo": True},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert _instancia_de(b.id).estado == EstadoInstancia.PENDENTE
    assert evolution_simulada["garantir"].call_count == 1


def test_desativar_barbearia_sem_zap_nao_fala_com_a_evolution(client, cenario, evolution_simulada):
    _logar_admin(client)
    r = client.patch(
        f"/api/admin/barbearias/{cenario['brutus'].id}", {"ativo": False},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert evolution_simulada["apagar"].call_count == 0


def test_listagem_mostra_o_plano(client, cenario, evolution_simulada):
    """A lista do admin e o unico lugar onde se ve quem comprou o que."""
    from tenant.models import Barbearia

    _logar_admin(client)
    Barbearia.objects.using("owner").filter(id=cenario["brutus"].id).update(plano="COM_ZAP")

    r = client.get("/api/admin/barbearias", headers={"host": HOST})
    planos = {b["slug"]: b["plano"] for b in r.json()["barbearias"]}
    assert planos == {"brutus": "COM_ZAP", "dontony": "SEM_ZAP"}
