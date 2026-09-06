import os
from pathlib import Path

from corsheaders.defaults import default_headers

from tenant.config import tenant_padrao

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "inseguro-so-em-dev")

# Default "0", nao "1": variavel que ninguem pos nao deve ligar depuracao.
# Sob DEBUG=True a pagina de erro do Django renderiza a mensagem de qualquer
# excecao (inclusive Http404) verbatim para o cliente — errar para o lado
# seguro aqui e o que evita a barreira do admin (tenant/middleware.py)
# vazando por que ela bloqueou. O docker-compose.yml poe DJANGO_DEBUG=1
# explicito no servico `api`, entao o desenvolvimento nao perde a pagina de
# erro; so quem nao disse nada e que passa a rodar sem ela.
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# O dominio que o slug.py compara com o Host. Sem esquema e sem porta, igual
# ao NEXT_PUBLIC_DOMINIO_BASE do outro lado — os dois precisam concordar, e a
# forma canonica e a que o slug.ts ja usa.
DOMINIO_BASE = os.environ.get("DOMINIO_BASE", "localhost")

# ---- Barbearia padrao: testar pelo celular sem DNS (tenant/config.py) ----
#
# O gate esta DENTRO de `tenant_padrao`, que devolve "" quando DEBUG e' falso.
# Ou seja: por mais que a variavel exista no ambiente de producao, ela nao liga
# nada. E' proposital que o gate seja uma funcao pura — assim ha teste sobre a
# trava (tests/test_tenant_padrao.py), e nao so' sobre o efeito dela.
TENANT_PADRAO = tenant_padrao(os.environ.get("TENANT_PADRAO", ""), DEBUG)

# O ponto e o curinga: `.localhost` cobre brutus.localhost, dontony.localhost
# e admin.localhost de uma vez.
#
# No modo barbearia-padrao o host e' o IP da maquina na rede, que muda a cada
# DHCP e ninguem sabe na hora de escrever isto — dai o curinga. So' se alcanca
# esta linha sob DEBUG (ver acima), e a protecao que importa (o par
# origem/host do CORS) nao passa por ALLOWED_HOSTS.
if TENANT_PADRAO:
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = [f".{DOMINIO_BASE}", DOMINIO_BASE]

# DESLIGADO de proposito. O tenant sai do Host real; confiar em cabecalho de
# upstream faria o back precisar do front na frente para funcionar, e ele
# precisa subir, testar e ir para producao sozinho (spec §5).
USE_X_FORWARDED_HOST = False

# CORS e da biblioteca (django-cors-headers, igual ao Unistock_Back). A unica
# adaptacao obrigatoria: la a lista de origens e estatica, aqui a origem varia
# por barbearia (brutus.localhost:3000, dontony.localhost:3000, …).
#
# NAO e CORS_ALLOWED_ORIGIN_REGEXES — foi, e saiu (revisao final). Aquele
# regex so pergunta se a origem tem CARA de barbearia, nunca contra qual Host
# ela chegou, e o django-cors-headers usa `check_request_enabled` OR'd com a
# lista estatica (nunca AND'd) — entao um regex estatico continuando aceito
# aqui bastaria sozinho pra liberar o cabecalho, e o sinal abaixo nunca
# conseguiria RECUSAR uma origem que a lista estatica ja aceitou. Por isso a
# checagem inteira (forma + par origem/host) mora agora so no receiver de
# `corsheaders.signals.check_request_enabled` que `tenant/apps.py` conecta —
# `tenant/cors.py` explica o mecanismo com a citacao exata da biblioteca.
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False
# Sem acrescentar o nosso, o preflight recusa o X-Brutus-Cliente — e o sintoma
# e a escrita falhando com um erro de CORS que nao menciona CSRF nenhum.
CORS_ALLOW_HEADERS = [*default_headers, "x-brutus-cliente"]

# Sem contrib.admin, contrib.auth, contrib.contenttypes nem sessions: nenhum
# dos quatro tem uso aqui, e cada um criaria tabela propria sem consumidor
# (contenttypes criaria django_content_type, auth criaria as suas, etc). Sem
# django_celery_beat pela mesma razao — o beat usa o agendador de arquivo
# (CELERY_BEAT_SCHEDULE, abaixo), nao a agenda em tabela que aquele app traria.
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "tenant",
    # A superficie HTTP versionada (fatia 1). Sem model proprio: os models
    # managed=False continuam em `tenant`. Ver app/apps.py.
    "app",
]

MIDDLEWARE = [
    # Primeiro de todos: ele responde o preflight OPTIONS e sai, sem passar
    # pela resolucao de tenant. Preflight nao carrega Host de barbearia.
    "corsheaders.middleware.CorsMiddleware",
    # Antes do TenantMiddleware de proposito: um POST sem o header e recusado
    # sem nem consultar o banco. Recusa barata vem antes de trabalho caro.
    "tenant.middleware.ClienteMiddleware",
    "tenant.middleware.TenantMiddleware",
    "tenant.middleware.BarreiraAdminMiddleware",
    # Por ultimo: os dois crivos acima recusam por HOST (admin ou nao), e este
    # recusa por CAMINHO. Deixando-o no fim, um pedido que ja morreu por host
    # nao passa por aqui — os prefixos dos dois nao se cruzam hoje, entao a
    # ordem entre eles nao muda resposta nenhuma, mas manter "host primeiro,
    # caminho depois" e o que faz a lista continuar previsivel quando alguem
    # acrescentar o proximo prefixo.
    "tenant.middleware.CrivoPainelMiddleware",
]

ROOT_URLCONF = "backend.urls"
WSGI_APPLICATION = "backend.wsgi.application"

# Dois papeis, dois aliases — espelha exatamente o tests/setup.ts do front.
# `default` e o papel da aplicacao e e sobre ele que o RLS age. `owner` ignora
# o RLS e existe SO para montar cenario de teste.
def _banco(usuario: str, senha_padrao: str) -> dict:
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["PGDATABASE"],
        "USER": usuario,
        "PASSWORD": os.environ.get(f"PGPASSWORD_{usuario.split('_')[1].upper()}", senha_padrao),
        "HOST": os.environ.get("PGHOST", "db"),
        "PORT": os.environ.get("PGPORT", "5432"),
    }


DATABASES = {
    "default": _banco("brutus_app", "app"),
    "owner": _banco("brutus_owner", "owner"),
    # `brutus_admin`: sujeito ao MESMO RLS que `brutus_app` em toda tabela de
    # tenant — a diferenca e' so' o GRANT extra de INSERT/UPDATE em
    # `Barbearia`, que `brutus_app` nao tem de proposito (spec do admin da
    # plataforma, §5: "sem BYPASSRLS e' a decisao central"). Usado via
    # `tenant.rls.com_barbearia_admin` e por leituras diretas de `Barbearia`
    # (fora do RLS) nas rotas de admin.
    "admin": _banco("brutus_admin", "admin"),
    # O banco da Evolution — outro banco FISICO, dono e credencial proprios
    # (docker/init-db.sql), sem relacao nenhuma com PGDATABASE (que so
    # escolhe entre `brutus`/`brutus_test`). So o zelador (fatia 7,
    # app/services/zelador.py) usa este alias, com SQL cru — sem models: o
    # schema e' da Evolution, nao e' nosso pra declarar.
    #
    # `_banco()` nao serve aqui sem adaptar: ela deriva o sufixo do env var
    # de senha de `usuario.split('_')[1]`, e "evolution" nao tem `_`.
    "evolution": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PGDATABASE_EVOLUTION", "evolution"),
        "USER": "evolution",
        "PASSWORD": os.environ.get("PGPASSWORD_EVOLUTION", "evolution"),
        "HOST": os.environ.get("PGHOST", "db"),
        "PORT": os.environ.get("PGPORT", "5432"),
    },
}

# DRF sem autenticacao nem permissao por padrao: a sessao e a fatia 3, e um
# default que ninguem leu e como uma porta que ninguem sabe se esta trancada.
#
# UNAUTHENTICATED_USER: None e obrigatorio aqui, e nao e o default do DRF. O
# default e "django.contrib.auth.models.AnonymousUser", e so o import desse
# modulo (mesmo sem nenhuma classe de autenticacao ativa) forca o registro de
# django.contrib.auth.models.Permission, que quebra com "doesn't declare an
# explicit app_label and isn't in an application in INSTALLED_APPS" — porque
# contrib.auth foi excluido de proposito (comentario acima). None evita o
# import inteiro.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://redis:6379/1")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = "America/Sao_Paulo"

# Fatia 7: `ping` (que so provava que worker/beat respondem) deu lugar as
# tres tarefas de verdade que substituem os `while true` do docker-compose.
# Os tiques espelham exatamente o `sleep` que cada um tinha: 600s para
# lembrete e healthcheck do WhatsApp (giravam a cada 10 min), 3600s para o
# zelador (girava de hora em hora — recusa que ja aconteceu nao fica mais
# urgente sendo relida seis vezes na mesma hora).
CELERY_BEAT_SCHEDULE = {
    "lembretes": {"task": "app.tasks.lembretes", "schedule": 600.0},
    "whatsapp-healthcheck": {"task": "app.tasks.whatsapp_healthcheck", "schedule": 600.0},
    "zelador": {"task": "app.tasks.zelador", "schedule": 3600.0},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
USE_TZ = True
TIME_ZONE = "America/Sao_Paulo"
