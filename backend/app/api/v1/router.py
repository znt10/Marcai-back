from django.urls import path

from .views.autenticacao import ConviteView, EuView, LoginView, LogoutView
from .views.barbeiro_servicos import BarbeiroServicosView
from .views.barbeiros import BarbeirosView
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
]
