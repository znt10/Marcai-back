import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from app.services.senha import gerar
from tenant.identidade import normalizar_login
from tenant.models import PapelUsuario, Usuario


class Command(BaseCommand):
    """O UNICO jeito de nascer o primeiro `Usuario(ADMIN)`.

    E o analogo do `createsuperuser`, escrito a mao porque
    `django.contrib.auth` esta fora do INSTALLED_APPS de proposito (o admin de
    fabrica dele enxergaria toda barbearia, o oposto do RLS deste banco).

    Antes da fatia 3 nao havia o que criar: o admin era um par de variaveis de
    ambiente (`ADMIN_USUARIO` e `ADMIN_SENHA_HASH_B64`), e "criar o admin" era
    editar um `.env` e reiniciar. O hash ia em BASE64 porque o argon2 em claro
    tem `$` e tanto o dotenv quanto o Compose o expandiam como variavel,
    truncando o valor sem avisar. Nada disso existe mais.
    """

    help = "Cria o primeiro Usuario(ADMIN) da plataforma."

    def add_arguments(self, parser):
        parser.add_argument("--login", required=True)
        parser.add_argument(
            "--senha",
            help=(
                "Omita para digitar sem eco. Passar por argumento deixa a senha "
                "no historico do shell e na lista de processos."
            ),
        )

    def handle(self, *args, **opcoes):
        login = normalizar_login(opcoes["login"])
        if not login:
            raise CommandError("O login nao pode ser vazio.")

        senha = opcoes.get("senha") or getpass.getpass("Senha do admin: ")
        if not senha:
            raise CommandError("A senha nao pode ser vazia.")

        # `using("admin")`: o papel `brutus_admin` e o unico que alcanca a linha
        # de `barbearia_id IS NULL` (politica `admin_da_plataforma`). Por
        # `default` (brutus_app) o INSERT morreria no WITH CHECK de
        # `tenant_isolation`, que compara com uma variavel de sessao vazia.
        try:
            criado = Usuario.objects.using("admin").create(
                login=login,
                papel=PapelUsuario.ADMIN,
                barbearia=None,
                senha_hash=gerar(senha),
            )
        except IntegrityError as e:
            # `login` e unico no sistema inteiro, entao isto tambem dispara se
            # o valor ja pertence ao dono de alguma barbearia. Dizer "ja existe"
            # sem afirmar QUAL das duas coisas e' de proposito: este comando roda
            # no terminal de quem opera a plataforma, mas a mensagem dele acaba
            # em log.
            raise CommandError(f"Nao foi possivel criar: login '{login}' ja existe.") from e

        self.stdout.write(self.style.SUCCESS(f"Admin criado: {criado.login}"))
