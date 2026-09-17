from datetime import datetime, timedelta

from django.utils import timezone

from tenant.config import LEMBRETE_ANTECEDENCIA_MIN
from tenant.models import (
    Agendamento,
    Barbearia,
    EstadoInstancia,
    PlanoBarbearia,
    TipoMensagem,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

from .mensagens import msg_lembrete
from .whatsapp import enviar_ao_cliente


def lembrete_ao_criar(inicio: datetime, agora: datetime) -> datetime | None:
    """O valor de `lembrete_enviado_em` com que um agendamento NASCE. Porte
    de `lembreteAoCriar`.

    Marcar um horario ja dentro da janela do lembrete manda duas mensagens em
    minutos: a confirmacao e, no proximo tique do agendador, um "Lembrete:" do
    que a pessoa acabou de fazer. Nao e' hipotese — o painel marca a 30
    minutos de antecedencia por padrao, entao todo encaixe de balcao
    produziria isso.

    A correcao e' de CONCEITO: dentro da janela, a confirmacao JA e' o
    lembrete. O agendamento nasce avisado e o cron nunca o ve.
    """
    dentro_da_janela = inicio <= agora + timedelta(minutes=LEMBRETE_ANTECEDENCIA_MIN)
    return agora if dentro_da_janela else None


def enviar_pendentes(agora: datetime) -> int:
    """POST /api/cron/lembretes — o motor que o `agendador` chama a cada
    tique. `Barbearia` esta FORA do RLS (lida direto, sem `com_barbearia`);
    `Agendamento` nao, entao cada tenant precisa da propria consulta
    escopada — mesmo laco tenant-a-tenant que o bloco B (admin) ja usa.
    """
    limite = agora + timedelta(minutes=LEMBRETE_ANTECEDENCIA_MIN)
    enviados = 0

    for b in Barbearia.objects.filter(ativo=True):
        with com_barbearia(b.id):
            pendentes = list(
                Agendamento.objects.filter(
                    status="CONFIRMADO", lembrete_enviado_em__isnull=True,
                    inicio__gt=agora, inicio__lte=limite,
                ).select_related("barbeiro", "cliente")
            )
            instancia = WhatsappInstancia.objects.filter(barbearia_id=b.id).first()

        # Pelo bot so' com tudo de pe: plano com zap, bot ligado e conectado.
        # Qualquer outro caso segue `enviar_ao_cliente`, que ja sabe registrar
        # a "nao enviada" quando o numero esta fora do ar.
        pelo_bot = (
            b.plano == PlanoBarbearia.COM_ZAP
            and instancia is not None
            and instancia.bot_ativo
            and instancia.estado == EstadoInstancia.CONECTADO
        )

        for a in pendentes:
            # MARCA antes de mandar, numa transacao PROPRIA por agendamento —
            # igual ao route.ts (uma `comBarbearia` so' pro update, separada
            # da leitura). Se o processo morrer no meio do laco, so' os que
            # ja' COMMITARAM ficam marcados — exatamente os que ja' saíram
            # pelo WhatsApp. Acumular tudo na mesma transacao da leitura
            # desalinharia as duas coisas: `enviar_texto` e' fire-and-forget
            # e nao espera commit nenhum, entao uma mensagem podia sair e o
            # commit correspondente nunca chegar a acontecer.
            with com_barbearia(b.id):
                Agendamento.objects.filter(id=a.id).update(lembrete_enviado_em=timezone.now())
            texto = msg_lembrete(
                servico_nome=a.servico_nome, barbeiro_nome=a.barbeiro.nome,
                inicio=a.inicio, endereco=b.endereco,
            )
            if pelo_bot:
                # Import tardio: bot -> agendamentos -> lembrete.
                from .bot import enviar_lembrete_pelo_bot

                enviar_lembrete_pelo_bot(
                    str(b.id), instancia.nome, a.cliente.whatsapp, a.codigo, texto, agora,
                )
            else:
                enviar_ao_cliente(
                    b, a.cliente.whatsapp, texto,
                    tipo=TipoMensagem.LEMBRETE, cliente_nome=a.cliente.nome,
                )
            enviados += 1

    return enviados
