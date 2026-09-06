import uuid

from django.db import models
from django.utils import timezone


# Os tres enums nativos do Postgres (`PapelBarbeiro`, `MotivoBloqueio`,
# `StatusAgendamento`) NAO sobrevivem a troca de dono, e isso e deliberado.
#
# Enquanto o Prisma era dono, o enum nativo era de graca: ele emitia o
# `CREATE TYPE` e o Django so precisava mandar `str`, que o psycopg manda como
# `unknown` e o Postgres resolve para o tipo da coluna. Agora que o DDL e
# nosso, manter o tipo nativo custaria um `RunSQL` por enum, mais um por
# valor novo (`ALTER TYPE ... ADD VALUE`, que ate o Postgres 11 nem rodava
# dentro de transacao) — e o Django continuaria sem saber que o tipo existe.
#
# `TextChoices` poe a lista de valores num lugar so, do lado que le e escreve,
# e o banco guarda `varchar`. O que se perde e a recusa do Postgres a um valor
# fora da lista; quem passa a recusar sao os `choices` do Django e as rotas —
# e nenhuma delas aceita valor livre. A garantia que importava de verdade
# (dupla marcacao) nunca foi o enum, e continua sendo o EXCLUDE da 0003.
class PapelBarbeiro(models.TextChoices):
    DONO = "DONO"
    BARBEIRO = "BARBEIRO"


class MotivoBloqueio(models.TextChoices):
    ALMOCO = "ALMOCO"
    FOLGA = "FOLGA"
    PESSOAL = "PESSOAL"
    OUTRO = "OUTRO"


class StatusAgendamento(models.TextChoices):
    CONFIRMADO = "CONFIRMADO"
    CANCELADO_CLIENTE = "CANCELADO_CLIENTE"
    CANCELADO_BARBEIRO = "CANCELADO_BARBEIRO"


class Barbearia(models.Model):
    """A tabela de tenant. Unica sem barbearia_id e unica fora do RLS — ela e
    lida ANTES de existir tenant, para traduzir subdominio em id, e por isso e
    protegida por GRANT (REVOKE INSERT/UPDATE/DELETE) e nao por politica.
    """

    # UUIDField de verdade, e a coluna vira `uuid`. Enquanto o Prisma era dono
    # ela era TEXT porque ele declara `id String @id @default(uuid())` sem
    # `@db.Uuid` — o valor sempre foi um uuid, o TIPO e que nao era. Todo o
    # comentario que existia aqui sobre "TextField, nao UUIDField" descrevia a
    # consequencia disso (o psycopg manda o parametro tipado `uuid`, `INSERT`
    # passa por cast de atribuicao e `filter(id=...)` nao acha nada, porque
    # `text = uuid` nao resolve). Com a coluna sendo `uuid` os dois lados
    # passam a falar o mesmo tipo e o descasamento deixa de existir.
    #
    # `default=uuid.uuid4` espelha o `@default(uuid())` do Prisma. Quem cria
    # hoje passa o id explicito (`id=str(uuid.uuid4())` nos services) e
    # continua mandando o seu — UUIDField aceita `str` e converte.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    slug = models.TextField(unique=True)
    nome = models.TextField()
    endereco = models.TextField()
    # Nulo ate o DONO preencher: o admin da plataforma nao sabe o horario da
    # barbearia. Nulo e string vazia seriam dois jeitos de dizer a mesma coisa.
    horario_resumo = models.TextField(null=True)
    whatsapp_contato = models.TextField()
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(default=timezone.now)

    def __str__(self):
        # Sem isto o Django escreve "Barbearia object (uuid)" em TODO lugar que
        # mostra o objeto: cabecalho de formulario, <select> de chave
        # estrangeira, log de acao do admin. O uuid nao identifica nada para
        # quem esta olhando — o nome, sim.
        return self.nome


class Barbeiro(models.Model):
    """Quem atende. Tambem e a tabela de tenant que o teste de RLS conta para
    provar que o escopo funciona.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    # ForeignKey de verdade no lugar do `TextField(db_column="barbeariaId")`.
    # A coluna continua se chamando `barbearia_id` e o atributo Python tambem,
    # entao todo `filter(barbearia_id=...)` e `create(barbearia_id=...)` que ja
    # existe segue valendo palavra por palavra — o que muda e que agora ha uma
    # FK de verdade atras dele, com o tipo casando (uuid contra uuid).
    #
    # RESTRICT espelha o `onDelete: Restrict` do Prisma: apagar uma barbearia
    # que ainda tem barbeiro tem que doer, nao levar a equipe junto em silencio.
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="barbeiros",
    )
    nome = models.TextField()
    whatsapp = models.TextField()
    ativo = models.BooleanField(default=True)
    # O que sai daqui para o cliente e so id, nome e foto (§9.1).
    foto_url = models.TextField(null=True)
    ordem = models.IntegerField(default=0)

    # ---- A sessao ----
    #
    # Nenhum destes sai em resposta nenhuma. Eles existem para que o login e o
    # convite possam ser DECIDIDOS aqui; o que o cliente ve continua sendo o
    # que o serializer lista, e ele nao lista nenhum deles.
    papel = models.CharField(
        max_length=20, choices=PapelBarbeiro, default=PapelBarbeiro.BARBEIRO,
    )
    # Nulo ate o convite ser aceito: o admin cria o dono SEM senha, e o
    # `senha_hash` nulo e o que a rota do login tem que recusar sem revelar que
    # o numero existe.
    senha_hash = models.TextField(null=True)
    # O que faz "desligar o barbeiro" derrubar a sessao dele na hora. O numero
    # viaja dentro do cookie (`tv`) e e conferido contra a coluna a cada
    # pedido; incrementa-lo invalida todo cookie ja emitido sem que exista
    # lista de sessao nenhuma para varrer.
    token_version = models.IntegerField(default=0)
    convite_token_hash = models.TextField(null=True)
    convite_expira_em = models.DateTimeField(null=True)
    tentativas_login = models.IntegerField(default=0)
    bloqueado_ate = models.DateTimeField(null=True)
    # Nulo ate desativar, de novo nulo ao reativar — a mesma logica de
    # "ausencia e o estado" do resto do schema.
    desativado_em = models.DateTimeField(null=True)
    criado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["barbearia", "whatsapp"], name="barbeiro_whatsapp_por_tenant",
            ),
            # Redundante como chave (`id` ja e pk); necessaria como ALVO das FK
            # compostas que a 0003 cria — e o que impede o `barbearia_id`
            # denormalizado de divergir do dono real.
            models.UniqueConstraint(
                fields=["barbearia", "id"], name="barbeiro_id_por_tenant",
            ),
        ]

    def __str__(self):
        return self.nome


class Servico(models.Model):
    """O catalogo da barbearia.

    As duas duracoes sao NOT NULL sem default: um servico sem elas nao tem como
    virar horario na grade.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="servicos",
    )
    nome = models.TextField()
    duracao_minima_min = models.IntegerField()
    duracao_sugerida_min = models.IntegerField()
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["barbearia", "nome"], name="servico_nome_por_tenant",
            ),
            models.UniqueConstraint(
                fields=["barbearia", "id"], name="servico_id_por_tenant",
            ),
        ]

    def __str__(self):
        return self.nome


class BarbeiroServico(models.Model):
    """O vinculo, e o unico lugar onde mora o preco.

    A chave primaria e COMPOSTA (`@@id([barbeiroId, servicoId])` no Prisma), e
    aqui ela finalmente e declarada como tal. Enquanto os models eram
    `managed=False` isso nao era possivel — a saida da epoca foi marcar
    `barbeiro` como `primary_key=True`, o que o Django aceitava porque nao
    criava tabela nenhuma: a pk composta de verdade existia no banco, e o
    Django so fingia uma pk de uma coluna por cima dela.

    Agora que o Django CRIA a tabela, aquele fingimento viraria dano real —
    uma pk so em `barbeiro_id` proibiria um barbeiro de ter dois servicos, que
    e exatamente o caso normal. `CompositePrimaryKey` (Django 5.2+) declara a
    chave que o banco sempre teve.
    """

    pk = models.CompositePrimaryKey("barbeiro", "servico")

    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="barbeiro_servicos",
    )
    barbeiro = models.ForeignKey(
        Barbeiro, on_delete=models.CASCADE, related_name="vinculos",
    )
    servico = models.ForeignKey(
        Servico, on_delete=models.RESTRICT, related_name="vinculos",
    )
    duracao_min = models.IntegerField()
    # Nulo ate o barbeiro decidir — sem `default=`, de proposito: ao
    # contrario de `duracao_min` (que sempre tem um valor resolvido, a
    # sugerida do servico quando falta o praticado), preco nao tem
    # sugestao nenhuma pra herdar do catalogo. Quem cobra e' o barbeiro.
    preco_centavos = models.IntegerField(null=True)
    ativo = models.BooleanField(default=True)


class HorarioTrabalho(models.Model):
    """A jornada semanal do barbeiro. Sem linha para um dia da semana, aquele
    dia nao gera horario nenhum — fechar e APAGAR a linha, nao gravar uma de
    duracao zero (spec 4). Por isso o motor trata "nao achei jornada" e "achei
    jornada vazia" como o mesmo nada.

    `dia_semana` guarda o que o `getDay()` do JavaScript produz: DOMINGO = 0.
    Ver `dia_semana_de` em tenant/datas.py — e a conversao que o Python erra
    por padrao.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="horarios",
    )
    barbeiro = models.ForeignKey(
        Barbeiro, on_delete=models.CASCADE, related_name="horarios",
    )
    dia_semana = models.IntegerField()
    minutos_inicio = models.IntegerField()
    minutos_fim = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["barbeiro", "dia_semana"], name="jornada_unica_por_dia",
            ),
        ]

    def __str__(self):
        return f"{self.barbeiro_id} dia {self.dia_semana}"


class Bloqueio(models.Model):
    """Duas formas na MESMA tabela, e o motor le uma OU a outra:

    - semanal: `repete_semanalmente=True` + dia da semana e minutos;
    - pontual: `inicio` e `fim` em instantes.

    Os campos da forma nao usada ficam nulos. Gravar as duas juntas produziria
    uma linha cuja interpretacao depende de qual campo alguem leu primeiro —
    e o sintoma seria horario sumido sem explicacao. Quem recusa isso e o
    CHECK `bloqueio_forma_valida` da 0003, e nao a boa vontade do painel.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="bloqueios",
    )
    barbeiro = models.ForeignKey(
        Barbeiro, on_delete=models.CASCADE, related_name="bloqueios",
    )
    motivo = models.CharField(
        max_length=20, choices=MotivoBloqueio, default=MotivoBloqueio.OUTRO,
    )
    repete_semanalmente = models.BooleanField()
    dia_semana = models.IntegerField(null=True)
    minutos_inicio = models.IntegerField(null=True)
    minutos_fim = models.IntegerField(null=True)
    inicio = models.DateTimeField(null=True)
    fim = models.DateTimeField(null=True)
    observacao = models.TextField(null=True)
    criado_em = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.motivo} {self.barbeiro_id}"


class Cliente(models.Model):
    """Sem cadastro e sem senha: o cliente e identificado pelo WhatsApp dentro
    da barbearia.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="clientes",
    )
    nome = models.TextField()
    whatsapp = models.TextField()
    criado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["barbearia", "whatsapp"], name="cliente_whatsapp_por_tenant",
            ),
            models.UniqueConstraint(
                fields=["barbearia", "id"], name="cliente_id_por_tenant",
            ),
        ]

    def __str__(self):
        # Nome MAIS whatsapp: dois clientes com o mesmo primeiro nome sao o
        # caso comum numa barbearia, e o <select> de agendamento precisa
        # distinguir os dois.
        return f"{self.nome} ({self.whatsapp})"


class Agendamento(models.Model):
    """O horario marcado.

    `servico_nome` e gravado junto e nao vem por join de proposito (decisao do
    schema): renomear um servico depois nao pode reescrever o historico do que
    foi vendido. `preco_centavos` e `duracao_min` sao snapshot pela mesma razao.

    So `CONFIRMADO` ocupa. Um cancelado que continuasse ocupando deixaria o
    horario morto na agenda ate o fim do dia — o pior tipo de defeito aqui,
    porque a barbearia perde dinheiro e nada aparece na tela.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="agendamentos",
    )
    # Token de URL publica — unico GLOBALMENTE, de proposito (§5.1).
    codigo = models.TextField(unique=True)
    barbeiro = models.ForeignKey(
        Barbeiro, on_delete=models.RESTRICT, related_name="agendamentos",
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.RESTRICT, related_name="agendamentos",
    )
    servico = models.ForeignKey(
        Servico, on_delete=models.RESTRICT, related_name="agendamentos",
    )
    servico_nome = models.TextField()
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    duracao_min = models.IntegerField()
    preco_centavos = models.IntegerField(null=True)
    status = models.CharField(
        max_length=20, choices=StatusAgendamento, default=StatusAgendamento.CONFIRMADO,
    )
    criado_em = models.DateTimeField(default=timezone.now)
    cancelado_em = models.DateTimeField(null=True)
    # Nulo ate o AGENDAR decidir: marcar dentro da janela do lembrete grava
    # `agora` aqui na criacao (a confirmacao JA e' o lembrete), e o cron
    # nunca ve esse agendamento.
    lembrete_enviado_em = models.DateTimeField(null=True)

    def __str__(self):
        # Quem e', quando, e o que — nessa ordem, porque e' assim que se procura
        # um agendamento ("o corte do Joao de terca").
        return f"{self.servico_nome} {self.inicio:%d/%m %H:%M}"

    class Meta:
        indexes = [
            # O unico indice que a FK nao da de graca: as consultas da agenda
            # sempre entram por barbeiro E janela de tempo juntos.
            models.Index(fields=["barbeiro", "inicio"], name="agendamento_barbeiro_dia"),
        ]
