import logging
from datetime import datetime, timezone

from celery import shared_task

from app.services.lembrete import enviar_pendentes
from app.services.whatsapp import estado_da_instancia
from app.services.zelador import alarmar_e_podar

logger = logging.getLogger(__name__)


@shared_task
def lembretes() -> int:
    """Substitui o `curl -X POST .../api/cron/lembretes` do `agendador`
    (docker-compose, antes da fatia 7). Chama `enviar_pendentes` DIRETO —
    sem HTTP — porque a tarefa roda dentro do mesmo processo Django: o
    salto por rota (com toda a via-crucis de `TenantMiddleware`,
    `ClienteMiddleware` e o `Host` forjado que o `agendador` precisava
    mandar) deixa de ser necessario pro disparo AGENDADO.

    A rota `POST /api/cron/lembretes` continua existindo, pro gancho
    manual/externo — e' seguro rodar as duas: `enviar_pendentes` e'
    idempotente por `lembrete_enviado_em`.
    """
    return enviar_pendentes(datetime.now(timezone.utc))


@shared_task
def whatsapp_healthcheck() -> str:
    """Substitui a metade `connectionState` do `agendador`. So' loga — a
    outra metade (o selo na tela do admin) e' card separado no Trello."""
    estado = estado_da_instancia()
    if estado != "open":
        logger.warning(
            "[agendador] !!! WHATSAPP FORA DO AR: %s — rode: npm run whatsapp:qr",
            estado,
        )
    return estado


@shared_task
def zelador() -> dict:
    """Substitui o `while true` de `docker/zelador.sh`."""
    return alarmar_e_podar()
