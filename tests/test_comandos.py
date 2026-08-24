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


import pytest

from tenant.models import Barbearia, Barbeiro, BarbeiroServico, HorarioTrabalho, Servico


@pytest.fixture(autouse=True)
def _debug_ligado(settings):
    """`semear` recusa rodar fora de DEBUG=True (a trava de producao do
    comando). O pytest-django zera `settings.DEBUG` por padrao a cada teste
    (`django_debug_mode`, default `False`), sem olhar para DJANGO_DEBUG do
    ambiente — entao os testes deste comando precisam religa-lo aqui para
    exercitar o `handle()` de verdade, e nao so a guarda."""
    settings.DEBUG = True


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_semear_cria_os_dois_tenants():
    """Dois tenants, e nao um: a barbearia-controle `dontony` existe para que
    o isolamento seja demonstravel na mao — logar na BRUTUS e nao ver nada
    dela. Um seed de um tenant so tornaria o RLS indistinguivel de um WHERE
    esquecido."""
    call_command("semear", verbosity=0)

    slugs = set(Barbearia.objects.using("owner").values_list("slug", flat=True))
    assert slugs == {"brutus", "dontony"}


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_semear_e_idempotente():
    """Rodar duas vezes nao pode duplicar. O seed do Prisma garantia isso com
    um TRUNCATE na entrada, e este faz o mesmo — vale o mesmo aviso: ele
    APAGA o que estiver la."""
    call_command("semear", verbosity=0)
    call_command("semear", verbosity=0)

    assert Barbearia.objects.using("owner").count() == 2
    assert Barbeiro.objects.using("owner").filter(barbearia__slug="brutus").count() == 3
    assert Servico.objects.using("owner").filter(barbearia__slug="brutus").count() == 4


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_semear_deixa_o_convite_pendente_da_duda():
    """`senha_hash=None` e' o estado que o wireframe 3e desenha (convite
    pendente). Semear todo mundo com senha deixaria a tela de convite sem
    caso para exercitar."""
    call_command("semear", verbosity=0)

    duda = Barbeiro.objects.using("owner").get(barbearia__slug="brutus", nome="Duda")
    assert duda.senha_hash is None


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_semear_nao_da_pezinho_ao_rael():
    """Ausencia DE PROPOSITO no seed do Prisma: e' o caso que prova que a
    grade de servico por barbeiro e' consultada, e nao assumida. Portar o
    seed sem esta lacuna apagaria o unico cenario negativo que ele tinha."""
    call_command("semear", verbosity=0)

    servicos_do_rael = set(
        BarbeiroServico.objects.using("owner")
        .filter(barbeiro__nome="Rael")
        .values_list("servico__nome", flat=True)
    )
    assert "Pezinho" not in servicos_do_rael
    assert servicos_do_rael == {"Corte", "Barba", "Corte + Barba"}


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_semear_da_duracoes_diferentes_aos_dois_barbeiros():
    """Duracoes iguais esconderiam um bug que ignora a duracao por barbeiro.
    O seed do Prisma as fez diferentes de proposito."""
    call_command("semear", verbosity=0)

    def duracao(nome_barbeiro, nome_servico):
        return (
            BarbeiroServico.objects.using("owner")
            .get(barbeiro__nome=nome_barbeiro, servico__nome=nome_servico)
            .duracao_min
        )

    assert duracao("Téo", "Corte") == 40
    assert duracao("Rael", "Corte") == 30


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_semear_da_expediente_de_seg_a_sab_ao_teo_e_ter_a_sab_ao_rael():
    """Grades diferentes: sem isso, "o barbeiro nao trabalha nesse dia" nunca
    aparece na tela em desenvolvimento."""
    call_command("semear", verbosity=0)

    def dias(nome):
        return set(
            HorarioTrabalho.objects.using("owner")
            .filter(barbeiro__nome=nome)
            .values_list("dia_semana", flat=True)
        )

    assert dias("Téo") == {1, 2, 3, 4, 5, 6}
    assert dias("Rael") == {2, 3, 4, 5, 6}
