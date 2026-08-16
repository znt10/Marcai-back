from django.db import models
from django.utils import timezone


class Barbearia(models.Model):
    """A tabela de tenant. Unica sem barbeariaId e unica fora do RLS — ela e
    lida ANTES de existir tenant, para traduzir subdominio em id, e por isso e
    protegida por GRANT (REVOKE INSERT/UPDATE/DELETE) e nao por politica.
    """

    # TextField, nao UUIDField: o Prisma declara `id String @id @default(uuid())`
    # sem `@db.Uuid` (front/prisma/schema.prisma:29) — o valor e um uuid, a
    # coluna e TEXT, e as duas coisas nao sao a mesma. UUIDField faz o psycopg3
    # mandar o parametro tipado como `uuid` (dumper com oid=UUID_OID); INSERT
    # passa porque uuid->text e cast de atribuicao, mas um `filter(id=...)`
    # compara `text = uuid`, que nao resolve, e o WHERE nao acha nada.
    id = models.TextField(primary_key=True, db_column="id")
    slug = models.TextField(unique=True, db_column="slug")
    nome = models.TextField(db_column="nome")
    endereco = models.TextField(db_column="endereco")
    # Nulo ate o DONO preencher: o admin da plataforma nao sabe o horario da
    # barbearia. Nulo e string vazia seriam dois jeitos de dizer a mesma coisa.
    horario_resumo = models.TextField(null=True, db_column="horarioResumo")
    whatsapp_contato = models.TextField(db_column="whatsappContato")
    # `default=True`/`default=timezone.now` espelham `@default(true)` e
    # `@default(now())` do Prisma — mesmo motivo de `Barbeiro.ativo` (fatia
    # 4): o Django manda TODAS as colunas declaradas no INSERT de um model
    # managed=False, entao sem eles o cadastro de barbearia (bloco B da
    # travessia, `POST /api/admin/barbearias`) mandaria NULL contra colunas
    # NOT NULL. Nenhuma fatia anterior CRIAVA Barbearia pelo Django — so lia
    # — entao o buraco nunca disparou ate agora.
    ativo = models.BooleanField(db_column="ativo", default=True)
    criado_em = models.DateTimeField(db_column="criadoEm", default=timezone.now)

    class Meta:
        managed = False
        db_table = "Barbearia"


class Barbeiro(models.Model):
    """Existe nesta fatia por um motivo so: e a tabela de tenant que o teste de
    RLS conta para provar que o escopo funciona. Os campos que a fatia 1 vai
    precisar entram la.
    """

    # TextField pelo mesmo motivo de Barbearia.id acima: a coluna do Prisma e
    # TEXT, e UUIDField mandaria o parametro tipado `uuid` contra uma coluna
    # `text` — o INSERT passa (uuid->text e cast de atribuicao) mas o
    # `filter(barbearia_id=...)` nao, porque `text = uuid` nao resolve. Esta
    # e a coluna sobre a qual o teste de isolamento de RLS e construido.
    id = models.TextField(primary_key=True, db_column="id")
    barbearia_id = models.TextField(db_column="barbeariaId")
    nome = models.TextField(db_column="nome")
    whatsapp = models.TextField(db_column="whatsapp")
    # `default=True` espelha o `@default(true)` do Prisma — achado na fatia 4:
    # nenhuma fatia anterior CRIAVA Barbeiro pelo Django (so lia), entao o
    # buraco (Django manda todas as colunas declaradas no INSERT; sem default
    # aqui, `ativo` viraria NULL contra uma coluna NOT NULL) nunca disparou
    # ate a rota de equipe cadastrar o primeiro barbeiro novo.
    ativo = models.BooleanField(db_column="ativo", default=True)
    # Os dois que a fatia 1 pediu. `foto_url` e nulavel no Prisma
    # (`fotoUrl String?`); `ordem` tem default 0 e e a chave de ordenacao da
    # lista publica. Nenhum dos dois e senha, whatsapp ou token — o que sai
    # daqui para o cliente e so id, nome e foto (§9.1).
    foto_url = models.TextField(null=True, db_column="fotoUrl")
    # `default=0` espelha o `@default(0)` do Prisma, e nao e conveniencia: o
    # Django manda TODAS as colunas no INSERT de um model managed=False, entao
    # sem default aqui um `Barbeiro.objects.create(...)` que nao cite `ordem`
    # manda NULL explicito e leva NOT NULL violation — o default do banco so
    # vale quando a coluna e OMITIDA da instrucao, e ela nunca e.
    ordem = models.IntegerField(db_column="ordem", default=0)

    # ---- A sessao (fatia 2) ----
    #
    # Nenhum destes sai em resposta nenhuma. Eles existem para que o login e o
    # convite possam ser DECIDIDOS aqui; o que o cliente ve continua sendo o
    # que o serializer lista, e ele nao lista nenhum deles.
    #
    # Todos com o mesmo default do Prisma pelo motivo ja explicado em `ordem`:
    # o Django manda TODAS as colunas declaradas no INSERT de um model
    # managed=False, entao um default que so exista no banco nunca e aplicado.
    #
    # `papel` e um ENUM no Postgres (`PapelBarbeiro`), nao um text. Fica
    # TextField mesmo assim porque o psycopg3 manda `str` como `unknown`, e o
    # Postgres resolve `unknown` para o tipo da coluna — o mesmo mecanismo que
    # faz `INSERT ... VALUES ('DONO')` funcionar. Um CharField com choices nao
    # mudaria nada no fio e so acrescentaria uma segunda lista de valores para
    # sair de sincronia com o schema.prisma.
    papel = models.TextField(db_column="papel", default="BARBEIRO")
    # Nulo ate o convite ser aceito: o admin cria o dono SEM senha, e o
    # `senhaHash` nulo e o que a rota do login tem que recusar sem revelar que
    # o numero existe.
    senha_hash = models.TextField(null=True, db_column="senhaHash")
    # O que faz "desligar o barbeiro" derrubar a sessao dele na hora. O numero
    # viaja dentro do cookie (`tv`) e e conferido contra a coluna a cada
    # pedido; incrementa-lo invalida todo cookie ja emitido sem que exista
    # lista de sessao nenhuma para varrer.
    token_version = models.IntegerField(db_column="tokenVersion", default=0)
    convite_token_hash = models.TextField(null=True, db_column="conviteTokenHash")
    convite_expira_em = models.DateTimeField(null=True, db_column="conviteExpiraEm")
    tentativas_login = models.IntegerField(db_column="tentativasLogin", default=0)
    bloqueado_ate = models.DateTimeField(null=True, db_column="bloqueadoAte")
    # Os dois que a fatia 4 (equipe) precisa. `desativado_em` nulo ate
    # desativar, de novo nulo ao reativar — a mesma logica de "ausencia e o
    # estado" do resto do schema. `criado_em` precisa de `default=timezone.now`
    # porque o cadastro de barbeiro (equipe POST) CRIA a linha, e o Django
    # manda todas as colunas declaradas no INSERT — sem default aqui a criacao
    # mandaria NULL contra uma coluna NOT NULL.
    desativado_em = models.DateTimeField(null=True, db_column="desativadoEm")
    criado_em = models.DateTimeField(db_column="criadoEm", default=timezone.now)

    class Meta:
        managed = False
        db_table = "Barbeiro"


class Servico(models.Model):
    """Lido pela fatia 1 apenas como FILTRO: um barbeiro sem servico ativo nao
    aparece na lista publica.

    As duas duracoes sao declaradas mesmo sem ninguem AINDA as ler, e isso e
    obrigatorio, nao zelo: as colunas sao NOT NULL sem default no banco, e o
    Django so escreve as colunas que o model declara — um model sem elas nao
    consegue INSERIR um Servico, e o proprio teste desta rota precisa criar um.
    """

    # TextField pelo mesmo motivo de Barbearia.id: a coluna do Prisma e TEXT.
    id = models.TextField(primary_key=True, db_column="id")
    barbearia_id = models.TextField(db_column="barbeariaId")
    nome = models.TextField(db_column="nome")
    duracao_minima_min = models.IntegerField(db_column="duracaoMinimaMin")
    duracao_sugerida_min = models.IntegerField(db_column="duracaoSugeridaMin")
    # Defaults espelhando o Prisma pelo mesmo motivo de Barbeiro.ordem acima.
    ativo = models.BooleanField(db_column="ativo", default=True)
    ordem = models.IntegerField(db_column="ordem", default=0)

    class Meta:
        managed = False
        db_table = "Servico"


class BarbeiroServico(models.Model):
    """O vinculo. No Prisma a chave primaria e COMPOSTA (`@@id([barbeiroId,
    servicoId])`) e o Django nao suporta isso em model managed=False — ele
    exige uma pk de uma coluna so.

    `barbeiro` como primary_key=True e a saida honesta: nao muda o banco (nada
    de DDL, o Prisma segue dono), e da ao Django uma pk de uma coluna. A
    consequencia REAL e que `BarbeiroServico.objects.get(pk=...)` devolveria um
    vinculo arbitrario quando o mesmo barbeiro tem varios servicos — por isso
    esta classe existe so para ser ALVO de subquery (`filter(...).values(...)`),
    nunca para busca por pk. Se um dia alguem precisar buscar o vinculo em si,
    o caminho e filtrar pelos dois campos, nao por pk.
    """

    barbeiro = models.ForeignKey(
        "Barbeiro",
        on_delete=models.DO_NOTHING,
        db_column="barbeiroId",
        primary_key=True,
        related_name="vinculos",
    )
    servico = models.ForeignKey(
        "Servico", on_delete=models.DO_NOTHING, db_column="servicoId",
        related_name="vinculos",
    )
    barbearia_id = models.TextField(db_column="barbeariaId")
    duracao_min = models.IntegerField(db_column="duracaoMin")
    # Nulo ate o barbeiro decidir — sem `default=`, de proposito: ao
    # contrario de `duracao_min` (que sempre tem um valor resolvido, a
    # sugerida do servico quando falta o praticado), preco nao tem
    # sugestao nenhuma pra herdar do catalogo. Quem cobra e' o barbeiro.
    preco_centavos = models.IntegerField(db_column="precoCentavos", null=True)
    ativo = models.BooleanField(db_column="ativo", default=True)

    class Meta:
        managed = False
        db_table = "BarbeiroServico"


class HorarioTrabalho(models.Model):
    """A jornada semanal do barbeiro. Sem linha para um dia da semana, aquele
    dia nao gera horario nenhum — fechar e APAGAR a linha, nao gravar uma de
    duracao zero (spec 4). Por isso o motor trata "nao achei jornada" e "achei
    jornada vazia" como o mesmo nada.

    `dia_semana` guarda o que o `getDay()` do JavaScript produz: DOMINGO = 0.
    Ver `dia_semana_de` em tenant/datas.py — e a conversao que o Python erra
    por padrao.
    """

    id = models.TextField(primary_key=True, db_column="id")
    barbearia_id = models.TextField(db_column="barbeariaId")
    barbeiro = models.ForeignKey(
        "Barbeiro", on_delete=models.DO_NOTHING, db_column="barbeiroId",
        related_name="horarios",
    )
    dia_semana = models.IntegerField(db_column="diaSemana")
    minutos_inicio = models.IntegerField(db_column="minutosInicio")
    minutos_fim = models.IntegerField(db_column="minutosFim")

    class Meta:
        managed = False
        db_table = "HorarioTrabalho"


class Bloqueio(models.Model):
    """Duas formas na MESMA tabela, e o motor le uma OU a outra:

    - semanal: `repete_semanalmente=True` + dia da semana e minutos;
    - pontual: `inicio` e `fim` em instantes.

    Os campos da forma nao usada ficam nulos. Gravar as duas juntas produziria
    uma linha cuja interpretacao depende de qual campo alguem leu primeiro —
    e o sintoma seria horario sumido sem explicacao. Quem recusa isso e a
    validacao do painel; aqui embaixo o motor confia no que esta gravado.

    `criado_em` NAO e declarado de proposito: ele tem `@default(now())` no
    Prisma, e o default do banco so vale quando a coluna e OMITIDA da
    instrucao. Como o Django manda todas as colunas declaradas, declara-lo
    obrigaria a inventar um default aqui tambem — duas fontes para a mesma
    data. O mesmo vale para `observacao`, que ninguem deste lado le ainda.
    """

    id = models.TextField(primary_key=True, db_column="id")
    barbearia_id = models.TextField(db_column="barbeariaId")
    barbeiro = models.ForeignKey(
        "Barbeiro", on_delete=models.DO_NOTHING, db_column="barbeiroId",
        related_name="bloqueios",
    )
    # ENUM `MotivoBloqueio` no Postgres (ALMOCO|FOLGA|PESSOAL|OUTRO), TextField
    # aqui pelo mesmo motivo de `Barbeiro.papel`: o psycopg manda `str` como
    # `unknown` e o Postgres resolve para o tipo da coluna.
    motivo = models.TextField(db_column="motivo", default="OUTRO")
    repete_semanalmente = models.BooleanField(db_column="repeteSemanalmente")
    dia_semana = models.IntegerField(null=True, db_column="diaSemana")
    minutos_inicio = models.IntegerField(null=True, db_column="minutosInicio")
    minutos_fim = models.IntegerField(null=True, db_column="minutosFim")
    inicio = models.DateTimeField(null=True, db_column="inicio")
    fim = models.DateTimeField(null=True, db_column="fim")
    # Os dois que a fatia 4 (expediente) le: `observacao` no GET do painel e
    # `criado_em` como desempate na listagem (bloqueio semanal antes do
    # pontual, e dentro de cada grupo o mais antigo primeiro). `criado_em`
    # ganha default pelo mesmo motivo do Barbeiro acima: POST /bloqueios cria
    # a linha.
    observacao = models.TextField(null=True, db_column="observacao")
    criado_em = models.DateTimeField(db_column="criadoEm", default=timezone.now)

    class Meta:
        managed = False
        db_table = "Bloqueio"


class Cliente(models.Model):
    """Sem cadastro e sem senha: o cliente e identificado pelo WhatsApp dentro
    da barbearia (`@@unique([barbeariaId, whatsapp])`). Entra aqui como alvo da
    FK obrigatoria de `Agendamento` — nenhuma rota desta fatia o le.
    """

    id = models.TextField(primary_key=True, db_column="id")
    barbearia_id = models.TextField(db_column="barbeariaId")
    nome = models.TextField(db_column="nome")
    whatsapp = models.TextField(db_column="whatsapp")

    class Meta:
        managed = False
        db_table = "Cliente"


class Agendamento(models.Model):
    """O horario marcado. Nesta fatia ele e lido so como OCUPACAO — o que a
    grade precisa saber e que aquele intervalo nao esta livre.

    `servico_nome` e gravado junto e nao vem por join de proposito (decisao do
    schema): renomear um servico depois nao pode reescrever o historico do que
    foi vendido.

    So `CONFIRMADO` ocupa. Um cancelado que continuasse ocupando deixaria o
    horario morto na agenda ate o fim do dia — o pior tipo de defeito aqui,
    porque a barbearia perde dinheiro e nada aparece na tela.
    """

    id = models.TextField(primary_key=True, db_column="id")
    barbearia_id = models.TextField(db_column="barbeariaId")
    codigo = models.TextField(unique=True, db_column="codigo")
    barbeiro = models.ForeignKey(
        "Barbeiro", on_delete=models.DO_NOTHING, db_column="barbeiroId",
        related_name="agendamentos",
    )
    cliente = models.ForeignKey(
        "Cliente", on_delete=models.DO_NOTHING, db_column="clienteId",
        related_name="agendamentos",
    )
    servico = models.ForeignKey(
        "Servico", on_delete=models.DO_NOTHING, db_column="servicoId",
        related_name="agendamentos",
    )
    servico_nome = models.TextField(db_column="servicoNome")
    inicio = models.DateTimeField(db_column="inicio")
    fim = models.DateTimeField(db_column="fim")
    duracao_min = models.IntegerField(db_column="duracaoMin")
    # Snapshot do preco praticado no momento de marcar — mesma razao de
    # `servico_nome`/`duracao_min`: repreçar depois nao pode reescrever
    # quanto um agendamento passado custou. Nulo quando o barbeiro nao
    # tinha preco definido pra aquele servico na hora de marcar.
    preco_centavos = models.IntegerField(db_column="precoCentavos", null=True)
    status = models.TextField(db_column="status", default="CONFIRMADO")
    # So a fatia 4 (cancelamento pelo painel) escreve nesta coluna. Nulo na
    # criacao (omitida do INSERT quando a chamada nao a cita, ver Bloqueio),
    # gravada com o instante do cancelamento no update de status.
    cancelado_em = models.DateTimeField(null=True, db_column="canceladoEm")
    # Nulo ate o AGENDAR decidir: marcar dentro da janela do lembrete grava
    # `agora` aqui na criacao (a confirmacao JA e' o lembrete), e o cron
    # (fatia futura) nunca ve esse agendamento.
    lembrete_enviado_em = models.DateTimeField(null=True, db_column="lembreteEnviadoEm")

    class Meta:
        managed = False
        db_table = "Agendamento"
