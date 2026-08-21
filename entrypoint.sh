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

# A semente de DESENVOLVIMENTO. Duas guardas, e cada uma resolve um problema
# diferente:
#
# `SEMEAR_DEV` existe SO no servico `api` do compose. O ENTRYPOINT esta no
# Dockerfile, entao `api`, `worker` e `beat` rodam este mesmo script — sem a
# variavel escopando, os tres tentariam semear ao mesmo tempo no boot.
#
# E o proprio comando recusa fora de DJANGO_DEBUG=1. Sem isso, a senha padrao
# de dev viraria credencial conhecida no primeiro ambiente exposto que subisse
# este compose, sem nada quebrar para avisar.
#
# `|| true`: semente e conveniencia. Se ela falhar, o contêiner tem de subir
# assim mesmo e deixar o erro no log — derrubar a api porque o cenario de
# demonstracao nao coube seria trocar um incomodo por uma parede.
if [ -n "$SEMEAR_DEV" ]; then
  python manage.py semear_dev || true
fi

exec "$@"
