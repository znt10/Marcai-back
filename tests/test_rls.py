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
    """
    with com_barbearia(cenario["brutus"].id):
        with pytest.raises(RuntimeError):
            with com_barbearia(cenario["dontony"].id):
                pass
