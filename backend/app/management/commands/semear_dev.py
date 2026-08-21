import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SLUG_PRINCIPAL = "brutus"
SLUG_SEGUNDO = "dontony"

# Nove as sete, todo dia. Nao e realista, e e de proposito: o que a semente tem
# de garantir e que SEMPRE exista horario livre, em qualquer dia que voce abrir.
# Expediente parcial faria a home aparecer vazia numa segunda de manha e isso
# passaria por bug.
ABRE_MIN = 9 * 60
FECHA_MIN = 19 * 60


class Command(BaseCommand):
    """O cenario minimo para o sistema ser CLICAVEL depois de um `down -v`.

    Sem isto, um banco recem-migrado tem zero linhas e a primeira tela util
    esta a uns dez minutos de trabalho manual: criar admin, entrar, cadastrar
    barbearia, abrir o convite, definir senha, cadastrar barbeiro, abrir o
    convite dele, criar servico, vincular aos dois e definir expediente. Foi
    exatamente essa sequencia que a travessia da fatia 5 fez a mao.

    Chama os MESMOS servicos que as telas chamam, em vez de montar INSERT
    proprio. E o que impede a semente de virar uma segunda definicao de como
    uma barbearia nasce, que envelhece em silencio enquanto a de verdade muda —
    e de quebra, se um servico passar a exigir campo novo, a semente quebra
    junto e avisa.

    Idempotente: se a barbearia principal ja existe, nao faz nada. Roda a cada
    boot pelo entrypoint, e um `docker compose restart` nao pode duplicar nada
    nem derrubar a senha de quem ja estava usando.
    """

    help = "Cria admin + cenario de demonstracao. So em DEBUG."

    def add_arguments(self, parser):
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Semeia mesmo se a barbearia principal ja existir (nao apaga nada).",
        )

    def handle(self, *args, **opcoes):
        # A trava que faz a senha padrao ser aceitavel. Sem ela, a mesma
        # configuracao que e comoda aqui vira credencial conhecida no primeiro
        # ambiente exposto que subir este compose — e ninguem percebe, porque
        # nada quebra.
        if not settings.DEBUG:
            raise CommandError(
                "semear_dev so roda com DJANGO_DEBUG=1. Em producao o admin "
                "nasce pelo `manage.py criar_admin`, que pede a senha sem eco."
            )

        # `or`, e nao o default do `.get()`: o compose passa
        # `${SEMENTE_ADMIN_LOGIN:-}`, que define a variavel como string VAZIA
        # quando ela nao esta no `.env`. A chave existe, entao o default do
        # `.get()` nunca entraria — e o admin nasceria com login vazio, que o
        # banco aceita (`login` e unico, nao NOT-blank) e ninguem consegue usar.
        login = os.environ.get("SEMENTE_ADMIN_LOGIN") or "admin"
        senha = os.environ.get("SEMENTE_ADMIN_SENHA") or "dev12345"

        self._semear_admin(login, senha)

        from tenant.models import Barbearia

        if Barbearia.objects.using("owner").filter(slug=SLUG_PRINCIPAL).exists():
            if not opcoes["forcar"]:
                self.stdout.write(f"[semear_dev] '{SLUG_PRINCIPAL}' ja existe; nada a fazer.")
                return
            self.stdout.write("[semear_dev] --forcar: semeando por cima.")

        self._semear_cenario(senha)
        self._resumo(login, senha)

    # ------------------------------------------------------------------ admin

    def _semear_admin(self, login, senha):
        from app.services.senha import gerar
        from tenant.identidade import normalizar_login
        from tenant.models import PapelUsuario, Usuario

        # `using("admin")`: o papel `brutus_admin` e o unico que alcanca a linha
        # de `barbearia_id IS NULL` (politica `admin_da_plataforma`).
        if Usuario.objects.using("admin").filter(papel=PapelUsuario.ADMIN).exists():
            self.stdout.write("[semear_dev] admin ja existe; senha preservada.")
            return

        Usuario.objects.using("admin").create(
            login=normalizar_login(login),
            papel=PapelUsuario.ADMIN,
            barbearia=None,
            senha_hash=gerar(senha),
        )
        self.stdout.write(f"[semear_dev] admin '{login}' criado.")

    # ---------------------------------------------------------------- cenario

    def _semear_cenario(self, senha):
        from app.services import admin_barbearias, barbeiro_servicos, equipe, horarios, servicos

        principal = admin_barbearias.criar(
            {
                "slug": SLUG_PRINCIPAL,
                "nome": "Brutus",
                "endereco": "Rua Aurora, 88",
                "whatsappContato": "11999998888",
                "donoNome": "Jorge Brutus",
                # E-mail, e nao o telefone da barbearia: e a fatia 3 inteira num
                # campo. O dono tem identificador PROPRIO, e trocar o whatsapp
                # publico nao mexe em como ele entra.
                "donoEmail": "jorge@brutus.com.br",
            }
        )
        if principal["tipo"] != "ok":
            raise CommandError(f"nao consegui criar a barbearia: {principal['tipo']}")

        bid = str(principal["id"])
        self._dar_senha(bid, "jorge@brutus.com.br", senha)
        dono_id = self._perfil_de(bid, "jorge@brutus.com.br")

        novo = equipe.criar(bid, nome="Zeca Navalha", whatsapp="11977776666", papel="BARBEIRO")
        if novo["tipo"] != "ok":
            raise CommandError(f"nao consegui criar o barbeiro: {novo['tipo']}")
        zeca_id = str(novo["id"])
        self._dar_senha(bid, "11977776666", senha)

        servico = servicos.criar(
            bid, nome="Corte", duracao_minima_min=15, duracao_sugerida_min=30
        )
        if servico["tipo"] != "ok":
            raise CommandError(f"nao consegui criar o servico: {servico['tipo']}")

        # Sem vinculo E expediente o barbeiro NAO aparece para o cliente — e a
        # tela de equipe avisa isso em destaque. Uma semente que parasse antes
        # daqui entregaria uma home sem ninguem para marcar, que e o mesmo que
        # nao semear.
        for barbeiro_id, preco in ((dono_id, 5000), (zeca_id, 4500)):
            barbeiro_servicos.definir_vinculo(
                bid,
                barbeiro_id=barbeiro_id,
                servico_id=servico["id"],
                faz=True,
                duracao_min=30,
                preco_centavos=preco,
            )
            for dia in range(7):
                horarios.definir_horario(bid, barbeiro_id, dia, ABRE_MIN, FECHA_MIN)

        # O SEGUNDO tenant, e ele nao e enfeite: sem um vizinho, nenhum erro de
        # isolamento aparece ao clicar. Fica vazio de proposito — a graca e
        # abrir `dontony.localhost` e nao ver nada do Brutus.
        segundo = admin_barbearias.criar(
            {
                "slug": SLUG_SEGUNDO,
                "nome": "Dom Tony",
                "endereco": "Av. Central, 12",
                "whatsappContato": "11933332222",
                "donoNome": "Tony Dias",
                "donoEmail": "tony@domtony.com.br",
            }
        )
        if segundo["tipo"] == "ok":
            self._dar_senha(str(segundo["id"]), "tony@domtony.com.br", senha)

    def _perfil_de(self, barbearia_id, login):
        """O id do PERFIL a partir do login da conta.

        `admin_barbearias.criar` devolve o id da barbearia e o do convite, mas
        nao o do `Barbeiro` — e e o perfil que servico e expediente referenciam.
        """
        from tenant.identidade import normalizar_login
        from tenant.models import Barbeiro

        return str(
            Barbeiro.objects.using("owner")
            .filter(barbearia_id=barbearia_id, usuario__login=normalizar_login(login))
            .values_list("id", flat=True)
            .first()
        )

    def _dar_senha(self, barbearia_id, login, senha):
        """Aceita o convite no lugar da pessoa.

        A conta nasce com `senha_hash=None` e um convite pendente, porque em
        producao quem escolhe a senha e quem abre o link. Aqui nao ha quem abra,
        e um cenario onde ninguem consegue entrar nao serve para nada.

        Zera o convite junto: deixar o token valido daria duas portas para a
        mesma conta, e a tela de equipe mostraria 'sem senha ainda' ao lado de
        alguem que ja tem senha.
        """
        from app.services.senha import gerar
        from tenant.identidade import normalizar_login
        from tenant.models import Usuario

        Usuario.objects.using("owner").filter(
            barbearia_id=barbearia_id, login=normalizar_login(login)
        ).update(senha_hash=gerar(senha), convite_token_hash=None, convite_expira_em=None)

    def _resumo(self, login, senha):
        for linha in (
            "",
            "  [semear_dev] cenario pronto",
            f"    admin.localhost:3000/admin     {login} / {senha}",
            f"    brutus.localhost:3000/painel   jorge@brutus.com.br / {senha}  (DONO)",
            f"    brutus.localhost:3000/painel   11977776666 / {senha}          (BARBEIRO)",
            f"    dontony.localhost:3000         tony@domtony.com.br / {senha}  (vazia, de proposito)",
            "",
        ):
            self.stdout.write(self.style.SUCCESS(linha))
