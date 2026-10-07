"""O que o painel da barbearia sabe sobre o WhatsApp dela, desde a etapa 1
do numero central (spec 2026-10-06): o texto pronto da saudacao, com o link,
quantas mensagens de cliente nao sairam e a hora da lista do dia da equipe. Nao ha mais QR nem estado de
conexao — o numero da barbearia nao fica ligado a nada.

`desconectar` e `ligar_bot` ficam para quando o numero da barbearia voltar a
ser conectado (etapa 2, API oficial).
"""

from django.utils import timezone

from tenant import config
from tenant.models import (
    EstadoInstancia,
    MensagemNaoEnviada,
    PlanoBarbearia,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

from .convite import link_da_vitrine
from .lista_do_dia import HORAS_DA_LISTA_MIN, hora_da_lista
from .mensagens import msg_saudacao
from .whatsapp_instancias import aplicar_assinatura, desconectar_aparelho


def ver(barbearia) -> dict:
    with com_barbearia(barbearia.id):
        nao_enviadas = MensagemNaoEnviada.objects.filter(barbearia_id=barbearia.id).count()
    return {
        "saudacao": msg_saudacao(link=link_da_vitrine(barbearia.slug)),
        "naoEnviadas": nao_enviadas,
        "horaDaLista": hhmm(hora_da_lista(barbearia.id)),
        "horasDaLista": [hhmm(m) for m in HORAS_DA_LISTA_MIN],
    }


def hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def minutos_de(hora) -> int | None:
    """Converte "07:30" em 450. None para o que nao for "HH:MM" — a
    conferencia de que a hora e' uma das escolhiveis fica em
    `mudar_hora_da_lista`."""
    if not isinstance(hora, str) or len(hora) != 5 or hora[2] != ":":
        return None
    h, m = hora[:2], hora[3:]
    if not (h.isdigit() and m.isdigit()):
        return None
    return int(h) * 60 + int(m)


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
    # Desligar continua passando: e' o que leva uma linha velha a False.
    if ativo and not config.BOT_DISPONIVEL:
        return False
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False

    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
    if linha is None or linha.estado == EstadoInstancia.PENDENTE:
        return False

    # Ligar exige o aparelho CONECTADO: sem isso o bot ficaria "ativo"
    # respondendo para ninguem enquanto o dono ainda nem leu o QR. Desligar
    # continua permitido em qualquer estado que ja passava por aqui.
    if ativo and linha.estado != EstadoInstancia.CONECTADO:
        return False

    if not aplicar_assinatura(linha.nome, bot=ativo):
        return False

    with com_barbearia(barbearia.id):
        WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).update(
            bot_ativo=ativo, atualizado_em=timezone.now(),
        )
    return True
