from contextlib import contextmanager

from django.db import connection, transaction


@contextmanager
def com_barbearia(barbearia_id):
    """Executa o bloco com o RLS apontando para `barbearia_id`.

    O terceiro argumento `true` de set_config e is_local: a variavel morre com
    a TRANSACAO. Com `false` ela viveria na SESSAO — e como a conexao volta
    para a pool, o proximo pedido herdaria este tenant. Vazamento cruzado,
    intermitente, dependente de temporizacao. Nunca trocar para `false`.

    O `atomic` nao e zelo: o set_config PRECISA rodar na mesma transacao das
    consultas. Sem ele, em autocommit, cada statement e a sua propria
    transacao e a variavel morre antes da primeira consulta — o sintoma sai
    como 'nao encontrado' em tudo.
    """
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.barbearia_id', %s, true)",
                [str(barbearia_id)],
            )
        yield
