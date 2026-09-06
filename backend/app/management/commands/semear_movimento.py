import random
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from app.services.senha import gerar
from tenant.models import (
    Barbearia,
    Barbeiro,
    BarbeiroServico,
    Cliente,
    HorarioTrabalho,
    Servico,
)
from tenant.models import Agendamento, PapelBarbeiro, StatusAgendamento

# Quanto do movimento cabe a cada barbeiro, do mais cheio ao mais vazio. Nao
# sao partes iguais de proposito: uma pizza de fatias identicas nao mostra
# nada, e barbearia de verdade nao divide corte por igual — tem quem puxa a
# clientela e quem esta comecando.
FATIAS = [0.42, 0.28, 0.18, 0.12]

NOMES_DE_BARBEIRO = ["Nando", "Igor", "Val", "Cacá", "Bruno", "Léo"]

# Telefone de mentira, e que PARECE de mentira: `1192222` para barbeiro,
# `1193333` para cliente, e os quatro ultimos digitos so' contam. Ninguem olha
# `11922221003` e acha que e' o telefone de alguem.
#
# O numero nao pode se repetir DENTRO da barbearia — a constraint e'
# `(barbearia, whatsapp)`, tanto em `Barbeiro` quanto em `Cliente`. Entre
# barbearias diferentes, pode: e' o mesmo padrao em todas, de proposito.
PREFIXO_BARBEIRO = "1192222"
PREFIXO_CLIENTE = "1193333"


def _telefone(prefixo: str, n: int) -> str:
    return f"{prefixo}{n:04d}"

NOMES_DE_CLIENTE = [
    "Marcos", "Paulo", "Lucas", "Rafael", "Bruno", "Diego", "Tiago", "Felipe",
    "Gustavo", "Rodrigo", "Vitor", "André", "Caio", "Murilo", "Henrique",
]

SEG_A_SAB = [1, 2, 3, 4, 5, 6]


class Command(BaseCommand):
    """Enche UMA barbearia de movimento passado, para o resumo ter o que mostrar.

    **Nao apaga nada**, ao contrario do `semear`, que da' TRUNCATE nas oito
    tabelas. Este comando existe justamente porque aquele nao serve quando ja'
    ha dado de verdade na barbearia — e a barbearia que o dono usa no dia a dia
    e' exatamente esse caso.

    Roda pela conexao `owner`: o RLS filtraria as escritas (a variavel de
    tenant nao esta definida num comando de terminal) e `owner` e' isento pela
    politica `owner_irrestrito`.

    Todo agendamento nasce **no passado, CONFIRMADO e com `fim` ja' vencido** —
    e' a unica forma que o resumo conta (ver `app/services/resumo.py`: o filtro
    e' `status=CONFIRMADO, inicio no periodo, fim <= agora`). Agendamento
    futuro nao entra na conta, e e' assim que tem que ser: corte que ainda nao
    aconteceu nao e' corte feito.
    """

    help = "Cria barbeiros, clientes e agendamentos PASSADOS numa barbearia, sem apagar nada."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="A barbearia, pelo slug (ex.: znt).")
        parser.add_argument(
            "--dias", type=int, default=90,
            help="Quantos dias para tras espalhar o movimento (padrao: 90).",
        )
        parser.add_argument(
            "--barbeiros", type=int, default=4,
            help="Quantos barbeiros ATIVOS a barbearia deve ter ao fim (padrao: 4).",
        )
        parser.add_argument(
            "--cortes", type=int, default=120,
            help="Quantos agendamentos criar ao todo (padrao: 120).",
        )

    def handle(self, *args, **op):
        from django.conf import settings

        # Mesma trava do `semear`, e pelo mesmo motivo: os barbeiros que ele
        # cria saem com senha conhecida.
        if not settings.DEBUG:
            raise CommandError(
                "semear_movimento so roda com DJANGO_DEBUG=1: ele cria senha conhecida."
            )

        slug = op["slug"]
        barbearia = Barbearia.objects.using("owner").filter(slug=slug).first()
        if barbearia is None:
            existentes = ", ".join(
                Barbearia.objects.using("owner").order_by("slug").values_list("slug", flat=True)
            )
            raise CommandError(f"nao achei a barbearia '{slug}'. Existem: {existentes}")

        # Semente fixa: rodar duas vezes com os mesmos argumentos produz a
        # mesma divisao. Sem isto a pizza mudaria de forma a cada corrida e
        # ninguem saberia se foi o codigo ou o acaso.
        random.seed(f"{slug}:{op['dias']}:{op['cortes']}")

        servicos = list(Servico.objects.using("owner").filter(barbearia_id=barbearia.id, ativo=True))
        if not servicos:
            raise CommandError(
                f"'{slug}' nao tem servico ativo — sem isso nao ha o que agendar."
            )

        barbeiros = self._garantir_barbeiros(barbearia, op["barbeiros"], servicos)
        clientes = self._garantir_clientes(barbearia)
        criados = self._agendar_no_passado(
            barbearia, barbeiros, clientes, servicos, op["dias"], op["cortes"]
        )

        self.stdout.write(f"{slug}: {criados} agendamentos passados, entre {len(barbeiros)} barbeiros.")
        for b, quantos in criados_por(criados, barbeiros, FATIAS):
            self.stdout.write(f"  {b.nome}: ~{quantos}")
        self.stdout.write(f"Veja em http://{slug}.localhost:3000/painel/resumo")

    def _garantir_barbeiros(self, barbearia, quantos, servicos):
        """Completa ate' `quantos` barbeiros ATIVOS, preservando os que ja'
        existem. A pizza precisa de pelo menos duas fatias para existir — com
        um barbeiro so' ela se apaga, porque um circulo cheio dizendo 100% nao
        informa nada que o numero embaixo ja' nao diga."""
        atuais = list(
            Barbeiro.objects.using("owner")
            .filter(barbearia_id=barbearia.id, ativo=True)
            .order_by("ordem", "nome")
        )
        senha = gerar("123456")
        disponiveis = [n for n in NOMES_DE_BARBEIRO if n not in {b.nome for b in atuais}]

        while len(atuais) < quantos and disponiveis:
            nome = disponiveis.pop(0)
            novo = Barbeiro.objects.using("owner").create(
                barbearia_id=barbearia.id, nome=nome,
                whatsapp=_telefone(PREFIXO_BARBEIRO, len(atuais) + 1),
                ativo=True, papel=PapelBarbeiro.BARBEIRO,
                ordem=len(atuais), senha_hash=senha,
            )
            # Sem servico e sem expediente o barbeiro existe mas nao pode ser
            # agendado pela tela — o resumo funcionaria e o resto nao, o que
            # daria um dado que nao se consegue reproduzir usando o produto.
            for s in servicos:
                BarbeiroServico.objects.using("owner").create(
                    barbearia_id=barbearia.id, barbeiro_id=novo.id, servico_id=s.id,
                    duracao_min=s.duracao_sugerida_min, preco_centavos=4000, ativo=True,
                )
            for dia in SEG_A_SAB:
                HorarioTrabalho.objects.using("owner").create(
                    barbearia_id=barbearia.id, barbeiro_id=novo.id,
                    dia_semana=dia, minutos_inicio=9 * 60, minutos_fim=20 * 60,
                )
            atuais.append(novo)

        return atuais

    def _garantir_clientes(self, barbearia):
        """Clientes suficientes para "clientes unicos" ser menor que "cortes" —
        que e' a coisa que o resumo tem para dizer e um cliente por corte
        esconderia."""
        atuais = list(Cliente.objects.using("owner").filter(barbearia_id=barbearia.id))
        usados = {c.nome for c in atuais}
        # O contador comeca em quantos JA existem: os telefones dos que o dono
        # cadastrou de verdade nao seguem este padrao, entao contar a partir do
        # total e' o que garante nao esbarrar num ja' usado.
        proximo = len(atuais) + 1
        for nome in NOMES_DE_CLIENTE:
            if nome in usados:
                continue
            atuais.append(
                Cliente.objects.using("owner").create(
                    barbearia_id=barbearia.id, nome=nome,
                    whatsapp=_telefone(PREFIXO_CLIENTE, proximo),
                )
            )
            proximo += 1
        return atuais

    def _agendar_no_passado(self, barbearia, barbeiros, clientes, servicos, dias, cortes):
        agora = timezone.now()
        pesos = (FATIAS + [0.05] * len(barbeiros))[: len(barbeiros)]

        criados = 0
        colisoes = 0
        for _ in range(cortes):
            barbeiro = random.choices(barbeiros, weights=pesos, k=1)[0]
            servico = random.choice(servicos)
            cliente = random.choice(clientes)

            # Sempre no passado, e nunca hoje: `fim <= agora` e' o que faz o
            # resumo contar. Um agendamento comecando ha' 30 minutos ficaria
            # com `fim` no futuro e sumiria da conta sem explicacao.
            dias_atras = random.randint(1, dias)
            hora = random.randint(9, 18)
            minuto = random.choice([0, 30])
            inicio = (agora - timedelta(days=dias_atras)).replace(
                hour=hora, minute=minuto, second=0, microsecond=0
            )
            duracao = servico.duracao_sugerida_min

            # A `0003_restricoes` cria um EXCLUDE (`agendamento_sem_sobreposicao`)
            # que impede dois cortes sobrepostos no MESMO barbeiro — regra de
            # produto de verdade, e o sorteio acima nao a conhece. Com poucos
            # dias e muitos cortes a colisao deixa de ser rara.
            #
            # `atomic` por insercao e' obrigatorio: sem ele, o IntegrityError
            # aborta a transacao inteira e toda insercao seguinte morre com
            # "current transaction is aborted", perdendo o trabalho ja' feito.
            # Foi exatamente o que aconteceu na primeira corrida com --dias 5.
            try:
                with transaction.atomic(using="owner"):
                    Agendamento.objects.using("owner").create(
                        barbearia_id=barbearia.id,
                        codigo=uuid.uuid4().hex[:12],
                        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
                        servico_nome=servico.nome,
                        inicio=inicio, fim=inicio + timedelta(minutes=duracao),
                        duracao_min=duracao, preco_centavos=4000,
                        status=StatusAgendamento.CONFIRMADO,
                    )
            except IntegrityError:
                # Horario ja' ocupado. Pular e' melhor que tentar de novo: o
                # comando promete "ate' `cortes`", nao "exatamente `cortes`", e
                # insistir num espaco cheio so' faria a corrida demorar.
                colisoes += 1
                continue
            criados += 1

        if colisoes:
            self.stdout.write(
                f"  ({colisoes} sorteios cairam em horario ja' ocupado e foram pulados — "
                "espalhe por mais dias com --dias se quiser todos)"
            )
        return criados


def criados_por(total, barbeiros, fatias):
    """So' para o resumo que o comando imprime — a divisao de verdade e' a que
    o `random.choices` sorteou, e o numero real sai do proprio resumo."""
    pesos = (fatias + [0.05] * len(barbeiros))[: len(barbeiros)]
    soma = sum(pesos)
    return [(b, round(total * p / soma)) for b, p in zip(barbeiros, pesos)]
