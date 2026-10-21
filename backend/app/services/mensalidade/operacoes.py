"""O que se faz com a mensalidade: ler, gerar o Pix, avisar que pagou,
confirmar, recusar e registrar na mao. Nao conhece HTTP; as views, a tela
Plataforma e o vigia chamam aqui. Os avisos que nascem de uma acao (o "ja
paguei" para o Jose, confirmou/recusou para o dono) saem daqui, depois do
commit; os do calendario ficam em `avisos`.

`Assinatura` e `Cobranca` ficam fora do RLS e o `brutus_app` so le: toda
leitura e escrita daqui vai pelo alias `admin`, e toda busca filtra pela
barbearia no codigo. O relogio vem de fora (`agora`), sempre."""

import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from app.services import mensagens
from app.services.whatsapp import enviar_a_equipe
from tenant.models import (
    Assinatura,
    Barbearia,
    Barbeiro,
    Cobranca,
    ComoFoiPaga,
    MotivoCobranca,
    StatusCobranca,
)

from tenant.rls import com_barbearia_admin

from . import centavos, pix
from .centavos import SemCentavoLivre
from .datas import dia_de_vencimento_para
from .situacao import (
    ESPERA_DA_CONFIRMACAO,
    Leitura,
    Situacao,
    hoje_em_sao_paulo,
    ler_situacao,
    novo_paga_ate,
)

logger = logging.getLogger(__name__)

ALIAS = "admin"
SEM_MENSALIDADE = "Esta barbearia não tem mensalidade a pagar."


class RecusaDaMensalidade(Exception):
    """A operacao nao pode acontecer. A mensagem vai para a tela."""

    def __init__(self, mensagem):
        self.mensagem = mensagem
        super().__init__(mensagem)


def _whatsapp_do_dono(barbearia_id) -> str | None:
    from .avisos import whatsapp_do_dono  # avisos importa este modulo

    return whatsapp_do_dono(barbearia_id)


def _avisar_depois_do_commit(montar):
    """Agenda o envio para DEPOIS do commit: so' sai aviso de mudanca que
    ficou, e uma falha do zap nunca desfaz a operacao. `montar` devolve
    (numero, texto) e roda la' (as leituras do dono sao no banco e nao devem
    ocupar a transacao da operacao)."""
    def enviar():
        try:
            numero, texto = montar()
            if numero:
                enviar_a_equipe(numero, texto)
        except Exception:
            logger.exception("[mensalidade] aviso nao saiu")

    transaction.on_commit(enviar, using=ALIAS)


def _avisar_o_dono(barbearia_id, texto_para):
    """`texto_para(nome_da_barbearia)` vai ao dono ativo, se houver."""
    _avisar_depois_do_commit(lambda: (
        _whatsapp_do_dono(barbearia_id),
        texto_para(_nome_da_barbearia(barbearia_id)),
    ))


def _nome_da_barbearia(barbearia_id) -> str:
    return (
        Barbearia.objects.using(ALIAS)
        .filter(id=barbearia_id).values_list("nome", flat=True).first() or ""
    )


def _abertas_da_mensalidade(barbearia_id):
    return Cobranca.objects.using(ALIAS).filter(
        barbearia_id=barbearia_id,
        motivo=MotivoCobranca.MENSALIDADE,
        status=StatusCobranca.ABERTA,
    )


def _barbearia_ativa(barbearia_id, using=ALIAS):
    return Barbearia.objects.using(using).filter(id=barbearia_id, ativo=True).exists()


def _travar_assinatura(barbearia_id):
    """A linha da assinatura e' o semaforo de tudo que mexe na mensalidade da
    barbearia: duas cobrancas abertas, dois avisos no duplo clique e uma
    confirmacao correndo contra um "ja paguei" passam todos por aqui. Sempre
    ela primeiro e a cobranca depois, para ninguem esperar em ordem trocada."""
    return (
        Assinatura.objects.using(ALIAS)
        .select_for_update()
        .filter(pk=barbearia_id)
        .first()
    )


def cobravel(assinatura) -> bool:
    """Ha como pagar esta mensalidade? Precisa de valor e do Pix completo
    (chave, nome e cidade: sem um deles o BR Code sai invalido no banco).
    Quem nao tem como pagar le como ISENTA em todo lugar — a trava, a tela,
    a lista do admin e os avisos perguntam aqui —, porque trancar quem nao
    tem como sair do bloqueio e' trancar para sempre."""
    return (
        not assinatura.isenta
        and assinatura.valor_centavos > 0
        and bool(pix.normalizar_chave(settings.PIX_CHAVE))
        and bool(settings.PIX_NOME_RECEBEDOR)
        and bool(settings.PIX_CIDADE)
    )


def leitura(barbearia_id, *, agora, considerar_aviso=True, using=ALIAS) -> Leitura:
    """`using` so' muda por onde se LE: o crivo do painel passa "default"
    (o `brutus_app` tem SELECT nas tres tabelas); escrita fica sempre no admin."""
    hoje = hoje_em_sao_paulo(agora)
    ativa = _barbearia_ativa(barbearia_id, using)
    assinatura = Assinatura.objects.using(using).filter(pk=barbearia_id).first()
    if assinatura is None:
        # So acontece com dado torto (a criacao sempre faz a linha). Falta de
        # dado nao cobra nem tranca ninguem: vale como isenta.
        return ler_situacao(
            barbearia_ativa=ativa, isenta=True, nunca_bloquear=False,
            paga_ate=hoje, aviso_em=None, hoje=hoje, agora=agora,
        )
    aviso_em = None
    if considerar_aviso:
        aviso_em = (
            Cobranca.objects.using(using)
            .filter(
                barbearia_id=barbearia_id,
                motivo=MotivoCobranca.MENSALIDADE,
                status=StatusCobranca.ABERTA,
            )
            .exclude(informada_em=None)
            .values_list("informada_em", flat=True)
            .first()
        )
    return ler_situacao(
        barbearia_ativa=ativa,
        isenta=not cobravel(assinatura),
        nunca_bloquear=assinatura.nunca_bloquear,
        paga_ate=assinatura.paga_ate,
        aviso_em=aviso_em,
        hoje=hoje,
        agora=agora,
    )


def _ocupados(chave_pix):
    return centavos.ocupados(chave_pix, using=ALIAS)


def _abrir_cobranca(assinatura):
    chave = pix.normalizar_chave(settings.PIX_CHAVE)

    def criar(valor):
        cobranca_id = uuid.uuid4()
        return Cobranca.objects.using(ALIAS).create(
            id=cobranca_id,
            barbearia_id=assinatura.barbearia_id,
            motivo=MotivoCobranca.MENSALIDADE,
            chave_pix=chave,
            valor_base_centavos=assinatura.valor_centavos,
            valor_centavos=valor,
            copia_e_cola=pix.copia_e_cola(
                chave=chave,
                nome=settings.PIX_NOME_RECEBEDOR,
                cidade=settings.PIX_CIDADE,
                valor=Decimal(valor) / 100,
                identificador=pix.identificador(cobranca_id),
            ),
        )

    try:
        return centavos.criar_com_centavo_livre(
            chave, assinatura.valor_centavos, criar,
            ocupados_de=lambda c: _ocupados(c), using=ALIAS,
        )
    except SemCentavoLivre:
        raise RecusaDaMensalidade(
            "Não foi possível gerar o Pix agora. Tente de novo em alguns minutos."
        ) from None


# So' dentro da janela de pagamento ha Pix na tela: em dia, nao se abre
# cobranca (ocuparia um centavo da chave por semanas a toa).
JANELA_DE_PAGAMENTO = frozenset({
    Situacao.VENCENDO, Situacao.ATRASADA, Situacao.BLOQUEADA, Situacao.AGUARDANDO,
})


def _garantir_cobranca(assinatura, agora):
    """A cobranca aberta da barbearia, criada se faltar. Quem chama ja
    travou a assinatura. None quando nao ha o que cobrar ou fora da janela
    de pagamento (a linha ja aberta, se houver, fica como esta)."""
    if leitura(assinatura.barbearia_id, agora=agora).situacao not in JANELA_DE_PAGAMENTO:
        return None
    aberta = _abertas_da_mensalidade(assinatura.barbearia_id).first()
    if aberta is not None:
        return aberta
    if not cobravel(assinatura) or not _barbearia_ativa(assinatura.barbearia_id):
        return None
    return _abrir_cobranca(assinatura)


def cobranca_do_ciclo(barbearia_id, *, agora):
    """O Pix a mostrar na tela: a cobranca aberta ou uma nova. None se nao ha
    mensalidade a cobrar (isenta, valor zero, desativada ou sem PIX_CHAVE)."""
    with transaction.atomic(using=ALIAS):
        assinatura = _travar_assinatura(barbearia_id)
        if assinatura is None:
            return None
        return _garantir_cobranca(assinatura, agora)


def informar_pagamento(barbearia_id, barbeiro_id, *, agora):
    """O "Ja paguei": um aviso por vez dentro da espera de 3 dias."""
    if not _barbearia_ativa(barbearia_id):
        raise RecusaDaMensalidade("Esta barbearia está desativada.")
    with transaction.atomic(using=ALIAS):
        # A trava e' o que impede dois avisos no duplo clique: o segundo
        # pedido espera o primeiro e ja encontra a cobranca informada.
        assinatura = _travar_assinatura(barbearia_id)
        if assinatura is None or not cobravel(assinatura):
            raise RecusaDaMensalidade(SEM_MENSALIDADE)
        cobranca = _garantir_cobranca(assinatura, agora)
        if cobranca is None:
            raise RecusaDaMensalidade(SEM_MENSALIDADE)
        # Recusado uma vez, o aviso nao volta para a mesma cobranca: o Jose ja
        # olhou e nao achou o Pix, e um novo "ja paguei" so' seguraria o
        # painel mais 3 dias. A conversa segue fora do painel; uma cobranca
        # nova (registro, data movida) libera o botao outra vez.
        if cobranca.recusada_em is not None:
            raise RecusaDaMensalidade(
                "O pagamento informado foi recusado. Fale com o Marcaí."
            )
        if (
            cobranca.informada_em is not None
            and cobranca.informada_em >= agora - ESPERA_DA_CONFIRMACAO
        ):
            raise RecusaDaMensalidade(
                "Você já avisou; o pagamento está aguardando confirmação."
            )
        cobranca.informada_em = agora
        cobranca.informada_por_id = barbeiro_id
        cobranca.save(using=ALIAS, update_fields=["informada_em", "informada_por"])
        if settings.MENSALIDADE_WHATSAPP_AVISO:
            valor = cobranca.valor_centavos
            _avisar_depois_do_commit(lambda: (
                settings.MENSALIDADE_WHATSAPP_AVISO,
                mensagens.msg_mensalidade_ja_paguei(
                    _nome_da_barbearia(barbearia_id), valor,
                    _quem_avisou(barbearia_id, barbeiro_id),
                ),
            ))
        return cobranca


def _quem_avisou(barbearia_id, barbeiro_id) -> str:
    """O nome de quem apertou o "ja paguei". Barbeiro e' RLS, entao le no
    contexto da barbearia; sem achar, o aviso sai com "o dono" em vez de nao
    sair."""
    with com_barbearia_admin(barbearia_id):
        nome = (
            Barbeiro.objects.using(ALIAS)
            .filter(id=barbeiro_id).values_list("nome", flat=True).first()
        )
    return nome or "o dono"


def _travar_aberta(cobranca_id):
    """Trava assinatura e cobranca, nessa ordem, e devolve as duas. A
    cobranca e' lida antes so' para saber de quem e'."""
    barbearia_id = (
        Cobranca.objects.using(ALIAS)
        .filter(pk=cobranca_id, motivo=MotivoCobranca.MENSALIDADE)
        .values_list("barbearia_id", flat=True)
        .first()
    )
    if barbearia_id is None:
        raise RecusaDaMensalidade("Este pagamento já foi resolvido.")
    assinatura = _travar_assinatura(barbearia_id)
    cobranca = Cobranca.objects.using(ALIAS).select_for_update().get(pk=cobranca_id)
    if cobranca.status != StatusCobranca.ABERTA or assinatura is None:
        raise RecusaDaMensalidade("Este pagamento já foi resolvido.")
    return assinatura, cobranca


def confirmar(cobranca_id, *, agora, como=ComoFoiPaga.MANUAL):
    """Marca paga e avanca o `paga_ate`. E' a mesma funcao que o vigia chama."""
    if como not in (ComoFoiPaga.MANUAL, ComoFoiPaga.VIGIA):
        raise ValueError(como)
    with transaction.atomic(using=ALIAS):
        assinatura, cobranca = _travar_aberta(cobranca_id)
        # Sem o aviso: e' ele que faria a barbearia parecer AGUARDANDO, e a
        # pergunta aqui e' se ela estava bloqueada pelas datas.
        bloqueada = leitura(
            assinatura.barbearia_id, agora=agora, considerar_aviso=False,
        ).situacao == Situacao.BLOQUEADA
        novo, dia = novo_paga_ate(
            paga_ate=assinatura.paga_ate,
            dia_de_vencimento=assinatura.dia_de_vencimento,
            estava_bloqueada=bloqueada,
            hoje=hoje_em_sao_paulo(agora),
        )
        assinatura.paga_ate, assinatura.dia_de_vencimento = novo, dia
        assinatura.save(using=ALIAS, update_fields=["paga_ate", "dia_de_vencimento"])

        cobranca.status = StatusCobranca.PAGA
        cobranca.paga_em = agora
        cobranca.como_foi_paga = como
        cobranca.paga_ate_depois = novo
        cobranca.save(using=ALIAS, update_fields=[
            "status", "paga_em", "como_foi_paga", "paga_ate_depois",
        ])
        _avisar_o_dono(
            assinatura.barbearia_id,
            lambda nome: mensagens.msg_mensalidade_confirmada(nome, novo),
        )
        return cobranca


def recusar(cobranca_id, *, agora):
    """O dono nao achou o Pix: o aviso cai, a cobranca continua aberta."""
    with transaction.atomic(using=ALIAS):
        assinatura, cobranca = _travar_aberta(cobranca_id)
        if cobranca.informada_em is None:
            raise RecusaDaMensalidade("Não há aviso de pagamento para recusar.")
        cobranca.informada_em = None
        cobranca.informada_por_id = None
        cobranca.recusada_em = agora
        cobranca.save(using=ALIAS, update_fields=[
            "informada_em", "informada_por", "recusada_em",
        ])
        _avisar_o_dono(assinatura.barbearia_id, mensagens.msg_mensalidade_recusada)
        return cobranca


def cancelar_aberta(barbearia_id):
    """A cobranca aberta deixa de valer, mesmo ja avisada: a barbearia ficou
    isenta, foi desativada ou o admin mudou o `paga_ate` na mao — o ciclo
    daquela cobranca acabou. O centavo dela volta a ficar livre."""
    _abertas_da_mensalidade(barbearia_id).update(status=StatusCobranca.CANCELADA)


def registrar_manual(barbearia_id, *, paga_ate, valor_centavos, observacao="", agora):
    """Dinheiro, Pix sem aviso: o dono diz ate quando esta pago. A cobranca
    aberta do ciclo deixa de valer, e o centavo dela volta a ficar livre."""
    with transaction.atomic(using=ALIAS):
        assinatura = _travar_assinatura(barbearia_id)
        if assinatura is None:
            raise RecusaDaMensalidade("Esta barbearia não tem assinatura.")
        _abertas_da_mensalidade(barbearia_id).update(status=StatusCobranca.CANCELADA)
        cobranca = Cobranca.objects.using(ALIAS).create(
            barbearia_id=barbearia_id,
            motivo=MotivoCobranca.MENSALIDADE,
            chave_pix=pix.normalizar_chave(settings.PIX_CHAVE),
            valor_base_centavos=valor_centavos,
            valor_centavos=valor_centavos,
            copia_e_cola="",
            status=StatusCobranca.PAGA,
            paga_em=agora,
            como_foi_paga=ComoFoiPaga.REGISTRO,
            paga_ate_depois=paga_ate,
            observacao=observacao,
        )
        assinatura.paga_ate = paga_ate
        assinatura.dia_de_vencimento = dia_de_vencimento_para(paga_ate)
        assinatura.save(using=ALIAS, update_fields=["paga_ate", "dia_de_vencimento"])
        return cobranca
