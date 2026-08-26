import base64

from django.core.management.base import BaseCommand

from app.services.senha import gerar


class Command(BaseCommand):
    """Substitui o `npm run admin:hash` do front, apagado na fatia 8.

    Mora aqui porque e' aqui que o argon2 passou a viver (`argon2-cffi`; o
    `@node-rs/argon2` saiu junto com o Prisma) e porque a variavel que ele
    gera e' lida por `app/services/admin_senha.py`. Sem ele, girar a senha do
    admin exigiria escrever Python a mao.
    """

    help = 'Gera a linha ADMIN_SENHA_HASH_B64 do .env a partir de uma senha.'

    def add_arguments(self, parser):
        parser.add_argument("senha", help="A senha em claro do admin da plataforma.")

    def handle(self, *args, **opcoes):
        # BASE64, e nao o hash em claro: ele e' `$argon2id$v=19$m=...`, e tanto
        # o Compose quanto o dotenv expandem `$argon2id` e `$v` como variavel.
        # O valor chegaria truncado ao processo e a senha nunca conferiria.
        bruto = gerar(opcoes["senha"])
        b64 = base64.b64encode(bruto.encode("utf-8")).decode("ascii")
        self.stdout.write(f'ADMIN_SENHA_HASH_B64="{b64}"')
