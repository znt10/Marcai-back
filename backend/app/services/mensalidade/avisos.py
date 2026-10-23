"""Os avisos da mensalidade pelo zap: quem chama e' a tarefa diaria; as
mensagens que dependem de uma acao (confirmou, recusou, "ja paguei") saem
de `operacoes`. Aqui moram o telefone do dono e a regra de "uma vez por
nivel e por `paga_ate`"."""

import logging

from app.services import mensagens
from app.services.whatsapp import enviar_a_equipe
from tenant.models import Assinatura, Barbearia, Barbeiro
from tenant.rls import com_barbearia_admin

from . import operacoes
from .situacao import Situacao

logger = logging.getLogger(__name__)

ALIAS = "admin"

# Do mais leve ao mais grave: so' se avisa um nivel MAIOR que o ja dado para o
# mesmo `paga_ate`, e assim o aviso nunca volta atras nem se repete.
NIVEIS = {"VENCENDO": 1, "VENCE_HOJE": 2, "BLOQUEADA": 3}


def whatsapp_do_dono(barbearia_id) -> str | None:
    """O numero do dono ATIVO. `Barbeiro` esta sob RLS, entao a leitura
    precisa do contexto da barbearia."""
    with com_barbearia_admin(barbearia_id):
        return (
            Barbeiro.objects.using(ALIAS)
            .filter(barbearia_id=barbearia_id, papel="DONO", ativo=True)
            .values_list("whatsapp", flat=True)
            .first()
        ) or None


def _nivel_de_hoje(leitura) -> str | None:
    if leitura.situacao == Situacao.BLOQUEADA:
        return "BLOQUEADA"
    if leitura.situacao == Situacao.VENCENDO:
        return "VENCE_HOJE" if leitura.dias == 0 else "VENCENDO"
    return None  # EM_DIA, AGUARDANDO, ATRASADA...: nada a dizer


def _texto(nivel, nome, assinatura, leitura) -> str:
    if nivel == "VENCENDO":
        return mensagens.msg_mensalidade_vencendo(
            nome, assinatura.valor_centavos, assinatura.paga_ate, leitura.dias,
        )
    if nivel == "VENCE_HOJE":
        return mensagens.msg_mensalidade_vence_hoje(nome, assinatura.valor_centavos)
    return mensagens.msg_mensalidade_bloqueada(nome)


def enviar_do_dia(*, agora) -> int:
    """Manda o aviso que cabe hoje a cada barbearia que paga. Devolve quantos
    saiu. Um dia perdido nao acumula: manda o nivel de HOJE, uma vez."""
    enviados = 0
    pagantes = (
        Assinatura.objects.using(ALIAS)
        .filter(isenta=False, valor_centavos__gt=0)
        .select_related("barbearia")
    )
    for assinatura in pagantes:
        barbearia = assinatura.barbearia
        # Mesma pergunta da trava: sem como pagar, nao se ameaca trancar.
        if not barbearia.ativo or not operacoes.cobravel(assinatura):
            continue
        leitura = operacoes.leitura(barbearia.id, agora=agora)
        nivel = _nivel_de_hoje(leitura)
        if nivel is None:
            continue
        mesmo_ciclo = assinatura.ultimo_aviso_paga_ate == assinatura.paga_ate
        ja_dado = NIVEIS.get(assinatura.ultimo_aviso, 0) if mesmo_ciclo else 0
        if NIVEIS[nivel] <= ja_dado:
            continue
        numero = whatsapp_do_dono(barbearia.id)
        if not numero:
            continue
        # Marca ANTES de mandar: se o envio quebrar, perde-se um aviso do dia,
        # o que e' melhor que repeti-lo a cada rodada.
        Assinatura.objects.using(ALIAS).filter(pk=assinatura.pk).update(
            ultimo_aviso=nivel, ultimo_aviso_paga_ate=assinatura.paga_ate,
        )
        try:
            enviar_a_equipe(numero, _texto(nivel, barbearia.nome, assinatura, leitura))
        except Exception:
            logger.exception("[mensalidade] aviso %s nao saiu (%s)", nivel, barbearia.id)
            continue
        enviados += 1
    return enviados
