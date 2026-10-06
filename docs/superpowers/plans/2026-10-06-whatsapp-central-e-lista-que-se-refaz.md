# WhatsApp so' pelo numero central e a lista que se refaz — Plano de implementacao

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tirar a Evolution do numero de cada barbearia, mandar tudo (equipe e cliente) pelo numero central do Marcai, desligar o bot e fazer a lista do dia ser apagada e mandada de novo quando a agenda de hoje muda.

**Architecture:** dois interruptores em `tenant/config.py` (`WHATSAPP_POR_BARBEARIA`, `BOT_DISPONIVEL`) desligam instancia de barbearia e bot sem apagar codigo. `app/services/whatsapp.py` passa a mandar tudo pela instancia central e ganha `apagar_para_todos`. `app/services/lista_do_dia.py` guarda o id/jid da lista em `ListaDoDiaEnviada` e ganha `avisar_mudanca` (chamada pelas 5 views que mexem na agenda) e `refazer` (rodada por uma task Celery). O front troca a tela do QR pela mensagem de saudacao e o admin ganha o card do numero central.

**Tech Stack:** Django 6 + DRF + Celery + Postgres com RLS (back); Next 16 + React 19 + vitest (front); Evolution API 2.3.7.

**Spec:** `docs/superpowers/specs/2026-10-06-whatsapp-central-e-lista-que-se-refaz-design.md` (no `Marcai-back`). Ler antes de comecar.

## Global Constraints

- Back na branch `whatsapp-central` do `Marcai-back` (ja existe, com o spec). Front numa branch nova `whatsapp-central` do `Marcai-front`, criada com `git switch -c whatsapp-central --no-track origin/main`; depois conferir que `git rev-parse --abbrev-ref @{u}` da' erro ("no upstream") e NUNCA aponta para `origin/main`.
- Nada de `git push` nem PR sem o Jose pedir.
- Toda mensagem de commit termina com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Testes do back: `docker compose up -d db redis` uma vez, depois `docker compose run --rm api pytest -q <arquivo>` dentro de `Marcai-back`. Suite inteira: `docker compose run --rm api pytest -q`.
- Testes do front: `npm test` e `npx tsc --noEmit` dentro de `Marcai-front`.
- Envio de WhatsApp NUNCA levanta excecao: falha vira log (e, para cliente, `MensagemNaoEnviada`). Nunca deixar um erro de envio virar 500 numa rota que ja gravou o agendamento.
- Os interruptores sao lidos como `config.BOT_DISPONIVEL` / `config.WHATSAPP_POR_BARBEARIA` (com `from tenant import config`) NA HORA DA CHAMADA — nunca `from tenant.config import BOT_DISPONIVEL`, que congelaria o valor e impediria o `monkeypatch` dos testes.
- Comentarios do back em portugues sem acento (como o resto do back); textos que o usuario le, com acento. Comentarios do front com acento (como o resto do front).
- Textos ao cliente exatamente como a secao 5 do spec. Numero da barbearia formatado por `tenant.telefone.formatar` (11 digitos -> `(83) 9 9999-0000`).
- Linha da lista do barbeiro: a de sempre, `_linha_do_horario` (`João Silva · hoje 09:00 · Corte`).

## Review Focus

1. Duas mudancas seguidas na agenda do mesmo barbeiro (marcou e cancelou em segundos): a segunda lista tem que apagar a lista da PRIMEIRA, nao a das 07:00 — teste na Task 6 (`test_duas_mudancas_seguidas_a_segunda_apaga_a_lista_da_primeira`).
2. Mudanca para hoje as 06:59 nao refaz nada; as 07:00 em ponto refaz — testes na Task 6.
3. Barbeiro desativado entre enfileirar e a task rodar: nao recebe lista nenhuma — teste na Task 6.
4. A Evolution aceita mas devolve corpo sem `key.id`: nao grava linha (senao a proxima tentativa apagaria `None`) — teste na Task 6.
5. Ambiente sem `EVOLUTION_API_URL` (desenvolvimento): cliente nao vira "nao enviada" e a lista refeita nao quebra — testes nas Tasks 4 e 6.

---

## Mapa de arquivos

Back (`Marcai-back/`):

| Arquivo | O que muda |
|---|---|
| `backend/tenant/config.py` | + `WHATSAPP_POR_BARBEARIA`, `BOT_DISPONIVEL` |
| `backend/tenant/models.py` | default do `plano` vira `COM_ZAP`; + `ListaDoDiaEnviada` |
| `backend/tenant/migrations/0007_whatsapp_central.py` | novo: plano, dados, tabela com RLS |
| `backend/app/services/bot_entrada.py` | `receber` respeita `BOT_DISPONIVEL` |
| `backend/app/services/whatsapp_painel.py` | `ligar_bot` respeita `BOT_DISPONIVEL`; `ver` vira saudacao |
| `backend/app/services/lembrete.py` | ramo do bot respeita `BOT_DISPONIVEL`; texto com barbearia |
| `backend/app/services/admin_barbearias.py` | ganchos de instancia respeitam `WHATSAPP_POR_BARBEARIA`; default `COM_ZAP` |
| `backend/app/tasks.py` | `conferir_instancias` respeita o interruptor; + `refazer_lista` |
| `backend/app/management/commands/desligar_instancias_das_barbearias.py` | novo |
| `backend/app/services/whatsapp.py` | tudo pelo central; `Aceita`; `apagar_para_todos` |
| `backend/app/services/mensagens.py` | textos do cliente com barbearia; `msg_lista_refeita`; `msg_saudacao` |
| `backend/app/services/convite.py` | + `link_da_vitrine` |
| `backend/app/services/trava_conversa.py` | + `trava_consultiva` (generaliza a trava) |
| `backend/app/services/lista_do_dia.py` | grava a lista; `avisar_mudanca`; `refazer` |
| `backend/app/services/agendamentos.py` | retornos levam `id` e `barbeiro_id` |
| `backend/app/services/zelador.py` | + poda de `ListaDoDiaEnviada` |
| `backend/app/api/v1/views/agendamentos.py`, `agendamentos_painel.py`, `bloqueios.py` | gatilhos da lista; textos com barbearia |
| `backend/app/api/v1/views/whatsapp_painel.py` | `ver` sem papel |
| `backend/app/services/whatsapp_central.py`, `backend/app/api/v1/views/admin_whatsapp_central.py`, `backend/app/api/v1/router.py` | card do central |
| `tests/conftest.py` | TRUNCATE da tabela nova; `cenario` explicito `SEM_ZAP`; fixture `refazer_enfileirado` |

Front (`Marcai-front/`):

| Arquivo | O que muda |
|---|---|
| `src/app/painel/whatsapp/page.tsx` | reescrita: saudacao + Copiar |
| `src/lib/whatsapp-saudacao.ts` + `tests/whatsapp-saudacao.test.ts` | novo: texto das nao enviadas |
| `src/lib/api/painelAPI.ts`, `src/lib/api/index.ts` | tipo novo de `/painel/whatsapp`; sai `desconectar`/`ligarBot` |
| `src/components/painel/NavPainel.tsx` | sai a `FaixaDoWhatsapp` |
| `src/components/painel/FaixaDoWhatsapp.tsx`, `src/lib/whatsapp-estado.ts`, `tests/whatsapp-estado.test.ts` | apagados |
| `src/lib/api/adminAPI.ts` | + `whatsappCentral`; sai `trocarPlano` |
| `src/components/admin/WhatsappCentral.tsx` | novo: o card |
| `src/components/admin/FormBarbearia.tsx`, `ListaBarbearias.tsx`, `src/app/admin/page.tsx` | sai o seletor de plano; entra o card |

**Sobre a ordem do spec:** o spec pede medir "apagar para todos" (secao 6) antes de construir. Aqui a medicao e' a Task 12: o codigo da Task 6 ja trata apagar que falha exatamente como o plano B do spec ("so' manda de novo"), entao nada do que se constroi depende da resposta — ela so' diz se o "Mensagem apagada" aparece de verdade no celular.

---

### Task 1: Interruptores e bot desligado

**Files:**
- Modify: `backend/tenant/config.py` (fim do arquivo)
- Modify: `backend/app/services/bot_entrada.py` (`receber`)
- Modify: `backend/app/services/whatsapp_painel.py` (`ligar_bot`)
- Modify: `backend/app/services/lembrete.py` (`pelo_bot`)
- Modify: `tests/test_bot_entrada.py`, `tests/test_bot_interruptor.py`, `tests/test_bot_lembrete.py` (fixture)
- Create: `tests/test_bot_desligado.py`

**Interfaces:**
- Produces: `tenant.config.WHATSAPP_POR_BARBEARIA: bool = False`, `tenant.config.BOT_DISPONIVEL: bool = False`. Tasks 3 e 6 leem os dois.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_bot_desligado.py`:

```python
"""O bot de agendamento desligado (etapa 1 do numero central, spec
2026-10-06). O codigo dele fica inteiro — volta no plano de agendar pelo
WhatsApp com a API oficial —, mas nada chega nele enquanto `BOT_DISPONIVEL`
for False."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import bot_entrada
from tenant import config


def test_os_dois_interruptores_nascem_desligados():
    assert config.BOT_DISPONIVEL is False
    assert config.WHATSAPP_POR_BARBEARIA is False


def test_receber_ignora_antes_de_consultar_o_banco():
    """Sem marca de banco: se `receber` consultasse qualquer tabela, o
    pytest-django recusaria o acesso e o teste quebraria."""
    corpo = {
        "event": "messages.upsert",
        "instance": f"marcai-{uuid.uuid4()}",
        "data": {
            "key": {"remoteJid": "5583988887777@s.whatsapp.net", "id": "A1", "fromMe": False},
            "message": {"conversation": "oi"},
        },
    }
    assert bot_entrada.receber(corpo, datetime.now(timezone.utc)) == "ignorado:desligado"


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_ligar_o_bot_e_recusado_sem_tocar_na_evolution(cenario):
    from app.services import whatsapp_painel

    with patch.object(whatsapp_painel, "aplicar_assinatura") as aplicar:
        assert whatsapp_painel.ligar_bot(cenario["brutus"], True) is False
    aplicar.assert_not_called()


@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_lembrete_nao_vai_pelo_bot_mesmo_com_bot_ligado_na_linha(cenario, monkeypatch):
    """Uma linha de instancia velha com `bot_ativo=True` (sobra de antes do
    comando que desliga tudo) nao pode puxar o lembrete para o bot."""
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    from app.services import lembrete
    from tenant.models import (
        Agendamento, Barbearia, Barbeiro, Cliente, EstadoInstancia, Servico,
        WhatsappInstancia,
    )

    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=f"marcai-{b.id}",
        estado=EstadoInstancia.CONECTADO, bot_ativo=True,
    )
    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=30, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Ana", whatsapp="11977778888",
    )
    agora = datetime.now(timezone.utc)
    inicio = agora + timedelta(minutes=30)
    Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )

    with patch("app.services.lembrete.enviar_ao_cliente") as ao_cliente, patch(
        "app.services.bot.enviar_lembrete_pelo_bot"
    ) as pelo_bot:
        assert lembrete.enviar_pendentes(agora) == 1
    ao_cliente.assert_called_once()
    pelo_bot.assert_not_called()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_bot_desligado.py`
Expected: FAIL — `AttributeError: module 'tenant.config' has no attribute 'BOT_DISPONIVEL'`.

- [ ] **Step 3: Implementar**

No fim de `backend/tenant/config.py`:

```python
# ---- WhatsApp: etapa 1 do numero central (spec 2026-10-06) ---------------
#
# Lidos como `config.X` NA HORA DA CHAMADA, nunca com `from tenant.config
# import X`: os testes do bot ligam os dois com `monkeypatch.setattr(config,
# ...)`, e um nome importado congelaria o valor do import.

# Instancia da Evolution POR BARBEARIA. Desligada: o numero do negocio do
# cliente nao fica ligado a API nao oficial nenhuma. Ninguem cria, recria nem
# confere instancia de barbearia enquanto isto for False.
WHATSAPP_POR_BARBEARIA = False

# O bot de agendamento. Desligado com o codigo inteiro guardado: volta no
# plano de agendar pelo WhatsApp, com a API oficial.
BOT_DISPONIVEL = False
```

Em `backend/app/services/bot_entrada.py`, acrescentar `from tenant import config` aos imports e abrir `receber` assim:

```python
def receber(corpo, agora: datetime) -> str:
    # Antes de ler o corpo: com o bot desligado, nada que chega aqui vira
    # consulta ao banco nem task.
    if not config.BOT_DISPONIVEL:
        return "ignorado:desligado"
    lida = ler_mensagem(corpo)
```

(o resto da funcao fica igual).

Em `backend/app/services/whatsapp_painel.py`, acrescentar `from tenant import config` e abrir `ligar_bot` assim (o resto igual):

```python
def ligar_bot(barbearia, ativo: bool) -> bool:
    """...docstring atual..."""
    # Desligar continua passando: e' o que leva uma linha velha a False.
    if ativo and not config.BOT_DISPONIVEL:
        return False
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False
```

Em `backend/app/services/lembrete.py`, acrescentar `from tenant import config` e trocar o calculo de `pelo_bot` por:

```python
        pelo_bot = (
            config.BOT_DISPONIVEL
            and b.plano == PlanoBarbearia.COM_ZAP
            and instancia is not None
            and instancia.bot_ativo
            and instancia.estado == EstadoInstancia.CONECTADO
        )
```

- [ ] **Step 4: Manter vivos os testes do bot**

No topo (depois do `pytestmark`) de `tests/test_bot_entrada.py`, `tests/test_bot_interruptor.py` e `tests/test_bot_lembrete.py`, acrescentar:

```python
@pytest.fixture(autouse=True)
def _bot_disponivel(monkeypatch):
    """O bot esta desligado em producao (etapa 1 do numero central), mas o
    codigo fica para o plano de agendar pelo WhatsApp: estes casos o testam
    ligado."""
    from tenant import config

    monkeypatch.setattr(config, "BOT_DISPONIVEL", True)
```

- [ ] **Step 5: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_bot_desligado.py tests/test_bot_entrada.py tests/test_bot_interruptor.py tests/test_bot_lembrete.py tests/test_bot.py tests/test_cron_lembretes.py`
Expected: PASS. Se outro arquivo da suite falhar com `ignorado:desligado` ou com `ligar_bot` devolvendo False, acrescentar a ele a mesma fixture `_bot_disponivel`.

- [ ] **Step 6: Commit**

```bash
git add backend/tenant/config.py backend/app/services/bot_entrada.py backend/app/services/whatsapp_painel.py backend/app/services/lembrete.py tests/test_bot_desligado.py tests/test_bot_entrada.py tests/test_bot_interruptor.py tests/test_bot_lembrete.py
git commit -m "whatsapp: interruptores da etapa 1 e o bot desligado

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Migracao — todo mundo com zap e a tabela da lista enviada

**Files:**
- Modify: `backend/tenant/models.py` (`Barbearia.plano`, nova `ListaDoDiaEnviada` depois de `ConversaWhatsapp`)
- Create: `backend/tenant/migrations/0007_whatsapp_central.py`
- Modify: `backend/app/services/admin_barbearias.py:61` (default de `criar`)
- Modify: `tests/conftest.py` (TRUNCATE e `cenario`)
- Modify: `tests/test_rls.py`, `tests/test_admin_barbearias.py:356-366`

**Interfaces:**
- Produces: `tenant.models.ListaDoDiaEnviada` com campos `barbearia` (FK), `barbeiro` (FK), `dia` (`DateField`), `mensagem_id` (`TextField`), `remote_jid` (`TextField`), `enviada_em` (`DateTimeField`, default `timezone.now`); unica por `(barbeiro, dia)` (`lista_por_barbeiro_e_dia`). Tasks 6 e 7 usam.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_rls.py`, no fim:

```python
def test_lista_do_dia_enviada_nao_vaza_entre_barbearias(cenario):
    from tenant.models import Barbeiro, ListaDoDiaEnviada

    for slug, mensagem in (("brutus", "ID-BRUTUS"), ("dontony", "ID-DONTONY")):
        b = cenario[slug]
        barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
        ListaDoDiaEnviada.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id,
            dia="2026-10-06", mensagem_id=mensagem, remote_jid="x@s.whatsapp.net",
        )

    with com_barbearia(cenario["brutus"].id):
        assert list(ListaDoDiaEnviada.objects.values_list("mensagem_id", flat=True)) == [
            "ID-BRUTUS"
        ]
    assert ListaDoDiaEnviada.objects.count() == 0
```

(conferir que `uuid` e `com_barbearia` ja estao importados no topo de `test_rls.py`; se nao, importar.)

Em `tests/test_admin_barbearias.py`, trocar `test_criar_sem_plano_nasce_sem_zap_e_nao_fala_com_a_evolution` por:

```python
def test_criar_sem_plano_nasce_com_zap(client, evolution_simulada):
    """Etapa 1 do numero central: toda barbearia manda WhatsApp ao cliente
    (pelo central). O seletor de plano saiu do admin."""
    from tenant.models import Barbearia

    _logar_admin(client)
    r = _criar_barbearia(client)
    assert r.status_code == 201
    assert Barbearia.objects.using("owner").get(id=r.json()["id"]).plano == "COM_ZAP"
```

Em `tests/test_modelos.py`, no fim:

```python
@pytest.mark.django_db(databases=["default", "owner"], transaction=True)
def test_a_migracao_poe_toda_barbearia_com_zap(cenario):
    """O `cenario` nasce SEM_ZAP (explicito no conftest): a funcao de dados
    da 0007 tem que levar as duas para COM_ZAP."""
    import importlib
    from types import SimpleNamespace

    from django.apps import apps

    from tenant.models import Barbearia

    migracao = importlib.import_module("tenant.migrations.0007_whatsapp_central")
    migracao._todas_com_zap(apps, SimpleNamespace(connection=SimpleNamespace(alias="owner")))
    assert set(Barbearia.objects.using("owner").values_list("plano", flat=True)) == {"COM_ZAP"}
```

(conferir que `pytest` esta importado no topo de `test_modelos.py`.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_rls.py tests/test_admin_barbearias.py tests/test_modelos.py -k "lista_do_dia or nasce_com_zap or migracao"`
Expected: FAIL — `ImportError: cannot import name 'ListaDoDiaEnviada'`.

- [ ] **Step 3: Modelo**

Em `backend/tenant/models.py`, no `PlanoBarbearia`, trocar o docstring por:

```python
class PlanoBarbearia(models.TextChoices):
    """O que a barbearia comprou. Desde a etapa 1 do numero central (spec
    2026-10-06) toda barbearia e' `COM_ZAP`: o cliente recebe confirmacao e
    lembrete pelo numero central do Marcai. O campo fica para os planos
    futuros (WhatsApp x API oficial).
    """
```

No campo `Barbearia.plano`, trocar `default=PlanoBarbearia.SEM_ZAP` por `default=PlanoBarbearia.COM_ZAP`.

Depois de `class ConversaWhatsapp`, acrescentar:

```python
class ListaDoDiaEnviada(models.Model):
    """A ultima lista do dia que um barbeiro recebeu pelo numero central.

    Existe para a lista poder ser APAGADA quando a agenda de hoje muda: a
    Evolution so' apaga sabendo o id e o jid da mensagem. Uma linha por
    barbeiro por dia, sobrescrita a cada lista nova; o zelador poda as velhas.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="listas_enviadas",
    )
    barbeiro = models.ForeignKey(
        Barbeiro, on_delete=models.RESTRICT, related_name="listas_enviadas",
    )
    # A data LOCAL (Sao Paulo) da lista — a mesma de `dia_de_hoje(agora)`.
    dia = models.DateField()
    mensagem_id = models.TextField()
    remote_jid = models.TextField()
    enviada_em = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("barbeiro", "dia"), name="lista_por_barbeiro_e_dia"),
        ]

    def __str__(self):
        return f"lista de {self.dia} ({self.mensagem_id})"
```

- [ ] **Step 4: Migracao**

Gerar o esqueleto: `docker compose run --rm api python manage.py makemigrations tenant --name whatsapp_central`. Depois editar `backend/tenant/migrations/0007_whatsapp_central.py` para ficar com este conteudo (as `operations` geradas pelo Django — `AlterField` de `plano` e `CreateModel` — ficam como ele gerou; o que se acrescenta e' o `RunPython` e o `RunSQL`, nesta ordem):

```python
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# Tabela de tenant NOVA: nasce com politica e GRANT aqui, na propria
# migration, como a 0005 e a 0006 fizeram.
_T = "tenant_listadodiaenviada"

CRIAR = [
    f"ALTER TABLE {_T} ENABLE ROW LEVEL SECURITY;",
    f"ALTER TABLE {_T} FORCE  ROW LEVEL SECURITY;",
    f"""
    CREATE POLICY tenant_isolation ON {_T}
        TO brutus_app, brutus_admin
        USING      (barbearia_id::text = current_setting('app.barbearia_id', true))
        WITH CHECK (barbearia_id::text = current_setting('app.barbearia_id', true));
    """,
    f"""
    CREATE POLICY owner_irrestrito ON {_T}
        TO brutus_owner
        USING (true) WITH CHECK (true);
    """,
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_T} TO brutus_app;",
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_T} TO brutus_admin;",
]

REMOVER = [
    f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {_T} FROM brutus_admin;",
    f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {_T} FROM brutus_app;",
    f"DROP POLICY IF EXISTS owner_irrestrito ON {_T};",
    f"DROP POLICY IF EXISTS tenant_isolation ON {_T};",
    f"ALTER TABLE {_T} NO FORCE ROW LEVEL SECURITY;",
    f"ALTER TABLE {_T} DISABLE ROW LEVEL SECURITY;",
]


def _todas_com_zap(apps, schema_editor):
    """Etapa 1: toda barbearia passa a mandar WhatsApp ao cliente (pelo
    central). Volta nao desfaz: nao ha como saber quem era sem zap antes."""
    Barbearia = apps.get_model("tenant", "Barbearia")
    Barbearia.objects.using(schema_editor.connection.alias).update(plano="COM_ZAP")


class Migration(migrations.Migration):
    dependencies = [("tenant", "0006_bot_agendamento")]

    operations = [
        # <- o AlterField de `plano` que o makemigrations gerou fica aqui
        migrations.RunPython(_todas_com_zap, migrations.RunPython.noop),
        # <- o CreateModel de `ListaDoDiaEnviada` que o makemigrations gerou fica aqui
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
```

Conferir: `docker compose run --rm api python manage.py makemigrations --check --dry-run` responde "No changes detected".

- [ ] **Step 5: criar() e conftest**

Em `backend/app/services/admin_barbearias.py`, dentro de `criar`, trocar `plano = str(dados.get("plano") or PlanoBarbearia.SEM_ZAP)` por `plano = str(dados.get("plano") or PlanoBarbearia.COM_ZAP)`.

Em `tests/conftest.py`:
- no TRUNCATE, acrescentar `tenant_listadodiaenviada, ` logo antes de `tenant_conversawhatsapp, `;
- no `cenario`, acrescentar `plano="SEM_ZAP",` ao `Barbearia.objects.using("owner").create(...)`, com este comentario acima do `create`:

```python
        # `SEM_ZAP` EXPLICITO: o default do modelo virou `COM_ZAP` na etapa 1
        # do numero central, e os casos antigos foram escritos sobre uma
        # barbearia que nao manda nada ao cliente. Quem precisa de com zap
        # sobe o plano no proprio teste, como sempre fez.
```

- [ ] **Step 6: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_rls.py tests/test_admin_barbearias.py tests/test_modelos.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/tenant/models.py backend/tenant/migrations/0007_whatsapp_central.py backend/app/services/admin_barbearias.py tests/conftest.py tests/test_rls.py tests/test_admin_barbearias.py tests/test_modelos.py
git commit -m "tenant: toda barbearia com zap e a tabela da lista do dia enviada

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Barbearia sem instancia na Evolution

**Files:**
- Modify: `backend/app/services/admin_barbearias.py` (`criar`, `atualizar_ativo`, `atualizar_plano`)
- Modify: `backend/app/tasks.py` (`conferir_instancias`)
- Create: `backend/app/management/commands/desligar_instancias_das_barbearias.py`
- Modify: `tests/test_admin_barbearias.py`, `tests/test_conferir_instancias.py`
- Create: `tests/test_desligar_instancias.py`

**Interfaces:**
- Consumes: `config.WHATSAPP_POR_BARBEARIA` (Task 1); `apagar_instancia(barbearia)` (ja existe em `whatsapp_instancias.py`).
- Produces: comando `desligar_instancias_das_barbearias`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_admin_barbearias.py`, logo depois da fixture `evolution_simulada`, acrescentar:

```python
@pytest.fixture
def com_instancia_por_barbearia(monkeypatch):
    """Os ganchos de instancia continuam no codigo (voltam quando a API
    oficial chegar); estes casos os testam com o interruptor ligado."""
    from tenant import config

    monkeypatch.setattr(config, "WHATSAPP_POR_BARBEARIA", True)
```

Acrescentar `com_instancia_por_barbearia` aos parametros de `test_criar_com_zap_deixa_a_instancia_pendente_e_chama_a_evolution`, `test_patch_sobe_para_com_zap` e `test_reativar_barbearia_com_zap_recria_o_numero`. Depois acrescentar:

```python
def test_criar_com_zap_nao_cria_instancia_com_o_interruptor_desligado(client, evolution_simulada):
    _logar_admin(client)
    r = _criar_barbearia(client, plano="COM_ZAP")
    assert r.status_code == 201
    assert _instancia_de(r.json()["id"]) is None
    assert evolution_simulada["garantir"].call_count == 0


def test_patch_para_com_zap_nao_cria_instancia_com_o_interruptor_desligado(
    client, cenario, evolution_simulada,
):
    _logar_admin(client)
    b = cenario["brutus"]
    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"plano": "COM_ZAP"},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert _instancia_de(b.id) is None
    assert evolution_simulada["garantir"].call_count == 0


def test_reativar_nao_cria_instancia_com_o_interruptor_desligado(
    client, cenario, evolution_simulada,
):
    from tenant.models import Barbearia

    _logar_admin(client)
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP", ativo=False)
    r = client.patch(
        f"/api/admin/barbearias/{b.id}", {"ativo": True},
        content_type="application/json", headers={"host": HOST, **CABECALHO},
    )
    assert r.status_code == 200
    assert _instancia_de(b.id) is None
    assert evolution_simulada["garantir"].call_count == 0
```

Em `tests/test_conferir_instancias.py`, logo depois do `pytestmark`, acrescentar:

```python
@pytest.fixture(autouse=True)
def _com_instancia_por_barbearia(monkeypatch):
    """A conferencia so' trabalha com o interruptor ligado; estes casos a
    testam assim. O caso desligado esta em `test_desligada_nao_faz_nada`."""
    from tenant import config

    monkeypatch.setattr(config, "WHATSAPP_POR_BARBEARIA", True)


def test_desligada_nao_faz_nada(cenario, monkeypatch):
    from unittest.mock import patch

    from app import tasks
    from tenant import config
    from tenant.models import Barbearia

    monkeypatch.setattr(config, "WHATSAPP_POR_BARBEARIA", False)
    Barbearia.objects.using("owner").filter(id=cenario["brutus"].id).update(plano="COM_ZAP")
    with patch.object(tasks, "garantir_instancia") as garantir, patch.object(
        tasks, "consultar_estado"
    ) as consultar:
        assert tasks.conferir_instancias() == {"criadas": 0, "conferidas": 0, "corrigidas": 0}
    garantir.assert_not_called()
    consultar.assert_not_called()
```

Criar `tests/test_desligar_instancias.py`:

```python
"""O comando de uma vez so' da etapa 1: tira a Evolution do numero de toda
barbearia."""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _sem_evolution(monkeypatch):
    # Sem URL, `apagar_instancia` pula as chamadas de rede e so' apaga a
    # linha — o que interessa aqui e' que TODA linha some.
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)


def test_apaga_a_instancia_de_toda_barbearia_e_e_idempotente(cenario):
    from tenant.models import WhatsappInstancia

    for b in cenario.values():
        WhatsappInstancia.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, nome=f"marcai-{b.id}",
        )

    saida = StringIO()
    call_command("desligar_instancias_das_barbearias", stdout=saida)
    assert WhatsappInstancia.objects.using("owner").count() == 0
    assert "2 instancia(s) desligada(s)" in saida.getvalue()

    saida = StringIO()
    call_command("desligar_instancias_das_barbearias", stdout=saida)
    assert "0 instancia(s) desligada(s)" in saida.getvalue()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_admin_barbearias.py tests/test_conferir_instancias.py tests/test_desligar_instancias.py`
Expected: FAIL — os tres `..._com_o_interruptor_desligado` (instancia criada), `test_desligada_nao_faz_nada` e o comando inexistente (`Unknown command`).

- [ ] **Step 3: Implementar os ganchos**

Em `backend/app/services/admin_barbearias.py`, acrescentar `from tenant import config` e, perto de `_criar_linha_da_instancia`:

```python
def _com_instancia(plano: str) -> bool:
    """A barbearia ganha instancia propria na Evolution? So' com zap E com o
    interruptor ligado. Desligado (etapa 1 do numero central), ninguem cria
    instancia de barbearia: tudo sai pelo central."""
    return plano == PlanoBarbearia.COM_ZAP and config.WHATSAPP_POR_BARBEARIA
```

Trocar:
- em `criar`, os dois `if plano == PlanoBarbearia.COM_ZAP:` (o que cria a linha e o do `on_commit`) por `if _com_instancia(plano):`;
- em `atualizar_ativo`, o bloco do gancho por:

```python
    if barbearia.plano == PlanoBarbearia.COM_ZAP:
        if ativo:
            if _com_instancia(barbearia.plano):
                _criar_linha_da_instancia(barbearia.id)
                garantir_instancia(barbearia)
        else:
            apagar_instancia(barbearia)
```

- em `atualizar_plano`, o bloco final por:

```python
    if plano == PlanoBarbearia.COM_ZAP:
        if _com_instancia(plano):
            _criar_linha_da_instancia(barbearia.id)
            garantir_instancia(barbearia)
    else:
        apagar_instancia(barbearia)
    return True
```

Em `backend/app/tasks.py`, acrescentar `from tenant import config` e abrir `conferir_instancias` com:

```python
    # Etapa 1 do numero central: nao ha instancia de barbearia para criar
    # nem conferir. A tarefa continua agendada para voltar sozinha quando o
    # interruptor for religado.
    if not config.WHATSAPP_POR_BARBEARIA:
        return {"criadas": 0, "conferidas": 0, "corrigidas": 0}
```

- [ ] **Step 4: O comando**

Criar `backend/app/management/commands/desligar_instancias_das_barbearias.py`:

```python
from django.core.management.base import BaseCommand

from app.services.whatsapp_instancias import apagar_instancia
from tenant.models import Barbearia, WhatsappInstancia


class Command(BaseCommand):
    """Etapa 1 do numero central (spec 2026-10-06): tira a Evolution do
    numero de toda barbearia.

    Roda UMA vez, no conteiner `api`, depois do deploy. `apagar_instancia`
    faz logout (o celular da barbearia deixa de listar o aparelho conectado),
    apaga a instancia na Evolution e apaga a linha. Rodar de novo nao acha
    nada.

    Le as instancias pela conexao `owner`, de todos os tenants de uma vez —
    o caso que a politica `owner_irrestrito` existe para servir.
    """

    help = "Desconecta e apaga a instancia da Evolution de toda barbearia."

    def handle(self, *args, **opcoes):
        ids = list(
            WhatsappInstancia.objects.using("owner").values_list("barbearia_id", flat=True)
        )
        for barbearia in Barbearia.objects.using("owner").filter(id__in=ids):
            apagar_instancia(barbearia)
            self.stdout.write(f"desligada: {barbearia.nome} ({barbearia.slug})")
        self.stdout.write(f"{len(ids)} instancia(s) desligada(s)")
```

- [ ] **Step 5: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_admin_barbearias.py tests/test_conferir_instancias.py tests/test_desligar_instancias.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/admin_barbearias.py backend/app/tasks.py backend/app/management/commands/desligar_instancias_das_barbearias.py tests/test_admin_barbearias.py tests/test_conferir_instancias.py tests/test_desligar_instancias.py
git commit -m "whatsapp: barbearia sem instancia na Evolution e o comando que desliga as que existem

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Tudo pelo numero central

**Files:**
- Modify: `backend/app/services/whatsapp.py`
- Replace: `tests/test_envio_por_plano.py` (conteudo inteiro novo)
- Modify: `tests/test_whatsapp.py` (fixture `com_zap` e testes novos no fim)

**Interfaces:**
- Produces (em `app.services.whatsapp`):
  - `@dataclass(frozen=True) class Aceita: id: str | None; jid: str | None`
  - `_enviar_aceita(instancia, whatsapp_digitos, mensagem, *, digitando_ms=None) -> Aceita | None` — `None` = nao saiu (sem URL, rede, recusa).
  - `_enviar(...) -> str | None` — igual a hoje (o bot usa), agora por cima de `_enviar_aceita`.
  - `enviar_a_equipe_aceita(whatsapp_digitos, mensagem) -> Aceita | None` — pelo central.
  - `apagar_para_todos(jid: str | None, mensagem_id: str | None) -> bool` — pelo central.
  - `enviar_a_equipe_da(barbearia_id, whatsapp_digitos, mensagem) -> None` — agora sempre pelo central.
  - `enviar_ao_cliente(barbearia, whatsapp_digitos, mensagem, *, tipo, cliente_nome) -> bool` — pelo central.

- [ ] **Step 1: Escrever os testes que falham**

Substituir `tests/test_envio_por_plano.py` inteiro por:

```python
"""Quem fala com quem, por qual numero — etapa 1 do numero central.

A regra inteira: **tudo sai pelo numero central do Marcai**, equipe e
cliente. O numero da barbearia saiu da Evolution (spec 2026-10-06): um
bloqueio do WhatsApp agora derruba o numero do Marcai, que o Jose troca, e
nunca o do negocio do cliente.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
import requests

from app.services import whatsapp
from tenant.models import (
    Barbearia,
    EstadoInstancia,
    MensagemNaoEnviada,
    TipoMensagem,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture(autouse=True)
def _evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "central-do-marcai")
    whatsapp.limpar_caches_numero()


def _com_zap(barbearia):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    barbearia.plano = "COM_ZAP"
    return barbearia


def _instancia_velha(barbearia):
    """Uma linha de instancia CONECTADA que sobrou de antes do comando que
    desliga tudo. Ela nao pode mais decidir por onde a mensagem sai."""
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=f"marcai-{barbearia.id}", estado=EstadoInstancia.CONECTADO,
    )


def _nao_enviadas(barbearia):
    with com_barbearia(barbearia.id):
        return list(MensagemNaoEnviada.objects.all())


def _instancia_usada(chamada):
    """A URL termina no nome da instancia: e' ela que diz de qual numero
    saiu."""
    return chamada.call_args.args[0].rsplit("/", 1)[-1]


def _ok():
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {
        "key": {"id": "3EB0X", "remoteJid": "5511977778888@s.whatsapp.net"},
        "status": "PENDING",
    }
    return resposta


def _para_o_cliente(barbearia, **kw):
    return whatsapp.enviar_ao_cliente(
        barbearia, "11977778888", "Fechou!", tipo=TipoMensagem.CONFIRMACAO,
        cliente_nome=kw.get("cliente_nome", "Ana"),
    )


# ---- cliente ----


def test_cliente_com_zap_recebe_pelo_central(cenario):
    b = _com_zap(cenario["brutus"])
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        assert _para_o_cliente(b) is True
    assert _instancia_usada(post) == "central-do-marcai"
    assert _nao_enviadas(b) == []


def test_instancia_velha_da_barbearia_nao_desvia_o_cliente(cenario):
    b = _com_zap(cenario["brutus"])
    _instancia_velha(b)
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        assert _para_o_cliente(b) is True
    assert _instancia_usada(post) == "central-do-marcai"


def test_sem_zap_nao_manda_e_nao_registra(cenario):
    b = cenario["brutus"]
    with patch.object(whatsapp.requests, "post") as post:
        assert _para_o_cliente(b) is False
    assert post.call_count == 0
    assert _nao_enviadas(b) == []


@pytest.mark.parametrize("status, texto", [(400, "desconectado"), (401, "Unauthorized")])
def test_central_recusando_registra_nao_enviada(cenario, status, texto):
    b = _com_zap(cenario["brutus"])
    with patch.object(
        whatsapp.requests, "post", return_value=Mock(ok=False, status_code=status, text=texto)
    ):
        assert _para_o_cliente(b) is False
    registradas = _nao_enviadas(b)
    assert len(registradas) == 1
    assert registradas[0].tipo == TipoMensagem.CONFIRMACAO
    assert registradas[0].cliente_nome == "Ana"


def test_central_fora_da_rede_registra_nao_enviada(cenario):
    b = _com_zap(cenario["brutus"])
    with patch.object(whatsapp.requests, "post", side_effect=requests.ConnectionError("x")):
        assert _para_o_cliente(b) is False
    assert len(_nao_enviadas(b)) == 1


def test_sem_url_nao_registra(cenario, monkeypatch):
    """Desenvolvimento: nao houve queda, so' nao ha servidor."""
    monkeypatch.delenv("EVOLUTION_API_URL")
    b = _com_zap(cenario["brutus"])
    assert _para_o_cliente(b) is False
    assert _nao_enviadas(b) == []


def test_registro_falhando_nao_derruba_quem_chamou(cenario, caplog):
    b = _com_zap(cenario["brutus"])
    with patch.object(
        whatsapp.requests, "post", return_value=Mock(ok=False, status_code=400, text="x")
    ), patch.object(
        whatsapp.MensagemNaoEnviada.objects, "create", side_effect=RuntimeError("boom")
    ):
        with caplog.at_level("ERROR"):
            assert _para_o_cliente(b) is False
    assert "nao enviada" in caplog.text


def test_a_nao_enviada_fica_na_barbearia_certa(cenario):
    b = _com_zap(cenario["brutus"])
    outra = _com_zap(cenario["dontony"])
    with patch.object(
        whatsapp.requests, "post", return_value=Mock(ok=False, status_code=400, text="x")
    ):
        _para_o_cliente(b, cliente_nome="Da Brutus")
    assert [m.cliente_nome for m in _nao_enviadas(b)] == ["Da Brutus"]
    assert _nao_enviadas(outra) == []


# ---- equipe ----


def test_equipe_da_barbearia_sai_pelo_central_mesmo_com_instancia_conectada(cenario):
    b = _com_zap(cenario["brutus"])
    _instancia_velha(b)
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        whatsapp.enviar_a_equipe_da(b.id, "11911112222", "Novo horário")
    assert _instancia_usada(post) == "central-do-marcai"


def test_equipe_sem_zap_tambem_recebe(cenario):
    with patch.object(whatsapp.requests, "post", return_value=_ok()) as post:
        whatsapp.enviar_a_equipe_da(cenario["brutus"].id, "11911112222", "Novo horário")
    assert post.call_count == 1


# ---- a checagem do numero ----


def test_sem_zap_nao_pergunta_se_o_numero_tem_whatsapp(cenario):
    with patch.object(whatsapp.requests, "post") as post:
        assert whatsapp.numero_existe(cenario["brutus"], "11977778888", "1.1.1.1") == "indeterminado"
    assert post.call_count == 0


def test_com_zap_pergunta_pelo_central_mesmo_sem_instancia_da_barbearia(cenario):
    b = _com_zap(cenario["brutus"])
    resposta = _ok()
    resposta.json.return_value = [{"exists": True}]
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        assert whatsapp.numero_existe(b, "11977778888", "1.1.1.1") == "existe"
    assert _instancia_usada(post) == "central-do-marcai"
```

Em `tests/test_whatsapp.py`, trocar o trecho que vai do comentario `# ---- numero_existe` ate o fim da fixture `com_zap` (o comentario que fala da "instancia DA BARBEARIA", o `pytestmark`, o `_config_evolution` e a fixture) por:

```python
# ------------------------------------------------------------- numero_existe
#
# Desde a etapa 1 a pergunta e' feita pela instancia CENTRAL. O plano ainda
# importa: sem zap, a pergunta nem e' feita.

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _config_evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "brutus")


@pytest.fixture
def com_zap(cenario):
    from tenant.models import Barbearia

    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    b.plano = "COM_ZAP"
    return b
```

E no fim de `tests/test_whatsapp.py`:

```python
# ------------------------------------------------ _enviar_aceita / apagar


def test_enviar_aceita_devolve_id_e_jid(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {
        "key": {"id": "3EB0ABC", "remoteJid": "5583988887777@s.whatsapp.net"},
    }
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        aceita = whatsapp._enviar_aceita("brutus", "83988887777", "oi")
    assert aceita == whatsapp.Aceita("3EB0ABC", "5583988887777@s.whatsapp.net")


def test_enviar_aceita_sem_key_ainda_e_aceita(monkeypatch):
    """Aceita sem id e' aceita: o cliente recebe. So' nao da para apagar
    depois — quem guarda (a lista do dia) confere o id."""
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {}
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp._enviar_aceita("brutus", "83988887777", "oi") == whatsapp.Aceita(None, None)


def test_enviar_a_equipe_aceita_vai_pelo_central(monkeypatch):
    _config_evolution(monkeypatch)
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {"key": {"id": "X", "remoteJid": "J"}}
    with patch.object(whatsapp.requests, "post", return_value=resposta) as post:
        assert whatsapp.enviar_a_equipe_aceita("83988887777", "oi") == whatsapp.Aceita("X", "J")
    assert post.call_args.args[0] == "http://evolution:8080/message/sendText/brutus"


def test_apagar_para_todos_manda_id_jid_e_fromme(monkeypatch):
    _config_evolution(monkeypatch)
    with patch.object(whatsapp.requests, "delete", return_value=Mock(ok=True)) as delete:
        assert whatsapp.apagar_para_todos("5583988887777@s.whatsapp.net", "3EB0X") is True
    assert delete.call_args.args[0] == "http://evolution:8080/chat/deleteMessageForEveryone/brutus"
    assert delete.call_args.kwargs["json"] == {
        "id": "3EB0X", "remoteJid": "5583988887777@s.whatsapp.net", "fromMe": True,
    }


def test_apagar_recusado_devolve_false_e_loga(monkeypatch, caplog):
    _config_evolution(monkeypatch)
    with patch.object(
        whatsapp.requests, "delete", return_value=Mock(ok=False, status_code=400, text="nao achei")
    ):
        with caplog.at_level("ERROR"):
            assert whatsapp.apagar_para_todos("j", "i") is False
    assert "nao achei" in caplog.text


def test_apagar_falha_de_rede_devolve_false(monkeypatch):
    _config_evolution(monkeypatch)
    import requests

    with patch.object(whatsapp.requests, "delete", side_effect=requests.ConnectionError("x")):
        assert whatsapp.apagar_para_todos("j", "i") is False


def test_apagar_sem_url_ou_sem_id_nao_chama_nada(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    with patch.object(whatsapp.requests, "delete") as delete:
        assert whatsapp.apagar_para_todos("j", "i") is False
    _config_evolution(monkeypatch)
    with patch.object(whatsapp.requests, "delete") as delete:
        assert whatsapp.apagar_para_todos(None, "i") is False
        assert whatsapp.apagar_para_todos("j", None) is False
    delete.assert_not_called()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_envio_por_plano.py tests/test_whatsapp.py`
Expected: FAIL — `AttributeError: ... 'Aceita'`, `enviar_a_equipe_aceita`, `apagar_para_todos`, e os de "central" usando a instancia da barbearia.

- [ ] **Step 3: Implementar**

Em `backend/app/services/whatsapp.py`:

1. Imports: acrescentar `from dataclasses import dataclass`; trocar o bloco `from tenant.models import (...)` por:

```python
from tenant.models import MensagemNaoEnviada, PlanoBarbearia
```

e apagar `from tenant.rls import com_barbearia` SE nao sobrar uso dele alem de `_registrar_nao_enviada` (ele SOBRA — `_registrar_nao_enviada` usa; manter).

2. Depois de `_config()`, acrescentar:

```python
@dataclass(frozen=True)
class Aceita:
    """A mensagem que a Evolution ACEITOU. `id` e `jid` sao o que permite
    apagar depois (a lista do dia). Podem vir None: aceita sem `key` ainda
    e' aceita — o destinatario recebe, so' nao da para apagar."""

    id: str | None
    jid: str | None
```

3. Substituir `enviar_a_equipe_da` inteira por:

```python
def enviar_a_equipe_da(barbearia_id, whatsapp_digitos: str, mensagem: str) -> None:
    """O aviso de equipe de UMA barbearia: lista, novo horario, cancelamento,
    convite.

    Desde a etapa 1 do numero central (spec 2026-10-06) sai SEMPRE pelo
    central: o numero da barbearia nao fica mais ligado a Evolution. A
    assinatura com `barbearia_id` fica para nao mexer em quem chama.
    """
    enviar_a_equipe(whatsapp_digitos, mensagem)


def enviar_a_equipe_aceita(whatsapp_digitos: str, mensagem: str) -> Aceita | None:
    """`enviar_a_equipe` para quem precisa do que a Evolution devolveu — a
    lista do dia guarda o id e o jid para poder apaga-la depois."""
    return _enviar_aceita(_config()["instancia"], whatsapp_digitos, mensagem)
```

4. Substituir `enviar_ao_cliente` inteira por:

```python
def enviar_ao_cliente(
    barbearia, whatsapp_digitos: str, mensagem: str, *, tipo: str, cliente_nome: str,
) -> bool:
    """Manda ao cliente pelo numero CENTRAL. Devolve se saiu.

    - **sem zap**: nao manda e NAO registra — o cliente desse plano nunca
      esperou WhatsApp. (Desde a etapa 1 toda barbearia e' com zap; o caminho
      fica para os planos futuros.)
    - **sem `EVOLUTION_API_URL`** (desenvolvimento): so' loga. Nao houve
      queda, so' nao ha servidor — registrar encheria o painel de mentira.
    - **envio recusado ou rede fora**: nao sai e FICA REGISTRADA. Sem fila:
      uma confirmacao tres horas atrasada e' pior que nenhuma.

    Isto desfaz a regra antiga "o central nunca fala com cliente" (spec
    2026-10-06, secao 2): risco aceito pelo Jose — se o chip cair, equipe e
    clientes param juntos ate a troca.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False

    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp] sem EVOLUTION_API_URL: %s %s", whatsapp_digitos, mensagem)
        return False

    if _enviar_aceita(cfg["instancia"], whatsapp_digitos, mensagem) is not None:
        return True

    _registrar_nao_enviada(barbearia, tipo, cliente_nome)
    return False
```

5. Renomear a funcao `_enviar` atual para `_enviar_aceita`, mudar a anotacao de retorno para `-> Aceita | None`, e trocar as ultimas linhas (a partir de `chave = (corpo or {}).get("key", {})`) por:

```python
    chave = (corpo or {}).get("key") or {}
    jid = chave.get("remoteJid")
    status = (corpo or {}).get("status", "?")
    logger.info(
        "[whatsapp] aceito para %s (jid %s, status %s)", whatsapp_digitos, jid or "?", status,
    )
    # O id e o jid sobem para quem chamou. O bot guarda o id para reconhecer
    # o eco da propria resposta; a lista do dia guarda os dois para apagar.
    return Aceita(chave.get("id"), jid)
```

(os `return` sem valor do comeco da funcao — sem URL, rede, `not r.ok` — continuam devolvendo `None`.) Logo depois, acrescentar:

```python
def _enviar(
    instancia: str, whatsapp_digitos: str, mensagem: str, *, digitando_ms: int | None = None,
) -> str | None:
    """O id da mensagem aceita, ou None. O que o bot sempre usou."""
    aceita = _enviar_aceita(instancia, whatsapp_digitos, mensagem, digitando_ms=digitando_ms)
    return aceita.id if aceita is not None else None


def apagar_para_todos(jid: str | None, mensagem_id: str | None) -> bool:
    """Apaga, para todos, uma mensagem que o CENTRAL mandou. Devolve se a
    Evolution aceitou. Nunca levanta: quem chama (a lista refeita) manda a
    lista nova de qualquer jeito — uma lista velha que nao sumiu e' feia, uma
    lista nova que nao chegou e' prejuizo.

    Premissa medida na Task 12 do plano: ha relato de a 2.3.7 nao apagar
    (evolution-api#592).
    """
    cfg = _config()
    if not cfg["url"] or not jid or not mensagem_id:
        return False

    try:
        r = requests.delete(
            f"{cfg['url']}/chat/deleteMessageForEveryone/{cfg['instancia']}",
            json={"id": mensagem_id, "remoteJid": jid, "fromMe": True},
            headers={"apikey": cfg["chave"]},
            timeout=3,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp] falha ao apagar %s: %s", mensagem_id, e)
        return False

    if not r.ok:
        logger.error(
            "[whatsapp] apagar recusado (%s) para %s: %s",
            r.status_code, mensagem_id, r.text[:300],
        )
        return False
    return True
```

6. Em `numero_existe`, substituir o trecho entre `cfg = _config()` e o `try:` por:

```python
    cfg = _config()
    if not cfg["url"] or not cfg["instancia"]:
        return "indeterminado"

    # Pela CENTRAL desde a etapa 1: a resposta e' a mesma para toda
    # barbearia, entao o cache e' por numero.
    chave = whatsapp_digitos
    guardado = _cache_numero.get(chave)
    if guardado and guardado["expira_em"] > _agora_ms():
        return "existe" if guardado["existe"] else "nao_existe"

    # Um formulario publico que responde "esse numero tem WhatsApp" e' uma
    # ferramenta de varredura. Sem limite, viram milhares de consultas.
    uso = _uso_por_ip.get(ip)
    if not uso or uso["janela_ate"] < _agora_ms():
        _uso_por_ip[ip] = {"contador": 1, "janela_ate": _agora_ms() + _HORA_MS}
    elif uso["contador"] >= CHECK_NUMERO_LIMITE_POR_IP_HORA:
        return "indeterminado"
    else:
        uso["contador"] += 1
```

e no `requests.post` dela trocar `{linha.nome}` por `{cfg['instancia']}`. Atualizar o docstring de `numero_existe`: o paragrafo "Com zap, a pergunta e' feita pela instancia DA BARBEARIA..." vira "Com zap, a pergunta e' feita pela instancia CENTRAL (etapa 1)."

- [ ] **Step 4: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_envio_por_plano.py tests/test_whatsapp.py tests/test_bot.py tests/test_bot_lembrete.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/whatsapp.py tests/test_envio_por_plano.py tests/test_whatsapp.py
git commit -m "whatsapp: equipe e cliente pelo numero central, e apagar mensagem para todos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: O que o cliente le

**Files:**
- Modify: `backend/app/services/mensagens.py` (`msg_confirmacao`, `msg_lembrete`, `msg_cancelamento`, `msg_cancelamento_pela_barbearia`)
- Modify: `backend/app/api/v1/views/agendamentos.py`, `agendamentos_painel.py`, `bloqueios.py`, `backend/app/services/lembrete.py` (passar a barbearia)
- Modify: `tests/test_mensagens.py`, `tests/test_agendamentos.py:179`

**Interfaces:**
- Produces: os quatro construtores ganham `barbearia_nome: str | None = None` e (os tres que pedem resposta) `contato: str | None = None` — digitos crus de `Barbearia.whatsapp_contato`. Sem `barbearia_nome`, o texto sai EXATAMENTE como hoje (o bot usa assim).

- [ ] **Step 1: Escrever os testes que falham**

No fim de `tests/test_mensagens.py`:

```python
# ------------------------------------------- pelo numero central (etapa 1)
#
# O cliente nao conhece o numero do Marcai: toda mensagem abre com o nome da
# barbearia, e as que pedem resposta apontam para o numero DELA.


def test_confirmacao_pelo_central_diz_de_quem_e_e_para_onde_falar():
    texto = msg_confirmacao(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88", link="http://x/y",
        barbearia_nome="Dom Tony", contato="83999990000",
    )
    assert texto == (
        "*Dom Tony*\n"
        "Fechou, Maria! Corte quinta 13/08 às 8:00, com Zeca.\n\n"
        "Cancelar: http://x/y\n"
        "Dúvida? Chama: (83) 9 9999-0000"
    )


def test_lembrete_pelo_central():
    texto = msg_lembrete(
        servico_nome="Cabelo", barbeiro_nome="Jose Cicero", inicio=INICIO,
        endereco="Rua Aurora, 88", barbearia_nome="Dom Tony", contato="83999990000",
    )
    assert texto == (
        "*Dom Tony — lembrete: cabelo hoje às 8:00*\n"
        "com Jose Cicero\n"
        "Endereço: Rua Aurora, 88\n"
        "Não vai dar? Chama: (83) 9 9999-0000"
    )


def test_cancelamento_pela_barbearia_pelo_central():
    texto = msg_cancelamento_pela_barbearia(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88",
        barbearia_nome="Dom Tony", contato="83999990000",
    )
    assert texto == (
        "*Dom Tony*\n"
        "Oi, Maria. Cancelamos seu corte de quinta 13/08 às 8:00. Desculpa! "
        "Pra remarcar, chama: (83) 9 9999-0000"
    )


def test_cancelamento_do_cliente_pelo_central():
    from app.services.mensagens import msg_cancelamento

    texto = msg_cancelamento(barbeiro_nome="Zeca", inicio=INICIO, barbearia_nome="Dom Tony")
    assert texto == "*Dom Tony*\nHorário de quinta 13/08 às 8:00, com Zeca cancelado. Até a próxima!"


def test_sem_barbearia_o_texto_e_o_de_sempre():
    """O bot manda pelo numero da propria barbearia: la o cabecalho seria
    repeticao."""
    texto = msg_confirmacao(
        cliente_nome="Maria Silva", barbeiro_nome="Zeca", servico_nome="Corte",
        inicio=INICIO, endereco="Rua Aurora, 88", link="http://x/y",
    )
    assert texto.startswith("Fechou, Maria!")
```

Em `tests/test_agendamentos.py:179`, trocar `assert confirmacao.startswith("Fechou,")` por `assert confirmacao.startswith("*Brutus*\nFechou,")`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_mensagens.py tests/test_agendamentos.py -k "central or sempre or sem_sessao_e_manda"`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'barbearia_nome'`.

- [ ] **Step 3: Implementar os textos**

Em `backend/app/services/mensagens.py`, acrescentar `from tenant.telefone import formatar` aos imports e trocar as quatro funcoes por:

```python
def msg_confirmacao(
    *, cliente_nome: str, barbeiro_nome: str, servico_nome: str,
    inicio, endereco: str, link: str,
    barbearia_nome: str | None = None, contato: str | None = None,
) -> str:
    primeiro_nome = cliente_nome.split(" ")[0]
    # (manter aqui o comentario atual sobre o endereco ter saido)
    texto = (
        f"Fechou, {primeiro_nome}! {_capitalizar(servico_nome)} "
        f"{formatar_dia_com_semana(inicio)} às {formatar_hora_falada(inicio)}, "
        f"com {barbeiro_nome}.\n\nCancelar: {link}"
    )
    if barbearia_nome is None:
        return texto
    # Pelo numero CENTRAL (etapa 1): o cliente nao conhece este numero. O
    # nome da barbearia abre, e a ultima linha diz para onde responder — sem
    # ela, a duvida iria para um numero que ninguem le.
    return f"*{barbearia_nome}*\n{texto}\nDúvida? Chama: {formatar(contato)}"


def msg_cancelamento_pela_barbearia(
    *, cliente_nome: str, barbeiro_nome: str, servico_nome: str,
    inicio, endereco: str,
    barbearia_nome: str | None = None, contato: str | None = None,
) -> str:
    primeiro_nome = cliente_nome.split(" ")[0]
    # (manter o comentario atual sobre o pedido de desculpa)
    base = (
        f"Oi, {primeiro_nome}. Cancelamos seu {servico_nome.lower()} de "
        f"{formatar_dia_com_semana(inicio)} às {formatar_hora_falada(inicio)}. Desculpa!"
    )
    if barbearia_nome is None:
        return f"{base} Chama a gente pra remarcar."
    # "Chama a gente" pelo central levaria o cliente a responder para o
    # Marcai. O numero da barbearia vai escrito.
    return f"*{barbearia_nome}*\n{base} Pra remarcar, chama: {formatar(contato)}"


def msg_cancelamento(*, barbeiro_nome: str, inicio, barbearia_nome: str | None = None) -> str:
    """(manter o docstring atual)"""
    texto = (
        f"Horário de {formatar_dia_com_semana(inicio)} às {formatar_hora_falada(inicio)}, "
        f"com {barbeiro_nome} cancelado. Até a próxima!"
    )
    return texto if barbearia_nome is None else f"*{barbearia_nome}*\n{texto}"


def msg_lembrete(
    *, servico_nome: str, barbeiro_nome: str, inicio, endereco: str,
    barbearia_nome: str | None = None, contato: str | None = None,
) -> str:
    # (manter os comentarios atuais)
    hora = formatar_hora_falada(inicio)
    if barbearia_nome is None:
        return (
            f"*Lembrete: {servico_nome.lower()} hoje às {hora}*\n"
            f"com {barbeiro_nome}\n"
            f"Endereço: {endereco}"
        )
    # Pelo central: o nome da barbearia entra na linha em negrito (a que a
    # previa da notificacao mostra), e a ultima diz para onde avisar que nao
    # vai — sem ela, quem desiste avisaria um numero que ninguem le.
    return (
        f"*{barbearia_nome} — lembrete: {servico_nome.lower()} hoje às {hora}*\n"
        f"com {barbeiro_nome}\n"
        f"Endereço: {endereco}\n"
        f"Não vai dar? Chama: {formatar(contato)}"
    )
```

- [ ] **Step 4: Passar a barbearia em quem manda pelo central**

Em cada chamada abaixo, acrescentar os argumentos indicados (as chamadas do `bot.py` NAO mudam):

- `backend/app/api/v1/views/agendamentos.py` — `msg_confirmacao(...)`: `barbearia_nome=request.barbearia.nome, contato=request.barbearia.whatsapp_contato`; `msg_cancelamento(...)`: `barbearia_nome=request.barbearia.nome`.
- `backend/app/api/v1/views/agendamentos_painel.py` — `msg_confirmacao(...)` e `msg_cancelamento_pela_barbearia(...)`: `barbearia_nome=request.barbearia.nome, contato=request.barbearia.whatsapp_contato`.
- `backend/app/api/v1/views/bloqueios.py` — `msg_cancelamento_pela_barbearia(...)`: idem.
- `backend/app/services/lembrete.py` — o texto passa a depender do caminho. Trocar o `texto = msg_lembrete(...)` por:

```python
            # Pelo bot (numero da propria barbearia) o texto e' o de sempre;
            # pelo central, leva o nome da barbearia e o numero dela.
            texto = msg_lembrete(
                servico_nome=a.servico_nome, barbeiro_nome=a.barbeiro.nome,
                inicio=a.inicio, endereco=b.endereco,
                **({} if pelo_bot else {
                    "barbearia_nome": b.nome, "contato": b.whatsapp_contato,
                }),
            )
```

- [ ] **Step 5: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_mensagens.py tests/test_mensagens_bot.py tests/test_agendamentos.py tests/test_agendamentos_painel.py tests/test_bloqueios.py tests/test_cron_lembretes.py tests/test_bot_lembrete.py tests/test_bot.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/mensagens.py backend/app/services/lembrete.py backend/app/api/v1/views/agendamentos.py backend/app/api/v1/views/agendamentos_painel.py backend/app/api/v1/views/bloqueios.py tests/test_mensagens.py tests/test_agendamentos.py
git commit -m "mensagens: pelo central, o cliente le de que barbearia e' e para onde responder

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: A lista do dia que se refaz

**Files:**
- Modify: `backend/app/services/trava_conversa.py` (+ `trava_consultiva`)
- Modify: `backend/app/services/mensagens.py` (+ `msg_lista_refeita`)
- Modify: `backend/app/services/lista_do_dia.py`
- Modify: `backend/app/tasks.py` (+ `refazer_lista`)
- Modify: `backend/app/services/zelador.py` (+ `_podar_listas`)
- Modify: `tests/conftest.py` (+ fixture `refazer_enfileirado`)
- Modify: `tests/test_lista_do_dia.py`, `tests/test_mensagens.py`, `tests/test_zelador.py`

**Interfaces:**
- Consumes: `Aceita`, `enviar_a_equipe_aceita`, `apagar_para_todos` (Task 4); `ListaDoDiaEnviada` (Task 2).
- Produces (em `app.services.lista_do_dia`):
  - `HORA_DA_LISTA_MIN = 7 * 60`
  - `avisar_mudanca(barbearia_id, barbeiro_id, agora, *, novos=(), cancelados=()) -> bool` — `novos`/`cancelados` sao pares `(agendamento_id, inicio)`. Devolve True quando enfileirou (havia mudanca de HOJE, de 07:00 em diante).
  - `refazer(barbearia_id: str, barbeiro_id: str, novos: list[str], cancelados: list[str], agora) -> str` — `"refeita" | "sem_barbeiro" | "vazia" | "nao_saiu"`.
  - `_enfileirar_refazer(barbearia_id: str, barbeiro_id: str, novos: list[str], cancelados: list[str]) -> None`
- Produces: `app.tasks.refazer_lista(barbearia_id, barbeiro_id, novos, cancelados)`; `app.services.trava_conversa.trava_consultiva(chave, *, espera_s=...)`; `app.services.mensagens.msg_lista_refeita(*, barbeiro_nome, linhas, agora)` com `linhas = [{"cliente_nome", "servico_nome", "inicio", "marca": None | "novo" | "cancelado"}]`.

- [ ] **Step 1: Fixture global e texto — testes que falham**

Em `tests/conftest.py`, no fim:

```python
@pytest.fixture(autouse=True)
def refazer_enfileirado():
    """Nenhum teste fala com o Redis: marcar ou cancelar para HOJE depois das
    07:00 enfileira `refazer_lista`, e sem broker de verdade o `.delay`
    travaria. Os casos que querem saber o que foi enfileirado pedem esta
    fixture pelo nome."""
    from unittest.mock import patch

    with patch("app.services.lista_do_dia._enfileirar_refazer") as enfileirar:
        yield enfileirar
```

No fim de `tests/test_mensagens.py`:

```python
def test_lista_refeita_marca_o_novo_e_risca_o_cancelado():
    from datetime import timedelta

    from app.services.mensagens import msg_lista_refeita

    texto = msg_lista_refeita(
        barbeiro_nome="Zeca Silva",
        linhas=[
            {"cliente_nome": "João Silva", "servico_nome": "Corte", "inicio": INICIO, "marca": None},
            {"cliente_nome": "Pedro Lima", "servico_nome": "Barba",
             "inicio": INICIO + timedelta(hours=7), "marca": "novo"},
            {"cliente_nome": "Ana Souza", "servico_nome": "Corte",
             "inicio": INICIO + timedelta(hours=8), "marca": "cancelado"},
        ],
        agora=AGORA,
    )
    assert texto == (
        "Zeca, sua agenda de hoje mudou:\n"
        "João Silva · hoje 08:00 · Corte\n"
        "🆕 Pedro Lima · hoje 15:00 · Barba\n"
        "~Ana Souza · hoje 16:00 · Corte~ cancelou"
    )


def test_lista_refeita_sem_horario_restante_diz_que_esvaziou():
    from app.services.mensagens import msg_lista_refeita

    texto = msg_lista_refeita(
        barbeiro_nome="Zeca Silva",
        linhas=[{"cliente_nome": "Ana Souza", "servico_nome": "Corte",
                 "inicio": INICIO, "marca": "cancelado"}],
        agora=AGORA,
    )
    assert texto.endswith("~Ana Souza · hoje 08:00 · Corte~ cancelou\nNão sobrou horário hoje.")
```

- [ ] **Step 2: Testes da lista — os que falham**

Em `tests/test_lista_do_dia.py`:

1. Acrescentar aos imports: `from unittest.mock import Mock` (junto do `patch`), `from app.services.whatsapp import Aceita` e `ListaDoDiaEnviada` ao bloco `from tenant.models import (...)`.
2. Trocar `_rodar` por:

```python
def _rodar(aceita=Aceita("ID-07H", "jid-07h")):
    with patch.object(lista_do_dia, "enviar_a_equipe_aceita", return_value=aceita) as envia:
        enviados = lista_do_dia.enviar(AGORA)
    return enviados, {c.args[0]: c.args[1] for c in envia.call_args_list}
```

3. Trocar `test_a_lista_sai_pela_equipe_da_propria_barbearia` por:

```python
def test_a_lista_das_7_sai_pelo_central_e_fica_guardada(cenario):
    """Guardada para poder ser APAGADA quando a agenda de hoje mudar."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)

    _rodar()

    linha = ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id)
    assert (str(linha.dia), linha.mensagem_id, linha.remote_jid) == (
        dia_de_hoje(AGORA), "ID-07H", "jid-07h",
    )


@pytest.mark.parametrize("aceita", [None, Aceita(None, "jid"), Aceita("id", None)])
def test_lista_que_nao_saiu_ou_sem_id_nao_e_guardada(cenario, aceita):
    """Guardar sem id faria a proxima mudanca tentar apagar `None`."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)

    _rodar(aceita)
    assert not ListaDoDiaEnviada.objects.using("owner").filter(barbeiro_id=zeca.id).exists()
```

4. No fim do arquivo:

```python
# ------------------------------------------------- a lista que se refaz

TARDE = local_para_utc("2026-09-16", 10 * 60)


def _guardada(barbearia, barbeiro, mensagem_id="ID-ANTIGA", jid="jid-antiga"):
    return ListaDoDiaEnviada.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, barbeiro_id=barbeiro.id,
        dia=dia_de_hoje(AGORA), mensagem_id=mensagem_id, remote_jid=jid,
    )


def _refazer(barbearia, barbeiro, novos=(), cancelados=(), aceita=Aceita("ID-NOVA", "jid-nova"),
             apagou=True, agora=TARDE):
    with patch.object(lista_do_dia, "apagar_para_todos", return_value=apagou) as apagar, \
            patch.object(lista_do_dia, "enviar_a_equipe_aceita", return_value=aceita) as envia:
        resultado = lista_do_dia.refazer(
            str(barbearia.id), str(barbeiro.id),
            [str(a.id) for a in novos], [str(a.id) for a in cancelados], agora,
        )
    return resultado, apagar, envia


def test_refazer_apaga_a_anterior_e_manda_a_nova_com_o_novo_marcado(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Ja estava")
    novo = _agendamento(b, zeca, 15 * 60, cliente_nome="Acabou de marcar")
    _guardada(b, zeca)

    resultado, apagar, envia = _refazer(b, zeca, novos=[novo])

    assert resultado == "refeita"
    apagar.assert_called_once_with("jid-antiga", "ID-ANTIGA")
    destino, texto = envia.call_args.args
    assert destino == zeca.whatsapp
    assert texto.startswith("Zeca, sua agenda de hoje mudou:")
    assert "\nJa estava ·" in texto
    assert "🆕 Acabou de marcar ·" in texto
    linha = ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id)
    assert (linha.mensagem_id, linha.remote_jid) == ("ID-NOVA", "jid-nova")


def test_refazer_risca_o_cancelado(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60, cliente_nome="Fica")
    saiu = _agendamento(
        b, zeca, 11 * 60, cliente_nome="Desmarcou",
        status=StatusAgendamento.CANCELADO_CLIENTE,
    )

    _, _, envia = _refazer(b, zeca, cancelados=[saiu])
    texto = envia.call_args.args[1]
    assert "~Desmarcou · hoje 11:00 ·" in texto and texto.endswith("~ cancelou")
    assert "\nFica ·" in texto


def test_cancelado_de_antes_nao_aparece_na_lista_refeita(cenario):
    """O riscado vale so' na lista daquela mudanca."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    _agendamento(b, zeca, 9 * 60)
    _agendamento(b, zeca, 11 * 60, cliente_nome="Saiu ontem",
                 status=StatusAgendamento.CANCELADO_CLIENTE)
    novo = _agendamento(b, zeca, 15 * 60)

    _, _, envia = _refazer(b, zeca, novos=[novo])
    assert "Saiu ontem" not in envia.call_args.args[1]


def test_refazer_sem_lista_anterior_so_manda(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    resultado, apagar, envia = _refazer(b, zeca, novos=[novo])
    assert resultado == "refeita"
    apagar.assert_not_called()
    envia.assert_called_once()


def test_refazer_manda_mesmo_se_apagar_falhar(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca)

    resultado, _, envia = _refazer(b, zeca, novos=[novo], apagou=False)
    assert resultado == "refeita"
    envia.assert_called_once()


def test_refazer_sem_horario_restante_avisa(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    saiu = _agendamento(b, zeca, 11 * 60, status=StatusAgendamento.CANCELADO_BARBEIRO)

    _, _, envia = _refazer(b, zeca, cancelados=[saiu])
    assert envia.call_args.args[1].endswith("Não sobrou horário hoje.")


def test_duas_mudancas_seguidas_a_segunda_apaga_a_lista_da_primeira(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    primeiro = _agendamento(b, zeca, 14 * 60)
    segundo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca, "ID-07H", "jid-07h")

    _refazer(b, zeca, novos=[primeiro], aceita=Aceita("ID-1", "jid-1"))
    _, apagar, _ = _refazer(b, zeca, novos=[segundo], aceita=Aceita("ID-2", "jid-2"))

    apagar.assert_called_once_with("jid-1", "ID-1")
    assert ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id).mensagem_id == "ID-2"


def test_barbeiro_desativado_nao_recebe_lista_refeita(cenario):
    b = cenario["brutus"]
    saiu = _barbeiro(b, "Ja Foi", ativo=False)
    novo = _agendamento(b, saiu, 15 * 60)

    resultado, _, envia = _refazer(b, saiu, novos=[novo])
    assert resultado == "sem_barbeiro"
    envia.assert_not_called()


def test_envio_recusado_mantem_a_linha_anterior(cenario):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca)

    resultado, _, _ = _refazer(b, zeca, novos=[novo], aceita=None)
    assert resultado == "nao_saiu"
    assert ListaDoDiaEnviada.objects.using("owner").get(barbeiro_id=zeca.id).mensagem_id == "ID-ANTIGA"


def test_refazer_sem_url_nao_quebra(cenario, monkeypatch):
    """Desenvolvimento, sem Evolution: tudo devolve None/False e nada levanta."""
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)
    _guardada(b, zeca)

    assert lista_do_dia.refazer(str(b.id), str(zeca.id), [str(novo.id)], [], TARDE) == "nao_saiu"


# ------------------------------------------------- quando enfileirar


def _avisar(barbearia, barbeiro, agora, novos=(), cancelados=()):
    return lista_do_dia.avisar_mudanca(
        barbearia.id, barbeiro.id, agora,
        novos=[(a.id, a.inicio) for a in novos],
        cancelados=[(a.id, a.inicio) for a in cancelados],
    )


def test_mudanca_de_hoje_depois_das_7_enfileira(cenario, refazer_enfileirado):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    assert _avisar(b, zeca, TARDE, novos=[novo]) is True
    refazer_enfileirado.assert_called_once_with(str(b.id), str(zeca.id), [str(novo.id)], [])


def test_mudanca_de_hoje_as_6_59_nao_enfileira(cenario, refazer_enfileirado):
    """Antes das 07:00 a mudanca entra na lista das 07:00."""
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    assert _avisar(b, zeca, local_para_utc("2026-09-16", 6 * 60 + 59), novos=[novo]) is False
    refazer_enfileirado.assert_not_called()


def test_mudanca_de_hoje_as_7_em_ponto_enfileira(cenario, refazer_enfileirado):
    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    novo = _agendamento(b, zeca, 15 * 60)

    assert _avisar(b, zeca, AGORA, novos=[novo]) is True


def test_mudanca_de_amanha_nao_enfileira(cenario, refazer_enfileirado):
    from tenant.datas import somar_dias

    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    amanha = _agendamento(b, zeca, 15 * 60, dia=somar_dias(dia_de_hoje(AGORA), 1))

    assert _avisar(b, zeca, TARDE, novos=[amanha]) is False
    refazer_enfileirado.assert_not_called()


def test_so_os_de_hoje_vao_para_a_fila(cenario, refazer_enfileirado):
    """Um bloqueio pode derrubar hoje e amanha de uma vez."""
    from tenant.datas import somar_dias

    b = cenario["brutus"]
    zeca = _barbeiro(b, "Zeca Silva")
    hoje = _agendamento(b, zeca, 15 * 60)
    amanha = _agendamento(b, zeca, 15 * 60, dia=somar_dias(dia_de_hoje(AGORA), 1))

    assert _avisar(b, zeca, TARDE, cancelados=[hoje, amanha]) is True
    refazer_enfileirado.assert_called_once_with(str(b.id), str(zeca.id), [], [str(hoje.id)])
```

Em `tests/test_zelador.py`, no fim:

```python
def test_poda_listas_enviadas_antigas_e_preserva_as_recentes(cenario):
    from datetime import timedelta

    from django.utils import timezone

    from app.services.zelador import _podar_listas
    from tenant.config import ZELADOR_DIAS_DE_HISTORICO
    from tenant.models import Barbeiro, ListaDoDiaEnviada
    from tenant.rls import com_barbearia

    b = cenario["brutus"]
    barbeiro = Barbeiro.objects.using("owner").filter(barbearia_id=b.id).first()
    hoje = timezone.now().date()
    for dia, mensagem in (
        (hoje - timedelta(days=ZELADOR_DIAS_DE_HISTORICO + 1), "VELHA"),
        (hoje, "NOVA"),
    ):
        ListaDoDiaEnviada.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, barbeiro_id=barbeiro.id,
            dia=dia, mensagem_id=mensagem, remote_jid="j",
        )

    assert _podar_listas() == 1
    with com_barbearia(b.id):
        assert list(ListaDoDiaEnviada.objects.values_list("mensagem_id", flat=True)) == ["NOVA"]
```

(conferir que `uuid` esta importado no topo de `test_zelador.py`; se nao, importar.)

- [ ] **Step 3: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_lista_do_dia.py tests/test_mensagens.py tests/test_zelador.py`
Expected: FAIL — `msg_lista_refeita`, `enviar_a_equipe_aceita` em `lista_do_dia`, `refazer`, `avisar_mudanca`, `_podar_listas` inexistentes. Ate o Step 6, a fixture `refazer_enfileirado` do conftest tambem quebra TODO teste de qualquer arquivo (`AttributeError: ... no attribute '_enfileirar_refazer'`) — e' esperado; some quando `_enfileirar_refazer` existir.

- [ ] **Step 4: A trava**

Em `backend/app/services/trava_conversa.py`, trocar `trava_da_conversa` por:

```python
@contextmanager
def trava_consultiva(chave: str, *, espera_s: float = BOT_ESPERA_TRAVA_S):
    """Uma trava consultiva do Postgres por `chave`, na CONEXAO — ver o
    docstring do modulo. A conversa do bot e a lista do dia refeita usam."""
    with connection.cursor() as cur:
        # `lock_timeout` vale para trava consultiva tambem. Sem ele, um worker
        # preso numa conversa travada ficaria parado para sempre. RESET logo
        # em seguida: a conexao volta para a pool e o proximo uso nao pode
        # herdar o limite.
        cur.execute(f"SET lock_timeout = '{int(espera_s * 1000)}ms'")
        try:
            cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
        finally:
            cur.execute("RESET lock_timeout")
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])


@contextmanager
def trava_da_conversa(barbearia_id: str, whatsapp: str, *, espera_s: float = BOT_ESPERA_TRAVA_S):
    with trava_consultiva(f"{barbearia_id}:{whatsapp}", espera_s=espera_s):
        yield
```

- [ ] **Step 5: O texto**

Em `backend/app/services/mensagens.py`, logo depois de `msg_lista_do_dia`:

```python
def msg_lista_refeita(*, barbeiro_nome: str, linhas: list[dict], agora) -> str:
    """A lista de HOJE de novo, depois que ela mudou (a anterior foi
    apagada). Mesma linha da lista das 07:00, com duas marcas que so' valem
    nesta mensagem: "🆕" no horario que acabou de entrar e o riscado do
    WhatsApp ("~...~") no que acabou de sair. Na proxima lista o novo vira
    linha comum e o cancelado some.

    `linhas`: [{"cliente_nome", "servico_nome", "inicio", "marca"}], ja em
    ordem de horario, com `marca` None, "novo" ou "cancelado".
    """
    partes = [f"{barbeiro_nome.split()[0]}, sua agenda de hoje mudou:"]
    for linha in linhas:
        base = _linha_do_horario(
            cliente_nome=linha["cliente_nome"], servico_nome=linha["servico_nome"],
            inicio=linha["inicio"], agora=agora,
        )
        if linha["marca"] == "novo":
            partes.append(f"🆕 {base}")
        elif linha["marca"] == "cancelado":
            partes.append(f"~{base}~ cancelou")
        else:
            partes.append(base)
    if all(linha["marca"] == "cancelado" for linha in linhas):
        partes.append("Não sobrou horário hoje.")
    return "\n".join(partes)
```

- [ ] **Step 6: A lista**

Em `backend/app/services/lista_do_dia.py`:

1. Imports — trocar o bloco de imports por:

```python
import logging
from datetime import datetime

from django.db.models import Q

from tenant.datas import dia_de_hoje, local_para_utc, utc_para_local
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    ListaDoDiaEnviada,
    StatusAgendamento,
)
from tenant.rls import com_barbearia

from .mensagens import msg_lista_do_dia, msg_lista_refeita
from .trava_conversa import trava_consultiva
from .whatsapp import Aceita, apagar_para_todos, enviar_a_equipe_aceita

logger = logging.getLogger(__name__)

# A hora da lista (o `crontab(hour=7)` do settings). Depois dela, mudanca na
# agenda de hoje refaz a lista; antes, a mudanca entra na das 07:00.
HORA_DA_LISTA_MIN = 7 * 60
```

2. No docstring do modulo, trocar o paragrafo "Por qual numero, quem decide e' `enviar_a_equipe_da`: ..." por: "Sai pelo numero CENTRAL (etapa 1, spec 2026-10-06), e fica GUARDADA (`ListaDoDiaEnviada`) para poder ser apagada e mandada de novo quando a agenda de hoje muda."

3. Em `enviar`, trocar o laco final por:

```python
        for agendamentos_do_barbeiro in por_barbeiro.values():
            barbeiro = agendamentos_do_barbeiro[0].barbeiro
            aceita = enviar_a_equipe_aceita(
                barbeiro.whatsapp,
                msg_lista_do_dia(
                    barbeiro_nome=barbeiro.nome,
                    agendamentos=[
                        {
                            "cliente_nome": a.cliente.nome,
                            "servico_nome": a.servico_nome,
                            "inicio": a.inicio,
                        }
                        for a in agendamentos_do_barbeiro
                    ],
                    agora=agora,
                ),
            )
            _guardar(b.id, barbeiro.id, hoje, aceita)
            enviados += 1
```

4. No fim do arquivo:

```python
def _guardar(barbearia_id, barbeiro_id, dia: str, aceita: Aceita | None) -> bool:
    """Guarda a lista que saiu, para a proxima mudanca poder apaga-la. Sem id
    ou sem jid nao guarda: a proxima tentativa apagaria `None`."""
    if aceita is None or not aceita.id or not aceita.jid:
        return False
    with com_barbearia(barbearia_id):
        ListaDoDiaEnviada.objects.update_or_create(
            barbearia_id=barbearia_id, barbeiro_id=barbeiro_id, dia=dia,
            defaults={"mensagem_id": aceita.id, "remote_jid": aceita.jid},
        )
    return True


def avisar_mudanca(barbearia_id, barbeiro_id, agora: datetime, *, novos=(), cancelados=()) -> bool:
    """Chamada por quem mexe na agenda (site, painel, bloqueio), DEPOIS do
    commit. `novos`/`cancelados`: pares `(agendamento_id, inicio)`.

    Enfileira a lista refeita so' para o que e' de HOJE e so' de 07:00 em
    diante — antes disso a mudanca entra na lista das 07:00. Devolve se
    enfileirou: quem chama pelo site usa isso para NAO mandar tambem o aviso
    curto ("Novo horário"/"Cancelou").
    """
    hoje, minutos_agora = utc_para_local(agora)
    if minutos_agora < HORA_DA_LISTA_MIN:
        return False

    def de_hoje(pares):
        return [str(i) for i, inicio in pares if utc_para_local(inicio)[0] == hoje]

    ids_novos, ids_cancelados = de_hoje(novos), de_hoje(cancelados)
    if not ids_novos and not ids_cancelados:
        return False
    _enfileirar_refazer(str(barbearia_id), str(barbeiro_id), ids_novos, ids_cancelados)
    return True


def _enfileirar_refazer(barbearia_id: str, barbeiro_id: str, novos: list, cancelados: list) -> None:
    # Import tardio: `app.tasks` importa servicos, e este e' um deles.
    from app.tasks import refazer_lista

    refazer_lista.delay(barbearia_id, barbeiro_id, novos, cancelados)


def refazer(
    barbearia_id: str, barbeiro_id: str, novos: list, cancelados: list, agora: datetime,
) -> str:
    """Apaga a lista de hoje do barbeiro e manda a nova. Roda na task
    `refazer_lista`, fora do pedido HTTP.

    A trava e' por barbeiro e dia: duas mudancas seguidas saem em ordem, e a
    segunda apaga a lista da PRIMEIRA (e nao a das 07:00, que a primeira ja
    apagou). Consultiva e nao `select_for_update` porque segura duas idas a
    Evolution, e a linha pode nem existir ainda.

    Apagar que falha nao segura a lista nova: uma lista velha que nao sumiu
    e' feia; uma lista nova que nao chegou e' prejuizo.
    """
    hoje = dia_de_hoje(agora)
    ids_novos, ids_cancelados = set(novos), set(cancelados)

    with trava_consultiva(f"lista:{barbeiro_id}:{hoje}"):
        with com_barbearia(barbearia_id):
            barbeiro = Barbeiro.objects.filter(id=barbeiro_id, ativo=True).first()
            do_dia = list(
                Agendamento.objects.filter(
                    barbeiro_id=barbeiro_id,
                    inicio__gte=local_para_utc(hoje, 0),
                    inicio__lt=local_para_utc(hoje, 24 * 60),
                )
                .filter(Q(status=StatusAgendamento.CONFIRMADO) | Q(id__in=ids_cancelados))
                .select_related("cliente")
                .order_by("inicio")
            )
            anterior = ListaDoDiaEnviada.objects.filter(barbeiro_id=barbeiro_id, dia=hoje).first()

        if barbeiro is None:
            return "sem_barbeiro"
        if not do_dia:
            return "vazia"

        linhas = []
        for a in do_dia:
            if a.status == StatusAgendamento.CONFIRMADO:
                marca = "novo" if str(a.id) in ids_novos else None
            else:
                marca = "cancelado"
            linhas.append({
                "cliente_nome": a.cliente.nome, "servico_nome": a.servico_nome,
                "inicio": a.inicio, "marca": marca,
            })

        if anterior is not None:
            apagar_para_todos(anterior.remote_jid, anterior.mensagem_id)
        aceita = enviar_a_equipe_aceita(
            barbeiro.whatsapp,
            msg_lista_refeita(barbeiro_nome=barbeiro.nome, linhas=linhas, agora=agora),
        )
        if not _guardar(barbearia_id, barbeiro_id, hoje, aceita):
            logger.error("[lista-do-dia] lista refeita de %s nao saiu", barbeiro_id)
            return "nao_saiu"
        return "refeita"
```

- [ ] **Step 7: A task e a poda**

Em `backend/app/tasks.py`, acrescentar `from app.services.lista_do_dia import refazer as refazer_lista_do_dia` aos imports e, depois de `lista_do_dia`:

```python
@shared_task(ignore_result=True)
def refazer_lista(barbearia_id: str, barbeiro_id: str, novos: list, cancelados: list) -> str:
    """A lista de hoje de um barbeiro, apagada e mandada de novo depois que
    a agenda mudou. Fora do pedido HTTP: sao duas idas a Evolution, e quem
    marcou nao espera por elas.

    NAO RETENTA: uma lista que chega minutos depois, por cima de uma mais
    nova, desarrumaria a ordem — a proxima mudanca refaz de qualquer jeito.
    """
    return refazer_lista_do_dia(
        barbearia_id, barbeiro_id, novos, cancelados, datetime.now(timezone.utc),
    )
```

Em `backend/app/services/zelador.py`, acrescentar `ListaDoDiaEnviada` ao import de `tenant.models`, a chave `"podadas_listas": _podar_listas(),` no `return` de `alarmar_e_podar`, e no fim:

```python
def _podar_listas() -> int:
    """A lista enviada so' serve no proprio dia: e' por ela que a proxima
    mudanca acha a mensagem para apagar. Passado o prazo do historico, so'
    ocupa espaco."""
    limite = (timezone.now() - timedelta(days=ZELADOR_DIAS_DE_HISTORICO)).date()
    podadas = 0
    for b in Barbearia.objects.all():
        with com_barbearia(b.id):
            apagadas, _ = ListaDoDiaEnviada.objects.filter(dia__lt=limite).delete()
        podadas += apagadas
    return podadas
```

Se algum teste de `test_zelador.py` comparar o dicionario inteiro de `alarmar_e_podar`, acrescentar `"podadas_listas"` nele.

- [ ] **Step 8: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_lista_do_dia.py tests/test_mensagens.py tests/test_zelador.py tests/test_trava_conversa.py tests/test_bot.py tests/test_celery.py`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/trava_conversa.py backend/app/services/mensagens.py backend/app/services/lista_do_dia.py backend/app/tasks.py backend/app/services/zelador.py tests/conftest.py tests/test_lista_do_dia.py tests/test_mensagens.py tests/test_zelador.py
git commit -m "lista do dia: guarda a mensagem e se refaz quando a agenda de hoje muda

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Os cinco gatilhos

**Files:**
- Modify: `backend/app/services/agendamentos.py` (retornos de `marcar`, `cancelar`, `cancelar_publico`)
- Modify: `backend/app/api/v1/views/agendamentos.py`, `agendamentos_painel.py`, `bloqueios.py`
- Modify: `tests/test_agendamentos.py`, `tests/test_agendamentos_painel.py`, `tests/test_bloqueios.py`

**Interfaces:**
- Consumes: `lista_do_dia.avisar_mudanca` (Task 6), chamado como `lista_do_dia.avisar_mudanca(...)` depois de `from app.services import lista_do_dia` — e' esse nome que os testes trocam.
- Produces: `marcar(...)` devolve tambem `"id": str` e `"barbeiro_id": str`; `cancelar(...)` e o `{"tipo": "ok"}` de `cancelar_publico(...)` tambem.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_agendamentos.py`, depois da fixture `_sem_whatsapp_de_verdade`:

```python
@pytest.fixture(autouse=True)
def lista_refeita():
    """Por padrao, nenhuma mudanca cai na lista de hoje: os casos daqui
    marcam "daqui a pouco", e a decisao real dependeria da hora em que a
    suite roda. Quem testa a troca do aviso curto pela lista liga o
    retorno."""
    with patch("app.services.lista_do_dia.avisar_mudanca", return_value=False) as avisar:
        yield avisar
```

e no fim do arquivo:

```python
def test_marcar_para_hoje_refaz_a_lista_em_vez_do_aviso_curto(client, cenario, lista_refeita):
    lista_refeita.return_value = True
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with _envios() as mock_envia:
        r = client.post(
            "/api/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "José Neto",
                "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 201
    assert barbeiro.whatsapp not in mock_envia.destinos, "a lista refeita substitui o aviso"
    assert "11977778888" in mock_envia.destinos

    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    args, kwargs = lista_refeita.call_args
    assert (str(args[0]), str(args[1])) == (str(b.id), str(barbeiro.id))
    assert kwargs["novos"] == [(str(criado.id), criado.inicio)]


def test_cliente_cancelando_hoje_refaz_a_lista_em_vez_do_aviso_curto(client, cenario, lista_refeita):
    lista_refeita.return_value = True
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico, daqui_a_min=180)
    a = _agendamento(b.id, barbeiro, inicio)

    with _envios() as mock_envia:
        r = client.post(
            f"/api/agendamentos/{a.codigo}/cancelar",
            content_type="application/json", headers={"host": HOST, **CABECALHO},
        )
    assert r.status_code == 200
    assert barbeiro.whatsapp not in mock_envia.destinos
    assert lista_refeita.call_args.kwargs["cancelados"] == [(str(a.id), a.inicio)]
```

(`a.inicio` vem do banco como `datetime` com fuso; `marcar` devolve o `inicio` que entrou — os dois comparam iguais.)

Em `tests/test_agendamentos_painel.py`, no fim:

```python
def test_marcar_no_painel_avisa_a_lista_de_hoje(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    servico = _servico_vinculado(b.id, barbeiro)
    inicio = _proximo_slot_livre(barbeiro, servico)

    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"), patch(
        "app.services.lista_do_dia.avisar_mudanca"
    ) as avisar:
        r = client.post(
            "/api/painel/agendamentos",
            {
                "barbeiroId": barbeiro.id, "servicoId": servico.id,
                "inicio": inicio.isoformat(), "nome": "Cliente Novo",
                "whatsapp": "11977778888",
            },
            content_type="application/json", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 201
    from tenant.models import Agendamento

    criado = Agendamento.objects.using("owner").get(codigo=r.json()["codigo"])
    args, kwargs = avisar.call_args
    assert str(args[1]) == str(barbeiro.id)
    assert kwargs["novos"] == [(str(criado.id), criado.inicio)]


def test_cancelar_no_painel_avisa_a_lista_de_hoje(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)

    from tenant.models import Agendamento, Cliente, Servico

    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=20, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Cliente", whatsapp="11988889999",
    )
    futuro = datetime.now(timezone.utc) + timedelta(hours=3)
    a = Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=str(uuid.uuid4())[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=futuro, fim=futuro + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )

    with patch("app.api.v1.views.agendamentos_painel.enviar_ao_cliente"), patch(
        "app.services.lista_do_dia.avisar_mudanca"
    ) as avisar:
        r = client.post(
            f"/api/painel/agendamentos/{a.id}/cancelar", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 200
    args, kwargs = avisar.call_args
    assert str(args[1]) == str(barbeiro.id)
    assert [str(i) for i, _ in kwargs["cancelados"]] == [str(a.id)]
```

Em `tests/test_bloqueios.py`, no fim:

```python
def test_bloqueio_que_derruba_horarios_avisa_a_lista_uma_vez_com_todos(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    inicio = datetime.now(timezone.utc) + timedelta(days=1)
    um = _com_agendamento(b.id, barbeiro, inicio)
    outro = _com_agendamento(b.id, barbeiro, inicio + timedelta(minutes=30))

    corpo = _bloqueio_de_uma_vez(inicio - timedelta(minutes=30), inicio + timedelta(hours=2))
    corpo["cancelarConflitos"] = True
    with patch("app.api.v1.views.bloqueios.enviar_ao_cliente"), patch(
        "app.services.lista_do_dia.avisar_mudanca"
    ) as avisar:
        r = client.post(
            "/api/painel/bloqueios", corpo,
            content_type="application/json", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 201
    avisar.assert_called_once()
    args, kwargs = avisar.call_args
    assert str(args[1]) == str(barbeiro.id)
    assert sorted(str(i) for i, _ in kwargs["cancelados"]) == sorted([str(um.id), str(outro.id)])


def test_bloqueio_sem_ninguem_dentro_nao_avisa_a_lista(client, cenario):
    b = cenario["brutus"]
    barbeiro = _barbeiro(b.id)
    host = _logar(client, barbeiro, b.id)
    inicio = datetime.now(timezone.utc) + timedelta(days=1)

    with patch("app.services.lista_do_dia.avisar_mudanca") as avisar:
        r = client.post(
            "/api/painel/bloqueios",
            _bloqueio_de_uma_vez(inicio, inicio + timedelta(hours=1)),
            content_type="application/json", headers={"host": host, **CABECALHO},
        )
    assert r.status_code == 201
    avisar.assert_not_called()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_agendamentos.py tests/test_agendamentos_painel.py tests/test_bloqueios.py`
Expected: FAIL — os testes novos (`avisar_mudanca` nunca chamado; aviso curto ainda sai).

- [ ] **Step 3: Retornos dos servicos**

Em `backend/app/services/agendamentos.py`:
- no `return` de `marcar`, acrescentar `"id": novo_id,` e `"barbeiro_id": str(barbeiro_id),`;
- no `return` de `cancelar`, acrescentar `"id": str(a.id), "barbeiro_id": str(a.barbeiro_id),`;
- no `return {"tipo": "ok", ...}` de `cancelar_publico`, acrescentar `"id": str(a.id),` e `"barbeiro_id": str(a.barbeiro_id),`.

- [ ] **Step 4: As views**

Nas tres views, acrescentar `from app.services import lista_do_dia` aos imports.

`backend/app/api/v1/views/agendamentos.py` — em `AgendamentosView.post`, trocar o bloco do aviso ao barbeiro (o comentario "E o barbeiro..." e o `enviar_a_equipe_da(...)`) por:

```python
        # E o barbeiro. Para HOJE, depois que a lista das 07:00 saiu, ele
        # recebe a lista inteira refeita (com o horario novo marcado) no lugar
        # do aviso curto — um lugar so' para ler. Para outro dia, o aviso
        # curto de sempre.
        refeita = lista_do_dia.avisar_mudanca(
            self.barbearia_id, criado["barbeiro_id"], agora,
            novos=[(criado["id"], criado["inicio"])],
        )
        if not refeita:
            enviar_a_equipe_da(
                self.barbearia_id,
                criado["barbeiro_whatsapp"],
                msg_barbeiro_novo(
                    cliente_nome=d["nome"], servico_nome=criado["servico_nome"],
                    inicio=criado["inicio"], agora=datetime.now(timezone.utc),
                ),
            )
```

e em `AgendamentoCancelarPublicoView.post`, dentro do `if resultado["tipo"] == "ok":`, trocar o `enviar_a_equipe_da(...)` (e o comentario dele) por:

```python
            # A vaga abriu: quem ia cortar precisa saber sem abrir o painel.
            # Hoje, depois das 07:00, pela lista refeita; senao, aviso curto.
            refeita = lista_do_dia.avisar_mudanca(
                self.barbearia_id, resultado["barbeiro_id"], agora,
                cancelados=[(resultado["id"], resultado["inicio"])],
            )
            if not refeita:
                enviar_a_equipe_da(
                    self.barbearia_id,
                    resultado["barbeiro_whatsapp"],
                    msg_barbeiro_cancelado(
                        cliente_nome=resultado["cliente_nome"],
                        servico_nome=resultado["servico_nome"],
                        inicio=resultado["inicio"], agora=datetime.now(timezone.utc),
                    ),
                )
```

`backend/app/api/v1/views/agendamentos_painel.py`:
- em `AgendamentosPainelView.post`, depois do `enviar_ao_cliente(...)` e antes do `return`:

```python
        # Painel nao manda aviso curto ao barbeiro (nunca mandou); mas a
        # lista de HOJE, se ja saiu, e' refeita — inclusive para quem marcou
        # na propria agenda: a lista antiga some, e a que fica tem que estar
        # certa.
        lista_do_dia.avisar_mudanca(
            self.barbearia_id, criado["barbeiro_id"], agora,
            novos=[(criado["id"], criado["inicio"])],
        )
```

- em `AgendamentoCancelarView.post`, depois do `enviar_ao_cliente(...)` e antes do `return`:

```python
        lista_do_dia.avisar_mudanca(
            self.barbearia_id, cancelado["barbeiro_id"], datetime.now(timezone.utc),
            cancelados=[(cancelado["id"], cancelado["inicio"])],
        )
```

`backend/app/api/v1/views/bloqueios.py` — em `BloqueiosView.post`: antes do laco `for c in pegos:` criar `derrubados = []`; dentro do laco, logo depois de `cancelados += 1`, acrescentar `derrubados.append((dados["id"], dados["inicio"]))`; depois do laco e antes do `return`:

```python
        # Um aviso so' com todos os que cairam: o bloqueio da tarde nao pode
        # virar cinco listas seguidas.
        if derrubados:
            lista_do_dia.avisar_mudanca(
                self.barbearia_id, barbeiro_id, agora, cancelados=derrubados,
            )
```

- [ ] **Step 5: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_agendamentos.py tests/test_agendamentos_painel.py tests/test_bloqueios.py tests/test_bot.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agendamentos.py backend/app/api/v1/views/agendamentos.py backend/app/api/v1/views/agendamentos_painel.py backend/app/api/v1/views/bloqueios.py tests/test_agendamentos.py tests/test_agendamentos_painel.py tests/test_bloqueios.py
git commit -m "lista do dia: site, painel e bloqueio refazem a lista de hoje

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: O painel mostra a saudacao

**Files:**
- Modify: `backend/app/services/convite.py` (+ `link_da_vitrine`)
- Modify: `backend/app/services/mensagens.py` (+ `msg_saudacao`)
- Modify: `backend/app/services/whatsapp_painel.py` (`ver`)
- Modify: `backend/app/api/v1/views/whatsapp_painel.py` (`WhatsappPainelView`)
- Modify: `tests/test_whatsapp_painel.py`, `tests/test_bot_interruptor.py`

**Interfaces:**
- Produces: `GET /api/painel/whatsapp` -> `{"saudacao": str, "naoEnviadas": int}` para qualquer barbeiro logado. A Task 10 (front) le isso.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_whatsapp_painel.py`:
- trocar o docstring do modulo por: `"""GET /api/painel/whatsapp (a saudacao com o link, etapa 1) e POST /api/painel/whatsapp/desconectar."""`;
- APAGAR os testes `test_sem_zap_responde_o_plano_e_mais_nada`, `test_dono_ve_o_qr`, `test_barbeiro_ve_o_estado_mas_nunca_o_qr`, `test_conectado_mostra_o_numero`, `test_conta_as_mensagens_que_nao_sairam`, `test_dono_sem_qr_guardado_pede_um_novo`, `test_barbeiro_sem_qr_guardado_nao_pede_nada`, `test_pendente_nao_pede_qr` e `test_uma_barbearia_nao_ve_o_whatsapp_da_outra` (os de `desconectar` ficam);
- acrescentar:

```python
SAUDACAO = (
    "Oi! Pra marcar seu horário, é só tocar no link: https://brutus.usemarcai.online\n"
    "Se preferir, espera uns minutinhos que já vamos te responder."
)


@pytest.fixture(autouse=True)
def _url_base(monkeypatch):
    monkeypatch.setenv("URL_BASE", "https://usemarcai.online")


@pytest.mark.parametrize("papel", ["DONO", "BARBEIRO"])
def test_todo_barbeiro_ve_a_saudacao_com_o_link_da_barbearia(client, cenario, papel):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, papel), b)
    assert client.get(ROTA, headers={"host": host}).json() == {
        "saudacao": SAUDACAO, "naoEnviadas": 0,
    }


def test_conta_as_mensagens_que_nao_sairam(client, cenario):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, "DONO"), b)
    for nome in ("Ana", "Bia"):
        MensagemNaoEnviada.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, tipo="CONFIRMACAO", cliente_nome=nome,
        )
    assert client.get(ROTA, headers={"host": host}).json()["naoEnviadas"] == 2


def test_nao_ve_as_nao_enviadas_da_outra(client, cenario):
    outra = cenario["dontony"]
    MensagemNaoEnviada.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=outra.id, tipo="CONFIRMACAO", cliente_nome="De la",
    )
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b.id, "DONO"), b)
    assert client.get(ROTA, headers={"host": host}).json()["naoEnviadas"] == 0
```

Em `tests/test_bot_interruptor.py`, APAGAR `test_ver_mostra_o_interruptor_para_todo_mundo` e `test_ver_sem_zap_diz_desligado` (o `ver` nao fala mais do bot).

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_whatsapp_painel.py`
Expected: FAIL — `KeyError`/corpo com `plano`, `estado`, ... em vez de `saudacao`.

- [ ] **Step 3: Implementar**

Em `backend/app/services/convite.py`, depois de `link_do_convite`:

```python
def link_da_vitrine(slug: str) -> str:
    """A pagina publica da barbearia — o link que a saudacao do WhatsApp
    Business manda para quem escreve."""
    esquema, host = _base_valida()
    return f"{esquema}://{slug}.{host}"
```

Em `backend/app/services/mensagens.py`, no fim:

```python
def msg_saudacao(*, link: str) -> str:
    """O texto que o dono cola na "Mensagem de saudação" do WhatsApp
    Business (etapa 1): sai do numero da propria barbearia, por isso sem o
    nome dela."""
    return (
        f"Oi! Pra marcar seu horário, é só tocar no link: {link}\n"
        "Se preferir, espera uns minutinhos que já vamos te responder."
    )
```

Em `backend/app/services/whatsapp_painel.py`:
- trocar o docstring do modulo por: `"""O que o painel da barbearia sabe sobre o WhatsApp dela, desde a etapa 1 do numero central (spec 2026-10-06): o texto pronto da saudacao, com o link, e quantas mensagens de cliente nao sairam. Nao ha mais QR nem estado de conexao — o numero da barbearia nao fica ligado a nada."""`;
- apagar `ESTADOS_QUE_PEDEM_QR` e o import de `pedir_qr`;
- acrescentar `from .convite import link_da_vitrine` e `from .mensagens import msg_saudacao`;
- trocar `ver` inteira por:

```python
def ver(barbearia) -> dict:
    with com_barbearia(barbearia.id):
        nao_enviadas = MensagemNaoEnviada.objects.filter(barbearia_id=barbearia.id).count()
    return {
        "saudacao": msg_saudacao(link=link_da_vitrine(barbearia.slug)),
        "naoEnviadas": nao_enviadas,
    }
```

Em `backend/app/api/v1/views/whatsapp_painel.py`, trocar `WhatsappPainelView` por:

```python
class WhatsappPainelView(ExigeSessao, APIView):
    """GET /api/painel/whatsapp — de todo barbeiro logado: a saudacao e' so'
    um texto para copiar, e a contagem de nao enviadas interessa a quem
    atende o cliente que ligou perguntando."""

    def get(self, request):
        return Response(ver(request.barbearia))
```

- [ ] **Step 4: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_whatsapp_painel.py tests/test_bot_interruptor.py tests/test_convite.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/convite.py backend/app/services/mensagens.py backend/app/services/whatsapp_painel.py backend/app/api/v1/views/whatsapp_painel.py tests/test_whatsapp_painel.py tests/test_bot_interruptor.py
git commit -m "painel: /painel/whatsapp devolve a saudacao com o link no lugar do QR

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: O card do numero central no admin (back)

**Files:**
- Create: `backend/app/services/whatsapp_central.py`
- Create: `backend/app/api/v1/views/admin_whatsapp_central.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `tests/test_whatsapp_central.py`

**Interfaces:**
- Produces: `GET /api/admin/whatsapp-central` (so' admin) -> `{"configurado": bool, "conectado": bool, "numero": str | None, "qrBase64": str | None}`. A Task 11 (front) le isso.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_whatsapp_central.py`:

```python
"""GET /api/admin/whatsapp-central — o numero que carrega tudo desde a
etapa 1. O admin precisa ver se ele esta de pe e, quando nao estiver, ler o
QR com o chip do Marcai."""

from unittest.mock import Mock, patch

import pytest

from app.services.admin_sessao import COOKIE_SESSAO_ADMIN, emitir
from tenant.models import EstadoInstancia

pytestmark = pytest.mark.django_db(databases=["default", "owner", "admin"], transaction=True)

ROTA = "/api/admin/whatsapp-central"
CABECALHO = {"x-brutus-cliente": "web"}
HOST = "admin.localhost"
SERVICO = "app.services.whatsapp_central"


@pytest.fixture(autouse=True)
def _evolution(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "Marcai")


def _get(client):
    client.cookies[COOKIE_SESSAO_ADMIN] = emitir()
    return client.get(ROTA, headers={"host": HOST, **CABECALHO})


def test_sem_cookie_da_401(client):
    assert client.get(ROTA, headers={"host": HOST, **CABECALHO}).status_code == 401


def test_conectado_mostra_o_numero_e_nao_pede_qr(client):
    with patch(f"{SERVICO}.consultar_estado", return_value=EstadoInstancia.CONECTADO), patch(
        f"{SERVICO}.consultar_dono", return_value="5583999990000@s.whatsapp.net"
    ), patch(f"{SERVICO}.pedir_qr") as pedir:
        corpo = _get(client).json()
    assert corpo == {
        "configurado": True, "conectado": True, "numero": "83999990000", "qrBase64": None,
    }
    pedir.assert_not_called()


def test_desconectado_traz_o_qr(client):
    with patch(f"{SERVICO}.consultar_estado", return_value=EstadoInstancia.DESCONECTADO), patch(
        f"{SERVICO}.pedir_qr", return_value="data:image/png;base64,AAA"
    ):
        corpo = _get(client).json()
    assert corpo == {
        "configurado": True, "conectado": False, "numero": None,
        "qrBase64": "data:image/png;base64,AAA",
    }


def test_instancia_inexistente_e_criada_e_traz_o_qr(client):
    with patch(f"{SERVICO}.consultar_estado", return_value=EstadoInstancia.PENDENTE), patch(
        f"{SERVICO}.requests.post", return_value=Mock(ok=True, status_code=201)
    ) as post, patch(f"{SERVICO}.pedir_qr", return_value="data:image/png;base64,BBB"):
        corpo = _get(client).json()
    assert post.call_args.args[0] == "http://evolution:8080/instance/create"
    assert post.call_args.kwargs["json"]["instanceName"] == "Marcai"
    assert corpo["qrBase64"] == "data:image/png;base64,BBB"


def test_sem_evolution_configurada(client, monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL")
    assert _get(client).json() == {
        "configurado": False, "conectado": False, "numero": None, "qrBase64": None,
    }
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose run --rm api pytest -q tests/test_whatsapp_central.py`
Expected: FAIL — 404 na rota / modulo inexistente.

- [ ] **Step 3: Implementar**

Criar `backend/app/services/whatsapp_central.py`:

```python
"""O numero central do Marcai, visto do admin.

Desde a etapa 1 (spec 2026-10-06) ele carrega TUDO — equipe e cliente —,
entao o admin precisa ver se ele esta de pe e, quando nao estiver, ler o QR.
Antes disso o unico jeito era o manager da Evolution exposto, e a unica
noticia de queda era uma linha no log do `whatsapp_healthcheck`.
"""

import logging

import requests

from tenant.models import EstadoInstancia

from . import whatsapp
from .whatsapp_eventos import _numero_do_jid
from .whatsapp_instancias import TIMEOUT_CRIACAO_S, consultar_dono, consultar_estado, pedir_qr

logger = logging.getLogger(__name__)


def ver_central() -> dict:
    cfg = whatsapp._config()
    if not cfg["url"] or not cfg["instancia"]:
        return {"configurado": False, "conectado": False, "numero": None, "qrBase64": None}

    nome = cfg["instancia"]
    estado = consultar_estado(nome)
    if estado == EstadoInstancia.CONECTADO:
        return {
            "configurado": True, "conectado": True,
            "numero": _numero_do_jid(consultar_dono(nome)), "qrBase64": None,
        }
    # 404 na Evolution vira PENDENTE: a instancia central nao existe la
    # (volume novo, apagada a mao). Cria, e o QR sai na mesma visita.
    if estado == EstadoInstancia.PENDENTE:
        _criar(cfg, nome)
    return {"configurado": True, "conectado": False, "numero": None, "qrBase64": pedir_qr(nome)}


def _criar(cfg: dict, nome: str) -> None:
    """Sem webhook: o central so' manda. 403 "already in use" e' sucesso
    disfarcado (medido na 2.3.7, mesmo caso de `garantir_instancia`)."""
    try:
        r = requests.post(
            f"{cfg['url']}/instance/create",
            json={"instanceName": nome, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            headers={"apikey": cfg["chave"]},
            timeout=TIMEOUT_CRIACAO_S,
        )
    except requests.RequestException as e:
        logger.error("[whatsapp-central] falha ao criar %s: %s", nome, e)
        return
    if not r.ok and not (r.status_code == 403 and "already in use" in r.text):
        logger.error(
            "[whatsapp-central] criacao recusada (%s) para %s: %s",
            r.status_code, nome, r.text[:300],
        )
```

Criar `backend/app/api/v1/views/admin_whatsapp_central.py`:

```python
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.v1.mixins import ExigeAdmin
from app.services.whatsapp_central import ver_central


class AdminWhatsappCentralView(ExigeAdmin, APIView):
    """GET /api/admin/whatsapp-central — estado e QR do numero central."""

    def get(self, request):
        return Response(ver_central())
```

Em `backend/app/api/v1/router.py`, importar `from .views.admin_whatsapp_central import AdminWhatsappCentralView` e acrescentar, logo depois da rota `admin-barbearias-convite`:

```python
    path(
        "admin/whatsapp-central",
        AdminWhatsappCentralView.as_view(),
        name="admin-whatsapp-central",
    ),
```

- [ ] **Step 4: Rodar**

Run: `docker compose run --rm api pytest -q tests/test_whatsapp_central.py`
Expected: PASS. Se `numero` vier diferente de `"83999990000"`, o defeito e' do teste: conferir o que `_numero_do_jid` devolve para esse JID em `tests/test_whatsapp_webhook.py` e usar a mesma forma.

- [ ] **Step 5: Suite inteira do back**

Run: `docker compose run --rm api pytest -q`
Expected: PASS, sem nenhum teste pulado a mais que na `main`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/whatsapp_central.py backend/app/api/v1/views/admin_whatsapp_central.py backend/app/api/v1/router.py tests/test_whatsapp_central.py
git commit -m "admin: estado e QR do numero central

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: A tela do WhatsApp no painel (front)

Dentro de `Marcai-front/`. Criar a branch antes: `git switch -c whatsapp-central --no-track origin/main` e conferir `git rev-parse --abbrev-ref @{u}` -> erro "no upstream".

**Files:**
- Create: `src/lib/whatsapp-saudacao.ts`, `tests/whatsapp-saudacao.test.ts`
- Modify: `src/lib/api/painelAPI.ts` (bloco do WhatsApp), `src/lib/api/index.ts`
- Replace: `src/app/painel/whatsapp/page.tsx`
- Modify: `src/components/painel/NavPainel.tsx`
- Delete: `src/components/painel/FaixaDoWhatsapp.tsx`, `src/lib/whatsapp-estado.ts`, `tests/whatsapp-estado.test.ts`

**Interfaces:**
- Consumes: `GET /painel/whatsapp` -> `{ saudacao: string; naoEnviadas: number }` (Task 8).

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/whatsapp-saudacao.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { textoDasNaoEnviadas } from '@/lib/whatsapp-saudacao';

describe('textoDasNaoEnviadas', () => {
  it('não diz nada quando tudo saiu', () => {
    expect(textoDasNaoEnviadas(0)).toBeNull();
  });

  it('fala no singular para uma', () => {
    expect(textoDasNaoEnviadas(1)).toBe(
      '1 cliente não recebeu a mensagem — o WhatsApp do Marcaí estava fora do ar.',
    );
  });

  it('fala no plural para várias', () => {
    expect(textoDasNaoEnviadas(3)).toBe(
      '3 clientes não receberam a mensagem — o WhatsApp do Marcaí estava fora do ar.',
    );
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npm test -- tests/whatsapp-saudacao.test.ts`
Expected: FAIL — modulo `@/lib/whatsapp-saudacao` inexistente.

- [ ] **Step 3: Implementar**

Criar `src/lib/whatsapp-saudacao.ts`:

```ts
/// O aviso de mensagens que não chegaram ao cliente, na tela do WhatsApp.
///
/// Desde a etapa 1 do número central, quem cai é o WhatsApp do Marcaí, não
/// o da barbearia — o texto diz isso para o dono não sair procurando um
/// problema no celular dele.
export function textoDasNaoEnviadas(quantas: number): string | null {
  if (quantas <= 0) return null;
  return quantas === 1
    ? '1 cliente não recebeu a mensagem — o WhatsApp do Marcaí estava fora do ar.'
    : `${quantas} clientes não receberam a mensagem — o WhatsApp do Marcaí estava fora do ar.`;
}
```

Em `src/lib/api/painelAPI.ts`, trocar o tipo `EstadoDoWhatsapp`, o tipo `WhatsappDaBarbearia` e o `whatsappApi` inteiros por:

```ts
/// A tela do WhatsApp desde a etapa 1 do número central: o número da
/// barbearia não fica ligado a nada, então não há estado nem QR — só o texto
/// pronto da mensagem de saudação e as mensagens que não chegaram.
export type WhatsappDaBarbearia = {
  /// O que o dono cola na "Mensagem de saudação" do WhatsApp Business.
  saudacao: string;
  /// Mensagens de cliente que não saíram porque o número do Marcaí caiu.
  naoEnviadas: number;
};

export const whatsappApi = {
  ver: (signal?: AbortSignal) =>
    pedir<WhatsappDaBarbearia>('/painel/whatsapp', { signal, loginEm: LOGIN_DO_PAINEL }),
};
```

Em `src/lib/api/index.ts`, tirar `EstadoDoWhatsapp` da lista de tipos exportados.

Substituir `src/app/painel/whatsapp/page.tsx` inteiro por:

```tsx
'use client';
import { useCallback, useEffect, useState } from 'react';
import { Box, Frame, Lbl, Sub } from '@/components/wf';
import { mensagemDoErro, whatsappApi, type WhatsappDaBarbearia } from '@/lib/api';
import { textoDasNaoEnviadas } from '@/lib/whatsapp-saudacao';

/// A resposta automática com o link, feita pelo próprio WhatsApp Business
/// da barbearia.
///
/// Desde a etapa 1 do número central o número da barbearia não fica ligado
/// a sistema nenhum — risco zero de bloqueio para o negócio. Quem responde
/// "marca por aqui" é a mensagem de saudação do app, e esta tela só entrega
/// o texto pronto, com o link certo, e o caminho para colar.
export default function WhatsappDoPainel() {
  const [dados, setDados] = useState<WhatsappDaBarbearia | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);

  const carregar = useCallback(async (signal?: AbortSignal) => {
    try {
      setDados(await whatsappApi.ver(signal));
    } catch (e) {
      // `mensagemDoErro` devolve string vazia para aborto: trocar de tela no
      // meio da busca não pinta erro nenhum.
      const msg = mensagemDoErro(e);
      if (msg) setErro(msg);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void carregar(ctrl.signal);
    return () => ctrl.abort();
  }, [carregar]);

  async function copiar() {
    if (!dados) return;
    try {
      await navigator.clipboard.writeText(dados.saudacao);
      setCopiado(true);
    } catch {
      setErro('Não deu para copiar. Segura o dedo no texto e copia na mão.');
    }
  }

  const naoEnviadas = dados ? textoDasNaoEnviadas(dados.naoEnviadas) : null;

  return (
    <Frame>
      <h1>WhatsApp</h1>
      {erro && <Box variante="alerta">{erro}</Box>}
      {!dados ? <Sub>carregando…</Sub> : (
        <>
          {naoEnviadas && <Box variante="alerta">{naoEnviadas}</Box>}
          <Lbl>Resposta automática com o link</Lbl>
          <Box variante="copia" className="whitespace-pre-line break-words">{dados.saudacao}</Box>
          <button type="button" onClick={copiar} className="text-left">
            <Box variante={copiado ? 'sel' : 'normal'}>{copiado ? 'Copiado' : 'Copiar'}</Box>
          </button>
          <Lbl>Como ligar</Lbl>
          <Sub>
            No WhatsApp Business: Ferramentas comerciais → Mensagem de saudação →
            ativar → colar o texto → destinatários: todos.
          </Sub>
          <Sub>
            O WhatsApp manda a saudação na primeira mensagem de cada pessoa, ou
            depois de 14 dias sem conversa.
          </Sub>
        </>
      )}
    </Frame>
  );
}
```

Em `src/components/painel/NavPainel.tsx`, apagar o `import { FaixaDoWhatsapp } ...` e o `<FaixaDoWhatsapp />` junto com o comentario `{/* DEPOIS da navegação, ... */}` logo acima dele.

Apagar os arquivos:

```bash
git rm src/components/painel/FaixaDoWhatsapp.tsx src/lib/whatsapp-estado.ts tests/whatsapp-estado.test.ts
```

(A faixa e o estado voltam do historico do git se a etapa 2 precisar.)

- [ ] **Step 4: Rodar**

Run: `npm test` e `npx tsc --noEmit`
Expected: PASS; `tsc` sem erro. Se `tsc` apontar outro uso de `EstadoDoWhatsapp`, `whatsappApi.desconectar` ou `whatsappApi.ligarBot`, apagar esse uso — nenhum deles existe mais no back desta etapa para o painel.

- [ ] **Step 5: Commit**

```bash
git add src/lib/whatsapp-saudacao.ts tests/whatsapp-saudacao.test.ts src/lib/api/painelAPI.ts src/lib/api/index.ts src/app/painel/whatsapp/page.tsx src/components/painel/NavPainel.tsx
git commit -m "painel: a tela do WhatsApp entrega a saudacao com o link; sai a faixa de desconectado

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Admin sem seletor de plano e com o card do central (front)

**Files:**
- Modify: `src/lib/api/adminAPI.ts`, `src/lib/api/index.ts`
- Create: `src/components/admin/WhatsappCentral.tsx`
- Modify: `src/components/admin/FormBarbearia.tsx`, `src/components/admin/ListaBarbearias.tsx`, `src/app/admin/page.tsx`

**Interfaces:**
- Consumes: `GET /admin/whatsapp-central` -> `{ configurado: boolean; conectado: boolean; numero: string | null; qrBase64: string | null }` (Task 9). `/admin` ja esta em `MIGRADAS` (`src/lib/api/client.ts`), entao a rota nova vai para o Django sem mexer na lista.

- [ ] **Step 1: A API**

Em `src/lib/api/adminAPI.ts`:
- trocar o comentario de `Plano` por `/// O que a barbearia comprou. Desde a etapa 1 do número central toda barbearia é \`COM_ZAP\` (o cliente recebe pelo número do Marcaí); o tipo fica para os planos futuros.`;
- trocar o comentario de `NovaBarbearia.plano` por `/// Ausente = \`COM_ZAP\` do lado do servidor.`;
- apagar `trocarPlano` (e o comentario dele) de `adminApi`;
- acrescentar, antes de `export const adminApi`:

```ts
/// O número central do Marcaí — desde a etapa 1 ele manda tudo, equipe e
/// cliente. `qrBase64` só vem quando ele não está conectado.
export type WhatsappCentral = {
  configurado: boolean;
  conectado: boolean;
  numero: string | null;
  qrBase64: string | null;
};
```

- e dentro de `adminApi`:

```ts
  whatsappCentral: (signal?: AbortSignal) =>
    pedir<WhatsappCentral>('/admin/whatsapp-central', { signal, loginEm: LOGIN_DO_ADMIN }),
```

Em `src/lib/api/index.ts`, acrescentar `WhatsappCentral` ao `export type { ... } from './adminAPI';`.

- [ ] **Step 2: O card**

Criar `src/components/admin/WhatsappCentral.tsx`:

```tsx
'use client';
import { useCallback, useEffect, useState } from 'react';
import { Box, Lbl, Sub } from '@/components/wf';
import { adminApi, mensagemDoErro, type WhatsappCentral as Central } from '@/lib/api';
import { formatar } from '@/lib/telefone';

/// O QR troca a cada ~40s na Evolution: enquanto não conecta, a tela confere
/// de 3 em 3 — o mesmo ritmo que a tela do QR da barbearia usava.
const CONFERIR_MS = 3_000;

/// O número central do Marcaí no topo do admin.
///
/// Desde a etapa 1 ele carrega tudo — lista, avisos, confirmação, lembrete.
/// Se ele cai, cai para todas as barbearias de uma vez; por isso o estado
/// fica à vista, e o QR para reconectar fica aqui, sem precisar expor o
/// manager da Evolution.
export function WhatsappCentral() {
  const [dados, setDados] = useState<Central | null>(null);
  const [erro, setErro] = useState('');

  const carregar = useCallback(async (signal?: AbortSignal) => {
    try {
      setDados(await adminApi.whatsappCentral(signal));
      setErro('');
    } catch (e) {
      const msg = mensagemDoErro(e);
      if (msg) setErro(msg);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void carregar(ctrl.signal);
    return () => ctrl.abort();
  }, [carregar]);

  const conectado = dados?.conectado === true;
  useEffect(() => {
    if (conectado) return;
    const t = setInterval(() => { void carregar(); }, CONFERIR_MS);
    return () => clearInterval(t);
  }, [conectado, carregar]);

  return (
    <>
      <Lbl>whatsapp do marcaí</Lbl>
      {erro && <Sub className="text-acento">{erro}</Sub>}
      {!dados ? <Sub>carregando…</Sub>
        : !dados.configurado ? <Box variante="mut">sem Evolution configurada neste ambiente</Box>
        : dados.conectado ? (
          <Box variante="sel">conectado{dados.numero ? ` · ${formatar(dados.numero)}` : ''}</Box>
        ) : dados.qrBase64 ? (
          <>
            <Box variante="alerta">desconectado — nada sai para equipe nem cliente</Box>
            {/* `data:image/png;base64,...` vem pronto da Evolution. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={dados.qrBase64}
              alt="QR code para conectar o WhatsApp do Marcaí"
              className="w-full max-w-[280px] self-center rounded-wf border border-borda bg-white p-2"
            />
            <Sub>No celular do chip do Marcaí: WhatsApp → Aparelhos conectados → Conectar um aparelho.</Sub>
          </>
        ) : (
          <Box variante="alerta">desconectado, e a Evolution não mandou QR — tenta de novo em instantes</Box>
        )}
    </>
  );
}
```

- [ ] **Step 3: Sem seletor de plano**

Em `src/components/admin/FormBarbearia.tsx`:
- import: `import { adminApi, mensagemDoErro, type NovaBarbearia } from '@/lib/api';` (sai `Plano`);
- apagar o `useState<Plano>` e o comentario dele, o `setPlano('SEM_ZAP')` do `criar`, o `, plano` do `criarBarbearia({...})`, e o bloco de JSX do plano (o comentario `{/* Escolha de DOIS ... */}`, o `<Lbl>plano</Lbl>`, o `<div>` com as duas `Chip` e o `{plano === 'COM_ZAP' && (...)}`);
- o `import { Box, Chip, Lbl, Sub }` vira `import { Box, Lbl, Sub }` se `Chip` nao sobrar em uso.

Em `src/components/admin/ListaBarbearias.tsx`: apagar a funcao `trocarPlano` (com o comentario `///` dela) e, no JSX, o comentario `{/* O plano é o que a barbearia PAGA ... */}` e a `<Chip ... onClick={() => trocarPlano(b)}>` logo abaixo.

Em `src/app/admin/page.tsx`: importar `import { WhatsappCentral } from '@/components/admin/WhatsappCentral';` e, no `return`, colocar antes de `<ListaBarbearias ... />`:

```tsx
      <WhatsappCentral />
      <Sep />
```

- [ ] **Step 4: Rodar**

Run: `npm test` e `npx tsc --noEmit`
Expected: PASS; `tsc` sem erro.

- [ ] **Step 5: Commit**

```bash
git add src/lib/api/adminAPI.ts src/lib/api/index.ts src/components/admin/WhatsappCentral.tsx src/components/admin/FormBarbearia.tsx src/components/admin/ListaBarbearias.tsx src/app/admin/page.tsx
git commit -m "admin: card do WhatsApp do Marcai e sem seletor de plano

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Medicao com numero de verdade e roteiro de subida (manual, com o Jose)

Nao e' codigo. Precisa do chip do Marcai e do celular de um barbeiro de teste.

- [ ] **Step 1: Subir local com a Evolution de pe**

Em `Marcai-back`: `docker compose up -d` e conferir que `Marcai-back-evolution` fica `Up` (hoje ela esta em `Restarting` na maquina do Jose — ver `docker compose logs evolution` antes de seguir). Front: `npm run dev` em `Marcai-front`.

- [ ] **Step 2: Conectar o central pelo card**

Entrar em `admin.localhost:3000/admin`, ler o QR do card "whatsapp do marcaí" com o chip do Marcai. Esperado: o card vira "conectado · (83) ...".

- [ ] **Step 3: Medir o apagar (a premissa do spec, secao 6)**

Com um barbeiro de teste cujo WhatsApp e' de um celular a mao, e com um horario dele hoje:

```bash
docker compose run --rm api python manage.py shell -c 'exec("from datetime import datetime, timezone\nfrom app.services import lista_do_dia\nprint(lista_do_dia.enviar(datetime.now(timezone.utc)))")'
```

Depois marcar pelo site um horario para HOJE com esse barbeiro (depois das 07:00). Esperado no celular: a lista anterior vira "Mensagem apagada" e chega a lista nova com "🆕". Se a anterior NAO sumir, anotar no ledger e no PR: a etapa segue com "so' manda de novo" (o codigo ja faz isso), e o log mostra `apagar recusado`.

- [ ] **Step 4: Conferir o resto no celular**

- confirmacao ao cliente chega do numero do Marcai, comecando com `*<nome da barbearia>*` e terminando em "Dúvida? Chama: ...";
- cancelar o horario pelo link: a lista do barbeiro e' refeita com o cancelado riscado;
- `/painel/whatsapp` mostra a saudacao com o link da barbearia, e o Copiar funciona;
- a faixa de "WhatsApp desconectado" nao aparece em tela nenhuma do painel.

- [ ] **Step 5: Roteiro de producao (para o PR)**

Escrever na descricao dos dois PRs, nesta ordem (secao 9 do spec):

1. Mergear back e front juntos.
2. Deploy no Coolify.
3. No admin, ler o QR do card com o chip do Marcai.
4. No terminal do conteiner `api`: `python manage.py desligar_instancias_das_barbearias`.
5. Cada dono cola a saudacao no WhatsApp Business.
