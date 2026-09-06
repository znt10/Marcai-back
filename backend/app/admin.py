"""Os ModelAdmin do admin do Django (spec de 06/09/2026).

Mora em `app/` e nao em `tenant/`: `tenant/` e' o pacote dos models e do RLS, e
`app/` e' a superficie.

O ESCOPO NAO ESTA AQUI. Nenhum `get_queryset` filtra por barbearia, e isso e'
deliberado: quem filtra e' a politica de RLS do Postgres, com a variavel que o
`AdminDjangoMiddleware` define por requisicao. A consequencia boa e' que um
ModelAdmin acrescentado amanha, por alguem que nunca ouviu falar de tenant, ja
nasce enxergando so' a barbearia escolhida.

**Por que `BarbeiroServico` nao aparece aqui.** `tenant.models.BarbeiroServico`
declara `pk = models.CompositePrimaryKey("barbeiro", "servico")`, e o Django
recusa registrar model de PK composta no admin — nao e' um limite deste
arquivo, e' `django/contrib/admin/sites.py` (Django 6.0.3), linhas 117-121:

    if model._meta.is_composite_pk:
        raise ImproperlyConfigured(
            "The model %s has a composite primary key, so it cannot be "
            "registered with admin." % model.__name__
        )

Isso estoura no IMPORT deste modulo (o `@admin.register` roda na carga da
classe), entao registrar `BarbeiroServico` aqui nao quebraria so' os testes
desta tarefa — derrubaria a suite inteira e o processo do Django nao subiria,
porque `admin.autodiscover()` roda antes de qualquer view responder. Por isso
o import de `BarbeiroServico` fica de fora tambem, e nao so' o registro: um
import sem uso denunciaria a omissao errado, como descuido.

A consequencia pratica: o vinculo barbeiro-servico (preco, duracao) continua
sem tela no admin do Django. Quem precisar mexer nisso usa o painel custom ou
a API, como ja fazia antes desta tarefa — nada aqui piora esse caminho, so'
deixa de abrir um atalho que o Django nao permite abrir.

**Sobre o `<select>` de `barbearia` nos formularios abaixo.** `Barbearia` esta
fora do RLS (e' lida antes de existir tenant), entao o campo `barbearia` de
`Barbeiro`, `Servico`, `Cliente`, `Agendamento`, `HorarioTrabalho` e `Bloqueio`
renderiza um <select> com TODAS as barbearias, nao so' a escolhida. Decisao:
nenhum destes campos vira `readonly_fields` aqui. Tornar `barbearia` readonly
tiraria o campo do formulario de CRIACAO tambem (nao so' do de edicao), e sem
ele nao da' para criar um Cliente ou Agendamento novo pelo admin — pior que o
risco que se estaria evitando. Quem tentar mover um registro para outra
barbearia esbarra no `WITH CHECK` da politica de RLS no banco, que recusa o
UPDATE/INSERT; o preco e' um erro do Postgres estourando como 500 em vez de
uma mensagem de formulario, mas quem esta neste admin e' o dono da plataforma,
nao um usuario final, e o dado nunca chega a trocar de dono.
"""

from django.contrib import admin

from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    Bloqueio,
    Cliente,
    HorarioTrabalho,
    Servico,
)


class Base(admin.ModelAdmin):
    """Base comum dos ModelAdmin de tenant.

    Antes ela se chamava `SemApagar` e desligava `has_delete_permission`. O
    dono da plataforma pediu o admin com TUDO ativo, e a decisao e' dele: e' a
    ferramenta dele, e um admin que esconde metade dos botoes obriga a sair
    dele para fazer o trabalho — que era exatamente o problema que ele veio
    resolver.

    O que continua valendo, e nao depende de botao: apagar aqui e' apagar de
    verdade, sem confirmacao de negocio. Apagar um cliente leva junto o
    historico dele (as chaves estrangeiras sao ON DELETE CASCADE), e nao ha
    desfazer. O aviso mora aqui porque a tela nao o da'.
    """


@admin.register(Barbearia)
class BarbeariaAdmin(admin.ModelAdmin):
    """Editavel, a pedido do dono da plataforma — com uma ressalva que a tela
    nao consegue dar.

    **Criar barbearia por aqui produz uma barbearia ORFA.** No painel custom,
    criar e' UMA transacao que faz tres coisas: a barbearia, o barbeiro DONO
    dela, e o token de convite que permite esse dono entrar. O "adicionar" do
    Django faz o primeiro INSERT e mais nada — sobra uma barbearia sem dono e
    sem convite, em que ninguem consegue entrar, e o conserto e' pelo banco.

    Para CRIAR, use o painel da plataforma. Para olhar, corrigir um nome, um
    endereco ou desligar o `ativo`, aqui serve e e' mais direto.

    `Barbearia` e' a unica das oito tabelas de tenant fora do RLS (e' lida
    antes de existir tenant, no `TenantMiddleware`), entao esta lista mostra
    TODAS as barbearias, nao so' a escolhida.
    """

    list_display = ("slug", "nome", "ativo", "criado_em")
    search_fields = ("slug", "nome")


@admin.register(Barbeiro)
class BarbeiroAdmin(Base):
    list_display = ("nome", "whatsapp", "papel", "ativo", "ordem")
    list_filter = ("papel", "ativo")
    search_fields = ("nome", "whatsapp")
    # Nenhum destes sai em resposta nenhuma da API (spec 9.1), e aqui eles sao
    # so' leitura: mexer em hash de senha ou em token de convite pela mao
    # arrisca deixar o barbeiro fora da propria conta sem nada explicar.
    readonly_fields = ("senha_hash", "convite_token_hash", "token_version")


@admin.register(Cliente)
class ClienteAdmin(Base):
    list_display = ("nome", "whatsapp", "criado_em")
    search_fields = ("nome", "whatsapp")


@admin.register(Agendamento)
class AgendamentoAdmin(Base):
    list_display = ("inicio", "fim", "servico_nome", "status", "barbeiro", "cliente")
    list_filter = ("status",)
    # `codigo` e' o token de URL publica: trocar a mao invalidaria o link que o
    # cliente ja tem em maos.
    readonly_fields = ("codigo",)


@admin.register(Servico)
class ServicoAdmin(Base):
    list_display = ("nome", "duracao_minima_min", "duracao_sugerida_min", "ativo", "ordem")
    list_filter = ("ativo",)


@admin.register(HorarioTrabalho)
class HorarioTrabalhoAdmin(Base):
    list_display = ("barbeiro", "dia_semana", "minutos_inicio", "minutos_fim")


@admin.register(Bloqueio)
class BloqueioAdmin(Base):
    list_display = ("barbeiro", "motivo", "repete_semanalmente", "inicio", "fim")
    list_filter = ("motivo", "repete_semanalmente")
