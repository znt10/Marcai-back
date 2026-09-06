from django.contrib import admin
from django.urls import include, path

from tenant import views

urlpatterns = [
    path("api/saude", views.saude, name="saude"),
    # A superficie da travessia. Prefixo `api/` sem barra depois de
    # `barbeiros`: o front monta `origem + '/api' + '/barbeiros'`, e casar ao
    # pe da letra evita o 301 que quebraria o pedido credenciado no navegador
    # (ver app/api/v1/router.py).
    path("api/", include("app.api.v1.router")),
    # Sob `/admin/` de PROPOSITO: o `BarreiraAdminMiddleware` ja devolve 404
    # para tudo que comeca com `/admin` fora do host do admin, entao esta rota
    # nasce protegida sem regra nova. Montar num prefixo proprio exigiria uma
    # barreira nova — mais uma coisa para alguem esquecer.
    path("admin/django/", admin.site.urls),
]
