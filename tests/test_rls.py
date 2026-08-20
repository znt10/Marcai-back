import uuid

import pytest

from tenant.models import Barbeiro
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def test_escopa_para_a_barbearia_pedida(cenario):
    with com_barbearia(cenario["brutus"].id):
        assert Barbeiro.objects.count() == 1
        assert Barbeiro.objects.first().nome == "Barbeiro da Brutus"


def test_nao_enxerga_a_outra(cenario):
    with com_barbearia(cenario["dontony"].id):
        nomes = list(Barbeiro.objects.values_list("nome", flat=True))
    assert nomes == ["Barbeiro da Dom Tony"]


def test_fora_do_wrapper_nao_enxerga_nada(cenario):
    # Falha FECHADA: sem app.barbearia_id definido, a politica compara com
    # NULL e nenhuma linha casa. E a propriedade que faz esquecer o wrapper
    # virar zero resultado em vez de vazamento.
    assert Barbeiro.objects.count() == 0


def test_a_variavel_morre_com_a_transacao(cenario):
    with com_barbearia(cenario["brutus"].id):
        pass
    # Se o set_config tivesse is_local=False, a variavel sobreviveria na
    # SESSAO e a conexao voltaria para a pool carregando o tenant anterior.
    # Vazamento cruzado, intermitente e dependente de temporizacao.
    assert Barbeiro.objects.count() == 0


def test_barbearia_inexistente_nao_enxerga_nada(cenario):
    with com_barbearia(str(uuid.uuid4())):
        assert Barbeiro.objects.count() == 0


def test_aninhar_com_barbearia_falha_alto_em_vez_de_vazar(cenario):
    """Aninhar com_barbearia dentro de com_barbearia seria SAVEPOINT (atomic
    aninhado no Django), e o Postgres mantem o SET LOCAL do
    'app.barbearia_id' vivo depois do RELEASE SAVEPOINT. Sem durable=True,
    sair do bloco de dentro NAO devolveria o tenant de fora: o resto do bloco
    externo leria e escreveria como o tenant de dentro — dado com cara de
    certo, da barbearia errada, sem erro nenhum. durable=True troca esse
    vazamento silencioso por RuntimeError na entrada do wrapper aninhado.
    Falhar alto aqui e o comportamento desejado, nao efeito colateral.

    O `match` prende o teste na mensagem que o proprio Django emite para o
    guarda de durabilidade, e nao em RuntimeError generico: um guarda escrito
    a mao (`if connection.in_atomic_block: raise RuntimeError(...)`) tambem
    passaria em `pytest.raises(RuntimeError)` sem provar nada sobre o
    mecanismo real. E a asercao de linhas depois do `pytest.raises` prova a
    propriedade que interessa — que o tenant de fora sobreviveu ao
    aninhamento — e nao so que o guarda disparou: um guarda que levantasse
    DEPOIS de rodar o set_config de dentro passaria no `pytest.raises` e
    teria vazado o tenant do mesmo jeito.
    """
    with com_barbearia(cenario["brutus"].id):
        with pytest.raises(RuntimeError, match="durable atomic block"):
            with com_barbearia(cenario["dontony"].id):
                pass
        assert list(Barbeiro.objects.values_list("nome", flat=True)) == [
            "Barbeiro da Brutus"
        ]


# --------------------------------------------------------------------------
# `Usuario` (fatia 2) — as DUAS direcoes
# --------------------------------------------------------------------------

# `admin` alem de default/owner: estes dois leem pela conexao do
# `brutus_admin`, e o pytest-django bloqueia alias nao declarado.
_COM_ADMIN = pytest.mark.django_db(
    databases=["default", "owner", "admin"], transaction=True,
)


def _usuario(login, papel, barbearia_id):
    from tenant.models import Usuario

    return Usuario.objects.using("owner").create(
        id=uuid.uuid4(), login=login, papel=papel, barbearia_id=barbearia_id,
    )


def test_o_runtime_nao_enxerga_o_admin_da_plataforma(cenario):
    """A propriedade central da fatia 2, e ela cai fora da algebra do SQL em
    vez de depender de excecao escrita.

    `tenant_isolation` compara `barbearia_id` com `current_setting`, e a linha
    do ADMIN tem `barbearia_id` NULL. `NULL = 'algo'` nao e falso: e NULL, e
    NULL nao satisfaz politica nenhuma. O admin da plataforma e' invisivel para
    `brutus_app` DE GRACA, dentro do wrapper ou fora dele.
    """
    from tenant.models import PapelUsuario, Usuario

    _usuario("admin", PapelUsuario.ADMIN, None)
    _usuario("dono@brutus.com", PapelUsuario.DONO, cenario["brutus"].id)

    with com_barbearia(cenario["brutus"].id):
        logins = set(Usuario.objects.values_list("login", flat=True))

    # O que importa e a AUSENCIA do admin, nao a lista exata: o `cenario` ja
    # cria a propria identidade de barbeiro, e prender o teste ao conteudo
    # inteiro faria ele quebrar toda vez que o cenario ganhasse alguem.
    assert "admin" not in logins
    assert "dono@brutus.com" in logins


@_COM_ADMIN
def test_o_admin_da_plataforma_so_alcanca_a_propria_linha(cenario):
    """A outra direcao: `admin_da_plataforma` e' `USING (barbearia_id IS NULL)`,
    entao FORA de `com_barbearia_admin()` o admin nao ve usuario de barbearia
    nenhuma — so' a si mesmo. Sem BYPASSRLS, igual ao resto do schema.
    """
    from tenant.models import PapelUsuario, Usuario

    _usuario("admin", PapelUsuario.ADMIN, None)
    _usuario("dono@brutus.com", PapelUsuario.DONO, cenario["brutus"].id)

    logins = list(Usuario.objects.using("admin").values_list("login", flat=True))
    assert logins == ["admin"]  # exata de proposito: fora do wrapper e' SO' ele


@_COM_ADMIN
def test_o_admin_dentro_do_wrapper_ve_o_tenant_e_a_si_mesmo(cenario):
    """Politicas permissivas se somam por OR: dentro de `com_barbearia_admin()`
    o admin alcanca "o que e' do tenant corrente" OU "a linha de barbearia
    nula". Ver as duas nao e' vazamento — e' o que faz o cadastro de barbearia
    conseguir criar o dono e continuar enxergando quem ele acabou de criar.
    """
    from tenant.models import PapelUsuario, Usuario
    from tenant.rls import com_barbearia_admin

    _usuario("admin", PapelUsuario.ADMIN, None)
    _usuario("dono@brutus.com", PapelUsuario.DONO, cenario["brutus"].id)
    _usuario("dono@dontony.com", PapelUsuario.DONO, cenario["dontony"].id)

    with com_barbearia_admin(cenario["brutus"].id):
        logins = set(Usuario.objects.using("admin").values_list("login", flat=True))

    assert {"admin", "dono@brutus.com"} <= logins
    # E' esta que prova o isolamento: o dono da OUTRA barbearia fica de fora.
    assert "dono@dontony.com" not in logins
