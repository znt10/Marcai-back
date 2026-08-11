import uuid

import pytest
from django.db import connections


# O banco de teste ja existe (init-db.sql cria o brutus_test) e ja esta migrado
# (o Prisma o migra via DATABASE_URL_TEST, do lado do front). Se deixassemos o
# pytest-django cria-lo, ele nasceria SEM tabela nenhuma, porque os models sao
# managed=False — e o sintoma seria "relation Barbearia does not exist" num
# banco que existe e esta cheio.
@pytest.fixture(scope="session")
def django_db_setup():
    pass


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
                'TRUNCATE TABLE "Agendamento", "Cliente", "Bloqueio", '
                '"HorarioTrabalho", "BarbeiroServico", "Servico", "Barbeiro", '
                '"Barbearia" RESTART IDENTITY CASCADE'
            )
    yield


@pytest.fixture
def cenario():
    """Duas barbearias com um barbeiro cada. Duas, e nao uma, porque o unico
    teste de isolamento que vale alguma coisa e o que tem de quem se isolar.

    id e barbearia_id entram como `str(uuid.uuid4())`, nao como `uuid.uuid4()`
    puro: os campos sao TextField (a coluna do Prisma e TEXT, nao uuid — ver
    tenant/models.py), e um objeto `uuid.UUID` faria o psycopg3 mandar o
    parametro tipado como `uuid`, reabrindo contra a propria fixture o mesmo
    descasamento texto/uuid que o TextField foi feito para evitar.
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
