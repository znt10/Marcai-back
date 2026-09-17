"""Duas mensagens do mesmo numero nao podem andar a conversa ao mesmo tempo.

As duas conexoes (`default` e `owner`) sao SESSOES diferentes do Postgres,
entao uma prova a trava que a outra segura — que e' a situacao real de dois
workers do Celery.
"""

import pytest
from django.db import OperationalError, connections

from app.services.trava_conversa import trava_da_conversa

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _tentar_de_outra_sessao(chave):
    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [chave])
        conseguiu = cur.fetchone()[0]
        if conseguiu:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])
    return conseguiu


def test_enquanto_segura_ninguem_mais_pega(cenario):
    b = cenario["brutus"]
    with trava_da_conversa(str(b.id), "83988887777"):
        assert _tentar_de_outra_sessao(f"{b.id}:83988887777") is False
    assert _tentar_de_outra_sessao(f"{b.id}:83988887777") is True


def test_outro_numero_nao_espera(cenario):
    b = cenario["brutus"]
    with trava_da_conversa(str(b.id), "83988887777"):
        assert _tentar_de_outra_sessao(f"{b.id}:83911112222") is True


def test_o_mesmo_numero_noutra_barbearia_nao_espera(cenario):
    with trava_da_conversa(str(cenario["brutus"].id), "83988887777"):
        assert _tentar_de_outra_sessao(f"{cenario['dontony'].id}:83988887777") is True


def test_solta_mesmo_quando_o_bloco_explode(cenario):
    b = cenario["brutus"]
    with pytest.raises(RuntimeError):
        with trava_da_conversa(str(b.id), "83988887777"):
            raise RuntimeError("boom")
    assert _tentar_de_outra_sessao(f"{b.id}:83988887777") is True


def test_espera_estourada_levanta_em_vez_de_travar_o_worker(cenario):
    b = cenario["brutus"]
    chave = f"{b.id}:83988887777"
    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
    try:
        with pytest.raises(OperationalError):
            with trava_da_conversa(str(b.id), "83988887777", espera_s=0.2):
                pass
    finally:
        with connections["owner"].cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])
