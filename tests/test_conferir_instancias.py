"""A conferencia periodica: a rede de seguranca do webhook.

O webhook e' instantaneo e o suficiente em 99% dos tiques — e e' justamente
por isso que esta tarefa precisa de teste proprio. Ela so' faz diferenca no
dia em que um evento se perde (Django reiniciando no meio do deploy, rede do
compose piscando, webhook apontando para o lugar errado), e nesse dia ninguem
esta olhando: o sintoma de ela nao funcionar e' um painel que jura estar
conectado enquanto nenhuma mensagem sai.
"""

import uuid
from unittest.mock import patch

import pytest

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import Barbearia, EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _com_zap(barbearia, estado=EstadoInstancia.PENDENTE, **campos):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    return WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=nome_da_instancia(barbearia.id), estado=estado, **campos,
    )


def _recarregar(barbearia):
    with com_barbearia(barbearia.id):
        return WhatsappInstancia.objects.get(barbearia_id=barbearia.id)


def _rodar(estado_lido=None, dono=None):
    """`consultar_estado`, `consultar_dono` e `garantir_instancia` simulados: o
    que esta sob teste e' a DECISAO da tarefa, nao a conversa com a Evolution."""
    from app import tasks
    from app.services import whatsapp_eventos

    with patch.object(tasks, "consultar_estado", return_value=estado_lido) as consultar, patch.object(
        tasks, "garantir_instancia"
    ) as garantir, patch.object(whatsapp_eventos, "consultar_dono", return_value=dono):
        resultado = tasks.conferir_instancias()
    return resultado, consultar, garantir


def test_pendente_manda_criar_a_instancia(cenario):
    """O caminho que salva uma barbearia cadastrada com a Evolution fora do
    ar: o cadastro deixou a linha `PENDENTE`, e e aqui que ela vira instancia
    de verdade."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.PENDENTE)

    _, consultar, garantir = _rodar()

    assert garantir.call_count == 1
    # Nao consulta o estado de quem ainda nao existe la.
    assert consultar.call_count == 0


def test_corrige_o_estado_quando_o_webhook_se_perdeu(cenario):
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="5583999990000")

    _rodar(estado_lido=EstadoInstancia.DESCONECTADO)

    linha = _recarregar(b)
    assert linha.estado == EstadoInstancia.DESCONECTADO
    assert linha.desconectado_desde is not None


def test_estado_igual_nao_reescreve_a_hora_da_queda(cenario):
    """A tarefa passa a cada cinco minutos. Reescrever a linha em todo tique
    faria `desconectado_desde` dizer "desde agora" para sempre."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.DESCONECTADO)
    _rodar(estado_lido=EstadoInstancia.DESCONECTADO)
    antes = _recarregar(b).desconectado_desde

    _rodar(estado_lido=EstadoInstancia.DESCONECTADO)
    assert _recarregar(b).desconectado_desde == antes


def test_evolution_muda_nada_quando_nao_sabe(cenario):
    """`None` e "nao sei" — rede fora, resposta estranha, `connecting`. Gravar
    `DESCONECTADO` porque a rede piscou faria a faixa mentir para a barbearia
    inteira."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO)

    _rodar(estado_lido=None)
    assert _recarregar(b).estado == EstadoInstancia.CONECTADO


def test_instancia_sumida_volta_para_pendente_e_e_recriada(cenario):
    """404 do lado de la (volume perdido, instancia apagada a mao). Voltar a
    `PENDENTE` e' o que faz o proximo tique recria-la."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO)

    _rodar(estado_lido=EstadoInstancia.PENDENTE)
    assert _recarregar(b).estado == EstadoInstancia.PENDENTE

    _, _, garantir = _rodar()
    assert garantir.call_count == 1


def test_barbearia_sem_zap_nao_e_consultada(cenario):
    _, consultar, garantir = _rodar(estado_lido=EstadoInstancia.CONECTADO)
    assert consultar.call_count == 0
    assert garantir.call_count == 0


def test_barbearia_desativada_nao_e_consultada(cenario):
    """Desativar ja apaga a instancia. Consultar aqui pediria a Evolution um
    nome que nao existe mais, e o 404 a marcaria `PENDENTE` — a tarefa
    recriaria, a cada cinco minutos, o numero de uma barbearia que saiu."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO)
    Barbearia.objects.using("owner").filter(id=b.id).update(ativo=False)

    _, consultar, garantir = _rodar(estado_lido=EstadoInstancia.PENDENTE)
    assert consultar.call_count == 0
    assert garantir.call_count == 0


def test_barbearia_com_zap_sem_linha_nao_derruba_o_tique(cenario):
    """Estado possivel de verdade: plano trocado com a Evolution fora do ar,
    ou linha apagada a mao. Um `None` nao tratado aqui mataria o tique inteiro
    e levaria junto todas as barbearias seguintes."""
    Barbearia.objects.using("owner").filter(id=cenario["brutus"].id).update(plano="COM_ZAP")
    _com_zap(cenario["dontony"], estado=EstadoInstancia.PENDENTE)

    _, _, garantir = _rodar()
    assert garantir.call_count == 1


def test_confere_cada_barbearia_no_proprio_tenant(cenario):
    """Duas com zap, e o estado de uma nao pode pousar na outra."""
    b, outra = cenario["brutus"], cenario["dontony"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO)
    _com_zap(outra, estado=EstadoInstancia.CONECTADO)

    _rodar(estado_lido=EstadoInstancia.DESCONECTADO)

    assert _recarregar(b).estado == EstadoInstancia.DESCONECTADO
    assert _recarregar(outra).estado == EstadoInstancia.DESCONECTADO


# ---- o numero do aparelho ----


def test_reconexao_vista_pela_conferencia_traz_o_numero_novo(cenario):
    """Regressao do numero preso: o `open` do celular novo se perdeu (Django
    reiniciando) e a conferencia viu `CONECTADO`. Antes ela regravava o numero
    que ja estava na linha — o do celular ANTERIOR — e ninguem o corrigia."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.DESCONECTADO, numero_conectado="5583911112222")

    _rodar(estado_lido=EstadoInstancia.CONECTADO, dono="558399990000@s.whatsapp.net")

    linha = _recarregar(b)
    assert linha.estado == EstadoInstancia.CONECTADO
    assert linha.numero_conectado == "83999990000"


def test_conectado_com_numero_velho_e_corrigido(cenario):
    """O estado nao mudou, mas o aparelho sim. Sem isto uma linha que ja
    ficou com o numero errado nunca sairia dele."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="5583911112222")

    resultado, _, _ = _rodar(estado_lido=EstadoInstancia.CONECTADO, dono="5583999990000@s.whatsapp.net")

    assert _recarregar(b).numero_conectado == "83999990000"
    assert resultado["corrigidas"] == 1


def test_conectado_com_numero_certo_nao_reescreve(cenario):
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="83999990000")
    antes = _recarregar(b).atualizado_em

    resultado, _, _ = _rodar(estado_lido=EstadoInstancia.CONECTADO, dono="558399990000@s.whatsapp.net")

    assert resultado["corrigidas"] == 0
    assert _recarregar(b).atualizado_em == antes


def test_dono_desconhecido_nao_apaga_o_numero(cenario):
    """`None` e' "nao sei" (rede fora): nao vira numero apagado."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.CONECTADO, numero_conectado="83999990000")

    resultado, _, _ = _rodar(estado_lido=EstadoInstancia.CONECTADO, dono=None)

    assert _recarregar(b).numero_conectado == "83999990000"
    assert resultado["corrigidas"] == 0
