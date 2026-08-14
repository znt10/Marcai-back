from django.apps import AppConfig


class AppConfig_(AppConfig):
    """A superficie HTTP da travessia.

    Separado de `tenant` de proposito, e a divisao e por PAPEL, nao por
    tamanho: `tenant` e infraestrutura (middleware, RLS, slug, models) e
    responde "como este pedido vira uma barbearia"; `app` e a API versionada e
    responde "o que esta barbearia expoe". A fatia 8 vai mexer muito em
    `tenant` (posse do DDL) e quase nada aqui.

    Os models continuam morando em `tenant/models.py`, e nao aqui como no
    Unistock, porque sao `managed = False` sobre tabelas de que o Prisma e
    dono. Mudar de app agora mudaria o `app_label` deles sem nenhum ganho.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "app"
