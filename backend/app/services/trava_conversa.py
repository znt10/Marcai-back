"""Uma conversa do bot por vez, por numero.

Trava CONSULTIVA do Postgres, e nao `select_for_update`: a conversa atravessa
varias transacoes (`marcar` e `cancelar_publico` abrem as proprias, e
`com_barbearia` nao pode ser aninhado), e uma trava de linha morreria no fim
da primeira. A consultiva vive na CONEXAO e segura ler, decidir, marcar,
responder e gravar.

Sem ela, "1" e "2" mandados com meio segundo de diferenca viram duas tasks que
leem o mesmo estado e avancam as duas.
"""

from contextlib import contextmanager

from django.db import connection

from tenant.config import BOT_ESPERA_TRAVA_S


@contextmanager
def trava_da_conversa(barbearia_id: str, whatsapp: str, *, espera_s: float = BOT_ESPERA_TRAVA_S):
    chave = f"{barbearia_id}:{whatsapp}"
    with connection.cursor() as cur:
        # `lock_timeout` vale para trava consultiva tambem. Sem ele, um worker
        # preso numa conversa travada ficaria parado para sempre. RESET logo
        # em seguida: a conexao volta para a pool e o proximo uso nao pode
        # herdar o limite.
        cur.execute(f"SET lock_timeout = '{int(espera_s * 1000)}ms'")
        try:
            cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
        finally:
            cur.execute("RESET lock_timeout")
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])
