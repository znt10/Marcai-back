#!/bin/sh
set -e

# O entrypoint do Unistock roda `python manage.py migrate` aqui. NAO FACA ISSO.
#
# O dono do DDL deste banco e o Prisma, do lado do front, ate a fatia 8. Um
# `migrate` nesta linha criaria as tabelas do Django num banco que nao e dele,
# e o estrago seria silencioso: a suite do front continuaria verde por um
# tempo, e a divergencia so apareceria quando alguem estranhasse uma tabela
# django_content_type ao lado de "Barbearia".
#
# O que este entrypoint faz e esperar o banco. So isso.
until python -c "
import os, socket, sys
s = socket.socket()
s.settimeout(1)
try:
    s.connect((os.environ.get('PGHOST', 'db'), int(os.environ.get('PGPORT', 5432))))
except OSError:
    sys.exit(1)
"; do
  echo "[entrypoint] esperando o banco..."
  sleep 1
done

exec "$@"
