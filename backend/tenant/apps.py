from django.apps import AppConfig


class TenantConfig(AppConfig):
    name = "tenant"

    def ready(self):
        # Import (nao chamada): o modulo conecta o proprio receiver de CORS
        # ao ser importado (ver o `.connect(...)` no fim de tenant/cors.py).
        # Precisa estar em ready(), nao em nivel de modulo de apps.py: e o
        # ponto em que o Django garante o app registry pronto antes de
        # qualquer signal.connect.
        from . import cors  # noqa: F401
