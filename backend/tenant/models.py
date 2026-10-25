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


class PlanoBarbearia(models.TextChoices):
    """O que a barbearia comprou. Desde a etapa 1 do numero central (spec
    2026-10-06) toda barbearia e' `COM_ZAP`: o cliente recebe confirmacao e
    lembrete pelo numero central do Marcai. O campo fica para os planos
    futuros (WhatsApp x API oficial).
    """

    SEM_ZAP = "SEM_ZAP"
    COM_ZAP = "COM_ZAP"


class TipoNegocio(models.TextChoices):
    """O ramo do estabelecimento (spec 2026-10-08). Muda as PALAVRAS que o
    cliente e a equipe leem ("o estudio", "a profissional") — nunca o que o
    sistema faz: agenda, lista do dia e lembrete sao os mesmos em todos. As
    palavras de cada um moram em `tenant/tipos.py` (aqui) e `src/lib/tipos.ts`
    (front). Tipo novo entra pelos dois lados."""

    BARBEARIA = "BARBEARIA"
    # O valor fica SOBRANCELHA (e' o que esta' no banco); o nome mudou para
    # Estetica em 22/10/2026, que e' como o ramo se chama.
    SOBRANCELHA = "SOBRANCELHA", "Estética"
    MANICURE = "MANICURE", "Manicure"
    MAQUIAGEM = "MAQUIAGEM", "Maquiagem"
    OUTRO = "OUTRO"


class Paleta(models.TextChoices):
    """As cores das telas do cliente (e o destaque do painel). Escolhida pelo
    admin da plataforma ao criar; o tipo so' sugere a padrao
    (`tipos.PALETA_PADRAO`). Os valores de cada uma moram no front
    (`src/lib/paletas.ts`): o back so' guarda qual."""

    PRETO_AMARELO = "PRETO_AMARELO", "Preto e amarelo"
    BRANCO_ROSE = "BRANCO_ROSE", "Branco e rosé"
    PRETO_ROSE = "PRETO_ROSE", "Preto e rosé"
    BRANCO_DOURADO = "BRANCO_DOURADO", "Branco e dourado"


class EstadoInstancia(models.TextChoices):
    """O ciclo de vida do vinculo com o WhatsApp da barbearia.

    `PENDENTE` nao e "desconectado": e "a Evolution ainda nao sabe que esta
    instancia existe". Os dois precisam ser distintos porque a conferencia
    periodica age diferente em cada um — no `PENDENTE` ela CRIA a instancia,
    no `DESCONECTADO` ela so confere. Colapsar os dois faria a conferencia
    tentar recriar uma instancia viva a cada cinco minutos.
    """

    PENDENTE = "PENDENTE"
    AGUARDANDO_QR = "AGUARDANDO_QR"
    CONECTADO = "CONECTADO"
    DESCONECTADO = "DESCONECTADO"


class TipoMensagem(models.TextChoices):
    CONFIRMACAO = "CONFIRMACAO"
    CANCELAMENTO = "CANCELAMENTO"
    LEMBRETE = "LEMBRETE"


class EstadoConversa(models.TextChoices):
    """Em que pergunta a conversa do bot esta parada.

    NAO existe estado "mudo". O silencio e' a coluna `mudo_ate`: entrar em mudo
    nao pode apagar onde a conversa estava (spec, secao 3).
    """

    MENU = "MENU"
    SERVICO = "SERVICO"
    BARBEIRO = "BARBEIRO"
    DIA = "DIA"
    HORA = "HORA"
    NOME = "NOME"
    CONFIRMA = "CONFIRMA"
    QUAL_AGENDAMENTO = "QUAL_AGENDAMENTO"
    CONFIRMA_CANCEL = "CONFIRMA_CANCEL"
    AGUARDANDO_LEMBRETE = "AGUARDANDO_LEMBRETE"


class MotivoCobranca(models.TextChoices):
    MENSALIDADE = "MENSALIDADE"
    AGENDAMENTO = "AGENDAMENTO"


class StatusCobranca(models.TextChoices):
    ABERTA = "ABERTA"
    PAGA = "PAGA"
    EXPIRADA = "EXPIRADA"
    CANCELADA = "CANCELADA"


class ComoFoiPaga(models.TextChoices):
    MANUAL = "MANUAL"
    VIGIA = "VIGIA"
    REGISTRO = "REGISTRO"
    INFINITEPAY = "INFINITEPAY"


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
    # QUEM VENDE decide isto, nao o dono da barbearia: a coluna vive numa
    # tabela em que `brutus_app` nao tem UPDATE nenhum (o REVOKE da 0002), e
    # so o alias `admin` (`brutus_admin`, GRANT da 0004) a escreve. Nao e
    # zelo — e a razao de o estado da CONEXAO morar noutra tabela: guardar o
    # QR aqui obrigaria a abrir aquele REVOKE para o runtime escrever, e com
    # ele viria `slug` e `ativo` de brinde.
    plano = models.CharField(
        max_length=20, choices=PlanoBarbearia, default=PlanoBarbearia.COM_ZAP,
    )
    # A hora da lista do dia da equipe, em minutos desde a meia-noite de Sao
    # Paulo. O DONO escolhe, na tela de WhatsApp do painel: uma barbearia que
    # abre as 06:00 quer a lista antes disso. As horas que valem e o porque
    # moram em `lista_do_dia.HORAS_DA_LISTA_MIN`. Segunda coluna que o runtime
    # escreve (GRANT por coluna na 0009), ao lado de `horario_resumo`.
    hora_da_lista_min = models.PositiveSmallIntegerField(default=6 * 60 + 30)
    # Os dois so' o admin da plataforma escreve (GRANT de tabela da 0004): o
    # dono nao troca o ramo nem as cores. Os padroes sao o que toda barbearia
    # ja era antes de existirem.
    tipo = models.CharField(max_length=20, choices=TipoNegocio, default=TipoNegocio.BARBEARIA)
    paleta = models.CharField(max_length=20, choices=Paleta, default=Paleta.PRETO_AMARELO)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        # O nome que o admin do Django mostra. A classe segue `Barbearia`, mas
        # o estabelecimento pode ser um estudio de sobrancelha (tenant/tipos.py).
        verbose_name = "estabelecimento"
        verbose_name_plural = "estabelecimentos"

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
        # Mesmo motivo do `Barbearia.Meta`: num estudio, quem atende e' a
        # profissional.
        verbose_name = "profissional"
        verbose_name_plural = "profissionais"
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
    # Bloqueado = `bloqueado_em` preenchido (spec 2026-10-13). O site recusa
    # marcar com este numero, e com qualquer aparelho que ja' marcou com ele.
    bloqueado_em = models.DateTimeField(null=True, blank=True)
    bloqueado_por = models.ForeignKey(
        "Barbeiro", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

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
    # A marca do navegador que marcou pelo site (cookie `aparelho`). Nulo
    # para o painel, o bot e tudo que veio antes de 13/10/2026.
    aparelho = models.TextField(null=True, blank=True)

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


class WhatsappInstancia(models.Model):
    """O numero da propria barbearia, do lado de ca da Evolution.

    Uma linha por barbearia com zap. Tabela SEPARADA de `Barbearia`, e nao
    colunas nela, pelo motivo escrito no campo `plano` la em cima: o runtime
    escreve aqui a cada webhook (estado novo, QR novo), e `tenant_barbearia`
    e' justamente a tabela que o runtime nao pode escrever.

    O que ela guarda e' CACHE de um estado que mora na Evolution. A fonte da
    verdade continua sendo o `connectionState` de la; esta tabela existe para
    o painel poder responder sem uma chamada de rede por pedido, e para a
    faixa de "desconectado" aparecer sem esperar ninguem perguntar.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    # OneToOne e nao ForeignKey: duas instancias para a mesma barbearia seriam
    # dois numeros falando com o mesmo cliente, e nenhum codigo saberia qual e'
    # o certo. O banco recusa antes de a pergunta existir.
    barbearia = models.OneToOneField(
        Barbearia, on_delete=models.RESTRICT, related_name="whatsapp",
    )
    # `marcai-<barbearia_id>`, e o nome e' a chave do lado da Evolution: e' por
    # ele que o webhook descobre de quem e' o evento. UNIQUE aqui para que um
    # nome repetido morra no INSERT, e nao mais tarde, com dois tenants
    # disputando o mesmo vinculo na Evolution.
    nome = models.TextField(unique=True)
    estado = models.CharField(
        max_length=20, choices=EstadoInstancia, default=EstadoInstancia.PENDENTE,
    )
    # O ultimo QR recebido, ja no formato `data:image/png;base64,...` que a
    # Evolution manda (medido na 2.3.7) — o painel o joga direto no `<img
    # src>`. Nulo fora de `AGUARDANDO_QR`: QR velho guardado depois de
    # conectar e' um convite a escanear um codigo morto.
    qr_base64 = models.TextField(null=True)
    numero_conectado = models.TextField(null=True)
    # Nulo enquanto conectado, preenchido na TRANSICAO para desconectado —
    # nunca reescrito enquanto continua caido. E' isso que faz a faixa do
    # painel dizer "desde 14:02" em vez de "desde agora" a cada conferencia.
    desconectado_desde = models.DateTimeField(null=True)
    # O interruptor do bot. Mora AQUI e nao em `Barbearia` porque quem liga e'
    # o dono, pelo painel, e o runtime (`brutus_app`) nao tem UPDATE em
    # `tenant_barbearia` (0002_rls.py). Nasce desligado.
    bot_ativo = models.BooleanField(default=False)
    atualizado_em = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.nome} ({self.estado})"


class MensagemNaoEnviada(models.Model):
    """A mensagem que o cliente NAO recebeu porque o WhatsApp da barbearia
    estava fora do ar.

    Nao e' fila: nada aqui e' reenviado depois, e isso foi decidido. Uma
    confirmacao que chega tres horas atrasada, depois que o cliente ja ligou
    para perguntar, e' pior que nenhuma. O que a linha compra e' o painel
    poder dizer "N mensagens nao enviadas" — o dono descobre a queda pelo
    prejuizo, nao so pela faixa.

    Sem `cliente_id`: guardar o NOME (o que o painel mostra) em vez da chave
    evita segurar uma FK viva por um registro que o `zelador` apaga em 7 dias.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="nao_enviadas",
    )
    tipo = models.CharField(max_length=20, choices=TipoMensagem)
    cliente_nome = models.TextField()
    criado_em = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.tipo} para {self.cliente_nome}"


class ConversaWhatsapp(models.Model):
    """Onde a conversa do bot com UM numero esta parada.

    Uma linha por conversa, sobrescrita a cada passo, e NAO uma por mensagem:
    uma tabela que crescesse por mensagem seria ilimitada e cheia de texto de
    cliente, e o Marcai nao guarda o que foi conversado (spec, secao 2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="conversas",
    )
    # 10 ou 11 digitos nacionais, na MESMA forma de `Cliente.whatsapp` — e'
    # por essa igualdade que o bot acha o cliente.
    whatsapp = models.TextField()
    estado = models.CharField(
        max_length=24, choices=EstadoConversa, default=EstadoConversa.MENU,
    )
    # O que o bot OFERECEU: [{"id": ..., "rotulo": ...}]. Entender "2" e'
    # `opcoes[1]`, sem consultar o banco.
    opcoes = models.JSONField(default=list)
    # O que ja foi decidido: servico_id, barbeiro_id, dia, inicio...
    rascunho = models.JSONField(default=dict)
    tentativas = models.IntegerField(default=0)
    # O texto da ultima pergunta. "Nao entendi" repete ESTE texto, com as MESMAS
    # opcoes — refazer a lista do banco podia mudar a numeracao embaixo do
    # cliente.
    pergunta = models.TextField(null=True)
    ultima_mensagem_id = models.TextField(null=True)
    # Os ids das mensagens que o bot mandou. O webhook devolve cada uma como
    # `fromMe`; sem reconhecer o proprio eco, o bot se calaria a cada resposta.
    ids_do_bot = models.JSONField(default=list)
    mudo_ate = models.DateTimeField(null=True)
    atualizado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["barbearia", "whatsapp"], name="conversa_por_numero",
            ),
        ]

    def __str__(self):
        return f"{self.whatsapp} ({self.estado})"


class ListaDoDiaEnviada(models.Model):
    """A ultima lista do dia que um barbeiro recebeu pelo numero central.

    Existe para a lista poder ser APAGADA quando a agenda de hoje muda: a
    Evolution so' apaga sabendo o id e o jid da mensagem. Uma linha por
    barbeiro por dia, sobrescrita a cada lista nova; o zelador poda as velhas.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="listas_enviadas",
    )
    # CASCADE, e nao RESTRICT como o resto: esta linha nao e' historico de
    # ninguem, so' o endereco da mensagem para a Evolution apagar. RESTRICT
    # segurava o barbeiro de teste no admin depois de tudo apagado, e ela nao
    # tem tela para ser apagada a mao (07/10/2026).
    barbeiro = models.ForeignKey(
        Barbeiro, on_delete=models.CASCADE, related_name="listas_enviadas",
    )
    # A data LOCAL (Sao Paulo) da lista — a mesma de `dia_de_hoje(agora)`.
    dia = models.DateField()
    mensagem_id = models.TextField()
    remote_jid = models.TextField()
    enviada_em = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("barbeiro", "dia"), name="lista_por_barbeiro_e_dia"),
        ]

    def __str__(self):
        return f"lista de {self.dia} ({self.mensagem_id})"


class FinalidadeCodigo(models.TextChoices):
    """Para que serve um `CodigoConta`: confirmar o WhatsApp de uma conta
    recem-criada, ou escolher senha nova (esqueci a senha)."""

    CONFIRMAR = "CONFIRMAR"
    NOVA_SENHA = "NOVA_SENHA"


class ContaCliente(models.Model):
    """A conta opcional e GLOBAL do cliente (spec 2026-10-20): uma por
    WhatsApp, valendo em todos os estabelecimentos. Fica fora do RLS, como
    `Barbearia`: nao tem `barbearia_id` e nao pertence a tenant nenhum — e' de
    quem a criou, e atravessa todos. Por isso o `brutus_app` le e escreve nela
    direto (GRANT padrao do init-db.sh), sem `com_barbearia`.

    O que protege a conta nao e' politica, e' o que ela guarda: so' o hash da
    senha, e o numero em `canonico()` (tenant/telefone.py). Quem a enxerga por
    dentro de um tenant faz isso pela funcao `barbearias_do_whatsapp`, que
    devolve ids e mais nada.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    nome = models.TextField()
    # Unico no sistema inteiro: uma conta por numero, em `canonico()`.
    whatsapp = models.TextField(unique=True)
    senha_hash = models.TextField()
    # Nulo ate o cliente provar o numero com o codigo. Conta nao confirmada
    # nao entra e nao ve historico.
    confirmada_em = models.DateTimeField(null=True, blank=True)
    # Sobe quando a senha muda: derruba toda sessao emitida antes.
    token_version = models.IntegerField(default=0)
    criado_em = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.nome} ({self.whatsapp})"


class CodigoConta(models.Model):
    """Codigo de 6 digitos (ou token de link) mandado pelo WhatsApp. Fora do
    RLS pelo mesmo motivo de `ContaCliente`: pertence a conta, que e' global.

    So' o HASH e' guardado, nunca o codigo nem o token. `hash` tem indice e
    NAO e' unico: o de 6 digitos leva o id da conta junto
    (`hash_de_convite(f"{conta_id}:{codigo}")`) e e' procurado dentro da conta;
    o do link e' o hash do token, procurado direto. O que segura um chute e'
    `tentativas` mais `expira_em`, nao a unicidade.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    conta = models.ForeignKey(
        ContaCliente, on_delete=models.CASCADE, related_name="codigos",
    )
    finalidade = models.CharField(max_length=20, choices=FinalidadeCodigo)
    hash = models.TextField(db_index=True)
    expira_em = models.DateTimeField()
    tentativas = models.IntegerField(default=0)
    usado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.finalidade} de {self.conta_id}"


class Custo(models.Model):
    """Um gasto que o dono lanca no resumo: o valor e, se quiser, um nome.

    Sem campo de data de proposito (decisao do dono): o custo vale no dia em
    que foi lancado, e e' `criado_em` que o resumo usa para dizer de que
    periodo ele e'. So' registro — nao entra na conta do faturamento.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="custos",
    )
    nome = models.TextField(null=True, blank=True)
    valor_centavos = models.IntegerField()
    criado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valor_centavos__gt=0), name="custo_valor_positivo",
            ),
        ]

    def __str__(self):
        return f"{self.nome or 'Custo'} ({self.valor_centavos})"


class Assinatura(models.Model):
    """A mensalidade que a barbearia paga ao Marcai. Uma por barbearia.

    FORA do RLS, como `tenant_barbearia`: a busca de centavos livres atravessa
    barbearias, e quem le e' o middleware que decide se o painel trava. Quem
    protege e' o GRANT (a migration revoga INSERT/UPDATE/DELETE do
    `brutus_app`): leitura e escrita de verdade so' pelo alias `admin`, e todo
    acesso filtra por barbearia no codigo.

    Barbearia SEM linha aqui vale como isenta — dado torto nunca trava painel.
    """

    barbearia = models.OneToOneField(
        Barbearia, on_delete=models.RESTRICT, primary_key=True, related_name="assinatura",
    )
    valor_centavos = models.PositiveIntegerField(default=0)
    # 1 a 28: todo mes tem esse dia.
    dia_de_vencimento = models.PositiveSmallIntegerField()
    paga_ate = models.DateField()
    isenta = models.BooleanField(default=False)
    nunca_bloquear = models.BooleanField(default=False)
    # Qual aviso de vencimento ja foi dado e para qual `paga_ate`, para nao
    # repetir o mesmo aviso a cada tique.
    ultimo_aviso = models.TextField(blank=True, default="")
    ultimo_aviso_paga_ate = models.DateField(null=True, blank=True)
    atualizada_em = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"assinatura de {self.barbearia_id} (paga ate {self.paga_ate})"


class Cobranca(models.Model):
    """Um Pix pedido: mensalidade (etapa 1) ou sinal de agendamento (etapa 2).

    Fora do RLS, pelo mesmo motivo da `Assinatura`. O valor cobrado e' a base
    mais 1 a 99 centavos, o menor livre para a mesma chave entre cobrancas
    ABERTAS: e' isso que deixa o vigia casar o Pix recebido com a cobranca.
    O indice unico parcial abaixo e' a garantia no banco; a busca e' otimista.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="cobrancas",
    )
    motivo = models.TextField(choices=MotivoCobranca.choices)
    # Ja normalizada (a mesma forma do `copia_e_cola`).
    chave_pix = models.TextField()
    valor_base_centavos = models.PositiveIntegerField()
    valor_centavos = models.PositiveIntegerField()
    copia_e_cola = models.TextField()
    status = models.TextField(choices=StatusCobranca.choices, default=StatusCobranca.ABERTA)
    criada_em = models.DateTimeField(default=timezone.now)
    expira_em = models.DateTimeField(null=True, blank=True)
    informada_em = models.DateTimeField(null=True, blank=True)
    # O barbeiro apagado nao leva a cobranca junto: quem zera a coluna e' o
    # BANCO (FK feita a mao na 0016, ON DELETE SET NULL; por isso
    # `db_constraint=False`, ou o Django criaria outra, sem a acao). `SET_NULL` do Django faria o
    # coletor dar UPDATE em `tenant_cobranca` como `brutus_app`, que nao tem
    # esse direito — e apagar barbeiro pelo admin do Django estourava.
    informada_por = models.ForeignKey(
        Barbeiro, on_delete=models.DO_NOTHING, null=True, blank=True, related_name="+",
        db_constraint=False,
    )
    recusada_em = models.DateTimeField(null=True, blank=True)
    paga_em = models.DateTimeField(null=True, blank=True)
    como_foi_paga = models.TextField(choices=ComoFoiPaga.choices, null=True, blank=True)
    paga_ate_depois = models.DateField(null=True, blank=True)
    observacao = models.TextField(blank=True, default="")
    # So' a cobranca da InfinitePay usa: o link do checkout que a tela abre e
    # o `transaction_nsu` e o `invoice_slug` do primeiro aviso, sem os quais o
    # `payment_check` nao tem como conferir depois.
    link_pagamento = models.TextField(blank=True, default="")
    ip_transacao = models.TextField(blank=True, default="")
    ip_fatura = models.TextField(blank=True, default="")
    # Pagamento tirado do historico pelo admin. A linha fica (um clique errado
    # nao perde nada); so' some da tela e do "ultima paga". O `paga_ate` da
    # assinatura nao volta: corrigir a data e' outro botao.
    removida_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("chave_pix", "valor_centavos"),
                condition=models.Q(status="ABERTA"),
                name="cobranca_aberta_por_chave_e_valor",
            ),
        ]

    def __str__(self):
        return f"cobranca {self.valor_centavos} ({self.status})"
