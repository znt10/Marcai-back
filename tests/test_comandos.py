import base64
from io import StringIO

from django.core.management import call_command

from app.services.senha import confere


def test_admin_hash_imprime_a_linha_do_env_pronta():
    """A saida e' colavel no .env: `ADMIN_SENHA_HASH_B64="..."`. Imprimir so o
    hash cru obrigaria quem usa a lembrar do base64 — e esquecer o base64 e
    exatamente o defeito que o formato existe para evitar."""
    saida = StringIO()
    call_command("admin_hash", "batata-frita", stdout=saida)

    linha = saida.getvalue().strip()
    assert linha.startswith('ADMIN_SENHA_HASH_B64="')
    assert linha.endswith('"')


def test_admin_hash_produz_um_hash_que_confere_a_senha():
    """A prova que importa: o que sai daqui e' lido por `admin_senha.py`, que
    faz base64-decode e passa a `confere`. Se as duas pontas discordarem do
    formato, o login nega uma senha certa e nada mais quebra."""
    saida = StringIO()
    call_command("admin_hash", "batata-frita", stdout=saida)

    b64 = saida.getvalue().strip().removeprefix('ADMIN_SENHA_HASH_B64="').removesuffix('"')
    hash_em_claro = base64.b64decode(b64).decode("utf-8")

    assert confere(hash_em_claro, "batata-frita")
    assert not confere(hash_em_claro, "outra-senha")


def test_admin_hash_gera_hash_diferente_a_cada_chamada():
    """Argon2 sorteia sal. Dois hashes iguais para a mesma senha denunciariam
    sal fixo, que e' o defeito que torna tabela arco-iris viavel."""
    primeira, segunda = StringIO(), StringIO()
    call_command("admin_hash", "batata-frita", stdout=primeira)
    call_command("admin_hash", "batata-frita", stdout=segunda)

    assert primeira.getvalue() != segunda.getvalue()
