from django.urls import include, path

from tenant import views

urlpatterns = [
    path("api/saude", views.saude, name="saude"),
    # A superficie da travessia. Prefixo `api/` sem barra depois de
    # `barbeiros`: o front monta `origem + '/api' + '/barbeiros'`, e casar ao
    # pe da letra evita o 301 que quebraria o pedido credenciado no navegador
    # (ver app/api/v1/router.py).
    path("api/", include("app.api.v1.router")),
]
