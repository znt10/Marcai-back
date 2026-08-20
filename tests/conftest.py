import uuid

import pytest
from django.db import connections


# O banco de teste ja EXISTE — `init-db.sql` cria o `brutus_test` junto com o
# `brutus`, no mesmo volume. O que mudou na fatia 1 e quem o MIGRA: era o
# Prisma (via DATABASE_URL_TEST, do lado do front), e agora e este `migrate`.
#
# Continua sem deixar o pytest-django criar/derrubar banco, e agora ha um
# segundo motivo alem do primeiro: `brutus_owner` perdeu o CREATEDB junto com
# o Prisma (era do shadow database dele), entao nem daria. O caminho e migrar
# o banco que ja esta ali.
#
# `database="owner"` pelo mesmo motivo do entrypoint.sh: as duas conexoes
# apontam para o mesmo banco e o que muda e o papel. `brutus_app` (o default)
# nao tem direito de DDL, e as tabelas precisam nascer de `brutus_owner` para
# que o `ALTER DEFAULT PRIVILEGES` do init-db.sql conceda DML aos outros dois
# papeis.
#
# `migrate` e idempotente: numa segunda corrida ele le `django_migrations`, ve
# que nao ha nada a aplicar e sai. O que ele NAO faz e reconciliar um schema
# que mudou — depois de mexer num model, o banco de teste precisa ser
# derrubado e recriado (`docker compose down -v` da raiz).
@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    from django.core.management import call_command

    with django_db_blocker.unblock():
        call_command("migrate", "--noinput", database="owner", verbosity=0)


@pytest.fixture(scope="session", autouse=True)
def _sem_flush_no_teardown():
    """Desliga o `flush` que o pytest-django roda ao fim de cada teste
    `transaction=True`.

    Ele era inofensivo ate a fatia 1 por acidente: com todo model
    `managed=False`, o Django nao reconhecia tabela nenhuma como sua,
    `sql_flush()` devolvia lista vazia e o teardown nao fazia nada. Agora que o
    Django e dono do schema, o mesmo teardown gera `TRUNCATE` das oito tabelas
    — e o roda pela conexao `default`, que e `brutus_app`.

    `brutus_app` nao tem direito de TRUNCATE, e isso e deliberado, nao uma
    lacuna a preencher: o papel do runtime nao deve conseguir esvaziar tabela.
    Conceder o direito so para o teste passar enfraqueceria em producao a
    separacao que o `init-db.sql` monta de proposito.

    O que se perde ao desligar e nada: `limpar_banco` (abaixo) ja TRUNCA as
    mesmas tabelas, como `owner`, e na ENTRADA de cada teste — que e a ordem
    mais robusta, pelo motivo que o docstring dele explica.
    """
    from django.test import TransactionTestCase

    TransactionTestCase._fixture_teardown = lambda self: None


@pytest.fixture(autouse=True)
def limpar_banco(request):
    """Mesmo `beforeEach(limparBanco)` do tests/setup.ts do front (admin-convite,
    admin-criar-barbearia, admin-listar, admin-papel, admin-tenant,
    api-agendar), e pelo mesmo motivo: cada caso recria a barbearia com um id
    novo, e sobra de caso anterior faz o RLS filtrar tudo com sintoma de 'nao
    encontrado'.

    Limpa na ENTRADA, e nao no fim (TRUNCATE antes do `yield`), porque limpar
    so no fim nao se cura sozinho: se a corrida morre antes do TRUNCATE final
    — crash, Ctrl-C, `--maxfail` — o banco fica sujo e a PROXIMA corrida falha
    em dado que nao criou. Foi exatamente essa UniqueViolation em
    `Barbearia_slug_key` que apareceu na primeira execucao desta fixture.

    Roda como `owner` porque `brutus_app` nao tem direito de TRUNCATE.

    A guarda cobre marker E fixture de banco: `django_db_helper` (fixtures.py
    do pytest-django) libera conexao tanto por marker quanto por um teste
    pedir `db`/`transactional_db` direto (`def test_x(db, cenario)`, sem
    decorator nenhum) — um guarda que so olhasse o marker deixaria passar
    batido exatamente esse caso, sem TRUNCATE e sem aviso.
    """
    if request.node.get_closest_marker("django_db") or {"db", "transactional_db"} & set(
        request.fixturenames
    ):
        with connections["owner"].cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE tenant_agendamento, tenant_cliente, "
                "tenant_bloqueio, tenant_horariotrabalho, "
                "tenant_barbeiroservico, tenant_servico, tenant_barbeiro, "
                # `tenant_usuario` entre barbeiro e barbearia: o perfil aponta
                # para a identidade, e a identidade para a barbearia. O CASCADE
                # resolveria a ordem sozinho, mas listar todas deixa explicito
                # o que esta sendo esvaziado — uma tabela ESQUECIDA aqui nao da
                # erro, vaza para o teste seguinte.
                "tenant_usuario, "
                "tenant_barbearia RESTART IDENTITY CASCADE"
            )

        from tenant.middleware import _limpar_cache_tenant

        _limpar_cache_tenant()
    yield


@pytest.fixture
def cenario():
    """Duas barbearias com um barbeiro cada. Duas, e nao uma, porque o unico
    teste de isolamento que vale alguma coisa e o que tem de quem se isolar.

    O `str(uuid.uuid4())` sobreviveu a fatia 1 sem precisar mudar, mas por um
    motivo NOVO. Antes ele era obrigatorio: os campos eram TextField sobre
    coluna TEXT, e passar um `uuid.UUID` puro faria o psycopg mandar o
    parametro tipado como `uuid` contra uma coluna de texto. Agora a coluna e
    `uuid` de verdade e os dois funcionam — UUIDField converte a string na
    entrada. Fica como esta porque a fatia 1 nao mexe em teste que ja passa.
    """
    from tenant.models import Barbearia, Barbeiro

    dados = {}
    for slug, nome in (("brutus", "Brutus"), ("dontony", "Dom Tony")):
        b = Barbearia.objects.using("owner").create(
            id=str(uuid.uuid4()),
            slug=slug,
            nome=nome,
            endereco="Rua Aurora, 88",
            horario_resumo=None,
            whatsapp_contato="11999998888",
            ativo=True,
            criado_em="2026-08-11T12:00:00Z",
        )
        Barbeiro.objects.using("owner").create(
            id=str(uuid.uuid4()),
            barbearia_id=b.id,
            nome=f"Barbeiro da {nome}",
            whatsapp="11911112222",
            ativo=True,
        )
        dados[slug] = b
    return dados
