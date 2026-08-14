import os
from pathlib import Path

from corsheaders.defaults import default_headers

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

# O ponto e o curinga: `.localhost` cobre brutus.localhost, dontony.localhost
# e admin.localhost de uma vez.
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

# Sem contrib.admin, contrib.auth, contrib.contenttypes nem sessions: todos os
# quatro criariam tabela num banco de que o Prisma e dono (spec §8) —
# contenttypes criaria django_content_type (e django_migrations junto, so de
# existir uma migration para rodar) do mesmo jeito que os outros tres criariam
# a deles. Sem django_celery_beat pela mesma razao — o beat usa o agendador de
# arquivo, e a agenda em tabela e da fatia 7.
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

# Cadencia alta de proposito: e um sinal de vida, e um sinal de vida que
# aparece uma vez por hora nao serve para descobrir que o beat morreu.
CELERY_BEAT_SCHEDULE = {
    "ping": {"task": "tenant.tasks.ping", "schedule": 60.0},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
USE_TZ = True
TIME_ZONE = "America/Sao_Paulo"
