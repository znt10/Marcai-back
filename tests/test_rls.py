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


# ---- As duas tabelas da fatia 1 ----
#
# Elas nascem com politica na PROPRIA migration (0005), e nao por edicao da
# 0002/0004. Estes casos existem para provar que a politica nova vale de
# verdade, e nao so' que o `CREATE POLICY` rodou: uma tabela de tenant sem
# politica nao da erro nenhum — ela simplesmente mostra tudo para todo mundo,
# que e o defeito mais caro possivel num produto multi-barbearia.


def _instancia(barbearia, nome):
    from tenant.models import WhatsappInstancia

    return WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome,
    )


def _nao_enviada(barbearia, cliente_nome):
    from tenant.models import MensagemNaoEnviada

    return MensagemNaoEnviada.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        tipo="CONFIRMACAO", cliente_nome=cliente_nome,
    )


def test_instancia_de_whatsapp_nao_vaza_entre_barbearias(cenario):
    from tenant.models import WhatsappInstancia

    _instancia(cenario["brutus"], "marcai-da-brutus")
    _instancia(cenario["dontony"], "marcai-da-dontony")

    with com_barbearia(cenario["brutus"].id):
        assert list(WhatsappInstancia.objects.values_list("nome", flat=True)) == [
            "marcai-da-brutus"
        ]
    # Fora do wrapper, ZERO — o numero de WhatsApp de uma barbearia nao pode
    # aparecer numa consulta que esqueceu o tenant.
    assert WhatsappInstancia.objects.count() == 0


def test_mensagens_nao_enviadas_nao_vazam_entre_barbearias(cenario):
    from tenant.models import MensagemNaoEnviada

    _nao_enviada(cenario["brutus"], "Cliente da Brutus")
    _nao_enviada(cenario["dontony"], "Cliente da Dom Tony")

    with com_barbearia(cenario["dontony"].id):
        assert list(MensagemNaoEnviada.objects.values_list("cliente_nome", flat=True)) == [
            "Cliente da Dom Tony"
        ]
    assert MensagemNaoEnviada.objects.count() == 0


def test_escrever_para_a_barbearia_errada_e_recusado(cenario):
    """O WITH CHECK, que o teste de leitura sozinho nao cobre: dentro do
    tenant A, um INSERT carimbado com o id do tenant B tem que morrer no
    banco. Sem ele, um bug de `barbearia_id` no webhook escreveria o estado do
    WhatsApp de uma barbearia dentro de outra."""
    from django.db.utils import ProgrammingError
    from tenant.models import WhatsappInstancia

    with com_barbearia(cenario["brutus"].id):
        # O `match` prende o caso na POLITICA, e nao num erro qualquer: sem
        # ele, uma coluna renomeada ou uma FK quebrada tambem levantaria
        # ProgrammingError e o teste continuaria verde provando outra coisa.
        with pytest.raises(ProgrammingError, match="row-level security policy"):
            WhatsappInstancia.objects.create(
                id=str(uuid.uuid4()),
                barbearia_id=cenario["dontony"].id,
                nome="marcai-contrabandeada",
            )


def _conversa(barbearia, whatsapp):
    from tenant.models import ConversaWhatsapp

    return ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, whatsapp=whatsapp,
    )


def test_conversa_do_bot_nao_vaza_entre_barbearias(cenario):
    from tenant.models import ConversaWhatsapp

    _conversa(cenario["brutus"], "83911110000")
    _conversa(cenario["dontony"], "83922220000")

    with com_barbearia(cenario["brutus"].id):
        assert list(ConversaWhatsapp.objects.values_list("whatsapp", flat=True)) == [
            "83911110000"
        ]
    # Fora do wrapper, ZERO: o numero de quem conversa com uma barbearia nao
    # pode aparecer numa consulta que esqueceu o tenant.
    assert ConversaWhatsapp.objects.count() == 0
