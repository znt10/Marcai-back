import pytest

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

HOST = "brutus.localhost"


def _pedir(client, host=HOST):
    return client.get("/api/barbearia", headers={"host": host})


def test_devolve_o_que_a_vitrine_mostra(client, cenario):
    r = _pedir(client)
    assert r.status_code == 200
    assert r.json() == {
        "nome": "Brutus",
        "endereco": "Rua Aurora, 88",
        # Nulo ate o dono escrever a frase dele. A home tem de conseguir
        # distinguir "ainda nao disse" de uma frase vazia, senao ela mostra o
        # separador pendurado ("Rua Aurora, 88 · ").
        "horarioResumo": None,
        "whatsappContato": "11999998888",
    }


def test_nao_exige_sessao_nenhuma(client, cenario):
    """O ponto da rota existir. A irma `/api/painel/barbearia` devolve os
    mesmos campos e e' `ExigeSessao`; a home, o convite e a pagina de
    agendamento sao anonimas — quem as abre ainda nem e' cliente."""
    assert not client.cookies
    r = _pedir(client)
    assert r.status_code == 200
    # E nao e' que ela ACEITA anonimo e escolhe o que mostrar: nao ha ramo de
    # sessao aqui. Se houvesse, este assert passaria e a rota ainda poderia
    # vazar campo de painel para quem chegasse com cookie.
    assert "HTTP_COOKIE" not in r.request


def test_o_host_decide_a_barbearia(client, cenario):
    """Nao ha id na URL: quem escolhe o tenant e' o subdominio, e o RLS faz o
    resto. E' o mesmo contrato de `/api/barbeiros`."""
    assert _pedir(client).json()["nome"] == "Brutus"
    assert _pedir(client, "dontony.localhost").json()["nome"] == "Dom Tony"


def test_do_host_do_admin_da_404(client, cenario):
    """`ExigeTenant` sem sessao: do host do admin nao ha barbearia a resolver,
    e a resposta e 404 — nao um 500 por `request.barbearia` ser None."""
    assert _pedir(client, "admin.localhost").status_code == 404


def test_host_desconhecido_da_404(client, cenario):
    assert _pedir(client, "naoexiste.localhost").status_code == 404


def test_barbearia_desativada_nao_aparece(client, cenario):
    """Desativar tem de tirar a barbearia do ar de verdade, e nao so' do painel
    do admin: e' esta rota que a home chama para se desenhar."""
    from tenant.models import Barbearia

    Barbearia.objects.using("owner").filter(id=cenario["brutus"].id).update(ativo=False)
    from tenant.middleware import _limpar_cache_tenant

    _limpar_cache_tenant()
    assert _pedir(client).status_code == 404
