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


class PapelUsuario(models.TextChoices):
    """Os tres papeis do sistema, e note que ADMIN nao existe em
    `PapelBarbeiro`, que existia ate a fatia 3 e cobria so' DONO/BARBEIRO: o
    admin da plataforma nunca foi barbeiro de lugar nenhum — ele nao tinha
    tabela, morava em variavel de ambiente. Com o papel migrando para
    `Usuario`, aquele enum ficou sem nenhum campo apontando para ele e saiu.
    """

    ADMIN = "ADMIN"
    DONO = "DONO"
    BARBEIRO = "BARBEIRO"


class Usuario(models.Model):
    """Quem faz login. Tabela PROPRIA, e nao `django.contrib.auth`.

    O contrib.auth continua fora do INSTALLED_APPS pelo mesmo motivo de sempre
    (backend/settings.py): o admin de fabrica dele enxergaria TODA barbearia,
    que e o oposto exato do que o RLS deste banco existe para garantir. Herdar
    dele seria herdar um modelo de permissao global num sistema cuja regra
    central e' que ninguem ve fora do proprio tenant.

    Ate aqui a identidade nunca tinha sido modelada: `Barbeiro` acumulava
    credencial (senha, token, convite, bloqueio) junto com perfil de agenda
    (foto, ordem, whatsapp), e as duas coisas tem ciclos de vida diferentes —
    trocar o telefone de contato da barbearia derrubava o login do dono, porque
    era o mesmo campo.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    # ÚNICO no sistema inteiro, e nao por barbearia. Tem de ser: o login e
    # digitado ANTES de existir sessao, e e ele que diz quem esta entrando —
    # se o mesmo valor pudesse existir em duas barbearias, a resposta a "quem e
    # este?" dependeria de um tenant que ainda nao foi resolvido.
    #
    # A consequencia e real e vale saber: hoje `Barbeiro` permite o MESMO
    # whatsapp em barbearias diferentes (`unique(barbearia, whatsapp)`), e um
    # login unico global tira isso de quem for barbeiro nos dois lugares. E' o
    # preco de ter uma identidade so' por pessoa.
    #
    # Guardado ja normalizado — ver `tenant.identidade.normalizar_login`. O
    # `unique` so' vale alguma coisa sobre a forma canonica: sem ela
    # `" Joao@X.com "` e `joao@x.com` seriam duas linhas sem conflito nenhum.
    login = models.TextField(unique=True)
    papel = models.CharField(max_length=20, choices=PapelUsuario)

    # NULO so' para o ADMIN, e a CheckConstraint abaixo amarra as duas coisas.
    # Ele e o unico que existe fora de qualquer barbearia — e e exatamente essa
    # nulidade que o RLS aproveita (ver a migration 0005).
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="usuarios", null=True,
    )

    # Nulo ate o convite ser aceito. O admin cria o dono SEM senha, e e este
    # nulo que o login tem de recusar sem revelar que a conta existe.
    senha_hash = models.TextField(null=True)
    # O que faz "desligar alguem" derrubar a sessao na hora: o numero viaja no
    # cookie (`tv`) e e conferido a cada pedido, entao incrementa-lo invalida
    # todo cookie ja emitido sem existir lista de sessao para varrer.
    token_version = models.IntegerField(default=0)
    convite_token_hash = models.TextField(null=True)
    convite_expira_em = models.DateTimeField(null=True)
    tentativas_login = models.IntegerField(default=0)
    bloqueado_ate = models.DateTimeField(null=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(default=timezone.now)
    desativado_em = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            # "ADMIN nao tem barbearia, todo o resto tem" escrito no BANCO, e
            # nao so' na rota que cria. Sem ela as duas linhas erradas passam
            # caladas: um ADMIN preso a uma barbearia (que o RLS entao
            # esconderia do proprio admin) e um DONO sem barbearia nenhuma —
            # invisivel para o `tenant_isolation` e, por ser NULL, visivel para
            # a politica do admin. Os dois viram "usuario que some", o defeito
            # mais caro de diagnosticar que esta tabela pode ter.
            models.CheckConstraint(
                condition=(
                    models.Q(papel=PapelUsuario.ADMIN, barbearia__isnull=True)
                    | ~models.Q(papel=PapelUsuario.ADMIN) & models.Q(barbearia__isnull=False)
                ),
                name="admin_sem_barbearia_resto_com",
            ),
        ]


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
    # O perfil aponta para a identidade, e nao o contrario: um Usuario existe
    # sozinho (o ADMIN nao tem perfil de agenda nenhum), um Barbeiro sem
    # Usuario nao entra no sistema.
    #
    # OBRIGATORIO desde a fatia 3: quem cria perfil agora cria a identidade
    # junto (equipe.criar e admin_barbearias.criar, os dois numa transacao so').
    # Um perfil sem usuario seria alguem que aparece na agenda e nao consegue
    # entrar no sistema — e nada mais o produziria.
    #
    # RESTRICT e nao CASCADE: apagar a identidade nao pode levar junto o perfil
    # que carrega a agenda. Desligar alguem e' `ativo=False`, nunca DELETE.
    usuario = models.OneToOneField(
        "Usuario", on_delete=models.RESTRICT, related_name="perfil",
    )
    nome = models.TextField()
    whatsapp = models.TextField()
    ativo = models.BooleanField(default=True)
    # O que sai daqui para o cliente e so id, nome e foto (§9.1).
    foto_url = models.TextField(null=True)
    ordem = models.IntegerField(default=0)

    # Nulo ate desativar, de novo nulo ao reativar.
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

    class Meta:
        indexes = [
            # O unico indice que a FK nao da de graca: as consultas da agenda
            # sempre entram por barbeiro E janela de tempo juntos.
            models.Index(fields=["barbeiro", "inicio"], name="agendamento_barbeiro_dia"),
        ]
