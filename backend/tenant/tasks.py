from celery import shared_task


@shared_task
def ping() -> str:
    """A tarefa que existe para provar que o worker executa.

    Ela nao serve ao produto e nao deve crescer: quando a fatia 7 trouxer o
    lembrete, o healthcheck do WhatsApp e a poda do zelador, esta some. O que
    ela garante ate la e que `worker` e `beat` no compose nao sao enfeite —
    que o broker responde, que a tarefa foi descoberta e que a agenda dispara.
    """
    return "pong"
