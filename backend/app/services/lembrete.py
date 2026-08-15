from datetime import datetime, timedelta

from tenant.config import LEMBRETE_ANTECEDENCIA_MIN


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
