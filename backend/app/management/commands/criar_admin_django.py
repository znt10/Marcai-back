import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """O superusuario do admin do Django, criado sozinho ao subir o projeto.

    Sem isto, todo `docker compose down -v` levava junto o `auth_user` e o
    admin voltava inalcancavel — a tela pedia um login que nao existia mais, e
    o conserto era um `createsuperuser` a mao que ninguem lembra na hora.

    ## Por que as MESMAS credenciais do painel da plataforma

    Entrar no admin do Django ja' custa dois logins: o cookie `sessao_admin`
    abre a porta e o login do Django entra. Sao dois de proposito (portas
    diferentes, mecanismos diferentes), mas nada obriga a serem duas SENHAS
    diferentes — as duas contas pertencem a mesma pessoa, o dono da
    plataforma. Reusar `ADMIN_USUARIO`/`ADMIN_SENHA` tira a segunda senha de
    circulacao sem juntar os dois mecanismos.

    ## Por que so' com DEBUG

    Mesma trava de `semear` e `semear_movimento`, e pelo mesmo motivo: em
    producao a senha do admin costuma entrar por `ADMIN_SENHA_HASH_B64` (hash),
    e um comando que criasse conta de superusuario sozinho, no boot, e' uma
    porta que ninguem decidiu abrir. La' o `createsuperuser` continua sendo a
    mao, uma vez.

    NAO troca a senha de um usuario que ja' existe. Quem mudou a senha a mao
    mudou por algum motivo, e um comando que roda a cada boot desfazendo isso
    seria pior que nao existir.
    """

    help = "Cria (uma vez) o superusuario do admin do Django, a partir de ADMIN_USUARIO/ADMIN_SENHA."

    def handle(self, *args, **opcoes):
        if not settings.DEBUG:
            self.stdout.write("[admin-django] fora de DEBUG: crie com `createsuperuser`.")
            return

        usuario = os.environ.get("ADMIN_USUARIO") or ""
        senha = os.environ.get("ADMIN_SENHA") or ""

        if not usuario or not senha:
            # Acontece de verdade: o compose permite subir sem admin
            # configurado, e quem usa so' `ADMIN_SENHA_HASH_B64` nao tem a
            # senha em claro para dar ao Django. Dizer o que falta e' melhor
            # que criar uma conta com senha inventada.
            faltando = "ADMIN_USUARIO" if not usuario else "ADMIN_SENHA (em claro)"
            self.stdout.write(
                f"[admin-django] sem {faltando} no ambiente — nenhum superusuario criado."
            )
            return

        existente = User.objects.filter(username=usuario).first()
        if existente:
            self.stdout.write(f"[admin-django] '{usuario}' ja existe; senha intacta.")
            return

        User.objects.create_superuser(username=usuario, email="", password=senha)
        self.stdout.write(f"[admin-django] superusuario '{usuario}' criado.")
