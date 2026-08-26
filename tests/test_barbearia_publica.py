import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def test_devolve_a_barbearia_do_host(client, cenario):
    """Sem parametro de slug: aqui o tenant E' o Host, como em todo o resto do
    back. Um `?slug=` seria um seletor de barbearia por querystring — o
    defeito exato que o `baseDe()` do front existe para nao cometer."""
    b = cenario["brutus"]

    r = client.get("/api/barbearia", headers={"host": "brutus.localhost"})

    assert r.status_code == 200
    assert r.json() == {
        "nome": b.nome,
        "endereco": b.endereco,
        "horarioResumo": b.horario_resumo,
        "whatsappContato": b.whatsapp_contato,
    }


def test_camelcase_no_corpo(client, cenario):
    """O contrato repete o do Next ao pe da letra: a home ja le
    `b.horarioResumo`. Devolver snake_case quebraria a tela sem erro nenhum."""
    corpo = client.get("/api/barbearia", headers={"host": "brutus.localhost"}).json()

    assert "horarioResumo" in corpo
    assert "horario_resumo" not in corpo


def test_404_de_host_que_nao_e_tenant(client, cenario):
    """`localhost` puro nao e' barbearia nenhuma. O `ExigeTenant` responde 404,
    e nao 400: de um host sem tenant, esta rota nao existe."""
    assert client.get("/api/barbearia", headers={"host": "localhost"}).status_code == 404


def test_404_do_host_do_admin(client, cenario):
    """A BarreiraAdminMiddleware garante por posicao que rota de tenant nao e'
    alcancavel de `admin.localhost`."""
    assert client.get("/api/barbearia", headers={"host": "admin.localhost"}).status_code == 404


def test_404_de_barbearia_inativa(client, cenario):
    """`ativo=False` some do ar. O `findFirst` do Prisma filtrava por ele, e
    perder o filtro publicaria barbearia desativada — sem erro, sem log."""
    from tenant.models import Barbearia

    Barbearia.objects.using("owner").filter(slug="brutus").update(ativo=False)

    assert client.get("/api/barbearia", headers={"host": "brutus.localhost"}).status_code == 404


def test_horario_resumo_nulo_sai_como_none(client, cenario):
    """A coluna e' nullable ate o dono escrever a frase (`cenario` ja cria
    `brutus` assim). A home ja trata o nulo (`b.horarioResumo ? ... : ''`); o
    que ela nao pode receber e' a string "None"."""
    corpo = client.get("/api/barbearia", headers={"host": "brutus.localhost"}).json()

    assert corpo["horarioResumo"] is None
