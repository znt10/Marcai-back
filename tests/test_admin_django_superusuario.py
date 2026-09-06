import os

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import override_settings

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _rodar():
    from io import StringIO

    saida = StringIO()
    call_command("criar_admin_django", stdout=saida)
    return saida.getvalue()


def test_cria_o_superusuario_a_partir_do_ambiente(monkeypatch):
    monkeypatch.setenv("ADMIN_USUARIO", "dono-teste")
    monkeypatch.setenv("ADMIN_SENHA", "senha-de-teste-longa")
    User.objects.filter(username="dono-teste").delete()

    with override_settings(DEBUG=True):
        _rodar()

    u = User.objects.get(username="dono-teste")
    assert u.is_superuser and u.is_staff
    assert u.check_password("senha-de-teste-longa")


def test_nao_troca_a_senha_de_quem_ja_existe(monkeypatch):
    """Roda a cada boot. Se trocasse a senha, desfaria em silencio o
    `changepassword` de quem mudou por algum motivo."""
    monkeypatch.setenv("ADMIN_USUARIO", "dono-teste")
    monkeypatch.setenv("ADMIN_SENHA", "a-senha-do-ambiente")
    User.objects.filter(username="dono-teste").delete()
    User.objects.create_superuser(username="dono-teste", email="", password="a-que-eu-escolhi")

    with override_settings(DEBUG=True):
        saida = _rodar()

    assert "ja existe" in saida
    assert User.objects.get(username="dono-teste").check_password("a-que-eu-escolhi")


def test_fora_de_debug_nao_cria_nada(monkeypatch):
    """Mesma trava de `semear`: um comando que cria conta de superusuario
    sozinho, no boot, e' uma porta que ninguem decidiu abrir em producao."""
    monkeypatch.setenv("ADMIN_USUARIO", "nao-devia-nascer")
    monkeypatch.setenv("ADMIN_SENHA", "seja-la-o-que-for")
    User.objects.filter(username="nao-devia-nascer").delete()

    with override_settings(DEBUG=False):
        _rodar()

    assert not User.objects.filter(username="nao-devia-nascer").exists()


def test_sem_senha_em_claro_nao_inventa_uma(monkeypatch):
    """Quem configurou producao com ADMIN_SENHA_HASH_B64 nao tem senha em
    claro para dar ao Django. Dizer o que falta e' melhor que criar uma conta
    com senha inventada, que ninguem saberia e ninguem apagaria."""
    monkeypatch.setenv("ADMIN_USUARIO", "so-o-hash")
    monkeypatch.delenv("ADMIN_SENHA", raising=False)
    User.objects.filter(username="so-o-hash").delete()

    with override_settings(DEBUG=True):
        saida = _rodar()

    assert "ADMIN_SENHA" in saida
    assert not User.objects.filter(username="so-o-hash").exists()
