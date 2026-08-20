from django.db import migrations

# Porte das migrations `20260805142315_restricoes`,
# `20260805143808_corrige_agendamento_e_bloqueio` e a metade de CHECK da
# `20260816120000_preco_por_barbeiro` do Prisma, ja consolidadas: o que entra
# aqui e o estado FINAL de cada restricao, nao a historia de como ela chegou
# nele (o `bloqueio_forma_valida` original nunca existiu neste banco, entao
# nao ha o que corrigir depois).
#
# Tudo em RunSQL, e nao em `Meta.constraints`, por um motivo so: nenhuma
# destas e expressavel como CheckConstraint sem perder alguma coisa no
# caminho. O EXCLUDE nao tem equivalente no Django; as FK compostas tambem
# nao; e traduzir os CHECKs para `Q()` deixaria metade das restricoes num
# arquivo e metade no outro. Ficam todas juntas, no formato em que ja foram
# revisadas uma vez.

CRIAR = [
    "CREATE EXTENSION IF NOT EXISTS btree_gist;",

    # Limites globais de duracao. Os literais 10 e 60 duplicam
    # DURACAO_MINIMA_MIN / DURACAO_MAXIMA_MIN de tenant/config.py.
    """
    ALTER TABLE tenant_servico ADD CONSTRAINT servico_duracao_valida CHECK (
      duracao_minima_min   BETWEEN 10 AND 60 AND
      duracao_sugerida_min BETWEEN duracao_minima_min AND 60
    );
    """,
    """
    ALTER TABLE tenant_barbeiroservico ADD CONSTRAINT barbeiro_servico_duracao_valida
      CHECK (duracao_min BETWEEN 10 AND 60);
    """,
    # Preco nulo e "o barbeiro ainda nao disse"; preco zero seria um valor
    # dito, e nao existe servico de graca no catalogo.
    """
    ALTER TABLE tenant_barbeiroservico ADD CONSTRAINT barbeiro_servico_preco_valido
      CHECK (preco_centavos IS NULL OR preco_centavos > 0);
    """,
    """
    ALTER TABLE tenant_horariotrabalho ADD CONSTRAINT horario_valido CHECK (
      minutos_inicio >= 0 AND minutos_fim <= 1440 AND minutos_fim > minutos_inicio
    );
    """,

    # Bloqueio: exatamente um dos dois conjuntos preenchido (§5.1), e o ramo
    # semanal tambem valida o INTERVALO — sem isso um bloqueio com
    # minutos_fim <= minutos_inicio passaria, virando janela vazia/negativa
    # para o calculo de disponibilidade. `horario_valido` ja faz essa mesma
    # checagem para a mesma grandeza; replicada aqui por simetria.
    """
    ALTER TABLE tenant_bloqueio ADD CONSTRAINT bloqueio_forma_valida CHECK (
      (repete_semanalmente = true
         AND dia_semana IS NOT NULL AND minutos_inicio IS NOT NULL
         AND minutos_fim IS NOT NULL AND inicio IS NULL AND fim IS NULL
         AND minutos_inicio >= 0 AND minutos_fim <= 1440
         AND minutos_fim > minutos_inicio)
      OR
      (repete_semanalmente = false
         AND inicio IS NOT NULL AND fim IS NOT NULL AND fim > inicio
         AND dia_semana IS NULL AND minutos_inicio IS NULL AND minutos_fim IS NULL)
    );
    """,

    # O EXCLUDE protege o intervalo ARMAZENADO, mas nada amarraria `fim` a
    # `inicio` + `duracao_min`. Sem isto: um `fim` calculado errado (20min
    # gravados para um corte de 40) escaparia da protecao contra dupla
    # marcacao; e `fim = inicio` produz um range VAZIO, que nunca sobrepoe
    # nada, deixando um agendamento de duracao zero invisivel para o EXCLUDE.
    """
    ALTER TABLE tenant_agendamento ADD CONSTRAINT agendamento_duracao_valida CHECK (
      duracao_min BETWEEN 10 AND 60
      AND fim = inicio + make_interval(mins => duracao_min)
    );
    """,
    """
    ALTER TABLE tenant_agendamento ADD CONSTRAINT agendamento_preco_valido
      CHECK (preco_centavos IS NULL OR preco_centavos > 0);
    """,

    # FK compostas: o `barbearia_id` denormalizado nunca diverge do dono real.
    # O Django nao modela FK de mais de uma coluna, entao elas so podem nascer
    # aqui — e sem elas o denormalizado seria so uma copia que ninguem confere.
    """
    ALTER TABLE tenant_barbeiroservico
      ADD CONSTRAINT bs_barbeiro_mesmo_tenant
      FOREIGN KEY (barbearia_id, barbeiro_id)
        REFERENCES tenant_barbeiro (barbearia_id, id) ON DELETE CASCADE,
      ADD CONSTRAINT bs_servico_mesmo_tenant
      FOREIGN KEY (barbearia_id, servico_id)
        REFERENCES tenant_servico  (barbearia_id, id);
    """,
    """
    ALTER TABLE tenant_horariotrabalho
      ADD CONSTRAINT ht_barbeiro_mesmo_tenant
      FOREIGN KEY (barbearia_id, barbeiro_id)
        REFERENCES tenant_barbeiro (barbearia_id, id) ON DELETE CASCADE;
    """,
    """
    ALTER TABLE tenant_bloqueio
      ADD CONSTRAINT bl_barbeiro_mesmo_tenant
      FOREIGN KEY (barbearia_id, barbeiro_id)
        REFERENCES tenant_barbeiro (barbearia_id, id) ON DELETE CASCADE;
    """,
    """
    ALTER TABLE tenant_agendamento
      ADD CONSTRAINT ag_barbeiro_mesmo_tenant
      FOREIGN KEY (barbearia_id, barbeiro_id)
        REFERENCES tenant_barbeiro (barbearia_id, id),
      ADD CONSTRAINT ag_cliente_mesmo_tenant
      FOREIGN KEY (barbearia_id, cliente_id)
        REFERENCES tenant_cliente  (barbearia_id, id),
      ADD CONSTRAINT ag_servico_mesmo_tenant
      FOREIGN KEY (barbearia_id, servico_id)
        REFERENCES tenant_servico  (barbearia_id, id);
    """,

    # A UNICA garantia real contra dupla marcacao (§5.4).
    #
    # Compara INTERVALOS, nao instantes: um indice unico em
    # (barbeiro_id, inicio) deixaria passar 16:00+40min colidindo com
    # 16:30+30min.
    #
    # O `timezone('UTC', col)` que envolvia as duas pontas no Prisma NAO vem
    # junto, e a ausencia dele e a prova de que a troca de dono valeu a pena:
    # ele so existia porque o Prisma mapeia DateTime para `timestamp` SEM
    # fuso, e um cast implicito para timestamptz depende do fuso da sessao e
    # por isso nao entra em indice — a funcao era o jeito IMMUTABLE de dizer
    # "este valor ja e UTC". Com USE_TZ o Django cria as colunas como
    # `timestamptz` e o rotulo vira redundante. E' a mesma virada que torna
    # `como_utc()` (tenant/datas.py) um no-op, como o docstring dele previa.
    """
    ALTER TABLE tenant_agendamento
      ADD CONSTRAINT agendamento_sem_sobreposicao
      EXCLUDE USING gist (
        barbeiro_id WITH =,
        tstzrange(inicio, fim, '[)') WITH &&
      )
      WHERE (status = 'CONFIRMADO');
    """,
]

REMOVER = [
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT agendamento_sem_sobreposicao;",
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT ag_servico_mesmo_tenant;",
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT ag_cliente_mesmo_tenant;",
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT ag_barbeiro_mesmo_tenant;",
    "ALTER TABLE tenant_bloqueio DROP CONSTRAINT bl_barbeiro_mesmo_tenant;",
    "ALTER TABLE tenant_horariotrabalho DROP CONSTRAINT ht_barbeiro_mesmo_tenant;",
    "ALTER TABLE tenant_barbeiroservico DROP CONSTRAINT bs_servico_mesmo_tenant;",
    "ALTER TABLE tenant_barbeiroservico DROP CONSTRAINT bs_barbeiro_mesmo_tenant;",
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT agendamento_preco_valido;",
    "ALTER TABLE tenant_agendamento DROP CONSTRAINT agendamento_duracao_valida;",
    "ALTER TABLE tenant_bloqueio DROP CONSTRAINT bloqueio_forma_valida;",
    "ALTER TABLE tenant_horariotrabalho DROP CONSTRAINT horario_valido;",
    "ALTER TABLE tenant_barbeiroservico DROP CONSTRAINT barbeiro_servico_preco_valido;",
    "ALTER TABLE tenant_barbeiroservico DROP CONSTRAINT barbeiro_servico_duracao_valida;",
    "ALTER TABLE tenant_servico DROP CONSTRAINT servico_duracao_valida;",
]


class Migration(migrations.Migration):
    dependencies = [("tenant", "0002_rls")]

    operations = [migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER)]
