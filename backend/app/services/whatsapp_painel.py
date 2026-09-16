"""O que o painel da barbearia sabe sobre o proprio WhatsApp.

Uma regra manda em tudo aqui: **o QR e' so do dono; o ESTADO e de todo
mundo.** As duas metades tem peso igual. Com o QR na mao, um barbeiro liga o
WhatsApp da barbearia ao proprio celular e passa a receber a conversa de todo
cliente; sem o estado, ele passa a tarde sem entender por que ninguem
confirma. Por isso o papel filtra UM campo, e nao a rota inteira.
"""

import logging

from django.utils import timezone

from tenant.models import (
    EstadoInstancia,
    MensagemNaoEnviada,
    PlanoBarbearia,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

from .whatsapp_instancias import aplicar_assinatura, desconectar_aparelho, pedir_qr

logger = logging.getLogger(__name__)

# Os dois estados em que existe instancia viva do lado de la e ainda nao ha
# ninguem conectado — ou seja, em que pedir um QR novo faz sentido. `PENDENTE`
# fica de fora porque a instancia ainda nao existe na Evolution, e o pedido
# viria 404; quem resolve aquele caso e a conferencia periodica, criando-a.
ESTADOS_QUE_PEDEM_QR = (EstadoInstancia.AGUARDANDO_QR, EstadoInstancia.DESCONECTADO)


def ver(barbearia, papel: str) -> dict:
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        # Sem zap nao ha instancia, nao ha queda e nao ha mensagem retida — o
        # caminho de "nao enviadas" nem chega a gravar nesse plano. Zeros
        # explicitos, e nao campos ausentes: a tela le sempre as mesmas chaves.
        return {
            "plano": barbearia.plano,
            "estado": None,
            "numeroConectado": None,
            "desconectadoDesde": None,
            "qrBase64": None,
            "naoEnviadas": 0,
            "botAtivo": False,
        }

    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
        nao_enviadas = MensagemNaoEnviada.objects.filter(barbearia_id=barbearia.id).count()

    if linha is None:
        # Com zap e sem linha: plano trocado com o banco no meio do caminho. A
        # tela mostra "ainda preparando", que e a verdade — a conferencia
        # periodica nao conserta este caso (ela precisa da linha), mas trocar
        # o plano de novo conserta, e um 500 aqui nao ajudaria ninguem.
        logger.warning("[whatsapp-painel] barbearia %s com zap e sem linha", barbearia.id)
        return {
            "plano": barbearia.plano,
            "estado": EstadoInstancia.PENDENTE,
            "numeroConectado": None,
            "desconectadoDesde": None,
            "qrBase64": None,
            "naoEnviadas": nao_enviadas,
            "botAtivo": False,
        }

    eh_dono = papel == "DONO"
    qr = linha.qr_base64 if eh_dono else None

    # So o dono, e so quando falta: o QR chega sozinho pelo webhook o tempo
    # todo. Este caminho e para quem abre a tela depois de o ultimo ter
    # expirado — sem ele, a tela ficaria vazia para sempre e o dono nunca
    # conectaria. Pedir um QR que o barbeiro nao vai ver seria gastar rede
    # para produzir (e guardar) um segredo que ninguem pediu.
    if eh_dono and qr is None and linha.estado in ESTADOS_QUE_PEDEM_QR:
        qr = pedir_qr(linha.nome)
        if qr:
            with com_barbearia(barbearia.id):
                WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).update(
                    estado=EstadoInstancia.AGUARDANDO_QR,
                    qr_base64=qr,
                    atualizado_em=timezone.now(),
                )
            linha.estado = EstadoInstancia.AGUARDANDO_QR

    return {
        "plano": barbearia.plano,
        "estado": linha.estado,
        "numeroConectado": linha.numero_conectado,
        "desconectadoDesde": linha.desconectado_desde,
        "qrBase64": qr,
        "naoEnviadas": nao_enviadas,
        "botAtivo": linha.bot_ativo,
    }


def desconectar(barbearia) -> bool:
    """Trocar de celular. Faz logout SEM apagar a instancia — ela continua
    existindo e volta a gerar QR, que e' exatamente o que o dono precisa para
    ler o codigo no aparelho novo.

    Diferente de `apagar_instancia`, que e' saida do plano: la o vinculo acaba,
    aqui ele so' troca de dono.

    A linha volta a `AGUARDANDO_QR` na hora, sem esperar o webhook: quem
    clicou esta olhando para a tela, e o proximo `ver()` ja pede o QR novo.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False

    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
    if linha is None:
        return False

    desconectar_aparelho(linha.nome)

    with com_barbearia(barbearia.id):
        WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).update(
            estado=EstadoInstancia.AGUARDANDO_QR,
            qr_base64=None,
            numero_conectado=None,
            atualizado_em=timezone.now(),
        )
    return True


def ligar_bot(barbearia, ativo: bool) -> bool:
    """Liga ou desliga o atendimento automatico. A EVOLUTION PRIMEIRO.

    A lista de eventos mora na instancia, la. Gravar antes e aplicar depois
    abriria a janela em que o banco diz "ligado" e nenhuma mensagem chega —
    e se a aplicacao falhasse, a janela nunca fecharia. Falhou, nada muda.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False

    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
    if linha is None or linha.estado == EstadoInstancia.PENDENTE:
        return False

    if not aplicar_assinatura(linha.nome, bot=ativo):
        return False

    with com_barbearia(barbearia.id):
        WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).update(
            bot_ativo=ativo, atualizado_em=timezone.now(),
        )
    return True
