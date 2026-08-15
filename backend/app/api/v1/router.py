from django.urls import path

from .views.admin_autenticacao import AdminLoginView, AdminLogoutView
from .views.admin_barbearias import (
    AdminBarbeariaConviteView,
    AdminBarbeariaDetalheView,
    AdminBarbeariasView,
)
from .views.agenda_painel import AgendaPainelView
from .views.agendamentos_painel import AgendamentoCancelarView, AgendamentosPainelView
from .views.autenticacao import ConviteView, EuView, LoginView, LogoutView
from .views.barbearia_painel import BarbeariaPainelView
from .views.barbeiro_servicos import BarbeiroServicosView
from .views.barbeiros import BarbeirosView
from .views.bloqueios import BloqueioDetalheView, BloqueiosView
from .views.conflitos import ConflitosView
from .views.dia import DiaView
from .views.equipe import (
    EquipeConviteView,
    EquipeDesativarView,
    EquipeDetalheView,
    EquipeReativarView,
    EquipeView,
)
from .views.expediente import ExpedienteView
from .views.horarios import DiasComVagaView, HorariosView
from .views.servicos import ServicosView
from .views.servicos_painel import ServicoPainelDetalheView, ServicosPainelView

# SEM DefaultRouter, e isso e uma decisao, nao esquecimento.
#
# O DefaultRouter gera `^barbeiros/$` — COM barra final. O front monta a URL
# como `baseDe(caminho) + caminho`, e o caminho e `/barbeiros`, sem barra. Com
# rota so na versao barrada, o Django responderia 301 para a barrada, e um 301
# atravessando origem (3000 -> 8000) com `credentials: 'include'` e exatamente
# o tipo de coisa que funciona no curl e falha no navegador.
#
# Casar o caminho ao pe da letra e mais barato que descobrir isso depois. Pelo
# mesmo motivo o item 1 do card manda tirar a barra final das entradas do
# MIGRADAS: os dois lados concordam em nao ter barra.
#
# O pacote se chama v1 mas o prefixo publico e so `/api/`: a versao esta na
# ORGANIZACAO do codigo, nao na URL, porque a URL e contrato com o front que
# ja existe e nao pode mudar durante a travessia.
urlpatterns = [
    path("barbeiros", BarbeirosView.as_view(), name="barbeiros"),
    path("servicos", ServicosView.as_view(), name="servicos"),
    path("horarios", HorariosView.as_view(), name="horarios"),
    path("dias-com-vaga", DiasComVagaView.as_view(), name="dias-com-vaga"),
    # A sessao (fatia 2). As quatro atravessam JUNTAS e nao ha como separa-las:
    # o `MIGRADAS` casa por prefixo, e `/auth` pega as quatro de uma vez.
    # Tentar migrar so o login deixaria o `/auth/eu` no Next lendo um cookie
    # emitido pelo Django — o que funciona (o segredo e o mesmo), mas esconde
    # um erro de configuracao de segredo ate a hora errada.
    #
    # `/auth` NAO colide com `/admin/auth/login`: aquele caminho comeca com
    # `/admin`, e o `BarreiraAdminMiddleware` o trata muito antes.
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/eu", EuView.as_view(), name="auth-eu"),
    # `<str:token>` e nao `<path:token>`: o token e base64url, que nunca tem
    # barra. `path:` engoliria barras e faria `/auth/convite/a/b` casar, o que
    # so serviria para transformar um erro de digitacao em uma busca a mais.
    path("auth/convite/<str:token>", ConviteView.as_view(), name="auth-convite"),
    # Fatia 4, bloco 1 — catalogo e vinculos. `CrivoPainelMiddleware` ja
    # protege tudo sob `/api/painel/*` por POSICAO; estas views herdam
    # `ExigeSessao` so para ganhar `self.sessao`/`self.papel` sem consulta
    # nova, nao para repetir a checagem de autenticacao.
    path("painel/servicos", ServicosPainelView.as_view(), name="painel-servicos"),
    path(
        "painel/servicos/<str:id>",
        ServicoPainelDetalheView.as_view(),
        name="painel-servicos-detalhe",
    ),
    path(
        "painel/barbeiro-servicos",
        BarbeiroServicosView.as_view(),
        name="painel-barbeiro-servicos",
    ),
    # Fatia 4, bloco 2 — expediente e bloqueios.
    path("painel/expediente", ExpedienteView.as_view(), name="painel-expediente"),
    path("painel/bloqueios", BloqueiosView.as_view(), name="painel-bloqueios"),
    path(
        "painel/bloqueios/<str:id>",
        BloqueioDetalheView.as_view(),
        name="painel-bloqueios-detalhe",
    ),
    # Fatia 4, bloco 3 — equipe. So o dono, nas cinco.
    path("painel/equipe", EquipeView.as_view(), name="painel-equipe"),
    path("painel/equipe/<str:id>", EquipeDetalheView.as_view(), name="painel-equipe-detalhe"),
    path(
        "painel/equipe/<str:id>/desativar",
        EquipeDesativarView.as_view(),
        name="painel-equipe-desativar",
    ),
    path(
        "painel/equipe/<str:id>/reativar",
        EquipeReativarView.as_view(),
        name="painel-equipe-reativar",
    ),
    path(
        "painel/equipe/<str:id>/convite",
        EquipeConviteView.as_view(),
        name="painel-equipe-convite",
    ),
    # Fatia 4, bloco 4 — agenda, quadro do dia, conflitos, agendamentos e a
    # frase de horario da barbearia.
    path("painel/agenda", AgendaPainelView.as_view(), name="painel-agenda"),
    path("painel/dia", DiaView.as_view(), name="painel-dia"),
    path("painel/conflitos", ConflitosView.as_view(), name="painel-conflitos"),
    path(
        "painel/agendamentos", AgendamentosPainelView.as_view(), name="painel-agendamentos",
    ),
    path(
        "painel/agendamentos/<str:id>/cancelar",
        AgendamentoCancelarView.as_view(),
        name="painel-agendamentos-cancelar",
    ),
    path("painel/barbearia", BarbeariaPainelView.as_view(), name="painel-barbearia"),
    # Fecha a travessia, bloco A — sessao do admin da plataforma. So estas
    # duas rotas chegam aqui de qualquer host que nao seja o do admin
    # tambem por posicao: a `BarreiraAdminMiddleware` da 404 antes.
    path("admin/auth/login", AdminLoginView.as_view(), name="admin-auth-login"),
    path("admin/auth/logout", AdminLogoutView.as_view(), name="admin-auth-logout"),
    # Bloco B — as barbearias em si. `ExigeAdmin` em cada view: o host ja e'
    # o do admin (a BarreiraAdminMiddleware garante por posicao), mas a
    # SESSAO ainda precisa ser conferida — o host certo nao e' credencial.
    path("admin/barbearias", AdminBarbeariasView.as_view(), name="admin-barbearias"),
    path(
        "admin/barbearias/<str:id>",
        AdminBarbeariaDetalheView.as_view(),
        name="admin-barbearias-detalhe",
    ),
    path(
        "admin/barbearias/<str:id>/convite",
        AdminBarbeariaConviteView.as_view(),
        name="admin-barbearias-convite",
    ),
]
