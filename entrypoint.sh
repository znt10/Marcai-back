#!/bin/sh
set -e

# Espera o banco e roda as migrations. O bloco que ficava aqui dizia
# "NAO FACA ISSO" sobre exatamente a linha de `migrate` que agora existe
# — o DDL deste banco era do Prisma, do lado do front, e um `migrate`
# criaria tabela do Django num banco que nao era dele.
#
# A fatia 1 inverteu o dono, entao o aviso inverteu junto: hoje o silencioso
# seria o contrario, um contêiner subindo contra um schema que ninguem
# aplicou.
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

# `--database=owner`, e nao a conexao default. As duas apontam para o MESMO
# banco; o que muda e o papel. `default` e `brutus_app`, o do runtime, que nao
# tem direito de criar tabela nenhuma e nem deve ter — migrar por ele daria
# "permission denied for schema public" na primeira linha.
#
# `owner` e `brutus_owner`: e ele quem tem o DDL, e e ele que a politica
# `owner_irrestrito` isenta do RLS. As tabelas tambem precisam NASCER dele,
# porque o `ALTER DEFAULT PRIVILEGES FOR ROLE brutus_owner` do init-db.sql so
# concede DML a brutus_app/brutus_admin no que brutus_owner cria.
echo "[entrypoint] aplicando migrations..."
python manage.py migrate --noinput --database=owner

exec "$@"
