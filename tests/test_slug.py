import pytest

from tenant.config import SLUG_REGEX
from tenant.slug import eh_host_admin, extrair_slug


@pytest.mark.parametrize(
    "host,base,esperado",
    [
        ("brutus.seuapp.com.br", "seuapp.com.br", "brutus"),
        ("brutus.localhost:3000", "localhost", "brutus"),
        ("dontony.localhost", "localhost", "dontony"),
        # A porta do Django, que o lado Next nunca ve: mesmo host, porta outra.
        ("brutus.localhost:8000", "localhost", "brutus"),
    ],
)
def test_resolve(host, base, esperado):
    assert extrair_slug(host, base) == esperado


@pytest.mark.parametrize(
    "host,base,porque",
    [
        ("seuapp.com.br", "seuapp.com.br", "dominio nu"),
        ("localhost:3000", "localhost", "localhost puro"),
        ("www.seuapp.com.br", "seuapp.com.br", "reservado www"),
        ("api.seuapp.com.br", "seuapp.com.br", "reservado api"),
        ("painel.seuapp.com.br", "seuapp.com.br", "reservado painel"),
        ("outrodominio.com", "seuapp.com.br", "dominio alheio"),
        ("BRUTUS!.localhost", "localhost", "slug invalido"),
        ("a.b.seuapp.com.br", "seuapp.com.br", "subdominio de subdominio"),
        # Regressao: em Python $ casa antes de \n final, entao re.match com $ passaria
        # por "brutus\n" enquanto fullmatch rejeita corretamente. Esta case garante que
        # se alguem "simplificar" de volta para match+$, a suite falha.
        ("brutus\n.localhost", "localhost", "newline no slug"),
    ],
)
def test_nao_resolve(host, base, porque):
    assert extrair_slug(host, base) is None


def test_host_do_admin():
    assert eh_host_admin("admin.localhost:8000", "localhost") is True
    assert eh_host_admin("brutus.localhost", "localhost") is False
    # O 'admin' e reservado, entao extrair_slug devolve None para ele — a
    # mesma resposta que da para o dominio nu. E por isso que esta funcao
    # existe: sem ela, admin.localhost cairia na vitrine do produto.
    assert extrair_slug("admin.localhost", "localhost") is None


def test_slug_regex_rejeita_newline():
    """Regressao: protege contra "simplificacao" de fullmatch para match+$.

    Em Python, $ em regex casa antes de \n final: re.match(r"...$", "brutus\n")
    retorna match! Mas em JavaScript, $ so casa no final absoluto. fullmatch()
    evita esta divergencia. Este teste garante que a protecao permanece: se
    alguem "simplificar" de volta para match + anchors, este teste falha.
    """
    # fullmatch deve rejeitar slug com newline
    assert SLUG_REGEX.fullmatch("brutus\n") is None
    assert SLUG_REGEX.fullmatch("brutus") is not None
