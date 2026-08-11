import pytest


# O banco de teste ja existe (init-db.sql cria o brutus_test) e ja esta migrado
# (o Prisma o migra via DATABASE_URL_TEST, do lado do front). Se deixassemos o
# pytest-django cria-lo, ele nasceria SEM tabela nenhuma, porque os models sao
# managed=False — e o sintoma seria "relation Barbearia does not exist" num
# banco que existe e esta cheio.
@pytest.fixture(scope="session")
def django_db_setup():
    pass
