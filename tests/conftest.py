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
    """Mesmo TRUNCATE do tests/setup.ts do front, e pelo mesmo motivo: cada
    caso recria a barbearia com um uuid novo, e sobra de caso anterior faz o
    RLS filtrar tudo com sintoma de 'nao encontrado'.

    Roda como `owner` porque `brutus_app` nao tem direito de TRUNCATE.

    So toca o banco se o proprio teste pediu banco (`django_db`): sem essa
    guarda, o autouse tenta abrir conexao no teardown de QUALQUER teste do
    modulo — inclusive test_slug.py e test_ambiente.py, que nao usam banco —
    e o pytest-django bloqueia com "Database access not allowed", quebrando
    suite que passava antes desta fixture existir.
    """
    yield
    if request.node.get_closest_marker("django_db") is None:
        return
    with connections["owner"].cursor() as cur:
        cur.execute(
            'TRUNCATE TABLE "Agendamento", "Cliente", "Bloqueio", '
            '"HorarioTrabalho", "BarbeiroServico", "Servico", "Barbeiro", '
            '"Barbearia" RESTART IDENTITY CASCADE'
        )


@pytest.fixture
def cenario():
    """Duas barbearias com um barbeiro cada. Duas, e nao uma, porque o unico
    teste de isolamento que vale alguma coisa e o que tem de quem se isolar.
    """
    from tenant.models import Barbearia, Barbeiro

    dados = {}
    for slug, nome in (("brutus", "Brutus"), ("dontony", "Dom Tony")):
        b = Barbearia.objects.using("owner").create(
            id=uuid.uuid4(),
            slug=slug,
            nome=nome,
            endereco="Rua Aurora, 88",
            horario_resumo=None,
            whatsapp_contato="11999998888",
            ativo=True,
            criado_em="2026-08-11T12:00:00Z",
        )
        Barbeiro.objects.using("owner").create(
            id=uuid.uuid4(),
            barbearia_id=b.id,
            nome=f"Barbeiro da {nome}",
            whatsapp="11911112222",
            ativo=True,
        )
        dados[slug] = b
    return dados
