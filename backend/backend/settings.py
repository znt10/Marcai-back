import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "inseguro-so-em-dev")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

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

# Sem contrib.admin, contrib.auth nem sessions: eles criariam tabela num banco
# de que o Prisma e dono (spec §8). Sem django_celery_beat pela mesma razao —
# o beat usa o agendador de arquivo, e a agenda em tabela e da fatia 7.
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "tenant",
]

MIDDLEWARE = []

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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
USE_TZ = True
TIME_ZONE = "America/Sao_Paulo"
