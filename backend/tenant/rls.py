from contextlib import contextmanager

from django.db import connection, connections, transaction


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

    `durable=True`, e nao `atomic()` liso: `atomic()` aninhado dentro de outro
    `atomic()` nao abre transacao nova, abre SAVEPOINT — e o Postgres mantem o
    `SET LOCAL` vivo depois do `RELEASE SAVEPOINT`. Sair do bloco de dentro
    NAO devolveria o tenant de fora; o resto do bloco externo passaria a ler e
    escrever como o tenant de dentro, dado com cara de certo, da barbearia
    errada, sem erro nenhum. `durable=True` troca essa troca de tenant em
    silencio por `RuntimeError` alto no ponto da chamada aninhada, restaurando
    a garantia que o lado TypeScript tinha de graca: `comBarbearia` chamava
    `prisma.$transaction` no cliente de topo, e uma chamada aninhada abria
    conexao independente da pool, sem como sobrescrever o tenant de fora.

    Ressalva que nao e obvia: o Django ISENTA da checagem de durabilidade os
    atomics que o `TestCase`/`transaction=False` abrem por baixo dos panos.
    `durable=True` protege producao (views, tasks, servicos), mas NAO protege
    um teste nao-transacional sozinho — quem protege ali e a regra separada de
    usar `transaction=True` no marcador `django_db`. As duas coisas trabalham
    juntas; nenhuma das duas basta sozinha.
    """
    if not barbearia_id:
        # str(None) vira a string 'None', que nao casa com id nenhum: o
        # sintoma seria "nao encontrado" bem longe da causa real (chamador
        # esqueceu de passar o id). Falhar aqui aponta pro lugar certo.
        raise ValueError("com_barbearia precisa de um barbearia_id")

    with transaction.atomic(durable=True):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.barbearia_id', %s, true)",
                [str(barbearia_id)],
            )
        yield


@contextmanager
def com_barbearia_admin(barbearia_id):
    """Irma de `com_barbearia` acima — o MESMO contrato (RLS por transacao,
    `durable=True` pelo mesmo motivo), so' que na conexao `"admin"` (papel
    `brutus_admin`) em vez de `"default"` (`brutus_app`).

    O admin da plataforma continua sujeito ao RLS em toda tabela de tenant —
    nao ha `BYPASSRLS` (spec do admin, §5). O que ele tem a mais e' um GRANT
    de INSERT/UPDATE em `Barbearia`, que `brutus_app` nao tem de proposito.
    E' por isso que criar barbearia/dono e trocar `ativo` precisam desta
    conexao, mas contar barbeiros/agendamentos por tenant (que so' precisa de
    SELECT, ja concedido aos dois papeis) tambem passa por aqui: uma unica
    conexao admin por request e' mais simples que alternar entre as duas.
    """
    if not barbearia_id:
        raise ValueError("com_barbearia_admin precisa de um barbearia_id")

    with transaction.atomic(using="admin", durable=True):
        with connections["admin"].cursor() as cur:
            cur.execute(
                "SELECT set_config('app.barbearia_id', %s, true)",
                [str(barbearia_id)],
            )
        yield


@contextmanager
def com_barbearia_por_requisicao(barbearia_id):
    """Irma das duas acima, para o admin do Django (spec de 06/09/2026).

    Mesma conexao que `com_barbearia` (`default`, papel `brutus_app` — menor
    privilegio: ele nao escreve em `tenant_barbearia` e nao precisa). O que
    muda e' a DURABILIDADE.

    `durable=True` existe nas outras duas para estourar alto quando alguem
    aninha wrapper de tenant — dentro de um bloco durable, um segundo `atomic`
    viraria SAVEPOINT, e sair dele NAO devolveria o tenant de fora. Aqui a
    transacao envolve a REQUISICAO inteira do admin, que passa por codigo do
    Django (formulario, permissao, log de acao) capaz de abrir os seus
    proprios blocos. Exigir durabilidade aqui transformaria uso normal do
    admin em RuntimeError.

    O que NAO muda, e e' o que importa: `is_local=true` no `set_config`. A
    variavel morre com a transacao, e a conexao volta para a pool limpa.
    """
    if not barbearia_id:
        raise ValueError("com_barbearia_por_requisicao precisa de um barbearia_id")

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.barbearia_id', %s, true)",
                [str(barbearia_id)],
            )
        yield
