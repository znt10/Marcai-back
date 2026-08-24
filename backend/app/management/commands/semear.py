from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from app.services.senha import gerar
from tenant.models import (
    Barbearia,
    Barbeiro,
    BarbeiroServico,
    Bloqueio,
    Cliente,
    HorarioTrabalho,
    Servico,
)

SEG_A_SAB = [1, 2, 3, 4, 5, 6]
TER_A_SAB = [2, 3, 4, 5, 6]

# A ordem importa: dependente antes de dependencia, senao o CASCADE faz o
# trabalho por acidente e a lista para de documentar o grafo.
#
# Nomes em minusculo com prefixo `tenant_` — a convencao padrao do Django
# (`{app_label}_{model}`), e nao mais o CamelCase entre aspas que o Prisma
# emitia. A fatia 1 trocou o dono do schema; `tests/conftest.py` (fixture
# `limpar_banco`) TRUNCA as mesmas oito tabelas com estes nomes.
TABELAS = [
    "tenant_agendamento", "tenant_cliente", "tenant_bloqueio",
    "tenant_horariotrabalho", "tenant_barbeiroservico", "tenant_servico",
    "tenant_barbeiro", "tenant_barbearia",
]


class Command(BaseCommand):
    """Porta de `prisma/seed.ts`, apagado na fatia 8.

    Roda pela conexao `owner` por dois motivos que se somam: `brutus_app` nao
    tem TRUNCATE (deliberado — o papel do runtime nao deve esvaziar tabela) e
    o RLS filtraria as escritas de dois tenants diferentes. `owner` e' isento
    pela politica `owner_irrestrito`.
    """

    help = "Popula o banco com os dois tenants de desenvolvimento. APAGA o que estiver la."

    def handle(self, *args, **opcoes):
        # O `throw` de NODE_ENV=production do seed do Prisma vira isto. A senha
        # conhecida abaixo e' o motivo: sem a trava, um `semear` distraido em
        # producao poe `123456` em toda conta de barbeiro.
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError(
                "semear so roda com DJANGO_DEBUG=1: ele cria senha conhecida."
            )

        with connections["owner"].cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {', '.join(TABELAS)} RESTART IDENTITY CASCADE")

        # Senha conhecida, so no seed (cliente §5.5): sem ela o painel nasce
        # intestavel — os dois papeis existem e nenhum dos dois entra.
        senha = gerar("123456")

        self._brutus(senha)
        self._dom_tony(senha)

        self.stdout.write("Seed pronto: brutus.localhost:3000 e dontony.localhost:3000")

    def _brutus(self, senha):
        brutus = Barbearia.objects.using("owner").create(
            slug="brutus", nome="BRUTUS", endereco="Rua Aurora, 88",
            horario_resumo="seg a sáb, 9h–20h", whatsapp_contato="11988887777",
        )

        servicos = {}
        for nome, mini, sugerida, ordem in [
            ("Corte", 20, 40, 0),
            ("Barba", 15, 30, 1),
            ("Corte + Barba", 40, 60, 2),
            ("Pezinho", 10, 15, 3),
        ]:
            servicos[nome] = Servico.objects.using("owner").create(
                barbearia=brutus, nome=nome, duracao_minima_min=mini,
                duracao_sugerida_min=sugerida, ordem=ordem,
            )

        teo = Barbeiro.objects.using("owner").create(
            barbearia=brutus, nome="Téo", whatsapp="11911112222",
            papel="DONO", senha_hash=senha, ordem=0,
        )
        rael = Barbeiro.objects.using("owner").create(
            barbearia=brutus, nome="Rael", whatsapp="11933334444",
            papel="BARBEIRO", senha_hash=senha, ordem=1,
        )
        # Convite pendente — o estado que o wireframe 3e desenha.
        Barbeiro.objects.using("owner").create(
            barbearia=brutus, nome="Duda", whatsapp="11955556666",
            papel="BARBEIRO", senha_hash=None, ordem=2,
        )

        # Duracoes DIFERENTES de proposito: se um bug ignorar a duracao por
        # barbeiro, aparece na primeira tela aberta. E o Rael NAO faz pezinho —
        # linha ausente de proposito, e' o unico caso negativo do seed.
        for barbeiro, nome_servico, minutos in [
            (teo, "Corte", 40), (teo, "Barba", 30),
            (teo, "Corte + Barba", 60), (teo, "Pezinho", 15),
            (rael, "Corte", 30), (rael, "Barba", 45),
            (rael, "Corte + Barba", 60),
        ]:
            BarbeiroServico.objects.using("owner").create(
                barbearia=brutus, barbeiro=barbeiro,
                servico=servicos[nome_servico], duracao_min=minutos,
            )

        for dia in SEG_A_SAB:
            HorarioTrabalho.objects.using("owner").create(
                barbearia=brutus, barbeiro=teo, dia_semana=dia,
                minutos_inicio=9 * 60, minutos_fim=20 * 60,
            )
        for dia in TER_A_SAB:
            HorarioTrabalho.objects.using("owner").create(
                barbearia=brutus, barbeiro=rael, dia_semana=dia,
                minutos_inicio=10 * 60, minutos_fim=19 * 60,
            )

        for barbeiro in (teo, rael):
            for dia in SEG_A_SAB:
                Bloqueio.objects.using("owner").create(
                    barbearia=brutus, barbeiro=barbeiro, motivo="ALMOCO",
                    repete_semanalmente=True, dia_semana=dia,
                    minutos_inicio=12 * 60, minutos_fim=13 * 60,
                )

    def _dom_tony(self, senha):
        """Barbearia-controle, nada em comum com a BRUTUS. E' com o login do
        Tony que se prova, na mao, que o cookie da BRUTUS nao a abre."""
        dom_tony = Barbearia.objects.using("owner").create(
            slug="dontony", nome="Dom Tony", endereco="Av. Central, 12",
            horario_resumo="ter a sáb, 10h–19h", whatsapp_contato="11955554444",
        )
        corte = Servico.objects.using("owner").create(
            barbearia=dom_tony, nome="Corte social",
            duracao_minima_min=25, duracao_sugerida_min=50,
        )
        tony = Barbeiro.objects.using("owner").create(
            barbearia=dom_tony, nome="Tony", whatsapp="11977778888",
            papel="DONO", senha_hash=senha,
        )
        BarbeiroServico.objects.using("owner").create(
            barbearia=dom_tony, barbeiro=tony, servico=corte, duracao_min=50,
        )
        for dia in TER_A_SAB:
            HorarioTrabalho.objects.using("owner").create(
                barbearia=dom_tony, barbeiro=tony, dia_semana=dia,
                minutos_inicio=10 * 60, minutos_fim=19 * 60,
            )
        Cliente.objects.using("owner").create(
            barbearia=dom_tony, nome="Jorge Dom Tony", whatsapp="11912121212",
        )
