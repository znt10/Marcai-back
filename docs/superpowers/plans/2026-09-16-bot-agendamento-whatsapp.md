# Bot de agendamento pelo WhatsApp — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O cliente escreve para o WhatsApp da própria barbearia e um bot de menu numerado marca, cancela e responde ao lembrete — sem ninguém da barbearia tocar no celular.

**Architecture:** Uma máquina de conversa **pura** (`conversa.py`) decide; uma casca (`bot.py`) lê o estado, busca opções no banco reusando os serviços que já existem (`marcar`, `cancelar_publico`, `dias_com_horarios`), executa e grava. O webhook descarta cedo e enfileira; um worker Celery responde. Uma trava consultiva do Postgres por `(barbearia, número)` serializa a conversa inteira.

**Tech Stack:** Python 3.12, Django 6.0.3, DRF 3.17, Celery 5.5, Postgres 16 com RLS, Evolution API 2.3.7 (Baileys), Next.js 16 + vitest no front.

**Spec:** `docs/superpowers/specs/2026-09-16-bot-agendamento-whatsapp-design.md` (inclusive a seção 11, resultado da fatia 0). Leia a spec inteira antes da primeira tarefa — este plano argumenta a partir dela.

## Global Constraints

- Repositórios: `Marcai-back` (tarefas 1–8, 10–13) e `Marcai-front` (tarefa 9). Comandos do back rodam de dentro de `Marcai-back`, via `docker compose exec -T api ...`. Crie os arquivos pelo host (editor), nunca com `docker compose run`: arquivo gerado dentro do contêiner nasce com dono `root`.
- Todo acesso a tabela de tenant acontece dentro de `com_barbearia(barbearia_id)`. **`com_barbearia` NUNCA é aninhado** (`atomic(durable=True)` estoura de propósito). `marcar`, `cancelar_publico`, `dias_com_horarios` e `servicos.listar_para_agendamento` abrem o próprio — chame-os FORA de qualquer `com_barbearia`.
- Testes de banco: `pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)`; cenário montado com `.using("owner")`; a fixture `cenario` do `conftest.py` dá as barbearias `brutus` e `dontony`.
- **Todo texto que sai pelo WhatsApp mora em `backend/app/services/mensagens.py`.**
- Cliente ← instância da barbearia (`_enviar(instancia.nome, ...)`); equipe ← número central (`enviar_a_equipe`). Nunca o contrário.
- O bot entende **só o número sozinho**. `"0"` chama gente em qualquer passo.
- O bot **nunca** responde grupo (`@g.us`) e **não guarda** texto de cliente: só o estado da conversa e o nome (que já vive em `Cliente`).
- O webhook responde `200` para tudo, exceto `401` de credencial. Qualquer outro status faz a Evolution reenviar.
- Constantes novas em `backend/tenant/config.py`. Datas pelo fuso `America/Sao_Paulo`, só via `tenant/datas.py`.
- A task do Celery **não retenta**.
- Commits em português, com o porquê no corpo, terminando em `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Onde este plano diverge da spec, e por quê

1. **Três colunas a mais em `ConversaWhatsapp`:** `tentativas` (a regra "na terceira vez oferece o 0" precisa contar), `pergunta` (repetir a pergunta com as MESMAS opções gravadas — refazer do banco mudaria a numeração embaixo do cliente) e `ids_do_bot` (ver item 3).
2. **Trava consultiva no lugar de `select_for_update`.** A trava de linha morre no fim da transação, e a conversa atravessa várias (`marcar` abre a própria). `pg_advisory_lock` vive na conexão e segura ler → decidir → marcar → responder → gravar.
3. **Eco das mensagens do próprio bot.** As respostas do bot saem do número da barbearia; se a Evolution devolver cada uma como `fromMe`, o bot se calaria sozinho a cada resposta. O bot guarda os ids do que mandou e `silenciar` ignora esses ids, esperando a mesma trava da conversa para não correr contra a gravação. A tarefa 10 mede se o eco existe e se os ids batem.
4. **O lembrete oferece "Não vou conseguir ir", e não "Cancelar".** O lembrete sai `LEMBRETE_ANTECEDENCIA_MIN = 60` minutos antes, e o cliente só cancela com mais de `PRAZO_CANCELAMENTO_MIN = 60`: um "cancelar" no lembrete daria SEMPRE "fora do prazo". A opção avisa o barbeiro, que desmarca pelo painel (onde não há prazo), e a regra de prazo continua intocada. **Decisão de produto a confirmar com o José antes da tarefa 12.**
5. **(Revertida depois da fatia 0b: `base64` é sempre `true`, com ou sem bot.)** **`base64: false` quando o bot está ligado.** A fatia 0 viu mídia inteira dentro dos eventos por causa do `base64: true` que o QR usa. Com o bot ligado, o QR ainda chega pela busca de `pedir_qr` no painel. A tarefa 10 confirma.

## Mapa de arquivos

**Back — criar**
- `backend/tenant/migrations/0006_bot_agendamento.py` — `bot_ativo`, `ConversaWhatsapp`, RLS.
- `backend/app/services/conversa.py` — a máquina pura.
- `backend/app/services/trava_conversa.py` — a trava consultiva.
- `backend/app/services/bot.py` — a casca: `processar`, `silenciar`, `enviar_lembrete_pelo_bot`.
- `backend/app/services/bot_entrada.py` — leitura do evento e despacho.
- Testes: `tests/test_conversa.py`, `tests/test_mensagens_bot.py`, `tests/test_trava_conversa.py`, `tests/test_bot.py`, `tests/test_bot_interruptor.py`, `tests/test_bot_entrada.py`, `tests/test_bot_lembrete.py`, `tests/test_conversa_modelo.py`.

**Back — modificar**
- `backend/tenant/config.py`, `backend/tenant/models.py`, `backend/tenant/telefone.py`
- `backend/app/services/mensagens.py`, `convite.py`, `whatsapp.py`, `whatsapp_instancias.py`, `whatsapp_painel.py`, `lembrete.py`, `zelador.py`
- `backend/app/api/v1/views/interno.py`, `views/whatsapp_painel.py`, `router.py`
- `backend/app/tasks.py`
- `tests/conftest.py`, `tests/test_rls.py`, `tests/test_telefone.py` (criar se não existir), `tests/test_convite.py`, `tests/test_whatsapp.py`, `tests/test_whatsapp_instancias.py`, `tests/test_zelador.py`, `tests/test_celery.py`

**Front — modificar**
- `src/lib/api/painelAPI.ts`, `src/app/painel/whatsapp/page.tsx`

## Ordem

As tarefas 1–9 não dependem de medição nenhuma e podem começar já. **A tarefa 10 exige um chip de WhatsApp dedicado a teste** e é portão das tarefas 11 e 12: elas leem o formato de evento que a 10 mede.

---

### Task 1: Constantes, modelos e migração com RLS

**Files:**
- Modify: `backend/tenant/config.py` (acrescentar no fim)
- Modify: `backend/tenant/models.py` (`EstadoConversa` depois de `TipoMensagem`; `bot_ativo` em `WhatsappInstancia`; `ConversaWhatsapp` no fim)
- Create: `backend/tenant/migrations/0006_bot_agendamento.py`
- Modify: `tests/conftest.py` (lista do `TRUNCATE`)
- Modify: `tests/test_rls.py` (acrescentar no fim)
- Create: `tests/test_conversa_modelo.py`

**Interfaces:**
- Produces: constantes `BOT_*`; `EstadoConversa`; `WhatsappInstancia.bot_ativo: bool`; `ConversaWhatsapp` com os campos `barbearia, whatsapp, estado, opcoes (list), rascunho (dict), tentativas (int), pergunta (str|None), ultima_mensagem_id (str|None), ids_do_bot (list[str]), mudo_ate (datetime|None), atualizado_em (datetime)`, único por `(barbearia, whatsapp)`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_rls.py`, no fim:

```python
def _conversa(barbearia, whatsapp):
    from tenant.models import ConversaWhatsapp

    return ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, whatsapp=whatsapp,
    )


def test_conversa_do_bot_nao_vaza_entre_barbearias(cenario):
    from tenant.models import ConversaWhatsapp

    _conversa(cenario["brutus"], "83911110000")
    _conversa(cenario["dontony"], "83922220000")

    with com_barbearia(cenario["brutus"].id):
        assert list(ConversaWhatsapp.objects.values_list("whatsapp", flat=True)) == [
            "83911110000"
        ]
    # Fora do wrapper, ZERO: o numero de quem conversa com uma barbearia nao
    # pode aparecer numa consulta que esqueceu o tenant.
    assert ConversaWhatsapp.objects.count() == 0
```

Crie `tests/test_conversa_modelo.py`:

```python
"""O que o banco garante sobre a conversa do bot, antes de qualquer regra."""

import uuid

import pytest
from django.db import IntegrityError

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import ConversaWhatsapp, WhatsappInstancia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _conversa(barbearia, whatsapp="83911110000"):
    return ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, whatsapp=whatsapp,
    )


def test_o_bot_nasce_desligado(cenario):
    """Ninguem acorda com um robo atendendo o numero do proprio negocio."""
    b = cenario["brutus"]
    linha = WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=nome_da_instancia(b.id),
    )
    assert linha.bot_ativo is False


def test_conversa_nasce_no_menu_sem_nada_guardado(cenario):
    c = _conversa(cenario["brutus"])
    assert c.estado == "MENU"
    assert c.opcoes == []
    assert c.rascunho == {}
    assert c.tentativas == 0
    assert c.ids_do_bot == []
    assert c.mudo_ate is None


def test_o_mesmo_numero_e_uma_conversa_so_por_barbearia(cenario):
    _conversa(cenario["brutus"])
    with pytest.raises(IntegrityError):
        _conversa(cenario["brutus"])


def test_o_mesmo_numero_em_duas_barbearias_sao_duas_conversas(cenario):
    _conversa(cenario["brutus"])
    _conversa(cenario["dontony"])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose exec -T api pytest tests/test_conversa_modelo.py tests/test_rls.py -q`
Expected: FAIL com `ImportError: cannot import name 'ConversaWhatsapp'`.

- [ ] **Step 3: Constantes**

No fim de `backend/tenant/config.py`:

```python
# ---- Bot de agendamento pelo WhatsApp ------------------------------------
# docs/superpowers/specs/2026-09-16-bot-agendamento-whatsapp-design.md

# Conversa parada ha mais que isto recomeca do menu: um "2" digitado amanha
# nao pode confirmar o horario escolhido hoje.
BOT_CONVERSA_EXPIRA_MIN = 20
# A resposta ao lembrete vale enquanto o lembrete vale: ele sai
# LEMBRETE_ANTECEDENCIA_MIN antes do horario, e depois disso nao ha o que
# responder.
BOT_LEMBRETE_VALE_MIN = LEMBRETE_ANTECEDENCIA_MIN
# Quanto o bot fica quieto numa conversa em que alguem da barbearia respondeu
# pelo celular, ou em que o cliente pediu gente ("0").
BOT_MUDO_HORAS = 4
# Na terceira resposta que nao e' numero da lista, o bot oferece o "0" em vez
# de repetir o mesmo menu para sempre.
BOT_TENTATIVAS_ANTES_DO_ZERO = 3
BOT_DIAS_OFERECIDOS = 5
BOT_HORAS_OFERECIDAS = 6
# Quantos dias a frente o bot procura vaga antes de dizer que nao ha.
BOT_JANELA_DIAS = 21
# Os ids das ultimas respostas do bot, para reconhecer o eco delas no webhook.
BOT_IDS_GUARDADOS = 20
BOT_ESPERA_TRAVA_S = 10
# Conversa e' estado de minutos. Passados estes dias sem mexer, a linha so'
# guardaria o numero de alguem sem motivo.
BOT_CONVERSA_GUARDADA_DIAS = 2
```

- [ ] **Step 4: Modelos**

Em `backend/tenant/models.py`, logo depois de `class TipoMensagem`:

```python
class EstadoConversa(models.TextChoices):
    """Em que pergunta a conversa do bot esta parada.

    NAO existe estado "mudo". O silencio e' a coluna `mudo_ate`: entrar em mudo
    nao pode apagar onde a conversa estava (spec, secao 3).
    """

    MENU = "MENU"
    SERVICO = "SERVICO"
    BARBEIRO = "BARBEIRO"
    DIA = "DIA"
    HORA = "HORA"
    NOME = "NOME"
    CONFIRMA = "CONFIRMA"
    QUAL_AGENDAMENTO = "QUAL_AGENDAMENTO"
    CONFIRMA_CANCEL = "CONFIRMA_CANCEL"
    AGUARDANDO_LEMBRETE = "AGUARDANDO_LEMBRETE"
```

Em `class WhatsappInstancia`, logo depois de `desconectado_desde`:

```python
    # O interruptor do bot. Mora AQUI e nao em `Barbearia` porque quem liga e'
    # o dono, pelo painel, e o runtime (`brutus_app`) nao tem UPDATE em
    # `tenant_barbearia` (0002_rls.py). Nasce desligado.
    bot_ativo = models.BooleanField(default=False)
```

No fim do arquivo:

```python
class ConversaWhatsapp(models.Model):
    """Onde a conversa do bot com UM numero esta parada.

    Uma linha por conversa, sobrescrita a cada passo, e NAO uma por mensagem:
    uma tabela que crescesse por mensagem seria ilimitada e cheia de texto de
    cliente, e o Marcai nao guarda o que foi conversado (spec, secao 2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.RESTRICT, related_name="conversas",
    )
    # 10 ou 11 digitos nacionais, na MESMA forma de `Cliente.whatsapp` — e'
    # por essa igualdade que o bot acha o cliente.
    whatsapp = models.TextField()
    estado = models.CharField(
        max_length=24, choices=EstadoConversa, default=EstadoConversa.MENU,
    )
    # O que o bot OFERECEU: [{"id": ..., "rotulo": ...}]. Entender "2" e'
    # `opcoes[1]`, sem consultar o banco.
    opcoes = models.JSONField(default=list)
    # O que ja foi decidido: servico_id, barbeiro_id, dia, inicio...
    rascunho = models.JSONField(default=dict)
    tentativas = models.IntegerField(default=0)
    # O texto da ultima pergunta. "Nao entendi" repete ESTE texto, com as MESMAS
    # opcoes — refazer a lista do banco podia mudar a numeracao embaixo do
    # cliente.
    pergunta = models.TextField(null=True)
    ultima_mensagem_id = models.TextField(null=True)
    # Os ids das mensagens que o bot mandou. O webhook devolve cada uma como
    # `fromMe`; sem reconhecer o proprio eco, o bot se calaria a cada resposta.
    ids_do_bot = models.JSONField(default=list)
    mudo_ate = models.DateTimeField(null=True)
    atualizado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["barbearia", "whatsapp"], name="conversa_por_numero",
            ),
        ]

    def __str__(self):
        return f"{self.whatsapp} ({self.estado})"
```

- [ ] **Step 5: Migração**

Crie `backend/tenant/migrations/0006_bot_agendamento.py`:

```python
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# Tabela de tenant NOVA: nasce com politica e GRANT aqui, na propria migration,
# como a 0005 fez — migration aplicada e' historia congelada.
_T = "tenant_conversawhatsapp"

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


class Migration(migrations.Migration):
    dependencies = [("tenant", "0005_whatsapp_por_barbearia")]

    operations = [
        migrations.AddField(
            model_name="whatsappinstancia",
            name="bot_ativo",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="ConversaWhatsapp",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("whatsapp", models.TextField()),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("MENU", "Menu"),
                            ("SERVICO", "Servico"),
                            ("BARBEIRO", "Barbeiro"),
                            ("DIA", "Dia"),
                            ("HORA", "Hora"),
                            ("NOME", "Nome"),
                            ("CONFIRMA", "Confirma"),
                            ("QUAL_AGENDAMENTO", "Qual Agendamento"),
                            ("CONFIRMA_CANCEL", "Confirma Cancel"),
                            ("AGUARDANDO_LEMBRETE", "Aguardando Lembrete"),
                        ],
                        default="MENU",
                        max_length=24,
                    ),
                ),
                ("opcoes", models.JSONField(default=list)),
                ("rascunho", models.JSONField(default=dict)),
                ("tentativas", models.IntegerField(default=0)),
                ("pergunta", models.TextField(null=True)),
                ("ultima_mensagem_id", models.TextField(null=True)),
                ("ids_do_bot", models.JSONField(default=list)),
                ("mudo_ate", models.DateTimeField(null=True)),
                ("atualizado_em", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "barbearia",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="conversas",
                        to="tenant.barbearia",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("barbearia", "whatsapp"), name="conversa_por_numero",
                    )
                ],
            },
        ),
        migrations.RunSQL(sql=CRIAR, reverse_sql=REMOVER),
    ]
```

- [ ] **Step 6: Limpeza entre testes**

Em `tests/conftest.py`, na string do `TRUNCATE`, troque
`"tenant_whatsappinstancia, tenant_mensagemnaoenviada, "`
por
`"tenant_whatsappinstancia, tenant_mensagemnaoenviada, tenant_conversawhatsapp, "`.

- [ ] **Step 7: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_conversa_modelo.py tests/test_rls.py -q`
Expected: PASS.

Run: `docker compose exec -T api python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`. Se aparecer diferença, a migração escrita à mão não bate com o modelo — corrija a migração, não o modelo.

Run: `docker compose exec -T api python manage.py migrate tenant 0005 --database=owner && docker compose exec -T api python manage.py migrate --database=owner`
Expected: as duas passam — prova que o `reverse_sql` desfaz a política sem erro.

- [ ] **Step 8: Suíte inteira e commit**

Run: `docker compose exec -T api pytest -q`
Expected: tudo passando.

```bash
git add backend/tenant/config.py backend/tenant/models.py backend/tenant/migrations/0006_bot_agendamento.py tests/conftest.py tests/test_rls.py tests/test_conversa_modelo.py
git commit -m "bot: interruptor na instancia e a conversa por numero, com RLS

O interruptor mora em WhatsappInstancia porque quem liga e' o dono, pelo
painel, e o runtime nao tem UPDATE em tenant_barbearia. Nasce desligado.

A conversa e' uma linha por numero, sobrescrita a cada passo: o Marcai nao
guarda o que foi conversado. Tres colunas a mais que a spec (tentativas,
pergunta, ids_do_bot) e o porque de cada uma esta no modelo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Do JID do WhatsApp ao número do cliente

**Files:**
- Modify: `backend/tenant/telefone.py`
- Create: `tests/test_telefone.py`

**Interfaces:**
- Produces: `do_jid(jid: str | None) -> str | None` — os 10 ou 11 dígitos nacionais, na forma de `Cliente.whatsapp`, ou `None`.

O WhatsApp guarda celular brasileiro antigo **sem o nono dígito**: a fatia 0 viu `558382217869@s.whatsapp.net` para um número que o Marcaí grava como `83982217869`. `normalizar` sozinho transformaria isso num fixo de 10 dígitos, e o bot nunca acharia o cliente.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/test_telefone.py`:

```python
import pytest

from tenant.telefone import do_jid


@pytest.mark.parametrize(
    "jid, esperado",
    [
        ("5583982217869@s.whatsapp.net", "83982217869"),
        # O caso que a fatia 0 mediu: celular sem o nono digito.
        ("558382217869@s.whatsapp.net", "83982217869"),
        # Fixo continua fixo: comeca de 2 a 5, e nao ganha 9 nenhum.
        ("551133334444@s.whatsapp.net", "1133334444"),
    ],
)
def test_jid_de_pessoa_vira_o_numero_gravado(jid, esperado):
    assert do_jid(jid) == esperado


@pytest.mark.parametrize(
    "jid",
    [
        "120363025246125486@g.us",       # grupo
        "status@broadcast",
        "207843221540943@lid",           # identificador sem numero
        "14155550100@s.whatsapp.net",    # fora do Brasil
        "55abc@s.whatsapp.net",
        "",
        None,
    ],
)
def test_o_que_nao_e_pessoa_no_brasil_vira_none(jid):
    assert do_jid(jid) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose exec -T api pytest tests/test_telefone.py -q`
Expected: FAIL com `ImportError: cannot import name 'do_jid'`.

- [ ] **Step 3: Implementar**

No fim de `backend/tenant/telefone.py`:

```python
_SUFIXO_DE_PESSOA = "@s.whatsapp.net"


def do_jid(jid: str | None) -> str | None:
    """O numero de quem escreveu, na MESMA forma de `Cliente.whatsapp`.

    O WhatsApp guarda celular brasileiro antigo SEM o nono digito
    (`558382217869`, medido na fatia 0). Sem recolocar o 9, `normalizar`
    devolveria um fixo de 10 digitos e o bot nunca acharia o cliente que ja
    marcou pela vitrine.

    Celular e' o assinante que comeca de 6 a 9; fixo comeca de 2 a 5 e fica
    como esta. Grupo, `@lid` e numero de fora do Brasil viram `None` — quem
    chama descarta.
    """
    if not isinstance(jid, str) or not jid.endswith(_SUFIXO_DE_PESSOA):
        return None
    digitos = jid[: -len(_SUFIXO_DE_PESSOA)]
    if not digitos.isdigit() or not digitos.startswith("55"):
        return None
    nacional = digitos[2:]
    if len(nacional) == 10 and nacional[2] in "6789":
        nacional = f"{nacional[:2]}9{nacional[2:]}"
    return normalizar(nacional)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_telefone.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tenant/telefone.py tests/test_telefone.py
git commit -m "telefone: o numero do cliente a partir do jid do WhatsApp

Celular antigo chega sem o nono digito (558382217869, medido na fatia 0).
Sem recolocar o 9, o numero viraria um fixo e o bot nunca acharia o cliente
que ja marcou pela vitrine.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Link do agendamento e os textos do bot

**Files:**
- Modify: `backend/app/services/convite.py` (acrescentar `link_do_agendamento` logo depois de `link_do_convite`)
- Modify: `tests/test_convite.py`
- Modify: `backend/app/services/mensagens.py` (seção nova no fim)
- Create: `tests/test_mensagens_bot.py`

**Interfaces:**
- Produces:
  - `link_do_agendamento(slug: str, codigo: str) -> str`
  - `rotulo_do_agendamento(*, barbeiro_nome: str, inicio: datetime) -> str`
  - `rotulo_da_hora(*, inicio: datetime, barbeiro_nome: str | None) -> str`
  - `msg_bot_pergunta(*, passo: str, opcoes: list[dict], contexto: dict) -> str` — `contexto` por passo: `MENU` → `barbearia_nome`, `agendamentos: list[str]`; `HORA` → `dia_rotulo`; `CONFIRMA` → `servico_nome`, `barbeiro_nome`, `inicio`; `CONFIRMA_CANCEL` → `agendamento_rotulo`; os demais → `{}`.
  - `msg_bot_nao_entendi(*, pergunta: str, mostrar_zero: bool) -> str`
  - `msg_bot_chamou_humano() -> str`, `msg_bot_pediu_humano(*, cliente: str) -> str`
  - `msg_bot_sem_opcoes(*, passo: str) -> str`
  - `msg_bot_fora_do_prazo() -> str`, `msg_bot_nao_achei_agendamento() -> str`
  - `msg_bot_lembrete_confirmado() -> str`, `msg_bot_desistencia_avisada() -> str`
  - `msg_barbeiro_desistiu(*, cliente_nome, servico_nome, inicio, agora) -> str`
  - `msg_lembrete_com_opcoes(*, lembrete: str) -> str`, `msg_bot_pergunta_do_lembrete() -> str`
  - `FALAR_COM_A_BARBEARIA = "0 - Falar com a barbearia"`

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_convite.py`, importe `link_do_agendamento` junto de `link_do_convite` e acrescente:

```python
def test_link_do_agendamento_usa_a_mesma_base_do_convite(monkeypatch):
    monkeypatch.setenv("URL_BASE", "https://usemarcai.online")
    assert (
        link_do_agendamento("brutus", "abc123defg")
        == "https://brutus.usemarcai.online/agendamento/abc123defg"
    )
```

Crie `tests/test_mensagens_bot.py`:

```python
from datetime import datetime, timedelta, timezone

from app.services.mensagens import (
    FALAR_COM_A_BARBEARIA,
    msg_barbeiro_desistiu,
    msg_bot_nao_entendi,
    msg_bot_pergunta,
    msg_bot_pergunta_do_lembrete,
    msg_bot_sem_opcoes,
    msg_lembrete_com_opcoes,
    rotulo_da_hora,
    rotulo_do_agendamento,
)

# 12:00 UTC = 9:00 em Sao Paulo, numa quinta.
QUINTA_9H = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
MARCAR = [{"id": "marcar", "rotulo": "Marcar horário"}]


def test_rotulo_do_agendamento_diz_quem_e_quando():
    assert rotulo_do_agendamento(barbeiro_nome="Pedro", inicio=QUINTA_9H) == (
        "Pedro, quinta 17/09 às 9:00"
    )


def test_rotulo_da_hora_so_diz_o_barbeiro_quando_foi_tanto_faz():
    assert rotulo_da_hora(inicio=QUINTA_9H, barbeiro_nome=None) == "9:00"
    assert rotulo_da_hora(inicio=QUINTA_9H, barbeiro_nome="Pedro") == "9:00 com Pedro"


def test_menu_de_quem_nao_tem_horario():
    texto = msg_bot_pergunta(
        passo="MENU", opcoes=MARCAR,
        contexto={"barbearia_nome": "Brutus", "agendamentos": []},
    )
    assert texto == (
        "Oi! Aqui é o atendimento da Brutus.\n\n"
        "1 - Marcar horário\n0 - Falar com a barbearia"
    )


def test_menu_de_quem_tem_um_horario_mostra_o_horario():
    texto = msg_bot_pergunta(
        passo="MENU",
        opcoes=[{"id": "marcar", "rotulo": "Marcar outro horário"},
                {"id": "cancelar:x", "rotulo": "Cancelar esse"}],
        contexto={"barbearia_nome": "Brutus",
                  "agendamentos": ["Pedro, quinta 17/09 às 9:00"]},
    )
    assert "Você tem: Pedro, quinta 17/09 às 9:00." in texto
    assert "2 - Cancelar esse" in texto


def test_hora_diz_de_que_dia_sao_os_horarios():
    texto = msg_bot_pergunta(
        passo="HORA", opcoes=[{"id": "x", "rotulo": "9:00"}],
        contexto={"dia_rotulo": "amanhã · qui 17 set"},
    )
    assert texto == "Horários de amanhã · qui 17 set:\n\n1 - 9:00"


def test_confirma_repete_o_que_vai_ser_marcado():
    texto = msg_bot_pergunta(
        passo="CONFIRMA",
        opcoes=[{"id": "confirmar", "rotulo": "Confirmar"},
                {"id": "recomecar", "rotulo": "Começar de novo"}],
        contexto={"servico_nome": "corte", "barbeiro_nome": "Pedro", "inicio": QUINTA_9H},
    )
    assert texto.startswith("Confere:\nCorte com Pedro, quinta 17/09 às 9:00.")
    assert texto.endswith("1 - Confirmar\n2 - Começar de novo")


def test_nome_e_pergunta_aberta():
    assert msg_bot_pergunta(passo="NOME", opcoes=[], contexto={}) == (
        "Pra marcar, me diz seu nome:"
    )


def test_nao_entendi_repete_a_pergunta_e_so_oferece_o_zero_quando_pedido():
    pergunta = "Qual dia?\n\n1 - hoje"
    sem = msg_bot_nao_entendi(pergunta=pergunta, mostrar_zero=False)
    com = msg_bot_nao_entendi(pergunta=pergunta, mostrar_zero=True)
    assert sem == "Não entendi. Responde só com o número.\n\nQual dia?\n\n1 - hoje"
    assert FALAR_COM_A_BARBEARIA not in sem
    assert com.endswith(f"1 - hoje\n{FALAR_COM_A_BARBEARIA}")


def test_nao_entendi_no_menu_nao_duplica_o_zero():
    pergunta = f"Oi!\n\n1 - Marcar horário\n{FALAR_COM_A_BARBEARIA}"
    texto = msg_bot_nao_entendi(pergunta=pergunta, mostrar_zero=True)
    assert texto.count(FALAR_COM_A_BARBEARIA) == 1


def test_sem_opcoes_separa_falta_de_vaga_de_falta_de_horario_marcado():
    assert "horário livre" in msg_bot_sem_opcoes(passo="DIA")
    assert "horário marcado" in msg_bot_sem_opcoes(passo="QUAL_AGENDAMENTO")


def test_lembrete_ganha_as_duas_opcoes_no_fim():
    texto = msg_lembrete_com_opcoes(lembrete="Lembrete: corte hoje às 9:00, com Pedro.")
    assert texto == (
        "Lembrete: corte hoje às 9:00, com Pedro.\n\n"
        "1 - Confirmar\n2 - Não vou conseguir ir"
    )
    assert msg_bot_pergunta_do_lembrete().endswith("1 - Confirmar\n2 - Não vou conseguir ir")


def test_barbeiro_sabe_quem_desistiu_na_mesma_forma_das_outras_mensagens():
    texto = msg_barbeiro_desistiu(
        cliente_nome="Maria Souza", servico_nome="Corte",
        inicio=QUINTA_9H, agora=QUINTA_9H - timedelta(minutes=50),
    )
    assert texto == "Avisou que não vem\nMaria Souza · hoje 09:00 · Corte"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose exec -T api pytest tests/test_mensagens_bot.py tests/test_convite.py -q`
Expected: FAIL com `ImportError`.

- [ ] **Step 3: Implementar o link**

Em `backend/app/services/convite.py`, logo depois de `link_do_convite`:

```python
def link_do_agendamento(slug: str, codigo: str) -> str:
    """O link de cancelar da confirmacao que o BOT manda. A rota publica monta
    o seu a partir do `Origin` do navegador; o bot nao tem navegador nenhum,
    entao usa a mesma base do convite."""
    esquema, host = _base_valida()
    return f"{esquema}://{slug}.{host}/agendamento/{codigo}"
```

- [ ] **Step 4: Implementar os textos**

No fim de `backend/app/services/mensagens.py`:

```python
# ---- O bot de agendamento -------------------------------------------------
#
# Menu NUMERADO, e o numero sozinho e' a unica coisa que o bot entende (spec,
# secao 2). Toda pergunta termina numa lista "1 - ...", e o "0" e' sempre a
# saida para gente de verdade.

FALAR_COM_A_BARBEARIA = "0 - Falar com a barbearia"

_CABECALHO_DO_PASSO = {
    "SERVICO": "Qual serviço?",
    "BARBEIRO": "Com quem?",
    "DIA": "Qual dia?",
    "QUAL_AGENDAMENTO": "Qual horário você quer cancelar?",
}

_OPCOES_DO_LEMBRETE = "1 - Confirmar\n2 - Não vou conseguir ir"


def _numerada(opcoes: list[dict]) -> str:
    return "\n".join(f"{i} - {o['rotulo']}" for i, o in enumerate(opcoes, start=1))


def rotulo_do_agendamento(*, barbeiro_nome: str, inicio) -> str:
    return (
        f"{barbeiro_nome}, {formatar_dia_com_semana(inicio)} "
        f"às {formatar_hora_falada(inicio)}"
    )


def rotulo_da_hora(*, inicio, barbeiro_nome: str | None) -> str:
    """O barbeiro so' aparece quando o cliente escolheu "tanto faz": ai' e' a
    unica forma de ele saber com quem vai cortar."""
    hora = formatar_hora_falada(inicio)
    return f"{hora} com {barbeiro_nome}" if barbeiro_nome else hora


def msg_bot_pergunta(*, passo: str, opcoes: list[dict], contexto: dict) -> str:
    lista = _numerada(opcoes)
    if passo == "MENU":
        partes = [f"Oi! Aqui é o atendimento da {contexto['barbearia_nome']}."]
        marcados = contexto.get("agendamentos") or []
        if len(marcados) == 1:
            partes.append(f"Você tem: {marcados[0]}.")
        elif marcados:
            partes.append("Você tem:\n" + "\n".join(marcados))
        partes.append(f"{lista}\n{FALAR_COM_A_BARBEARIA}")
        return "\n\n".join(partes)
    if passo == "NOME":
        return "Pra marcar, me diz seu nome:"
    if passo == "HORA":
        return f"Horários de {contexto['dia_rotulo']}:\n\n{lista}"
    if passo == "CONFIRMA":
        inicio = contexto["inicio"]
        return (
            f"Confere:\n{_capitalizar(contexto['servico_nome'])} com "
            f"{contexto['barbeiro_nome']}, {formatar_dia_com_semana(inicio)} "
            f"às {formatar_hora_falada(inicio)}.\n\n{lista}"
        )
    if passo == "CONFIRMA_CANCEL":
        return f"Cancelar {contexto['agendamento_rotulo']}?\n\n{lista}"
    return f"{_CABECALHO_DO_PASSO[passo]}\n\n{lista}"


def msg_bot_nao_entendi(*, pergunta: str, mostrar_zero: bool) -> str:
    texto = f"Não entendi. Responde só com o número.\n\n{pergunta}"
    if mostrar_zero and FALAR_COM_A_BARBEARIA not in pergunta:
        texto += f"\n{FALAR_COM_A_BARBEARIA}"
    return texto


def msg_bot_chamou_humano() -> str:
    return "Beleza, já chamei alguém da barbearia. Te respondem por aqui."


def msg_bot_pediu_humano(*, cliente: str) -> str:
    """Para o DONO, pelo numero central."""
    return f"Cliente pediu atendimento no WhatsApp da barbearia\n{cliente}"


def msg_bot_sem_opcoes(*, passo: str) -> str:
    if passo in ("QUAL_AGENDAMENTO", "CONFIRMA_CANCEL"):
        return (
            "Não achei horário marcado neste número. "
            "Responde 0 que alguém da barbearia te atende."
        )
    return (
        "Não achei horário livre nos próximos dias. "
        "Responde 0 que alguém da barbearia te atende."
    )


def msg_bot_fora_do_prazo() -> str:
    return (
        "Faltando menos de 1h não dá pra cancelar por aqui. "
        "Responde 0 que alguém da barbearia te atende."
    )


def msg_bot_nao_achei_agendamento() -> str:
    return "Não achei esse horário marcado neste número."


def msg_bot_lembrete_confirmado() -> str:
    return "Combinado, te esperamos!"


def msg_bot_desistencia_avisada() -> str:
    return "Tudo bem, avisei a barbearia. Obrigado por avisar!"


def msg_barbeiro_desistiu(*, cliente_nome: str, servico_nome: str, inicio, agora) -> str:
    return "Avisou que não vem\n" + _linha_do_horario(
        cliente_nome=cliente_nome, servico_nome=servico_nome, inicio=inicio, agora=agora,
    )


def msg_lembrete_com_opcoes(*, lembrete: str) -> str:
    """O lembrete de sempre, com as duas respostas que o bot entende. "Nao vou
    conseguir ir" e nao "cancelar": o lembrete sai 60 minutos antes, e o
    cliente so' cancela com mais de 60 — um "cancelar" aqui daria sempre fora
    do prazo."""
    return f"{lembrete}\n\n{_OPCOES_DO_LEMBRETE}"


def msg_bot_pergunta_do_lembrete() -> str:
    return f"Responde 1 pra confirmar ou 2 se não for conseguir ir.\n\n{_OPCOES_DO_LEMBRETE}"
```

- [ ] **Step 5: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_mensagens_bot.py tests/test_convite.py tests/test_mensagens.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/convite.py backend/app/services/mensagens.py tests/test_convite.py tests/test_mensagens_bot.py
git commit -m "bot: os textos do menu e o link do agendamento

Todo texto que sai pelo WhatsApp mora em mensagens.py, inclusive os do bot.
O lembrete oferece 'nao vou conseguir ir' e nao 'cancelar': ele sai 60 min
antes, e o cliente so' cancela com mais de 60.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: A máquina de conversa, pura

**Files:**
- Create: `backend/app/services/conversa.py`
- Create: `tests/test_conversa.py`

**Interfaces:**
- Consumes: `BOT_CONVERSA_EXPIRA_MIN`, `BOT_LEMBRETE_VALE_MIN` (Task 1).
- Produces:
  - Constantes de passo: `MENU, SERVICO, BARBEIRO, DIA, HORA, NOME, CONFIRMA, QUAL_AGENDAMENTO, CONFIRMA_CANCEL, AGUARDANDO_LEMBRETE` (strings iguais a `EstadoConversa`).
  - `Estado(passo: str, opcoes: list, rascunho: dict, tentativas: int, atualizado_em: datetime | None)`
  - Decisões: `Ir(passo, rascunho)`, `Repetir(tentativas)`, `ChamarHumano()`, `Marcar(rascunho)`, `Cancelar(codigo)`, `ConfirmarLembrete(codigo)`, `NaoVou(codigo)`
  - `numero_escolhido(texto) -> int | None`
  - `expirou(estado: Estado, agora: datetime) -> bool`
  - `decidir(estado: Estado, texto, agora: datetime) -> decisão`
  - `seguir_sozinho(passo: str, rascunho: dict, opcoes: list) -> Ir | None`
- Ids de opção que a casca (Task 6) precisa produzir, e que esta máquina entende: `MENU`: `"marcar"`, `"cancelar"` (vários horários), `"cancelar:<codigo>"` (um só). `SERVICO`: o `servico_id`. `BARBEIRO`: o `barbeiro_id` ou `"qualquer"`. `DIA`: `"AAAA-MM-DD"` ou `"mais:<AAAA-MM-DD>"`. `HORA`: `"<inicio ISO>|<barbeiro_id>"`, `"depois:<inicio ISO>"` ou `"outro_dia"`. `CONFIRMA`: `"confirmar"`, `"recomecar"`. `QUAL_AGENDAMENTO`: o `codigo`. `CONFIRMA_CANCEL`: `"sim"`, `"nao"`. `AGUARDANDO_LEMBRETE`: `"confirmar:<codigo>"`, `"nao_vou:<codigo>"`.
- Chaves do `rascunho`: `cliente_nome`, `servico_id`, `barbeiro_id`, `de`, `dia`, `depois`, `inicio`, `barbeiro_escolhido`, `codigo`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/test_conversa.py`:

```python
"""A maquina do bot, sem banco e sem rede.

Cada caso daqui e' um jeito de o bot errar caro — marcar o horario errado,
repetir o mesmo menu para sempre, agir sobre uma conversa de ontem.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import conversa as c
from tenant.models import EstadoConversa

AGORA = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
LISTA_DE_TRES = [{"id": f"s{i}", "rotulo": f"Serviço {i}"} for i in (1, 2, 3)]


def _estado(passo=c.SERVICO, opcoes=None, rascunho=None, tentativas=0, ha_min=1):
    return c.Estado(
        passo=passo,
        opcoes=LISTA_DE_TRES if opcoes is None else opcoes,
        rascunho=rascunho or {},
        tentativas=tentativas,
        atualizado_em=AGORA - timedelta(minutes=ha_min),
    )


def test_os_passos_sao_os_mesmos_do_banco():
    for passo in (c.MENU, c.SERVICO, c.BARBEIRO, c.DIA, c.HORA, c.NOME, c.CONFIRMA,
                  c.QUAL_AGENDAMENTO, c.CONFIRMA_CANCEL, c.AGUARDANDO_LEMBRETE):
        assert passo in EstadoConversa.values


@pytest.mark.parametrize("texto, numero", [
    ("1", 1), (" 2 ", 2), ("2.", 2), ("3)", 3), ("10", 10), ("0", 0),
])
def test_numero_sozinho_e_escolha(texto, numero):
    assert c.numero_escolhido(texto) == numero


@pytest.mark.parametrize("texto", ["quero o 1", "às 14", "1 e 2", "", "um", None, "123"])
def test_numero_no_meio_de_frase_nao_e_escolha(texto):
    """"as 14" virando a opcao 14 marcaria um horario que a pessoa so'
    estava mencionando."""
    assert c.numero_escolhido(texto) is None


def test_conversa_que_nunca_existiu_vai_ao_menu():
    estado = c.Estado(c.MENU, [], {}, 0, None)
    assert c.decidir(estado, "oi", AGORA) == c.Ir(c.MENU, {})


def test_conversa_velha_recomeca_mesmo_com_numero_valido():
    """Um "1" digitado amanha nao confirma o que foi escolhido hoje."""
    estado = _estado(ha_min=21)
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.MENU, {})


def test_resposta_ao_lembrete_vale_mais_que_vinte_minutos():
    opcoes = [{"id": "confirmar:abc", "rotulo": "Confirmar"}]
    assert c.decidir(_estado(c.AGUARDANDO_LEMBRETE, opcoes, ha_min=45), "1", AGORA) == (
        c.ConfirmarLembrete("abc")
    )
    assert c.decidir(_estado(c.AGUARDANDO_LEMBRETE, opcoes, ha_min=61), "1", AGORA) == (
        c.Ir(c.MENU, {})
    )


@pytest.mark.parametrize("passo", [c.MENU, c.SERVICO, c.HORA, c.CONFIRMA, c.NOME])
def test_zero_chama_gente_em_qualquer_passo(passo):
    assert c.decidir(_estado(passo), "0", AGORA) == c.ChamarHumano()


def test_zero_funciona_depois_de_um_beco_sem_opcoes():
    """Depois de "nao achei horario, responde 0", a conversa fica no MENU sem
    opcoes. O 0 tem que valer ali — foi o que a mensagem mandou fazer."""
    assert c.decidir(_estado(c.MENU, opcoes=[]), "0", AGORA) == c.ChamarHumano()


def test_sem_opcoes_guardadas_mostra_o_menu():
    assert c.decidir(_estado(c.MENU, opcoes=[]), "1", AGORA) == c.Ir(c.MENU, {})


@pytest.mark.parametrize("texto", ["9", "4", "oi", "pode ser"])
def test_fora_da_lista_repete_e_conta(texto):
    assert c.decidir(_estado(tentativas=1), texto, AGORA) == c.Repetir(2)


def test_menu_marcar_leva_o_nome_ja_conhecido():
    estado = _estado(c.MENU, [{"id": "marcar", "rotulo": "Marcar horário"}],
                     {"cliente_nome": "Maria"})
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.SERVICO, {"cliente_nome": "Maria"})


def test_menu_com_um_horario_vai_direto_confirmar_o_cancelamento():
    estado = _estado(c.MENU, [{"id": "marcar", "rotulo": "x"},
                              {"id": "cancelar:abc123", "rotulo": "y"}])
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.CONFIRMA_CANCEL, {"codigo": "abc123"})


def test_menu_com_varios_horarios_pergunta_qual():
    estado = _estado(c.MENU, [{"id": "marcar", "rotulo": "x"},
                              {"id": "cancelar", "rotulo": "y"}])
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.QUAL_AGENDAMENTO, {})


def test_servico_escolhido_segue_para_o_barbeiro_sem_perder_o_nome():
    estado = _estado(c.SERVICO, rascunho={"cliente_nome": "Maria"})
    assert c.decidir(estado, "2", AGORA) == c.Ir(
        c.BARBEIRO, {"cliente_nome": "Maria", "servico_id": "s2"}
    )


def test_barbeiro_escolhido_segue_para_o_dia():
    estado = _estado(c.BARBEIRO, [{"id": "b1", "rotulo": "Pedro"}], {"servico_id": "s1"})
    assert c.decidir(estado, "1", AGORA) == c.Ir(
        c.DIA, {"servico_id": "s1", "barbeiro_id": "b1", "de": None}
    )


def test_outros_dias_avanca_a_janela():
    estado = _estado(c.DIA, [{"id": "2026-09-16", "rotulo": "hoje"},
                             {"id": "mais:2026-09-22", "rotulo": "Outros dias"}],
                     {"de": None})
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.DIA, {"de": "2026-09-22"})


def test_dia_escolhido_segue_para_a_hora():
    estado = _estado(c.DIA, [{"id": "2026-09-17", "rotulo": "amanhã"}], {"de": None})
    assert c.decidir(estado, "1", AGORA) == c.Ir(
        c.HORA, {"de": None, "dia": "2026-09-17", "depois": None}
    )


HORARIOS = [
    {"id": "2026-09-17T12:00:00.000Z|b1", "rotulo": "9:00"},
    {"id": "depois:2026-09-17T12:00:00.000Z", "rotulo": "Mais tarde"},
    {"id": "outro_dia", "rotulo": "Outro dia"},
]


def test_hora_de_quem_ja_tem_nome_vai_confirmar():
    estado = _estado(c.HORA, HORARIOS, {"cliente_nome": "Maria", "barbeiro_id": "qualquer"})
    assert c.decidir(estado, "1", AGORA) == c.Ir(c.CONFIRMA, {
        "cliente_nome": "Maria", "barbeiro_id": "qualquer",
        "inicio": "2026-09-17T12:00:00.000Z", "barbeiro_escolhido": "b1",
    })


def test_hora_de_quem_nao_tem_nome_pergunta_o_nome():
    estado = _estado(c.HORA, HORARIOS, {"cliente_nome": None})
    assert c.decidir(estado, "1", AGORA).passo == c.NOME


def test_mais_tarde_continua_no_mesmo_dia():
    estado = _estado(c.HORA, HORARIOS, {"dia": "2026-09-17"})
    assert c.decidir(estado, "2", AGORA) == c.Ir(
        c.HORA, {"dia": "2026-09-17", "depois": "2026-09-17T12:00:00.000Z"}
    )


def test_outro_dia_volta_para_os_dias_do_comeco():
    estado = _estado(c.HORA, HORARIOS, {"dia": "2026-09-17", "depois": "x", "de": "y"})
    assert c.decidir(estado, "3", AGORA) == c.Ir(
        c.DIA, {"dia": "2026-09-17", "depois": None, "de": None}
    )


def test_nome_valido_segue_para_confirmar_sem_espacos_sobrando():
    estado = _estado(c.NOME, opcoes=[], rascunho={"servico_id": "s1"})
    assert c.decidir(estado, "  João   da Silva ", AGORA) == c.Ir(
        c.CONFIRMA, {"servico_id": "s1", "cliente_nome": "João da Silva"}
    )


@pytest.mark.parametrize("texto", ["1", "J", ""])
def test_nome_que_nao_e_nome_repete(texto):
    assert c.decidir(_estado(c.NOME, opcoes=[]), texto, AGORA) == c.Repetir(1)


def test_confirmar_marca_com_o_rascunho_inteiro():
    rascunho = {"servico_id": "s1", "inicio": "x", "barbeiro_escolhido": "b1"}
    estado = _estado(c.CONFIRMA, [{"id": "confirmar", "rotulo": "Confirmar"},
                                  {"id": "recomecar", "rotulo": "Começar de novo"}], rascunho)
    assert c.decidir(estado, "1", AGORA) == c.Marcar(rascunho)
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.MENU, {})


def test_qual_agendamento_leva_o_codigo_para_confirmar():
    estado = _estado(c.QUAL_AGENDAMENTO, [{"id": "cod1", "rotulo": "a"},
                                          {"id": "cod2", "rotulo": "b"}])
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.CONFIRMA_CANCEL, {"codigo": "cod2"})


def test_confirmar_cancelamento():
    estado = _estado(c.CONFIRMA_CANCEL, [{"id": "sim", "rotulo": "Sim"},
                                         {"id": "nao", "rotulo": "Não"}], {"codigo": "cod1"})
    assert c.decidir(estado, "1", AGORA) == c.Cancelar("cod1")
    assert c.decidir(estado, "2", AGORA) == c.Ir(c.MENU, {})


def test_lembrete_confirma_ou_avisa_que_nao_vai():
    opcoes = [{"id": "confirmar:cod1", "rotulo": "Confirmar"},
              {"id": "nao_vou:cod1", "rotulo": "Não vou conseguir ir"}]
    estado = _estado(c.AGUARDANDO_LEMBRETE, opcoes)
    assert c.decidir(estado, "1", AGORA) == c.ConfirmarLembrete("cod1")
    assert c.decidir(estado, "2", AGORA) == c.NaoVou("cod1")


def test_servico_unico_e_pulado():
    assert c.seguir_sozinho(c.SERVICO, {"cliente_nome": None}, [{"id": "s1", "rotulo": "Corte"}]) == (
        c.Ir(c.BARBEIRO, {"cliente_nome": None, "servico_id": "s1"})
    )


def test_barbeiro_unico_e_pulado():
    assert c.seguir_sozinho(c.BARBEIRO, {}, [{"id": "b1", "rotulo": "Pedro"}]).passo == c.DIA


@pytest.mark.parametrize("passo", [c.DIA, c.HORA, c.CONFIRMA, c.MENU])
def test_os_outros_passos_nunca_pulam(passo):
    """Um dia so' com vaga ainda e' uma escolha que a pessoa precisa ver."""
    assert c.seguir_sozinho(passo, {}, [{"id": "x", "rotulo": "x"}]) is None


def test_duas_opcoes_nao_pulam():
    assert c.seguir_sozinho(c.SERVICO, {}, LISTA_DE_TRES[:2]) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose exec -T api pytest tests/test_conversa.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.conversa'`.

- [ ] **Step 3: Implementar**

Crie `backend/app/services/conversa.py`:

```python
"""A maquina de conversa do bot de agendamento — PURA.

Sem banco, sem rede, sem relogio: tudo o que ela precisa chega por parametro,
e o que ela devolve e' uma DECISAO que a casca (`bot.py`) executa. Mesmo
desenho de `slots.py` e do `faixaDoWhatsapp` do front, e pelo mesmo motivo:
as regras que erram caro ("9 num menu de 3", "conversa de ontem", "0 em
qualquer lugar") ficam testaveis em milissegundos.

O que a deixa pura: o bot GUARDA as opcoes que ofereceu. Entender "2" e'
`opcoes[1]` — nao precisa perguntar nada ao banco. O banco so' entra para
MONTAR a proxima pergunta, e isso e' da casca.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from tenant.config import BOT_CONVERSA_EXPIRA_MIN, BOT_LEMBRETE_VALE_MIN

MENU = "MENU"
SERVICO = "SERVICO"
BARBEIRO = "BARBEIRO"
DIA = "DIA"
HORA = "HORA"
NOME = "NOME"
CONFIRMA = "CONFIRMA"
QUAL_AGENDAMENTO = "QUAL_AGENDAMENTO"
CONFIRMA_CANCEL = "CONFIRMA_CANCEL"
AGUARDANDO_LEMBRETE = "AGUARDANDO_LEMBRETE"

# Um servico so' ou um barbeiro so': perguntar "1 - Corte" e' fazer o cliente
# trabalhar para responder o obvio. DIA e HORA nunca pulam — um dia so' com
# vaga ainda e' uma escolha que a pessoa precisa ver.
PULA_SE_UNICA = frozenset({SERVICO, BARBEIRO})

# O numero SOZINHO, com no maximo uma pontuacao de quem digita rapido.
# Tres digitos nao casam: nenhuma lista do bot passa de dez itens, e "123"
# e' mais provavelmente um pedaço de telefone que uma escolha.
_NUMERO = re.compile(r"^\s*(\d{1,2})\s*[.)!]?\s*$")


@dataclass(frozen=True)
class Estado:
    passo: str
    opcoes: list
    rascunho: dict
    tentativas: int
    atualizado_em: datetime | None


@dataclass(frozen=True)
class Ir:
    """Avancar para `passo`. A casca busca as opcoes dele e pergunta."""

    passo: str
    rascunho: dict


@dataclass(frozen=True)
class Repetir:
    tentativas: int


@dataclass(frozen=True)
class ChamarHumano:
    pass


@dataclass(frozen=True)
class Marcar:
    rascunho: dict


@dataclass(frozen=True)
class Cancelar:
    codigo: str


@dataclass(frozen=True)
class ConfirmarLembrete:
    codigo: str


@dataclass(frozen=True)
class NaoVou:
    codigo: str


def numero_escolhido(texto) -> int | None:
    m = _NUMERO.match(texto) if isinstance(texto, str) else None
    return int(m.group(1)) if m else None


def expirou(estado: Estado, agora: datetime) -> bool:
    if estado.atualizado_em is None:
        return True
    limite = (
        BOT_LEMBRETE_VALE_MIN if estado.passo == AGUARDANDO_LEMBRETE
        else BOT_CONVERSA_EXPIRA_MIN
    )
    return agora - estado.atualizado_em > timedelta(minutes=limite)


def decidir(estado: Estado, texto, agora: datetime):
    """A ordem das regras e' o que importa, e cada uma tem um motivo:

    1. conversa velha recomeca ANTES de ler o numero — senao um "1" de ontem
       seria obedecido;
    2. o "0" vem antes de tudo o que sobrou, inclusive de "sem opcoes": e' a
       saida que as mensagens de beco mandam usar;
    3. NOME e' o unico passo de texto livre;
    4. sem opcoes guardadas nao ha o que entender, entao mostra o menu.
    """
    if expirou(estado, agora):
        return Ir(MENU, {})
    n = numero_escolhido(texto)
    if n == 0:
        return ChamarHumano()
    if estado.passo == NOME:
        nome = " ".join(texto.split()) if isinstance(texto, str) else ""
        if n is None and 2 <= len(nome) <= 60:
            return Ir(CONFIRMA, {**estado.rascunho, "cliente_nome": nome})
        return Repetir(estado.tentativas + 1)
    if not estado.opcoes:
        return Ir(MENU, {})
    if n is None or not 1 <= n <= len(estado.opcoes):
        return Repetir(estado.tentativas + 1)
    return _escolheu(estado.passo, estado.rascunho, estado.opcoes[n - 1]["id"])


def seguir_sozinho(passo: str, rascunho: dict, opcoes: list):
    if passo in PULA_SE_UNICA and len(opcoes) == 1:
        return _escolheu(passo, rascunho, opcoes[0]["id"])
    return None


def _apos(escolha: str, prefixo: str) -> str | None:
    return escolha[len(prefixo):] if escolha.startswith(prefixo) else None


def _escolheu(passo: str, r: dict, escolha: str):
    if passo == MENU:
        if escolha == "marcar":
            return Ir(SERVICO, {"cliente_nome": r.get("cliente_nome")})
        if escolha == "cancelar":
            return Ir(QUAL_AGENDAMENTO, {})
        codigo = _apos(escolha, "cancelar:")
        if codigo:
            return Ir(CONFIRMA_CANCEL, {"codigo": codigo})
    elif passo == SERVICO:
        return Ir(BARBEIRO, {**r, "servico_id": escolha})
    elif passo == BARBEIRO:
        return Ir(DIA, {**r, "barbeiro_id": escolha, "de": None})
    elif passo == DIA:
        de = _apos(escolha, "mais:")
        if de:
            return Ir(DIA, {**r, "de": de})
        return Ir(HORA, {**r, "dia": escolha, "depois": None})
    elif passo == HORA:
        if escolha == "outro_dia":
            return Ir(DIA, {**r, "de": None, "depois": None})
        depois = _apos(escolha, "depois:")
        if depois:
            return Ir(HORA, {**r, "depois": depois})
        inicio, barbeiro_id = escolha.split("|", 1)
        novo = {**r, "inicio": inicio, "barbeiro_escolhido": barbeiro_id}
        return Ir(CONFIRMA if r.get("cliente_nome") else NOME, novo)
    elif passo == CONFIRMA:
        if escolha == "confirmar":
            return Marcar(r)
    elif passo == QUAL_AGENDAMENTO:
        return Ir(CONFIRMA_CANCEL, {"codigo": escolha})
    elif passo == CONFIRMA_CANCEL:
        if escolha == "sim":
            return Cancelar(r["codigo"])
    elif passo == AGUARDANDO_LEMBRETE:
        codigo = _apos(escolha, "confirmar:")
        if codigo:
            return ConfirmarLembrete(codigo)
        codigo = _apos(escolha, "nao_vou:")
        if codigo:
            return NaoVou(codigo)
    # "recomecar", "nao" e qualquer id que nao se reconheca: volta ao menu.
    return Ir(MENU, {})
```

- [ ] **Step 4: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_conversa.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversa.py tests/test_conversa.py
git commit -m "bot: a maquina de conversa, pura

Entender a resposta e' opcoes[n-1], sem banco: o bot guarda o que ofereceu.
A ordem das regras e' o que protege — conversa velha recomeca antes de ler o
numero, e o 0 vale ate' depois de um beco sem opcoes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: A trava da conversa

**Files:**
- Create: `backend/app/services/trava_conversa.py`
- Create: `tests/test_trava_conversa.py`

**Interfaces:**
- Consumes: `BOT_ESPERA_TRAVA_S` (Task 1).
- Produces: `trava_da_conversa(barbearia_id: str, whatsapp: str, *, espera_s: float = BOT_ESPERA_TRAVA_S)` — context manager; levanta `django.db.OperationalError` se não conseguir a trava dentro de `espera_s`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/test_trava_conversa.py`:

```python
"""Duas mensagens do mesmo numero nao podem andar a conversa ao mesmo tempo.

As duas conexoes (`default` e `owner`) sao SESSOES diferentes do Postgres,
entao uma prova a trava que a outra segura — que e' a situacao real de dois
workers do Celery.
"""

import pytest
from django.db import OperationalError, connections

from app.services.trava_conversa import trava_da_conversa

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


def _tentar_de_outra_sessao(chave):
    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", [chave])
        conseguiu = cur.fetchone()[0]
        if conseguiu:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])
    return conseguiu


def test_enquanto_segura_ninguem_mais_pega(cenario):
    b = cenario["brutus"]
    with trava_da_conversa(str(b.id), "83988887777"):
        assert _tentar_de_outra_sessao(f"{b.id}:83988887777") is False
    assert _tentar_de_outra_sessao(f"{b.id}:83988887777") is True


def test_outro_numero_nao_espera(cenario):
    b = cenario["brutus"]
    with trava_da_conversa(str(b.id), "83988887777"):
        assert _tentar_de_outra_sessao(f"{b.id}:83911112222") is True


def test_o_mesmo_numero_noutra_barbearia_nao_espera(cenario):
    with trava_da_conversa(str(cenario["brutus"].id), "83988887777"):
        assert _tentar_de_outra_sessao(f"{cenario['dontony'].id}:83988887777") is True


def test_solta_mesmo_quando_o_bloco_explode(cenario):
    b = cenario["brutus"]
    with pytest.raises(RuntimeError):
        with trava_da_conversa(str(b.id), "83988887777"):
            raise RuntimeError("boom")
    assert _tentar_de_outra_sessao(f"{b.id}:83988887777") is True


def test_espera_estourada_levanta_em_vez_de_travar_o_worker(cenario):
    b = cenario["brutus"]
    chave = f"{b.id}:83988887777"
    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
    try:
        with pytest.raises(OperationalError):
            with trava_da_conversa(str(b.id), "83988887777", espera_s=0.2):
                pass
    finally:
        with connections["owner"].cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `docker compose exec -T api pytest tests/test_trava_conversa.py -q`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Crie `backend/app/services/trava_conversa.py`:

```python
"""Uma conversa do bot por vez, por numero.

Trava CONSULTIVA do Postgres, e nao `select_for_update`: a conversa atravessa
varias transacoes (`marcar` e `cancelar_publico` abrem as proprias, e
`com_barbearia` nao pode ser aninhado), e uma trava de linha morreria no fim
da primeira. A consultiva vive na CONEXAO e segura ler, decidir, marcar,
responder e gravar.

Sem ela, "1" e "2" mandados com meio segundo de diferenca viram duas tasks que
leem o mesmo estado e avancam as duas.
"""

from contextlib import contextmanager

from django.db import connection

from tenant.config import BOT_ESPERA_TRAVA_S


@contextmanager
def trava_da_conversa(barbearia_id: str, whatsapp: str, *, espera_s: float = BOT_ESPERA_TRAVA_S):
    chave = f"{barbearia_id}:{whatsapp}"
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
```

O `int(...)` na f-string é seguro: o valor nunca vem de fora, e `SET` não aceita parâmetro.

- [ ] **Step 4: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_trava_conversa.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/trava_conversa.py tests/test_trava_conversa.py
git commit -m "bot: a trava da conversa por numero

Consultiva e nao de linha: marcar() abre a propria transacao e com_barbearia
nao aninha, entao uma trava de linha morreria antes de a conversa terminar.
Com limite de espera, para um worker nunca ficar preso.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: A casca do bot

**Files:**
- Modify: `backend/app/services/whatsapp.py` (`_enviar` passa a devolver o id)
- Modify: `tests/test_whatsapp.py`
- Create: `backend/app/services/bot.py`
- Create: `tests/test_bot.py`

**Interfaces:**
- Consumes: `conversa` (Task 4), `trava_da_conversa` (Task 5), textos e `link_do_agendamento` (Task 3), modelos (Task 1), e os serviços existentes `marcar`, `cancelar_publico`, `eh_sobreposicao`, `ErroCliente` (`agendamentos.py`), `dias_com_horarios` (`agenda.py`), `listar_para_agendamento` e `QUALQUER` (`servicos.py`), `enviar_a_equipe` (`whatsapp.py`).
- Produces:
  - `_enviar(instancia: str, whatsapp_digitos: str, mensagem: str) -> str | None` — o `key.id` que a Evolution devolveu, ou `None`.
  - `processar(barbearia_id: str, numero: str, texto: str, mensagem_id: str, agora: datetime) -> str` — desfechos: `"ignorado"`, `"duplicada"`, `"mudo"`, `"perguntou"`, `"repetiu"`, `"humano"`, `"marcou"`, `"cancelou"`, `"fora_do_prazo"`, `"nao_e_seu"`, `"sem_opcoes"`, `"lembrete_confirmado"`, `"desistencia_avisada"`.
  - Internos usados pelas tarefas 11 e 12: `_conversa(barbearia_id, numero)`, `_estado_de(linha)`.

- [ ] **Step 1: `_enviar` devolve o id — teste que falha**

Em `tests/test_whatsapp.py`, no fim:

```python
def test_enviar_devolve_o_id_que_a_evolution_deu(monkeypatch):
    """O bot guarda este id para reconhecer o eco da propria resposta quando
    ele volta pelo webhook como `fromMe`."""
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    resposta = Mock(ok=True, status_code=201)
    resposta.json.return_value = {
        "key": {"id": "3EB0ABC123", "remoteJid": "5583988887777@s.whatsapp.net"},
        "status": "PENDING",
    }
    with patch.object(whatsapp.requests, "post", return_value=resposta):
        assert whatsapp._enviar("marcai-x", "83988887777", "oi") == "3EB0ABC123"


def test_enviar_recusado_devolve_none(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evolution:8080")
    monkeypatch.setenv("EVOLUTION_API_KEY", "chave")
    with patch.object(whatsapp.requests, "post", return_value=Mock(ok=False, status_code=400, text="x")):
        assert whatsapp._enviar("marcai-x", "83988887777", "oi") is None
```

Run: `docker compose exec -T api pytest tests/test_whatsapp.py -q`
Expected: FAIL no primeiro (`None != '3EB0ABC123'`).

- [ ] **Step 2: `_enviar` devolve o id — implementar**

Em `backend/app/services/whatsapp.py`, dentro de `_enviar`: troque a assinatura para `-> str | None`, e troque as três linhas finais

```python
    jid = (corpo or {}).get("key", {}).get("remoteJid", "?")
    status = (corpo or {}).get("status", "?")
    logger.info("[whatsapp] aceito para %s (jid %s, status %s)", whatsapp_digitos, jid, status)
```

por

```python
    chave = (corpo or {}).get("key", {})
    jid = chave.get("remoteJid", "?")
    status = (corpo or {}).get("status", "?")
    logger.info("[whatsapp] aceito para %s (jid %s, status %s)", whatsapp_digitos, jid, status)
    # O id sobe para quem chamou. Os envios de sempre o ignoram; o bot o
    # guarda para reconhecer o eco da propria mensagem no webhook.
    return chave.get("id")
```

Os `return` sem valor que já existem no corpo continuam devolvendo `None`. Acrescente ao docstring: `Devolve o id da mensagem aceita, ou None.`

Run: `docker compose exec -T api pytest tests/test_whatsapp.py tests/test_envio_por_plano.py -q`
Expected: PASS.

- [ ] **Step 3: Escrever os testes da casca que falham**

Crie `tests/test_bot.py`:

```python
"""O bot DENTRO do Django: da mensagem recebida ao agendamento gravado e a
resposta que sairia.

A Evolution e' dublada em dois pontos — `app.services.bot._enviar` (o que o
cliente le) e `app.services.bot.enviar_a_equipe` (o que o barbeiro le). O
resto e' de verdade: banco com RLS, `marcar()`, `slots_do_dia`,
`cancelar_publico`.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.bot import processar
from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    BarbeiroServico,
    Cliente,
    ConversaWhatsapp,
    EstadoInstancia,
    HorarioTrabalho,
    Servico,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

NUMERO = "83988887777"


def _barbearia_com_bot(barbearia, *, bot_ativo=True, estado=EstadoInstancia.CONECTADO):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=nome_da_instancia(barbearia.id), estado=estado, bot_ativo=bot_ativo,
    )
    return barbearia


def _barbeiro(barbearia, nome="Pedro", papel="BARBEIRO", ordem=0):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome,
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True, ordem=ordem,
    )


def _vincular(barbearia, barbeiro, servico):
    BarbeiroServico.objects.using("owner").create(
        barbeiro_id=barbeiro.id, servico_id=servico.id, barbearia_id=barbearia.id,
        duracao_min=30, preco_centavos=3500, ativo=True,
    )


def _servico(barbearia, barbeiros, nome="Corte"):
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome,
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    for barbeiro in barbeiros:
        _vincular(barbearia, barbeiro, servico)
    return servico


def _aberto_todo_dia(barbearia, barbeiro):
    for dia_semana in range(7):
        HorarioTrabalho.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=barbearia.id, barbeiro_id=barbeiro.id,
            dia_semana=dia_semana, minutos_inicio=0, minutos_fim=1440,
        )


def _cenario_simples(cenario):
    """Um servico e um barbeiro, aberto 24h todo dia: o menor cenario em que
    sempre ha horario, a qualquer hora que a suite rode."""
    b = _barbearia_com_bot(cenario["brutus"])
    pedro = _barbeiro(b)
    _aberto_todo_dia(b, pedro)
    return b, pedro, _servico(b, [pedro])


def _cliente(barbearia, nome="Maria Souza", whatsapp=NUMERO):
    return Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome, whatsapp=whatsapp,
    )


def _agendamento(barbearia, barbeiro, servico, cliente, inicio):
    return Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=barbeiro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome=servico.nome, inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )


def _amanha_redondo():
    return (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        minute=0, second=0, microsecond=0,
    )


class _Conversa:
    """Um cliente conversando. O relogio fica PARADO durante a conversa inteira:
    com um `agora` novo a cada mensagem, o horario oferecido podia passar entre
    a oferta e a confirmacao quando a suite roda perto de uma meia hora."""

    def __init__(self, barbearia, numero=NUMERO, agora=None):
        self.barbearia = barbearia
        self.numero = numero
        self.agora = agora or datetime.now(timezone.utc)
        self.cliente_leu = []
        self.equipe_leu = []

    def diz(self, texto, *, mensagem_id=None):
        def ao_cliente(instancia, numero, mensagem):
            assert instancia == nome_da_instancia(self.barbearia.id)
            assert numero == self.numero
            self.cliente_leu.append(mensagem)
            return f"bot-{uuid.uuid4().hex[:8]}"

        def a_equipe(numero, mensagem):
            self.equipe_leu.append((numero, mensagem))

        with patch("app.services.bot._enviar", side_effect=ao_cliente), patch(
            "app.services.bot.enviar_a_equipe", side_effect=a_equipe
        ):
            return processar(
                str(self.barbearia.id), self.numero, texto,
                mensagem_id or f"msg-{uuid.uuid4().hex}", self.agora,
            )

    @property
    def ultima(self):
        return self.cliente_leu[-1]


def _linha(barbearia, numero=NUMERO):
    with com_barbearia(barbearia.id):
        return ConversaWhatsapp.objects.filter(whatsapp=numero).first()


# ---- menu ----


def test_primeira_mensagem_recebe_o_menu_de_quem_nao_tem_horario(cenario):
    b, _, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    assert conversa.diz("oi") == "perguntou"
    assert conversa.ultima.startswith("Oi! Aqui é o atendimento da Brutus.")
    assert "1 - Marcar horário" in conversa.ultima
    assert "Cancelar" not in conversa.ultima
    assert _linha(b).estado == "MENU"


def test_quem_tem_horario_ve_o_horario_no_menu(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    _agendamento(b, pedro, servico, _cliente(b), _amanha_redondo())
    conversa = _Conversa(b)
    conversa.diz("oi")
    assert "Você tem: Pedro," in conversa.ultima
    assert "1 - Marcar outro horário" in conversa.ultima
    assert "2 - Cancelar esse" in conversa.ultima


# ---- marcar ----


def test_marca_do_oi_ao_horario_gravado(cenario):
    b, pedro, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    # Um servico e um barbeiro so': os dois passos sao pulados.
    assert conversa.ultima.startswith("Qual dia?")
    conversa.diz("1")
    assert conversa.ultima.startswith("Horários de")
    conversa.diz("1")
    assert conversa.ultima == "Pra marcar, me diz seu nome:"
    conversa.diz("  João   da Silva ")
    assert conversa.ultima.startswith("Confere:\nCorte com Pedro,")
    assert conversa.diz("1") == "marcou"

    with com_barbearia(b.id):
        [ag] = list(Agendamento.objects.select_related("cliente"))
    assert str(ag.barbeiro_id) == str(pedro.id)
    assert ag.cliente.whatsapp == NUMERO
    assert ag.cliente.nome == "João da Silva"
    assert conversa.ultima.startswith("Fechou, João!")
    assert "brutus." in conversa.ultima and "/agendamento/" in conversa.ultima
    assert [numero for numero, _ in conversa.equipe_leu] == [pedro.whatsapp]
    assert _linha(b).estado == "MENU"
    assert _linha(b).opcoes == []


def test_cliente_conhecido_nao_e_perguntado_o_nome(cenario):
    b, _, _ = _cenario_simples(cenario)
    _cliente(b)
    conversa = _Conversa(b)
    for texto in ("oi", "1", "1", "1"):
        conversa.diz(texto)
    assert conversa.ultima.startswith("Confere:")


def test_dois_servicos_fazem_o_bot_perguntar_qual(cenario):
    b, pedro, _ = _cenario_simples(cenario)
    _servico(b, [pedro], nome="Barba")
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    assert conversa.ultima.startswith("Qual serviço?")
    assert "Barba" in conversa.ultima and "Corte" in conversa.ultima


def test_dois_barbeiros_ganham_o_tanto_faz(cenario):
    b, _, servico = _cenario_simples(cenario)
    zeca = _barbeiro(b, nome="Zeca", ordem=1)
    _aberto_todo_dia(b, zeca)
    _vincular(b, zeca, servico)
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    assert conversa.ultima.startswith("Com quem?")
    assert "3 - Tanto faz" in conversa.ultima


def test_horario_pego_entre_oferecer_e_confirmar_volta_para_os_horarios(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    _cliente(b)
    conversa = _Conversa(b)
    for texto in ("oi", "1", "1", "1"):
        conversa.diz(texto)
    inicio = datetime.fromisoformat(_linha(b).rascunho["inicio"])
    _agendamento(b, pedro, servico, _cliente(b, "Mais Rápido", "83900001111"), inicio)

    assert conversa.diz("1") == "perguntou"
    assert conversa.ultima.startswith("Esse horário não está mais disponível.")
    assert _linha(b).estado == "HORA"
    with com_barbearia(b.id):
        assert Agendamento.objects.filter(cliente__whatsapp=NUMERO).count() == 0


# ---- cancelar ----


def test_cancela_o_proprio_horario(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    ag = _agendamento(b, pedro, servico, _cliente(b), _amanha_redondo())
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("2")
    assert conversa.ultima.startswith("Cancelar Pedro,")
    assert conversa.diz("1") == "cancelou"
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=ag.id).status == "CANCELADO_CLIENTE"
    assert [numero for numero, _ in conversa.equipe_leu] == [pedro.whatsapp]


def test_nao_cancela_horario_de_outro_numero(cenario):
    """O pior defeito possivel deste bot. A opcao so' existe se o bot a
    ofereceu, mas a casca confere o dono do horario do mesmo jeito: opcao
    guardada nao e' autoridade (spec, secao 3)."""
    b, pedro, servico = _cenario_simples(cenario)
    alheio = _agendamento(
        b, pedro, servico, _cliente(b, "Outra Pessoa", "83911112222"), _amanha_redondo(),
    )
    agora = datetime.now(timezone.utc)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, estado="CONFIRMA_CANCEL",
        opcoes=[{"id": "sim", "rotulo": "Sim, cancelar"}, {"id": "nao", "rotulo": "Não"}],
        rascunho={"codigo": alheio.codigo}, atualizado_em=agora,
    )
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("1") == "nao_e_seu"
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=alheio.id).status == "CONFIRMADO"
    assert conversa.equipe_leu == []


def test_cancelar_em_cima_da_hora_respeita_o_prazo(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ag = _agendamento(b, pedro, servico, _cliente(b), agora + timedelta(minutes=30))
    conversa = _Conversa(b, agora=agora)
    conversa.diz("oi")
    conversa.diz("2")
    assert conversa.diz("1") == "fora_do_prazo"
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=ag.id).status == "CONFIRMADO"


# ---- lembrete ----


def _parado_no_lembrete(b, ag, agora):
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, estado="AGUARDANDO_LEMBRETE",
        opcoes=[{"id": f"confirmar:{ag.codigo}", "rotulo": "Confirmar"},
                {"id": f"nao_vou:{ag.codigo}", "rotulo": "Não vou conseguir ir"}],
        atualizado_em=agora,
    )


def test_confirmar_o_lembrete_so_responde(cenario):
    b, pedro, servico = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ag = _agendamento(b, pedro, servico, _cliente(b), agora + timedelta(minutes=50))
    _parado_no_lembrete(b, ag, agora)
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("1") == "lembrete_confirmado"
    assert conversa.ultima == "Combinado, te esperamos!"
    assert conversa.equipe_leu == []


def test_nao_vou_avisa_o_barbeiro_e_nao_cancela(cenario):
    """Cancelar ficaria fora do prazo; quem desmarca e' o barbeiro, pelo
    painel. O que importa e' ele saber antes da cadeira ficar vazia."""
    b, pedro, servico = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ag = _agendamento(b, pedro, servico, _cliente(b), agora + timedelta(minutes=50))
    _parado_no_lembrete(b, ag, agora)
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("2") == "desistencia_avisada"
    [(numero, texto)] = conversa.equipe_leu
    assert numero == pedro.whatsapp
    assert texto.startswith("Avisou que não vem\nMaria Souza")
    with com_barbearia(b.id):
        assert Agendamento.objects.get(id=ag.id).status == "CONFIRMADO"


# ---- guardas ----


def test_mesma_mensagem_duas_vezes_responde_uma(cenario):
    b, _, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    assert conversa.diz("oi", mensagem_id="repetida") == "perguntou"
    assert conversa.diz("oi", mensagem_id="repetida") == "duplicada"
    assert len(conversa.cliente_leu) == 1


def test_fora_da_lista_repete_e_na_terceira_oferece_o_zero(cenario):
    b, pedro, _ = _cenario_simples(cenario)
    _servico(b, [pedro], nome="Barba")
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("1")
    for _ in range(2):
        assert conversa.diz("9") == "repetiu"
        assert "0 - Falar com a barbearia" not in conversa.ultima
    conversa.diz("9")
    assert conversa.ultima.startswith("Não entendi.")
    assert "Qual serviço?" in conversa.ultima
    assert "0 - Falar com a barbearia" in conversa.ultima
    assert _linha(b).estado == "SERVICO"


def test_zero_chama_o_dono_e_cala_o_bot(cenario):
    b, _, _ = _cenario_simples(cenario)
    dono = _barbeiro(b, nome="Dono", papel="DONO")
    conversa = _Conversa(b)
    conversa.diz("oi")
    assert conversa.diz("0") == "humano"
    [(numero, texto)] = conversa.equipe_leu
    assert numero == dono.whatsapp
    assert "(83) 9 8888-7777" in texto
    lidas = len(conversa.cliente_leu)
    assert conversa.diz("oi?") == "mudo"
    assert len(conversa.cliente_leu) == lidas


def test_conversa_muda_nao_responde(cenario):
    b, _, _ = _cenario_simples(cenario)
    agora = datetime.now(timezone.utc)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO,
        mudo_ate=agora + timedelta(hours=1), atualizado_em=agora,
    )
    conversa = _Conversa(b, agora=agora)
    assert conversa.diz("oi") == "mudo"
    assert conversa.cliente_leu == []


@pytest.mark.parametrize(
    "campos", [{"bot_ativo": False}, {"estado": EstadoInstancia.DESCONECTADO}],
)
def test_bot_desligado_ou_desconectado_nao_fala(cenario, campos):
    b = _barbearia_com_bot(cenario["brutus"], **campos)
    conversa = _Conversa(b)
    assert conversa.diz("oi") == "ignorado"
    assert conversa.cliente_leu == []
    assert _linha(b) is None


def test_guarda_o_id_de_cada_resposta(cenario):
    b, _, _ = _cenario_simples(cenario)
    conversa = _Conversa(b)
    conversa.diz("oi")
    conversa.diz("9")
    ids = _linha(b).ids_do_bot
    assert len(ids) == 2
    assert all(i.startswith("bot-") for i in ids)
```

Run: `docker compose exec -T api pytest tests/test_bot.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.bot'`.

- [ ] **Step 4: Implementar a casca**

Crie `backend/app/services/bot.py`:

```python
"""A casca do bot de agendamento: banco, Evolution e as acoes.

A regra da conversa NAO mora aqui — mora em `conversa.py`, pura. Este modulo
le o estado, executa a decisao (buscar opcoes, marcar, cancelar, chamar gente)
e grava o estado novo.

Tudo dentro de `trava_da_conversa`: `marcar`, `cancelar_publico` e
`dias_com_horarios` abrem o proprio `com_barbearia`, que nao pode ser
aninhado, entao uma trava de linha nao seguraria a conversa inteira.

Nenhuma funcao daqui e' chamada de dentro de um `com_barbearia`.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import IntegrityError

from tenant.config import (
    BOT_DIAS_OFERECIDOS,
    BOT_HORAS_OFERECIDAS,
    BOT_IDS_GUARDADOS,
    BOT_JANELA_DIAS,
    BOT_MUDO_HORAS,
    BOT_TENTATIVAS_ANTES_DO_ZERO,
)
from tenant.datas import como_utc, dia_de_hoje, formatar_instante_iso
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    BarbeiroServico,
    Cliente,
    ConversaWhatsapp,
    EstadoInstancia,
    PapelBarbeiro,
    PlanoBarbearia,
    Servico,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia
from tenant.telefone import formatar

from . import conversa as c
from .agenda import dias_com_horarios
from .agendamentos import ErroCliente, cancelar_publico, eh_sobreposicao, marcar
from .convite import link_do_agendamento
from .mensagens import (
    msg_barbeiro_cancelado,
    msg_barbeiro_desistiu,
    msg_barbeiro_novo,
    msg_bot_chamou_humano,
    msg_bot_desistencia_avisada,
    msg_bot_fora_do_prazo,
    msg_bot_lembrete_confirmado,
    msg_bot_nao_achei_agendamento,
    msg_bot_nao_entendi,
    msg_bot_pediu_humano,
    msg_bot_pergunta,
    msg_bot_sem_opcoes,
    msg_cancelamento,
    msg_confirmacao,
    rotulo_da_hora,
    rotulo_do_agendamento,
)
from .servicos import QUALQUER
from .servicos import listar_para_agendamento as servicos_para_agendamento
from .trava_conversa import trava_da_conversa
from .whatsapp import _enviar, enviar_a_equipe

logger = logging.getLogger(__name__)


@dataclass
class _Contexto:
    barbearia: Barbearia
    instancia: WhatsappInstancia
    numero: str
    agora: datetime

    @property
    def bid(self) -> str:
        return str(self.barbearia.id)


@dataclass
class _Saida:
    """O que sai de um passo: o estado novo da conversa e o que o cliente le."""

    desfecho: str
    passo: str
    textos: list
    opcoes: list = field(default_factory=list)
    rascunho: dict = field(default_factory=dict)
    tentativas: int = 0
    pergunta: str | None = None
    mudo_ate: datetime | None = None


def processar(barbearia_id: str, numero: str, texto: str, mensagem_id: str, agora: datetime) -> str:
    """Uma mensagem de cliente. `numero` ja vem normalizado (`do_jid`).

    Confere de novo o que a entrada ja conferiu (plano, bot ligado, conectado):
    entre enfileirar e rodar, o dono pode ter desligado o bot, e o bot nao fala
    onde deixou de ser convidado.
    """
    barbearia = Barbearia.objects.filter(
        id=barbearia_id, ativo=True, plano=PlanoBarbearia.COM_ZAP,
    ).first()
    if barbearia is None:
        return "ignorado"
    with com_barbearia(barbearia_id):
        instancia = WhatsappInstancia.objects.filter(barbearia_id=barbearia_id).first()
    if (
        instancia is None
        or not instancia.bot_ativo
        or instancia.estado != EstadoInstancia.CONECTADO
    ):
        return "ignorado"

    ctx = _Contexto(barbearia, instancia, numero, agora)
    with trava_da_conversa(ctx.bid, numero):
        linha = _conversa(ctx.bid, numero)
        if linha is not None and linha.ultima_mensagem_id == mensagem_id:
            return "duplicada"
        if linha is not None and linha.mudo_ate and como_utc(linha.mudo_ate) > agora:
            with com_barbearia(ctx.bid):
                ConversaWhatsapp.objects.filter(id=linha.id).update(
                    ultima_mensagem_id=mensagem_id,
                )
            return "mudo"

        estado = _estado_de(linha)
        decisao = c.decidir(estado, texto, agora)
        saida = _executar(ctx, estado, linha.pergunta if linha else None, decisao)
        ids = [i for i in (_enviar(instancia.nome, numero, t) for t in saida.textos) if i]
        _gravar(ctx, linha, saida, mensagem_id, ids)
        return saida.desfecho


# ---- leitura e gravacao ----


def _conversa(barbearia_id: str, numero: str):
    with com_barbearia(barbearia_id):
        return ConversaWhatsapp.objects.filter(whatsapp=numero).first()


def _estado_de(linha) -> c.Estado:
    if linha is None:
        return c.Estado(c.MENU, [], {}, 0, None)
    return c.Estado(
        linha.estado, linha.opcoes or [], linha.rascunho or {},
        linha.tentativas, como_utc(linha.atualizado_em),
    )


def _gravar(ctx: _Contexto, linha, saida: _Saida, mensagem_id: str, ids_novos: list) -> None:
    anteriores = list(linha.ids_do_bot or []) if linha is not None else []
    campos = {
        "estado": saida.passo,
        "opcoes": saida.opcoes,
        "rascunho": saida.rascunho,
        "tentativas": saida.tentativas,
        "pergunta": saida.pergunta,
        "ultima_mensagem_id": mensagem_id,
        "ids_do_bot": (anteriores + ids_novos)[-BOT_IDS_GUARDADOS:],
        "mudo_ate": saida.mudo_ate,
        "atualizado_em": ctx.agora,
    }
    with com_barbearia(ctx.bid):
        if linha is None:
            ConversaWhatsapp.objects.create(
                id=str(uuid.uuid4()), barbearia_id=ctx.bid, whatsapp=ctx.numero, **campos,
            )
        else:
            ConversaWhatsapp.objects.filter(id=linha.id).update(**campos)


# ---- executar a decisao ----


def _executar(ctx: _Contexto, estado: c.Estado, pergunta_anterior, decisao) -> _Saida:
    if isinstance(decisao, c.Repetir):
        texto = msg_bot_nao_entendi(
            pergunta=pergunta_anterior or "",
            mostrar_zero=decisao.tentativas >= BOT_TENTATIVAS_ANTES_DO_ZERO,
        )
        return _Saida(
            "repetiu", estado.passo, [texto], estado.opcoes, estado.rascunho,
            decisao.tentativas, pergunta_anterior,
        )
    if isinstance(decisao, c.ChamarHumano):
        _avisar_donos(ctx)
        return _Saida(
            "humano", c.MENU, [msg_bot_chamou_humano()],
            mudo_ate=ctx.agora + timedelta(hours=BOT_MUDO_HORAS),
        )
    if isinstance(decisao, c.Marcar):
        return _marcar(ctx, decisao.rascunho)
    if isinstance(decisao, c.Cancelar):
        return _cancelar(ctx, decisao.codigo)
    if isinstance(decisao, c.ConfirmarLembrete):
        return _Saida("lembrete_confirmado", c.MENU, [msg_bot_lembrete_confirmado()])
    if isinstance(decisao, c.NaoVou):
        return _nao_vou(ctx, decisao.codigo)
    return _ir(ctx, decisao.passo, decisao.rascunho)


def _ir(ctx: _Contexto, passo: str, rascunho: dict, prefixo: str | None = None) -> _Saida:
    opcoes, contexto, rascunho = _opcoes_do_passo(ctx, passo, rascunho)
    pulo = c.seguir_sozinho(passo, rascunho, opcoes)
    while pulo is not None:
        passo = pulo.passo
        opcoes, contexto, rascunho = _opcoes_do_passo(ctx, passo, pulo.rascunho)
        pulo = c.seguir_sozinho(passo, rascunho, opcoes)

    if passo != c.NOME and not opcoes:
        return _Saida("sem_opcoes", c.MENU, [msg_bot_sem_opcoes(passo=passo)])

    pergunta = msg_bot_pergunta(passo=passo, opcoes=opcoes, contexto=contexto)
    texto = f"{prefixo}\n\n{pergunta}" if prefixo else pergunta
    return _Saida("perguntou", passo, [texto], opcoes, rascunho, 0, pergunta)


def _opcoes_do_passo(ctx: _Contexto, passo: str, r: dict):
    """(opcoes, contexto do texto, rascunho). Os ids produzidos aqui sao os que
    `conversa._escolheu` entende — mudar um lado exige mudar o outro."""
    if passo == c.MENU:
        nome, marcados = _cliente_e_marcados(ctx)
        opcoes = [{
            "id": "marcar",
            "rotulo": "Marcar outro horário" if marcados else "Marcar horário",
        }]
        if len(marcados) == 1:
            opcoes.append({"id": f"cancelar:{marcados[0]['id']}", "rotulo": "Cancelar esse"})
        elif marcados:
            opcoes.append({"id": "cancelar", "rotulo": "Cancelar um deles"})
        contexto = {
            "barbearia_nome": ctx.barbearia.nome,
            "agendamentos": [m["rotulo"] for m in marcados],
        }
        return opcoes, contexto, {"cliente_nome": nome}

    if passo == c.SERVICO:
        itens = servicos_para_agendamento(ctx.bid)
        return [{"id": str(s["servico_id"]), "rotulo": s["servico__nome"]} for s in itens], {}, r

    if passo == c.BARBEIRO:
        with com_barbearia(ctx.bid):
            vinculos = list(
                BarbeiroServico.objects.filter(
                    servico_id=r["servico_id"], ativo=True,
                    barbeiro__ativo=True, servico__ativo=True,
                )
                .order_by("barbeiro__ordem", "barbeiro__nome")
                .values("barbeiro_id", "barbeiro__nome")
            )
        opcoes = [{"id": str(v["barbeiro_id"]), "rotulo": v["barbeiro__nome"]} for v in vinculos]
        if len(opcoes) > 1:
            opcoes.append({"id": QUALQUER, "rotulo": "Tanto faz"})
        return opcoes, {}, r

    if passo == c.DIA:
        de = r.get("de") or dia_de_hoje(ctx.agora)
        dias = dias_com_horarios(
            ctx.bid, r["barbeiro_id"], r["servico_id"], de, BOT_JANELA_DIAS, ctx.agora,
        )
        com_vaga = [d for d in dias if d["slots"]][: BOT_DIAS_OFERECIDOS + 1]
        opcoes = [{"id": d["data"], "rotulo": d["rotulo"]} for d in com_vaga[:BOT_DIAS_OFERECIDOS]]
        if len(com_vaga) > BOT_DIAS_OFERECIDOS:
            opcoes.append({
                "id": f"mais:{com_vaga[BOT_DIAS_OFERECIDOS]['data']}", "rotulo": "Outros dias",
            })
        return opcoes, {}, r

    if passo == c.HORA:
        [dia] = dias_com_horarios(ctx.bid, r["barbeiro_id"], r["servico_id"], r["dia"], 1, ctx.agora)
        slots = dia["slots"]
        if r.get("depois"):
            slots = [s for s in slots if formatar_instante_iso(s["inicio"]) > r["depois"]]
        mostrados = slots[:BOT_HORAS_OFERECIDAS]
        tanto_faz = r["barbeiro_id"] == QUALQUER
        opcoes = [
            {
                "id": f"{formatar_instante_iso(s['inicio'])}|{s['barbeiroId']}",
                "rotulo": rotulo_da_hora(
                    inicio=s["inicio"], barbeiro_nome=s["barbeiroNome"] if tanto_faz else None,
                ),
            }
            for s in mostrados
        ]
        if len(slots) > BOT_HORAS_OFERECIDAS:
            opcoes.append({
                "id": f"depois:{formatar_instante_iso(mostrados[-1]['inicio'])}",
                "rotulo": "Mais tarde",
            })
        opcoes.append({"id": "outro_dia", "rotulo": "Outro dia"})
        return opcoes, {"dia_rotulo": dia["rotulo"]}, r

    if passo == c.NOME:
        return [], {}, r

    if passo == c.CONFIRMA:
        with com_barbearia(ctx.bid):
            servico = Servico.objects.filter(id=r["servico_id"]).values_list("nome", flat=True).first()
            barbeiro = (
                Barbeiro.objects.filter(id=r["barbeiro_escolhido"])
                .values_list("nome", flat=True).first()
            )
        opcoes = [
            {"id": "confirmar", "rotulo": "Confirmar"},
            {"id": "recomecar", "rotulo": "Começar de novo"},
        ]
        contexto = {
            "servico_nome": servico or "",
            "barbeiro_nome": barbeiro or "",
            "inicio": datetime.fromisoformat(r["inicio"]),
        }
        return opcoes, contexto, r

    if passo == c.QUAL_AGENDAMENTO:
        _, marcados = _cliente_e_marcados(ctx)
        return marcados, {}, r

    if passo == c.CONFIRMA_CANCEL:
        a = _agendamento_do_numero(ctx, r["codigo"])
        if a is None:
            return [], {}, r
        opcoes = [{"id": "sim", "rotulo": "Sim, cancelar"}, {"id": "nao", "rotulo": "Não"}]
        rotulo = rotulo_do_agendamento(barbeiro_nome=a.barbeiro.nome, inicio=a.inicio)
        return opcoes, {"agendamento_rotulo": rotulo}, r

    raise ValueError(f"passo sem opcoes: {passo}")


def _cliente_e_marcados(ctx: _Contexto):
    with com_barbearia(ctx.bid):
        cliente = Cliente.objects.filter(whatsapp=ctx.numero).first()
        if cliente is None:
            return None, []
        marcados = list(
            Agendamento.objects.filter(
                cliente_id=cliente.id, status="CONFIRMADO", inicio__gt=ctx.agora,
            )
            .select_related("barbeiro")
            .order_by("inicio")[:BOT_HORAS_OFERECIDAS]
        )
    return cliente.nome, [
        {"id": a.codigo, "rotulo": rotulo_do_agendamento(barbeiro_nome=a.barbeiro.nome, inicio=a.inicio)}
        for a in marcados
    ]


def _agendamento_do_numero(ctx: _Contexto, codigo: str):
    """O horario so' e' deste numero se o CLIENTE dele tem este whatsapp. E' a
    unica barreira entre um codigo guardado e o horario de outra pessoa."""
    with com_barbearia(ctx.bid):
        return (
            Agendamento.objects.filter(
                codigo=codigo, status="CONFIRMADO", cliente__whatsapp=ctx.numero,
            )
            .select_related("barbeiro", "cliente")
            .first()
        )


def _marcar(ctx: _Contexto, r: dict) -> _Saida:
    nome = r.get("cliente_nome") or ""
    volta = {k: v for k, v in r.items() if k not in ("inicio", "barbeiro_escolhido", "depois")}
    try:
        criado = marcar(
            barbearia_id=ctx.bid, barbeiro_id=r["barbeiro_escolhido"],
            servico_id=r["servico_id"], inicio=datetime.fromisoformat(r["inicio"]),
            nome=nome, whatsapp=ctx.numero, agora=ctx.agora,
        )
    except ErroCliente as e:
        return _ir(ctx, c.HORA, volta, prefixo=e.mensagem)
    except IntegrityError as e:
        if not eh_sobreposicao(e):
            raise
        return _ir(ctx, c.HORA, volta, prefixo="Esse horário acabou de ser pego.")

    enviar_a_equipe(
        criado["barbeiro_whatsapp"],
        msg_barbeiro_novo(
            cliente_nome=nome, servico_nome=criado["servico_nome"],
            inicio=criado["inicio"], agora=ctx.agora,
        ),
    )
    confirmacao = msg_confirmacao(
        cliente_nome=nome, barbeiro_nome=criado["barbeiro_nome"],
        servico_nome=criado["servico_nome"], inicio=criado["inicio"],
        endereco=ctx.barbearia.endereco,
        link=link_do_agendamento(ctx.barbearia.slug, criado["codigo"]),
    )
    return _Saida("marcou", c.MENU, [confirmacao])


def _cancelar(ctx: _Contexto, codigo: str) -> _Saida:
    if _agendamento_do_numero(ctx, codigo) is None:
        return _Saida("nao_e_seu", c.MENU, [msg_bot_nao_achei_agendamento()])
    resultado = cancelar_publico(ctx.bid, codigo, ctx.agora)
    if resultado["tipo"] == "fora_do_prazo":
        return _Saida("fora_do_prazo", c.MENU, [msg_bot_fora_do_prazo()])
    if resultado["tipo"] != "ok":
        return _Saida("nao_e_seu", c.MENU, [msg_bot_nao_achei_agendamento()])
    enviar_a_equipe(
        resultado["barbeiro_whatsapp"],
        msg_barbeiro_cancelado(
            cliente_nome=resultado["cliente_nome"], servico_nome=resultado["servico_nome"],
            inicio=resultado["inicio"], agora=ctx.agora,
        ),
    )
    texto = msg_cancelamento(barbeiro_nome=resultado["barbeiro_nome"], inicio=resultado["inicio"])
    return _Saida("cancelou", c.MENU, [texto])


def _nao_vou(ctx: _Contexto, codigo: str) -> _Saida:
    a = _agendamento_do_numero(ctx, codigo)
    if a is None:
        return _Saida("nao_e_seu", c.MENU, [msg_bot_nao_achei_agendamento()])
    enviar_a_equipe(
        a.barbeiro.whatsapp,
        msg_barbeiro_desistiu(
            cliente_nome=a.cliente.nome, servico_nome=a.servico_nome,
            inicio=a.inicio, agora=ctx.agora,
        ),
    )
    return _Saida("desistencia_avisada", c.MENU, [msg_bot_desistencia_avisada()])


def _avisar_donos(ctx: _Contexto) -> None:
    with com_barbearia(ctx.bid):
        donos = list(
            Barbeiro.objects.filter(papel=PapelBarbeiro.DONO, ativo=True)
            .values_list("whatsapp", flat=True)
        )
        nome = Cliente.objects.filter(whatsapp=ctx.numero).values_list("nome", flat=True).first()
    texto = msg_bot_pediu_humano(cliente=nome or formatar(ctx.numero))
    for whatsapp in donos:
        enviar_a_equipe(whatsapp, texto)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_bot.py -q`
Expected: PASS.

Se `test_marca_do_oi_ao_horario_gravado` falhar em `"brutus." in conversa.ultima`, confira o `URL_BASE` do contêiner: `link_do_agendamento` usa a mesma base de `link_do_convite`.

- [ ] **Step 6: Suíte inteira e commit**

Run: `docker compose exec -T api pytest -q`
Expected: tudo passando.

```bash
git add backend/app/services/whatsapp.py backend/app/services/bot.py tests/test_whatsapp.py tests/test_bot.py
git commit -m "bot: a casca que le, decide, marca e responde

Reusa marcar(), cancelar_publico() e dias_com_horarios() como estao: o bot
e' um terceiro chamador, nao um caminho novo de gravacao. A conferencia de
quem e' dono do horario acontece aqui tambem, mesmo com a opcao ja' tendo
sido oferecida pelo proprio bot.

_enviar passa a devolver o id da mensagem, para o bot reconhecer o eco.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: O interruptor — assinatura do webhook, painel e rota

**Files:**
- Modify: `backend/app/services/whatsapp_instancias.py`
- Modify: `tests/test_whatsapp_instancias.py`
- Modify: `backend/app/services/whatsapp_painel.py`
- Modify: `backend/app/api/v1/views/whatsapp_painel.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `tests/test_bot_interruptor.py`

**Interfaces:**
- Consumes: `WhatsappInstancia.bot_ativo` (Task 1).
- Produces:
  - `EVENTOS_SEM_BOT`, `EVENTOS_COM_BOT` (listas de str)
  - `aplicar_assinatura(nome: str, *, bot: bool) -> bool`
  - `ligar_bot(barbearia, ativo: bool) -> bool`
  - `ver()` passa a devolver a chave `"botAtivo": bool` em todos os ramos.
  - `POST /api/painel/whatsapp/bot` com corpo `{"ativo": bool}` → `200 {"ok": true, "botAtivo": bool}` | `403` (barbeiro) | `422`.

A lista de eventos mora **na instância, lá na Evolution**. Duas regras saem disso, e as duas têm teste: o interruptor aplica o webhook **antes** de gravar (nunca existe interruptor ligado e surdo), e `garantir_instancia` reaplica respeitando o interruptor (senão a conferência periódica desligaria o bot em silêncio).

- [ ] **Step 1: Escrever os testes que falham — assinatura**

Em `tests/test_whatsapp_instancias.py`, no fim:

```python
def test_assinatura_com_bot_pede_mensagens_e_tira_a_midia():
    """`base64: false` com o bot ligado: com `true`, cada foto, audio e video
    que chega no numero viria inteiro dentro do evento (fatia 0). O QR continua
    chegando pela busca do painel (`pedir_qr`)."""
    with patch.object(wi.requests, "post", return_value=Mock(ok=True, status_code=201)) as post:
        assert wi.aplicar_assinatura("marcai-x", bot=True) is True
    corpo = post.call_args.kwargs["json"]["webhook"]
    assert sorted(corpo["events"]) == ["CONNECTION_UPDATE", "MESSAGES_UPSERT", "QRCODE_UPDATED"]
    assert corpo["base64"] is False


def test_assinatura_sem_bot_volta_ao_de_sempre():
    with patch.object(wi.requests, "post", return_value=Mock(ok=True, status_code=201)) as post:
        assert wi.aplicar_assinatura("marcai-x", bot=False) is True
    corpo = post.call_args.kwargs["json"]["webhook"]
    assert sorted(corpo["events"]) == ["CONNECTION_UPDATE", "QRCODE_UPDATED"]
    assert corpo["base64"] is True


def test_assinatura_sem_evolution_configurada_falha(monkeypatch):
    monkeypatch.delenv("EVOLUTION_API_URL", raising=False)
    assert wi.aplicar_assinatura("marcai-x", bot=True) is False


def test_garantir_reaplica_o_webhook_sem_desligar_o_bot(cenario):
    """A conferencia periodica chama `garantir_instancia`. Se ela reaplicasse
    a lista sem mensagens, o bot pararia de ouvir sem ninguem ter desligado."""
    barbearia = cenario["brutus"]
    _linha(barbearia, bot_ativo=True)
    with patch.object(wi.requests, "post", return_value=Mock(ok=True, status_code=201)) as post:
        wi.garantir_instancia(barbearia)
    _, webhook = post.call_args_list
    assert "MESSAGES_UPSERT" in webhook.kwargs["json"]["webhook"]["events"]
```

Run: `docker compose exec -T api pytest tests/test_whatsapp_instancias.py -q`
Expected: FAIL com `AttributeError: ... has no attribute 'aplicar_assinatura'`.

- [ ] **Step 2: Implementar a assinatura**

Em `backend/app/services/whatsapp_instancias.py`, logo depois de `TIMEOUT_CRIACAO_S`:

```python
# Assinados em MAIUSCULO; chegam minusculos e com ponto. MESSAGES_UPSERT so'
# entra com o bot ligado: barbearia sem bot nunca manda uma mensagem de
# cliente para o Marcai (spec, secao 7).
EVENTOS_SEM_BOT = ["CONNECTION_UPDATE", "QRCODE_UPDATED"]
EVENTOS_COM_BOT = EVENTOS_SEM_BOT + ["MESSAGES_UPSERT"]
```

Troque a assinatura de `_aplicar_webhook` por `def _aplicar_webhook(cfg: dict[str, str], nome: str, *, bot: bool = False) -> bool:` e, dentro do `json`, troque as linhas de `"base64"` e `"events"` (com os comentários acima delas) por:

```python
                    # O QR pronto para o `<img src>` precisa de `base64: true`.
                    # Com o bot ligado ele vira `false`: a mesma opcao poria
                    # cada foto e video recebido INTEIRO dentro do evento
                    # (fatia 0). O QR segue chegando por `pedir_qr`.
                    "base64": not bot,
                    "events": EVENTOS_COM_BOT if bot else EVENTOS_SEM_BOT,
```

Em `garantir_instancia`, troque `if not _aplicar_webhook(cfg, linha.nome):` por `if not _aplicar_webhook(cfg, linha.nome, bot=linha.bot_ativo):`.

Depois de `_aplicar_webhook`, acrescente:

```python
def aplicar_assinatura(nome: str, *, bot: bool) -> bool:
    """Reescreve a lista de eventos de uma instancia que ja existe. Medido na
    fatia 0: `webhook/set` aceita isso com a instancia conectada, sem derrubar
    a conexao."""
    cfg = _config()
    if not cfg["url"]:
        logger.info("[whatsapp-instancia] sem EVOLUTION_API_URL: assinatura de %s nao muda", nome)
        return False
    return _aplicar_webhook(cfg, nome, bot=bot)
```

Run: `docker compose exec -T api pytest tests/test_whatsapp_instancias.py -q`
Expected: PASS.

- [ ] **Step 3: Escrever os testes que falham — painel e rota**

Crie `tests/test_bot_interruptor.py`:

```python
"""POST /api/painel/whatsapp/bot — ligar e desligar o atendimento automatico.

Duas regras: so' o DONO liga (um barbeiro mudaria como todo cliente e'
atendido, sem o dono saber), e o interruptor nunca mente — a Evolution aceita
primeiro, o banco grava depois.
"""

import uuid
from unittest.mock import patch

import pytest

from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import Barbearia, Barbeiro, EstadoInstancia, WhatsappInstancia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/painel/whatsapp/bot"
ASSINAR = "app.services.whatsapp_painel.aplicar_assinatura"


def _barbeiro(barbearia, papel):
    return Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=f"{papel} teste",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel=papel, ativo=True,
    )


def _logar(client, barbeiro, barbearia):
    from app.services.sessao import COOKIE_SESSAO, emitir

    client.cookies[COOKIE_SESSAO] = emitir(
        sub=barbeiro.id, bid=barbearia.id, papel=barbeiro.papel, tv=barbeiro.token_version,
    )
    return f"{barbearia.slug}.localhost"


def _com_zap(barbearia, estado=EstadoInstancia.CONECTADO, **campos):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    return WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id,
        nome=nome_da_instancia(barbearia.id), estado=estado, **campos,
    )


def _bot_ativo(barbearia):
    return WhatsappInstancia.objects.using("owner").get(barbearia_id=barbearia.id).bot_ativo


def _post(client, host, corpo):
    return client.post(
        ROTA, corpo, content_type="application/json",
        headers={"host": host, "x-brutus-cliente": "web"},
    )


def test_dono_liga_e_a_evolution_e_avisada_antes(client, cenario):
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR, return_value=True) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "botAtivo": True}
    assinar.assert_called_once_with(nome_da_instancia(b.id), bot=True)
    assert _bot_ativo(b) is True


def test_dono_desliga(client, cenario):
    b = cenario["brutus"]
    _com_zap(b, bot_ativo=True)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR, return_value=True) as assinar:
        r = _post(client, host, {"ativo": False})
    assert r.status_code == 200
    assinar.assert_called_once_with(nome_da_instancia(b.id), bot=False)
    assert _bot_ativo(b) is False


def test_evolution_recusando_deixa_como_estava(client, cenario):
    """Ligado na tela e surdo na pratica e' o pior defeito possivel: o dono
    pararia de responder cliente achando que o robo responde."""
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR, return_value=False):
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 422
    assert _bot_ativo(b) is False


def test_barbeiro_nao_liga(client, cenario):
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "BARBEIRO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 403
    assinar.assert_not_called()
    assert _bot_ativo(b) is False


def test_sem_zap_nao_liga(client, cenario):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 422
    assinar.assert_not_called()


def test_instancia_pendente_nem_chama_a_evolution(client, cenario):
    """PENDENTE e' "a Evolution ainda nao sabe que isto existe": o `webhook/set`
    seria 404 de qualquer jeito."""
    b = cenario["brutus"]
    _com_zap(b, estado=EstadoInstancia.PENDENTE)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, {"ativo": True})
    assert r.status_code == 422
    assinar.assert_not_called()


@pytest.mark.parametrize("corpo", [{}, {"ativo": "sim"}, {"ativo": 1}, {"ativo": None}])
def test_ativo_precisa_ser_booleano(client, cenario, corpo):
    b = cenario["brutus"]
    _com_zap(b)
    host = _logar(client, _barbeiro(b, "DONO"), b)
    with patch(ASSINAR) as assinar:
        r = _post(client, host, corpo)
    assert r.status_code == 422
    assinar.assert_not_called()


def test_ver_mostra_o_interruptor_para_todo_mundo(client, cenario):
    b = cenario["brutus"]
    _com_zap(b, bot_ativo=True)
    host = _logar(client, _barbeiro(b, "BARBEIRO"), b)
    r = client.get("/api/painel/whatsapp", headers={"host": host})
    assert r.json()["botAtivo"] is True


def test_ver_sem_zap_diz_desligado(client, cenario):
    b = cenario["brutus"]
    host = _logar(client, _barbeiro(b, "DONO"), b)
    r = client.get("/api/painel/whatsapp", headers={"host": host})
    assert r.json()["botAtivo"] is False
```

Run: `docker compose exec -T api pytest tests/test_bot_interruptor.py -q`
Expected: FAIL (`404` na rota, `KeyError: 'botAtivo'`).

- [ ] **Step 4: Implementar o serviço**

Em `backend/app/services/whatsapp_painel.py`:

Troque o import `from .whatsapp_instancias import desconectar_aparelho, pedir_qr` por `from .whatsapp_instancias import aplicar_assinatura, desconectar_aparelho, pedir_qr`.

Nos três dicionários devolvidos por `ver()`, acrescente a chave: nos dois primeiros (sem zap, e com zap sem linha) `"botAtivo": False,`; no último `"botAtivo": linha.bot_ativo,`.

No fim do arquivo:

```python
def ligar_bot(barbearia, ativo: bool) -> bool:
    """Liga ou desliga o atendimento automatico. A EVOLUTION PRIMEIRO.

    A lista de eventos mora na instancia, la. Gravar antes e aplicar depois
    abriria a janela em que o banco diz "ligado" e nenhuma mensagem chega —
    e se a aplicacao falhasse, a janela nunca fecharia. Falhou, nada muda.
    """
    if barbearia.plano != PlanoBarbearia.COM_ZAP:
        return False

    with com_barbearia(barbearia.id):
        linha = WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).first()
    if linha is None or linha.estado == EstadoInstancia.PENDENTE:
        return False

    if not aplicar_assinatura(linha.nome, bot=ativo):
        return False

    with com_barbearia(barbearia.id):
        WhatsappInstancia.objects.filter(barbearia_id=barbearia.id).update(
            bot_ativo=ativo, atualizado_em=timezone.now(),
        )
    return True
```

- [ ] **Step 5: Implementar a rota**

Em `backend/app/api/v1/views/whatsapp_painel.py`, troque o import de serviço por `from app.services.whatsapp_painel import desconectar, ligar_bot, ver` e acrescente no fim:

```python
class WhatsappBotView(ExigeDono, APIView):
    """POST /api/painel/whatsapp/bot — liga ou desliga o atendimento automatico.

    So' o dono: um barbeiro que desligasse o bot mudaria como TODO cliente da
    barbearia e' atendido, sem o dono saber.
    """

    mensagem_papel_insuficiente = "Só o dono liga o atendimento automático."

    def post(self, request):
        ativo = request.data.get("ativo") if isinstance(request.data, dict) else None
        # `isinstance(..., bool)` e nao truthiness: "sim" e 1 ligariam o bot
        # por acidente de um cliente de API mal escrito.
        if not isinstance(ativo, bool):
            return Response({"erro": "Diz se é para ligar ou desligar."}, status=422)
        if not ligar_bot(request.barbearia, ativo):
            return Response(
                {"erro": "Não deu para mudar agora. Confere se o WhatsApp está conectado e tenta de novo."},
                status=422,
            )
        return Response({"ok": True, "botAtivo": ativo})
```

Em `backend/app/api/v1/router.py`, troque o import `from .views.whatsapp_painel import WhatsappDesconectarView, WhatsappPainelView` por `from .views.whatsapp_painel import WhatsappBotView, WhatsappDesconectarView, WhatsappPainelView`, e logo depois do `path("painel/whatsapp/desconectar", ...)`:

```python
    path("painel/whatsapp/bot", WhatsappBotView.as_view(), name="painel-whatsapp-bot"),
```

- [ ] **Step 6: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_bot_interruptor.py tests/test_whatsapp_painel.py tests/test_whatsapp_instancias.py -q`
Expected: PASS.

- [ ] **Step 7: Suíte inteira e commit**

Run: `docker compose exec -T api pytest -q`
Expected: tudo passando.

```bash
git add backend/app/services/whatsapp_instancias.py backend/app/services/whatsapp_painel.py backend/app/api/v1/views/whatsapp_painel.py backend/app/api/v1/router.py tests/test_whatsapp_instancias.py tests/test_bot_interruptor.py
git commit -m "bot: o interruptor, com a Evolution avisada antes do banco

A lista de eventos mora na instancia, la na Evolution. Ligar aplica o
webhook primeiro e so' grava se ela aceitar: nunca ha interruptor ligado e
surdo. garantir_instancia passa a reaplicar respeitando o interruptor, senao
a conferencia periodica desligaria o bot em silencio.

Com o bot ligado, base64 vira false: a mesma opcao que traz o QR poria cada
foto e video recebido dentro do evento.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: O zelador poda conversas paradas

**Files:**
- Modify: `backend/app/services/zelador.py`
- Modify: `tests/test_zelador.py`

**Interfaces:**
- Consumes: `ConversaWhatsapp`, `BOT_CONVERSA_GUARDADA_DIAS` (Task 1).
- Produces: `_podar_conversas() -> int`; `alarmar_e_podar()` ganha a chave `"podadas_conversas"`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_zelador.py`, no fim:

```python
def test_poda_conversas_paradas_e_preserva_as_vivas_e_as_mudas(cenario):
    from datetime import timedelta

    from django.utils import timezone

    from app.services.zelador import _podar_conversas
    from tenant.config import BOT_CONVERSA_GUARDADA_DIAS
    from tenant.models import ConversaWhatsapp
    from tenant.rls import com_barbearia

    b = cenario["brutus"]
    agora = timezone.now()
    velha = agora - timedelta(days=BOT_CONVERSA_GUARDADA_DIAS + 1)
    for numero, atualizado, mudo in (
        ("83900000001", velha, None),                         # some
        ("83900000002", agora - timedelta(hours=1), None),    # fica: recente
        # Fica: parada ha dias, mas alguem da barbearia ainda esta falando
        # com essa pessoa. Apagar a linha faria o bot voltar a atropelar.
        ("83900000003", velha, agora + timedelta(hours=2)),
    ):
        ConversaWhatsapp.objects.using("owner").create(
            id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=numero,
            atualizado_em=atualizado, mudo_ate=mudo,
        )

    assert _podar_conversas() == 1

    with com_barbearia(b.id):
        assert sorted(ConversaWhatsapp.objects.values_list("whatsapp", flat=True)) == [
            "83900000002", "83900000003",
        ]
```

O `pytestmark` do topo do arquivo já cobre o banco; `uuid` já é importado no topo.

Run: `docker compose exec -T api pytest tests/test_zelador.py -q`
Expected: FAIL com `ImportError: cannot import name '_podar_conversas'`.

- [ ] **Step 2: Implementar**

Em `backend/app/services/zelador.py`, acrescente `BOT_CONVERSA_GUARDADA_DIAS` ao import de `tenant.config` e `ConversaWhatsapp` ao import de `tenant.models`. No dicionário devolvido por `alarmar_e_podar`, depois de `"podadas_nao_enviadas": _podar_nao_enviadas(),`, acrescente `"podadas_conversas": _podar_conversas(),`. No fim do arquivo:

```python
def _podar_conversas() -> int:
    """Conversa do bot parada ha mais de BOT_CONVERSA_GUARDADA_DIAS.

    Conversa e' estado de minutos: depois de 20 ela ja recomeca do menu. Passado
    o prazo, a linha so' guardaria o numero de alguem sem motivo nenhum.

    A conversa MUDA fica, mesmo velha: `mudo_ate` no futuro quer dizer que
    alguem da barbearia esta falando com essa pessoa, e apagar a linha faria o
    bot voltar a responder por cima.
    """
    agora = timezone.now()
    limite = agora - timedelta(days=BOT_CONVERSA_GUARDADA_DIAS)
    podadas = 0
    for b in Barbearia.objects.all():
        with com_barbearia(b.id):
            apagadas, _ = (
                ConversaWhatsapp.objects.filter(atualizado_em__lt=limite)
                .exclude(mudo_ate__gt=agora)
                .delete()
            )
        podadas += apagadas
    return podadas
```

- [ ] **Step 3: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_zelador.py tests/test_celery.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/zelador.py tests/test_zelador.py
git commit -m "bot: o zelador poda conversa parada

Conversa e' estado de minutos; passados dois dias a linha so' guardaria um
numero. A conversa muda fica, senao o bot voltaria a atropelar quem ainda
esta falando com a barbearia.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Front — o interruptor na tela do WhatsApp

**Repositório:** `Marcai-front`, numa branch nova a partir da `main`.

**Files:**
- Modify: `src/lib/api/painelAPI.ts`
- Modify: `src/app/painel/whatsapp/page.tsx`

**Interfaces:**
- Consumes: `POST /api/painel/whatsapp/bot` e `botAtivo` em `GET /api/painel/whatsapp` (Task 7).
- Produces: `WhatsappDaBarbearia.botAtivo: boolean`; `whatsappApi.ligarBot(ativo: boolean)`.

`/painel/whatsapp` já está em `MIGRADAS` (`src/lib/api/client.ts`) e o casamento é por segmento: `/painel/whatsapp/bot` vai para o Django sem mudança ali. `tests/client-base.test.ts` lê os caminhos do próprio `painelAPI.ts` e falha se não for assim — ele é o teste desta tarefa do lado da rota. A faixa (`faixaDoWhatsapp`) recebe um `Pick<...>` sem `botAtivo`, então os testes dela não mudam.

- [ ] **Step 1: A API**

Em `src/lib/api/painelAPI.ts`, no tipo `WhatsappDaBarbearia`, depois de `naoEnviadas: number;`:

```ts
  /// O atendimento automático. Só liga com o WhatsApp conectado, e nasce
  /// desligado — ninguém acorda com um robô atendendo o número do negócio.
  botAtivo: boolean;
```

Em `whatsappApi`, depois de `desconectar`:

```ts
  /// Liga ou desliga o bot. Só o dono — a rota responde 403 para `BARBEIRO`.
  /// Responde 422 quando a Evolution recusa: nesse caso nada mudou.
  ligarBot: (ativo: boolean) =>
    pedir<{ ok: true; botAtivo: boolean }>('/painel/whatsapp/bot', {
      metodo: 'POST', corpo: { ativo }, loginEm: LOGIN_DO_PAINEL,
    }),
```

- [ ] **Step 2: A tela**

Em `src/app/painel/whatsapp/page.tsx`:

Depois de `const [trocando, setTrocando] = useState(false);`:

```tsx
  const [mudandoBot, setMudandoBot] = useState(false);
```

Depois da função `trocarDeCelular`:

```tsx
  async function mudarBot(ativo: boolean) {
    // Ligar pergunta; desligar não. Ligar faz as mensagens do número passarem
    // pelo Marcaí — o dono precisa saber disso ANTES, não descobrir depois.
    if (ativo && !confirm(
      'Ligar o atendimento automático? As mensagens que chegarem neste número '
      + 'passam pelo Marcaí para o robô responder. Nada da conversa fica guardado.',
    )) return;
    setMudandoBot(true);
    setErro(null);
    try {
      await whatsappApi.ligarBot(ativo);
      await carregar();
    } catch (e) {
      setErro(mensagemDoErro(e) || 'Não deu para mudar agora.');
    } finally {
      setMudandoBot(false);
    }
  }
```

Troque `<Miolo dados={dados} trocando={trocando} aoTrocar={trocarDeCelular} />` por:

```tsx
<Miolo
  dados={dados} trocando={trocando} aoTrocar={trocarDeCelular}
  mudandoBot={mudandoBot} aoMudarBot={mudarBot}
/>
```

Troque a assinatura de `Miolo` por:

```tsx
function Miolo({
  dados, trocando, aoTrocar, mudandoBot, aoMudarBot,
}: {
  dados: WhatsappDaBarbearia;
  trocando: boolean;
  aoTrocar: () => void;
  mudandoBot: boolean;
  aoMudarBot: (ativo: boolean) => void;
}) {
```

No ramo `if (dados.estado === 'CONECTADO')`, logo depois do `</button>` de "Trocar de celular" e antes do `</>`:

```tsx
        <Sep />
        <Lbl>Atendimento automático</Lbl>
        {/* Só com o WhatsApp conectado: ligar um robô num número que não
            recebe nada seria um interruptor que não faz coisa nenhuma. */}
        <button
          type="button" role="switch" aria-checked={dados.botAtivo}
          onClick={() => aoMudarBot(!dados.botAtivo)} disabled={mudandoBot}
          className="text-left"
        >
          <Box variante={dados.botAtivo ? 'sel' : 'normal'}>
            {mudandoBot ? 'mudando…' : dados.botAtivo ? 'Ligado' : 'Desligado'}
          </Box>
        </button>
        <Sub>
          {dados.botAtivo
            ? 'Quem escreve para este número recebe um menu para marcar ou cancelar. Se alguém da barbearia responder pelo celular, o robô fica quieto naquela conversa por 4 horas.'
            : 'Ligado, o robô responde quem escrever para este número com um menu para marcar ou cancelar horário. Grupo, áudio e foto ele ignora.'}
        </Sub>
```

- [ ] **Step 3: Verificar**

Run (em `Marcai-front`): `npx next typegen && npx tsc --noEmit && npm run test:ci`
Expected: `tsc` sem saída e todos os testes passando (incluindo `tests/client-base.test.ts`).

Conferência manual, com o back das tarefas 1–7 rodando: entrar como dono em `http://<slug>.localhost:3000/painel/whatsapp` com uma instância conectada → o interruptor aparece; ligar pede confirmação; com a Evolution local de pé, ele passa a "Ligado". Entrar como barbeiro → a tela continua dizendo "Só o dono conecta o WhatsApp da barbearia."

- [ ] **Step 4: Commit**

```bash
git add src/lib/api/painelAPI.ts src/app/painel/whatsapp/page.tsx
git commit -m "whatsapp: o interruptor do atendimento automatico

So' com o WhatsApp conectado, e ligar pergunta antes: as mensagens do numero
passam a atravessar o Marcai, e o dono precisa saber disso antes de ligar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Medição com número dedicado — PORTÃO das tarefas 11 e 12

**Precisa de:** um chip de WhatsApp **só para teste** e um segundo celular qualquer. **Nunca** o número de uso real de uma barbearia: medir exige capturar tudo o que chega, e num número real isso é capturar conversa de gente que não tem nada a ver com o teste (foi o que aconteceu na fatia 0 — spec, seção 11).

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-bot-agendamento-whatsapp-design.md` (acrescentar `### Fatia 0b` ao fim da seção 11)
- Nada de código de produto. Todo script daqui é descartável e vive em `/tmp`.

**Interfaces:**
- Produces: as respostas de G1–G4 abaixo, gravadas na spec. As tarefas 11 e 12 leem essas respostas.

- [ ] **Step 1: Conectar o chip a uma barbearia de teste local**

Com a pilha local de pé (`docker compose up -d`), no admin local (`http://admin.localhost:3000/admin`) crie a barbearia `teste-bot` com plano **com zap**, entre como dono em `http://teste-bot.localhost:3000/painel/whatsapp` e leia o QR **com o chip dedicado**.

Guarde o nome da instância e o número conectado:

```bash
docker compose exec -T api python - <<'PY'
import os, requests
u = os.environ["EVOLUTION_API_URL"]; H = {"apikey": os.environ["EVOLUTION_API_KEY"]}
for i in requests.get(f"{u}/instance/fetchInstances", headers=H, timeout=10).json():
    print(i.get("name"), i.get("connectionStatus"), i.get("ownerJid"))
PY
```

Anote em `INST` o `marcai-<uuid>` cujo `ownerJid` é o do chip.

- [ ] **Step 2: Coletor descartável e assinatura de teste**

```bash
mkdir -p /tmp/fatia0b && : > /tmp/fatia0b/eventos.jsonl
cat > /tmp/fatia0b/coletor.py <<'PY'
import json, time
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        corpo = self.rfile.read(int(self.headers.get("content-length", 0)))
        with open("/saida/eventos.jsonl", "a") as f:
            f.write(json.dumps({"t": time.time(), "corpo": corpo.decode("utf-8", "replace")}) + "\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
HTTPServer(("0.0.0.0", 9000), H).serve_forever()
PY
docker run -d --name fatia0b-coletor --network brutus --network-alias coletor \
  -v /tmp/fatia0b:/saida python:3.12-slim python /saida/coletor.py

INST=marcai-COLE-AQUI-O-UUID docker compose exec -T -e INST api python - <<'PY'
import os, json, requests
u = os.environ["EVOLUTION_API_URL"]; H = {"apikey": os.environ["EVOLUTION_API_KEY"]}; N = os.environ["INST"]
original = requests.get(f"{u}/webhook/find/{N}", headers=H, timeout=10).json()
json.dump(original, open("/tmp/webhook_original.json", "w"))
corpo = {"webhook": {"enabled": True, "url": "http://coletor:9000/evento",
         "headers": original.get("headers") or {}, "byEvents": False, "base64": False,
         "events": ["CONNECTION_UPDATE", "QRCODE_UPDATED", "MESSAGES_UPSERT"]}}
print("set:", requests.post(f"{u}/webhook/set/{N}", headers=H, json=corpo, timeout=10).status_code)
PY
```

Troque `marcai-COLE-AQUI-O-UUID` pelo `INST` do step 1 antes de rodar. Expected: `set: 201`.

- [ ] **Step 3: Produzir os eventos, um de cada vez, anotando a hora**

1. **Do segundo celular**, mande `oi` para o chip. (G1)
2. **Do chip**, responda qualquer coisa ao segundo celular. **Do segundo celular**, responda **citando** essa mensagem (segurar a mensagem → Responder) com `1`. (G2)
3. **Do chip, digitando no próprio aparelho**, mande `teste` ao segundo celular. (eco humano, `fromMe`)
4. **Pela API**, a partir da instância do chip — anote o `key.id` impresso: (G3)

```bash
INST=marcai-COLE-AQUI-O-UUID NUMERO=5583SEGUNDOCELULAR docker compose exec -T -e INST -e NUMERO api python - <<'PY'
import os, requests
u = os.environ["EVOLUTION_API_URL"]; H = {"apikey": os.environ["EVOLUTION_API_KEY"]}
r = requests.post(f"{u}/message/sendText/{os.environ['INST']}", headers=H,
                  json={"number": os.environ["NUMERO"], "text": "teste da API"}, timeout=30)
print(r.status_code, "id devolvido:", r.json().get("key", {}).get("id"))
PY
```

5. **Do segundo celular**, mande uma **foto** para o chip. (G4)
6. No painel de `teste-bot`, clique **Trocar de celular**, espere 30 s, e veja se o QR aparece na tela. (G4)

- [ ] **Step 4: Ler só a estrutura, sem conteúdo**

```bash
python3 - /tmp/fatia0b/eventos.jsonl <<'PY'
import json, sys
for linha in open(sys.argv[1]):
    e = json.loads(linha)
    try:
        c = json.loads(e["corpo"])
    except ValueError:
        print({"nao_json_bytes": len(e["corpo"])}); continue
    d = c.get("data"); forma = type(d).__name__
    if isinstance(d, list):
        d = d[0] if d else {}
    d = d or {}
    k = d.get("key") or {}
    jid = k.get("remoteJid") or ""
    msg = d.get("message") or {}
    print(json.dumps({
        "evento": c.get("event"), "data_e": forma,
        "jid_sufixo": jid[jid.find("@"):] if "@" in jid else None,
        "jid_digitos": sum(ch.isdigit() for ch in jid.split("@")[0]),
        "fromMe": k.get("fromMe"), "id": k.get("id"),
        "chaves_key": sorted(k), "chaves_data": sorted(d), "chaves_message": sorted(msg),
        "texto_em_conversation": bool(msg.get("conversation")),
        "texto_em_extended": bool((msg.get("extendedTextMessage") or {}).get("text")),
        "tem_base64": "base64" in json.dumps(msg),
        "bytes": len(e["corpo"]), "source": d.get("source"),
        "qr_base64": bool((d.get("qrcode") or {}).get("base64")),
    }, ensure_ascii=False))
PY
```

Este script não imprime texto de mensagem nenhum — só formas, chaves, ids e tamanhos.

- [ ] **Step 5: Devolver tudo como estava e apagar a captura**

```bash
INST=marcai-COLE-AQUI-O-UUID docker compose exec -T -e INST api python - <<'PY'
import os, json, requests
u = os.environ["EVOLUTION_API_URL"]; H = {"apikey": os.environ["EVOLUTION_API_KEY"]}; N = os.environ["INST"]
o = json.load(open("/tmp/webhook_original.json"))
corpo = {"webhook": {"enabled": o.get("enabled", True), "url": o["url"], "headers": o.get("headers") or {},
         "byEvents": o.get("webhookByEvents", False), "base64": o.get("webhookBase64", True), "events": o["events"]}}
print("restaura:", requests.post(f"{u}/webhook/set/{N}", headers=H, json=corpo, timeout=10).status_code)
d = requests.get(f"{u}/webhook/find/{N}", headers=H, timeout=10).json()
print("igual ao original:", d.get("url") == o["url"] and d.get("events") == o["events"] and d.get("headers") == o.get("headers"))
PY
docker compose exec -T api rm -f /tmp/webhook_original.json
docker rm -f fatia0b-coletor
shred -u /tmp/fatia0b/eventos.jsonl; rm -rf /tmp/fatia0b
```

Expected: `restaura: 201` e `igual ao original: True`.

- [ ] **Step 6: Responder os portões e gravar na spec**

Acrescente `### Fatia 0b (número dedicado)` ao fim da seção 11 da spec, com uma tabela das respostas:

| Portão | Pergunta | Se a resposta for SIM | Se for NÃO |
|---|---|---|---|
| **G1** | O `oi` do segundo celular chegou com `remoteJid` terminando em `@s.whatsapp.net`? | Nada muda. | Procure em `chaves_key`/`chaves_data` um campo com o número (ex.: `senderPn`, `remoteJidAlt`). Se existir, a Task 11 lê o número **desse campo** em `ler_mensagem`, e o teste `test_texto_simples_vira_recebida` usa o corpo medido. Se não existir, **PARE**: sem número o bot não acha o `Cliente`, e o desenho volta à spec. |
| **G2** | A resposta citando chegou com o texto em `extendedTextMessage.text`? | Nada muda. | Anote a chave onde o texto veio e troque a leitura em `ler_mensagem` (Task 11). |
| **G3** | O envio pela API gerou `messages.upsert` com `fromMe: true`? | Compare o `id` do evento com o `id devolvido` do step 3.4. **Iguais:** o desenho de `ids_do_bot` funciona, siga. **Diferentes:** **PARE** — sem um discriminador, cada resposta do bot o calaria; procure um (`source`, formato do id) e revise a Task 11 antes de implementar. | O eco não existe. `ids_do_bot` vira só proteção; siga sem mudança. |
| **G4** | A foto chegou com `tem_base64: false` e `bytes` pequeno, **e** o QR apareceu no painel depois de "Trocar de celular"? | `base64: false` com bot ligado está certo (Task 7). | **Mídia ainda inline:** a proteção de corpo grande da Task 11 é a única; mantenha. **QR não apareceu:** reverta `"base64": not bot` para `"base64": True` na Task 7 e registre que eventos com mídia continuam grandes. |

Registre também: `data_e` (dict ou list) e a presença de `source`.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-09-16-bot-agendamento-whatsapp-design.md
git commit -m "spec: fatia 0b do bot, medida num numero dedicado

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

**Não siga para a Task 11 com G1 ou G3 em PARE.**

---

### Task 11: A entrada — webhook, fila, silêncio e eco

**Files:**
- Create: `backend/app/services/bot_entrada.py`
- Modify: `backend/app/services/bot.py` (acrescentar `silenciar`)
- Modify: `backend/app/tasks.py`
- Modify: `backend/app/api/v1/views/interno.py`
- Modify: `tests/test_celery.py`
- Create: `tests/test_bot_entrada.py`

**Interfaces:**
- Consumes: `do_jid` (Task 2), `processar`, `_conversa` (Task 6), `trava_da_conversa` (Task 5), `barbearia_id_do_nome` (existente), respostas G1–G3 (Task 10).
- Produces:
  - `EVENTO_MENSAGEM = "messages.upsert"`
  - `Recebida(barbearia_id: str, numero: str, texto: str | None, mensagem_id: str, do_proprio_numero: bool)`
  - `ler_mensagem(corpo) -> Recebida | str` (a string é o motivo do descarte)
  - `receber(corpo, agora: datetime) -> str` — `"ignorado:<motivo>"`, `"enfileirado"`, `"silenciado"`, `"eco"`
  - `enfileirar(lida: Recebida) -> None`
  - `silenciar(barbearia_id: str, numero: str, mensagem_id: str, agora: datetime) -> str` (em `bot.py`)
  - task `app.tasks.tratar_mensagem(barbearia_id, numero, texto, mensagem_id) -> str`

**Antes de começar:** aplique aqui o que a Task 10 respondeu em G1 e G2 — o corpo de `_mensagem` nos testes abaixo deve ser o **medido**, e `ler_mensagem` lê o número e o texto dos campos medidos. O código abaixo assume as respostas SIM.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/test_bot_entrada.py`:

```python
"""POST /api/interno/whatsapp/evento com `messages.upsert`.

Num numero de uso real, 40 de 42 eventos eram de grupo e quase todos com
midia (spec, secao 11). O descarte tem que ser cedo e barato, e o que sobra
tem que chegar ao worker sem o webhook esperar resposta nenhuma.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.db import connections
from django.test import override_settings

from app.services import bot
from app.services.bot_entrada import Recebida, ler_mensagem
from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import Barbearia, ConversaWhatsapp, EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

ROTA = "/api/interno/whatsapp/evento"
SEGREDO = "segredo-do-webhook"
CABECALHO = {"host": "admin.localhost", "x-brutus-cliente": "evolution", "x-marcai-webhook": SEGREDO}
ENFILEIRAR = "app.services.bot_entrada.enfileirar"
NUMERO = "83988887777"


@pytest.fixture(autouse=True)
def _segredo(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SEGREDO", SEGREDO)


def _mensagem(barbearia_id, *, texto="oi", jid="5583988887777@s.whatsapp.net",
              from_me=False, mensagem_id="3A0000000001", citando=False, midia=False):
    if midia:
        message = {"imageMessage": {"caption": ""}}
    elif citando:
        message = {"extendedTextMessage": {"text": texto}}
    else:
        message = {"conversation": texto}
    return {
        "event": "messages.upsert",
        "instance": nome_da_instancia(barbearia_id),
        "data": {"key": {"remoteJid": jid, "fromMe": from_me, "id": mensagem_id}, "message": message},
    }


def _com_bot(barbearia, bot_ativo=True):
    Barbearia.objects.using("owner").filter(id=barbearia.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=barbearia.id, nome=nome_da_instancia(barbearia.id),
        estado=EstadoInstancia.CONECTADO, bot_ativo=bot_ativo,
    )


def _bater(client, corpo):
    return client.post(ROTA, corpo, content_type="application/json", headers=CABECALHO)


def _linha(barbearia):
    with com_barbearia(barbearia.id):
        return ConversaWhatsapp.objects.filter(whatsapp=NUMERO).first()


# ---- leitura pura ----

ID = str(uuid.uuid4())


def test_texto_simples_vira_recebida():
    assert ler_mensagem(_mensagem(ID)) == Recebida(ID, NUMERO, "oi", "3A0000000001", False)


def test_resposta_citando_le_o_texto_do_outro_campo():
    """Quem responde o lembrete segurando a mensagem manda o texto em
    `extendedTextMessage` — ler so' `conversation` ignoraria justamente essas."""
    assert ler_mensagem(_mensagem(ID, texto="1", citando=True)).texto == "1"


def test_midia_chega_sem_texto():
    assert ler_mensagem(_mensagem(ID, midia=True)).texto is None


def test_propria_barbearia_e_marcada():
    assert ler_mensagem(_mensagem(ID, from_me=True)).do_proprio_numero is True


@pytest.mark.parametrize("corpo, motivo", [
    ("nao e dict", "corpo"),
    ({"event": "connection.update"}, "evento"),
    ({**_mensagem(ID), "instance": "outra-coisa"}, "instancia"),
    ({**_mensagem(ID), "data": "x"}, "dados"),
    (_mensagem(ID, jid="120363025246125486@g.us"), "grupo"),
    (_mensagem(ID, jid="207843221540943@lid"), "numero"),
    (_mensagem(ID, mensagem_id=""), "id"),
])
def test_descartes(corpo, motivo):
    assert ler_mensagem(corpo) == motivo


# ---- pela rota ----


def test_texto_com_bot_ligado_vai_para_a_fila(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id))
    assert r.status_code == 200
    assert r.json()["resultado"] == "enfileirado"
    enfileirar.assert_called_once_with(Recebida(str(b.id), NUMERO, "oi", "3A0000000001", False))


def test_bot_desligado_nao_enfileira_nem_grava(client, cenario):
    b = cenario["brutus"]
    _com_bot(b, bot_ativo=False)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id))
    assert r.json()["resultado"] == "ignorado:desligado"
    enfileirar.assert_not_called()
    assert _linha(b) is None


def test_grupo_e_descartado_com_200(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id, jid="120363025246125486@g.us"))
    assert r.status_code == 200
    assert r.json()["resultado"] == "ignorado:grupo"
    enfileirar.assert_not_called()


def test_midia_de_cliente_nao_enfileira(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id, midia=True))
    assert r.json()["resultado"] == "ignorado:sem_texto"
    enfileirar.assert_not_called()


def test_dono_respondendo_pelo_celular_cala_o_bot(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    with patch(ENFILEIRAR) as enfileirar:
        r = _bater(client, _mensagem(b.id, from_me=True, mensagem_id="3A-DIGITADO"))
    assert r.json()["resultado"] == "silenciado"
    enfileirar.assert_not_called()
    assert _linha(b).mudo_ate > datetime.now(timezone.utc) + timedelta(hours=3)


def test_audio_do_dono_tambem_cala(client, cenario):
    """O dono respondeu com audio: ainda e' gente atendendo."""
    b = cenario["brutus"]
    _com_bot(b)
    r = _bater(client, _mensagem(b.id, from_me=True, midia=True))
    assert r.json()["resultado"] == "silenciado"


def test_eco_da_resposta_do_bot_nao_cala(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, ids_do_bot=["3EB0-DO-BOT"],
    )
    r = _bater(client, _mensagem(b.id, from_me=True, mensagem_id="3EB0-DO-BOT"))
    assert r.json()["resultado"] == "eco"
    assert _linha(b).mudo_ate is None


def test_silenciar_com_a_conversa_presa_nao_trava_o_webhook(cenario, monkeypatch):
    b = cenario["brutus"]
    monkeypatch.setattr(bot, "BOT_ESPERA_TRAVA_S", 0.2)
    chave = f"{b.id}:{NUMERO}"
    with connections["owner"].cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [chave])
    try:
        assert bot.silenciar(str(b.id), NUMERO, "x", datetime.now(timezone.utc)) == "ignorado:trava"
    finally:
        with connections["owner"].cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [chave])


def test_evento_de_conexao_continua_no_caminho_de_sempre(client, cenario):
    b = cenario["brutus"]
    _com_bot(b)
    corpo = {"event": "connection.update", "instance": nome_da_instancia(b.id),
             "data": {"state": "close"}}
    with patch("app.api.v1.views.interno.aplicar_evento", return_value="desconectado") as aplicar:
        r = _bater(client, corpo)
    assert r.json()["resultado"] == "desconectado"
    aplicar.assert_called_once()


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=512)
def test_evento_grande_demais_ainda_responde_200(client, cenario):
    """Um 400 aqui faria a Evolution reenviar a mesma foto para sempre."""
    b = cenario["brutus"]
    _com_bot(b)
    corpo = _mensagem(b.id, texto="x" * 4096)
    with patch(ENFILEIRAR):
        r = _bater(client, corpo)
    assert r.status_code == 200


def test_sem_credencial_continua_401(client, cenario):
    b = cenario["brutus"]
    r = client.post(ROTA, _mensagem(b.id), content_type="application/json",
                    headers={**CABECALHO, "x-marcai-webhook": "errado"})
    assert r.status_code == 401
```

Em `tests/test_celery.py`, troque `from app.tasks import lembretes, whatsapp_healthcheck, zelador` por `from app.tasks import lembretes, tratar_mensagem, whatsapp_healthcheck, zelador` e acrescente:

```python
def test_tratar_mensagem_chama_o_bot_e_esta_registrada():
    with patch("app.tasks.processar_mensagem_do_bot", return_value="perguntou") as processar:
        assert tratar_mensagem("b", "83988887777", "oi", "m1") == "perguntou"
    args = processar.call_args.args
    assert args[:4] == ("b", "83988887777", "oi", "m1")
    assert "app.tasks.tratar_mensagem" in celery_app.tasks
```

Run: `docker compose exec -T api pytest tests/test_bot_entrada.py tests/test_celery.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.bot_entrada'`.

- [ ] **Step 2: `silenciar` em `bot.py`**

Em `backend/app/services/bot.py`: acrescente `BOT_ESPERA_TRAVA_S` ao import de `tenant.config`, troque `from django.db import IntegrityError` por `from django.db import IntegrityError, OperationalError`, e no fim do arquivo:

```python
def silenciar(barbearia_id: str, numero: str, mensagem_id: str, agora: datetime) -> str:
    """Alguem da barbearia respondeu pelo celular: o bot fica quieto nessa
    conversa por BOT_MUDO_HORAS.

    Espera a MESMA trava da conversa. O eco de uma resposta do bot pode chegar
    ao webhook antes de `processar` gravar o id dela; esperando a trava, o id
    ja esta gravado quando esta funcao olha, e o bot nao se cala sozinho.

    Uma conversa presa alem do limite nao pode segurar o webhook: devolve
    "ignorado:trava" e segue.
    """
    try:
        with trava_da_conversa(barbearia_id, numero, espera_s=BOT_ESPERA_TRAVA_S):
            with com_barbearia(barbearia_id):
                linha = ConversaWhatsapp.objects.filter(whatsapp=numero).first()
                if linha is not None and mensagem_id in (linha.ids_do_bot or []):
                    return "eco"
                ate = agora + timedelta(hours=BOT_MUDO_HORAS)
                if linha is None:
                    ConversaWhatsapp.objects.create(
                        id=str(uuid.uuid4()), barbearia_id=barbearia_id, whatsapp=numero,
                        mudo_ate=ate, atualizado_em=agora,
                    )
                else:
                    ConversaWhatsapp.objects.filter(id=linha.id).update(mudo_ate=ate)
    except OperationalError:
        logger.warning("[bot] conversa de %s presa demais para silenciar", numero)
        return "ignorado:trava"
    return "silenciado"
```

- [ ] **Step 3: `bot_entrada.py`**

Crie `backend/app/services/bot_entrada.py`:

```python
"""A porta de entrada das mensagens de cliente no webhook.

`ler_mensagem` e' PURA e roda para TODO evento de mensagem. Num numero de uso
real, 40 de 42 eventos eram de grupo, quase todos com midia (spec, secao 11):
o descarte tem que acontecer antes de qualquer consulta ao banco.

O que passa vai para a fila com quatro campos, nao com o corpo inteiro: o
webhook responde em milissegundos, muito antes de a Evolution pensar em
reenviar, e a task fica testavel sem inventar um JSON da Evolution.
"""

from dataclasses import dataclass
from datetime import datetime

from tenant.models import WhatsappInstancia
from tenant.rls import com_barbearia
from tenant.telefone import do_jid

from .bot import silenciar
from .whatsapp_instancias import barbearia_id_do_nome

EVENTO_MENSAGEM = "messages.upsert"


@dataclass(frozen=True)
class Recebida:
    barbearia_id: str
    numero: str
    texto: str | None
    mensagem_id: str
    do_proprio_numero: bool


def ler_mensagem(corpo) -> "Recebida | str":
    if not isinstance(corpo, dict):
        return "corpo"
    if str(corpo.get("event") or "").lower() != EVENTO_MENSAGEM:
        return "evento"
    nome = corpo.get("instance")
    barbearia_id = barbearia_id_do_nome(nome) if isinstance(nome, str) else None
    if barbearia_id is None:
        return "instancia"
    dados = corpo.get("data")
    chave = dados.get("key") if isinstance(dados, dict) else None
    if not isinstance(chave, dict):
        return "dados"
    jid = chave.get("remoteJid")
    if isinstance(jid, str) and jid.endswith("@g.us"):
        return "grupo"
    numero = do_jid(jid)
    if numero is None:
        return "numero"
    mensagem_id = chave.get("id")
    if not isinstance(mensagem_id, str) or not mensagem_id:
        return "id"
    mensagem = dados.get("message") if isinstance(dados.get("message"), dict) else {}
    texto = mensagem.get("conversation")
    if not isinstance(texto, str) or not texto.strip():
        # Resposta CITANDO outra mensagem — como quem responde o lembrete.
        citando = mensagem.get("extendedTextMessage")
        texto = citando.get("text") if isinstance(citando, dict) else None
    if not isinstance(texto, str) or not texto.strip():
        texto = None
    return Recebida(barbearia_id, numero, texto, mensagem_id, chave.get("fromMe") is True)


def receber(corpo, agora: datetime) -> str:
    lida = ler_mensagem(corpo)
    if isinstance(lida, str):
        return f"ignorado:{lida}"
    with com_barbearia(lida.barbearia_id):
        instancia = WhatsappInstancia.objects.filter(barbearia_id=lida.barbearia_id).first()
    if instancia is None or not instancia.bot_ativo:
        return "ignorado:desligado"
    # `fromMe` ANTES de exigir texto: o dono respondendo com audio ainda e'
    # gente atendendo, e o bot tem que calar do mesmo jeito.
    if lida.do_proprio_numero:
        return silenciar(lida.barbearia_id, lida.numero, lida.mensagem_id, agora)
    if lida.texto is None:
        return "ignorado:sem_texto"
    enfileirar(lida)
    return "enfileirado"


def enfileirar(lida: Recebida) -> None:
    # Import tardio: `app.tasks` importa servicos, e este e' um deles.
    from app.tasks import tratar_mensagem

    tratar_mensagem.delay(lida.barbearia_id, lida.numero, lida.texto, lida.mensagem_id)
```

- [ ] **Step 4: A task**

Em `backend/app/tasks.py`, acrescente aos imports `from app.services.bot import processar as processar_mensagem_do_bot` e, no fim:

```python
@shared_task(ignore_result=True)
def tratar_mensagem(barbearia_id: str, numero: str, texto: str, mensagem_id: str) -> str:
    """Uma mensagem de cliente para o bot.

    NAO RETENTA, de proposito. Retentar rodaria a maquina de novo, e no passo
    de confirmar isso e' uma segunda tentativa de marcar: o banco recusaria a
    sobreposicao, e o cliente leria "nao deu certo" depois de ter dado. Mesma
    escolha de `MensagemNaoEnviada`: nada aqui e' reenviado depois.
    """
    return processar_mensagem_do_bot(
        barbearia_id, numero, texto, mensagem_id, datetime.now(timezone.utc),
    )
```

- [ ] **Step 5: O desvio na view**

Em `backend/app/api/v1/views/interno.py`:

Imports, trocando os atuais de serviço:

```python
from datetime import datetime, timezone

from django.core.exceptions import RequestDataTooBig

from app.services.bot_entrada import EVENTO_MENSAGEM, receber
from app.services.whatsapp_eventos import aplicar_evento
```

Troque as duas linhas finais de `post`

```python
        resultado = aplicar_evento(request.data if isinstance(request.data, dict) else {})
        return Response({"ok": True, "resultado": resultado})
```

por

```python
        try:
            corpo = request.data
        except RequestDataTooBig:
            # 200 e nao 400: a Evolution reenvia o que nao foi aceito, e uma
            # foto grande demais voltaria para sempre.
            logger.warning("[webhook] evento acima do limite de corpo: descartado")
            return Response({"ok": True, "resultado": "ignorado:grande"})
        corpo = corpo if isinstance(corpo, dict) else {}

        # Mensagem de cliente vai para o bot; conexao e QR seguem o caminho de
        # sempre. As duas coisas chegam pela mesma rota porque a Evolution so'
        # tem UM webhook por instancia.
        if str(corpo.get("event") or "").lower() == EVENTO_MENSAGEM:
            resultado = receber(corpo, datetime.now(timezone.utc))
        else:
            resultado = aplicar_evento(corpo)
        return Response({"ok": True, "resultado": resultado})
```

Acrescente ao docstring da classe, depois do parágrafo "Responde 200 para quase tudo": `Com o bot ligado chegam tambem as mensagens de cliente (messages.upsert): o descarte e a fila moram em bot_entrada.py.`

- [ ] **Step 6: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_bot_entrada.py tests/test_celery.py tests/test_whatsapp_webhook.py -q`
Expected: PASS.

Se `test_evento_grande_demais_ainda_responde_200` falhar com `400`, o limite estourou num ponto antes de `request.data` (um middleware leu `request.body`). Ache quem leu com `grep -rn "request.body" backend/tenant backend/app` e mova o `try/except RequestDataTooBig` para cobrir esse ponto — a exigência é o `200`, não o lugar do `try`.

- [ ] **Step 7: Suíte inteira e commit**

Run: `docker compose exec -T api pytest -q`
Expected: tudo passando.

```bash
git add backend/app/services/bot_entrada.py backend/app/services/bot.py backend/app/tasks.py backend/app/api/v1/views/interno.py tests/test_bot_entrada.py tests/test_celery.py
git commit -m "bot: a entrada pelo webhook, com descarte cedo e fila

Grupo, midia e evento de instancia que nao e' nossa saem antes de qualquer
consulta: num numero real, 40 de 42 eventos eram de grupo. O dono respondendo
pelo celular cala o bot; o eco da propria resposta do bot, nao — silenciar
espera a trava da conversa para o id ja estar gravado quando olha.

A task nao retenta: retentar no passo de confirmar tentaria marcar de novo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: O lembrete respondido pelo bot

**Pré-requisito:** a decisão 4 de "Onde este plano diverge da spec" confirmada com o José ("Não vou conseguir ir" avisa o barbeiro e não cancela).

**Files:**
- Modify: `backend/app/services/bot.py` (acrescentar `enviar_lembrete_pelo_bot` e `_registrar_lembrete`)
- Modify: `backend/app/services/lembrete.py`
- Create: `tests/test_bot_lembrete.py`

**Interfaces:**
- Consumes: `processar`, `silenciar`, `_conversa`, `_estado_de` (Tasks 6 e 11); `msg_lembrete_com_opcoes`, `msg_bot_pergunta_do_lembrete` (Task 3); `expirou` (Task 4).
- Produces: `enviar_lembrete_pelo_bot(barbearia_id: str, instancia_nome: str, numero: str, codigo: str, lembrete: str, agora: datetime) -> None`.

O lembrete não ganha máquina: ganha duas opções e deixa a conversa em `AGUARDANDO_LEMBRETE`. Duas regras, com teste cada: **conversa em andamento não é atropelada** (o lembrete sai sem opções e o estado fica), e **o id do lembrete é guardado** (senão o eco dele calaria o bot 4 horas, justamente quando o cliente vai responder).

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/test_bot_lembrete.py`:

```python
"""O lembrete que ja existia, respondido pelo bot."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import bot
from app.services.lembrete import enviar_pendentes
from app.services.whatsapp_instancias import nome_da_instancia
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    Cliente,
    ConversaWhatsapp,
    EstadoInstancia,
    Servico,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia

pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)

NUMERO = "83988887777"
ENVIAR = "app.services.bot._enviar"


def _cenario(cenario, *, bot_ativo=True):
    b = cenario["brutus"]
    Barbearia.objects.using("owner").filter(id=b.id).update(plano="COM_ZAP")
    WhatsappInstancia.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome=nome_da_instancia(b.id),
        estado=EstadoInstancia.CONECTADO, bot_ativo=bot_ativo,
    )
    pedro = Barbeiro.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Pedro",
        whatsapp=f"1199{uuid.uuid4().int % 10**7:07d}", papel="BARBEIRO", ativo=True,
    )
    servico = Servico.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Corte",
        duracao_minima_min=15, duracao_sugerida_min=30,
    )
    cliente = Cliente.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, nome="Maria Souza", whatsapp=NUMERO,
    )
    agora = datetime.now(timezone.utc)
    inicio = agora + timedelta(minutes=30)
    ag = Agendamento.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, codigo=uuid.uuid4().hex[:10],
        barbeiro_id=pedro.id, cliente_id=cliente.id, servico_id=servico.id,
        servico_nome="Corte", inicio=inicio, fim=inicio + timedelta(minutes=30),
        duracao_min=30, status="CONFIRMADO",
    )
    return b, ag, agora


def _linha(b):
    with com_barbearia(b.id):
        return ConversaWhatsapp.objects.filter(whatsapp=NUMERO).first()


def test_com_bot_o_lembrete_sai_com_opcoes_e_para_a_conversa(cenario):
    b, ag, agora = _cenario(cenario)
    with patch(ENVIAR, return_value="3EB0-LEMBRETE") as enviar:
        assert enviar_pendentes(agora) == 1
    instancia, numero, texto = enviar.call_args.args
    assert instancia == nome_da_instancia(b.id)
    assert numero == NUMERO
    assert texto.startswith("Lembrete:")
    assert texto.endswith("1 - Confirmar\n2 - Não vou conseguir ir")
    linha = _linha(b)
    assert linha.estado == "AGUARDANDO_LEMBRETE"
    assert [o["id"] for o in linha.opcoes] == [f"confirmar:{ag.codigo}", f"nao_vou:{ag.codigo}"]
    assert linha.ids_do_bot == ["3EB0-LEMBRETE"]


def test_responder_1_confirma(cenario):
    b, _, agora = _cenario(cenario)
    with patch(ENVIAR, return_value="3EB0-LEMBRETE"):
        enviar_pendentes(agora)
    respostas = []
    with patch(ENVIAR, side_effect=lambda i, n, t: respostas.append(t) or "3EB0-R"), patch(
        "app.services.bot.enviar_a_equipe"
    ):
        desfecho = bot.processar(str(b.id), NUMERO, "1", "3A-RESPOSTA", agora + timedelta(minutes=5))
    assert desfecho == "lembrete_confirmado"
    assert respostas == ["Combinado, te esperamos!"]


def test_o_eco_do_lembrete_nao_cala_o_bot(cenario):
    b, _, agora = _cenario(cenario)
    with patch(ENVIAR, return_value="3EB0-LEMBRETE"):
        enviar_pendentes(agora)
    assert bot.silenciar(str(b.id), NUMERO, "3EB0-LEMBRETE", agora) == "eco"
    assert _linha(b).mudo_ate is None


def test_conversa_em_andamento_recebe_o_lembrete_sem_opcoes(cenario):
    """Quem esta escolhendo horario agora nao pode ter a conversa trocada
    por baixo: o proximo "1" dele confirmaria o lembrete em vez da hora."""
    b, _, agora = _cenario(cenario)
    ConversaWhatsapp.objects.using("owner").create(
        id=str(uuid.uuid4()), barbearia_id=b.id, whatsapp=NUMERO, estado="HORA",
        opcoes=[{"id": "outro_dia", "rotulo": "Outro dia"}],
        atualizado_em=agora - timedelta(minutes=2),
    )
    with patch(ENVIAR, return_value="3EB0-LEMBRETE") as enviar:
        enviar_pendentes(agora)
    assert "1 - Confirmar" not in enviar.call_args.args[2]
    linha = _linha(b)
    assert linha.estado == "HORA"
    assert linha.ids_do_bot == ["3EB0-LEMBRETE"]


def test_sem_bot_o_lembrete_segue_o_caminho_de_sempre(cenario):
    b, _, agora = _cenario(cenario, bot_ativo=False)
    with patch("app.services.lembrete.enviar_ao_cliente") as ao_cliente, patch(ENVIAR) as enviar:
        assert enviar_pendentes(agora) == 1
    ao_cliente.assert_called_once()
    enviar.assert_not_called()
    assert _linha(b) is None
```

Run: `docker compose exec -T api pytest tests/test_bot_lembrete.py -q`
Expected: FAIL (o lembrete sai por `enviar_ao_cliente` e nenhuma conversa é criada).

- [ ] **Step 2: `bot.py`**

Acrescente `msg_bot_pergunta_do_lembrete` e `msg_lembrete_com_opcoes` ao import de `.mensagens` e, no fim do arquivo:

```python
def enviar_lembrete_pelo_bot(
    barbearia_id: str, instancia_nome: str, numero: str, codigo: str,
    lembrete: str, agora: datetime,
) -> None:
    """O lembrete de sempre, com as respostas que o bot entende.

    Dentro da trava da conversa, pelas mesmas duas razoes de `silenciar`: nao
    atropelar uma conversa que acontece agora, e gravar o id do lembrete antes
    de o eco dele chegar — senao o bot se calaria justo quando o cliente vai
    responder.

    Conversa ocupada (escolhendo horario, ou muda porque alguem da barbearia
    esta falando) recebe o lembrete SEM opcoes, e o estado dela fica.
    """
    enviado = False
    try:
        with trava_da_conversa(barbearia_id, numero, espera_s=BOT_ESPERA_TRAVA_S):
            linha = _conversa(barbearia_id, numero)
            ocupada = linha is not None and (
                (linha.mudo_ate is not None and como_utc(linha.mudo_ate) > agora)
                or (bool(linha.opcoes) and not c.expirou(_estado_de(linha), agora))
            )
            texto = lembrete if ocupada else msg_lembrete_com_opcoes(lembrete=lembrete)
            mensagem_id = _enviar(instancia_nome, numero, texto)
            enviado = True
            _registrar_lembrete(
                barbearia_id, numero, linha, mensagem_id, None if ocupada else codigo, agora,
            )
    except OperationalError:
        if enviado:
            logger.error("[bot] lembrete para %s saiu, mas a conversa nao foi gravada", numero)
            return
        logger.warning("[bot] conversa de %s presa: lembrete sai sem opcoes", numero)
        _enviar(instancia_nome, numero, lembrete)


def _registrar_lembrete(barbearia_id, numero, linha, mensagem_id, codigo, agora) -> None:
    ids = list(linha.ids_do_bot or []) if linha is not None else []
    if mensagem_id:
        ids = (ids + [mensagem_id])[-BOT_IDS_GUARDADOS:]
    campos = {"ids_do_bot": ids}
    if codigo is not None:
        campos.update(
            estado=c.AGUARDANDO_LEMBRETE,
            opcoes=[
                {"id": f"confirmar:{codigo}", "rotulo": "Confirmar"},
                {"id": f"nao_vou:{codigo}", "rotulo": "Não vou conseguir ir"},
            ],
            rascunho={}, tentativas=0,
            pergunta=msg_bot_pergunta_do_lembrete(),
            atualizado_em=agora,
        )
    with com_barbearia(barbearia_id):
        if linha is None:
            ConversaWhatsapp.objects.create(
                id=str(uuid.uuid4()), barbearia_id=barbearia_id, whatsapp=numero, **campos,
            )
        else:
            ConversaWhatsapp.objects.filter(id=linha.id).update(**campos)
```

- [ ] **Step 3: `lembrete.py`**

Troque o import de modelos por:

```python
from tenant.models import (
    Agendamento,
    Barbearia,
    EstadoInstancia,
    PlanoBarbearia,
    TipoMensagem,
    WhatsappInstancia,
)
```

Troque o laço de `enviar_pendentes` — de `for b in Barbearia.objects.filter(ativo=True):` até `enviados += 1`, inclusive — por:

```python
    for b in Barbearia.objects.filter(ativo=True):
        with com_barbearia(b.id):
            pendentes = list(
                Agendamento.objects.filter(
                    status="CONFIRMADO", lembrete_enviado_em__isnull=True,
                    inicio__gt=agora, inicio__lte=limite,
                ).select_related("barbeiro", "cliente")
            )
            instancia = WhatsappInstancia.objects.filter(barbearia_id=b.id).first()

        # Pelo bot so' com tudo de pe: plano com zap, bot ligado e conectado.
        # Qualquer outro caso segue `enviar_ao_cliente`, que ja sabe registrar
        # a "nao enviada" quando o numero esta fora do ar.
        pelo_bot = (
            b.plano == PlanoBarbearia.COM_ZAP
            and instancia is not None
            and instancia.bot_ativo
            and instancia.estado == EstadoInstancia.CONECTADO
        )

        for a in pendentes:
            # MARCA antes de mandar, numa transacao PROPRIA por agendamento:
            # se o processo morrer no meio do laco, so' os que ja' commitaram
            # ficam marcados — exatamente os que ja' sairam.
            with com_barbearia(b.id):
                Agendamento.objects.filter(id=a.id).update(lembrete_enviado_em=timezone.now())
            texto = msg_lembrete(
                servico_nome=a.servico_nome, barbeiro_nome=a.barbeiro.nome,
                inicio=a.inicio, endereco=b.endereco,
            )
            if pelo_bot:
                # Import tardio: bot -> agendamentos -> lembrete.
                from .bot import enviar_lembrete_pelo_bot

                enviar_lembrete_pelo_bot(
                    str(b.id), instancia.nome, a.cliente.whatsapp, a.codigo, texto, agora,
                )
            else:
                enviar_ao_cliente(
                    b, a.cliente.whatsapp, texto,
                    tipo=TipoMensagem.LEMBRETE, cliente_nome=a.cliente.nome,
                )
            enviados += 1
```

- [ ] **Step 4: Rodar e ver passar**

Run: `docker compose exec -T api pytest tests/test_bot_lembrete.py tests/test_cron_lembretes.py -q`
Expected: PASS.

- [ ] **Step 5: Suíte inteira e commit**

Run: `docker compose exec -T api pytest -q`
Expected: tudo passando.

```bash
git add backend/app/services/bot.py backend/app/services/lembrete.py tests/test_bot_lembrete.py
git commit -m "bot: o lembrete aceita resposta

1 confirma; 2 avisa o barbeiro que o cliente nao vem, sem cancelar — o
lembrete sai 60 min antes e o cliente so' cancela com mais de 60. Conversa
em andamento recebe o lembrete sem opcoes, e o id dele e' guardado para o
eco nao calar o bot.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Ponta a ponta local, com o número dedicado

**Precisa de:** o chip dedicado da Task 10 conectado a `teste-bot`, e o segundo celular.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-bot-agendamento-whatsapp-design.md` (seção nova `## 12. Ponta a ponta local`)

**Interfaces:**
- Consumes: tudo das tarefas 1–12.

Teste nenhum prova que o WhatsApp manda o que o bot espera. Esta tarefa prova, e só ela.

- [ ] **Step 1: Subir com o código novo**

```bash
docker compose exec -T api python manage.py migrate --database=owner
docker compose restart api worker beat
```

- [ ] **Step 2: Percorrer, anotando o resultado de cada item**

1. **Ligar.** Painel de `teste-bot` como dono → "Atendimento automático" → Ligar → confirmar. Esperado: "Ligado". Conferir a assinatura:
   ```bash
   INST=marcai-COLE-AQUI-O-UUID docker compose exec -T -e INST api python -c "import os,requests;u=os.environ['EVOLUTION_API_URL'];print(requests.get(f\"{u}/webhook/find/{os.environ['INST']}\",headers={'apikey':os.environ['EVOLUTION_API_KEY']},timeout=10).json().get('events'))"
   ```
   Esperado: a lista inclui `MESSAGES_UPSERT`.
2. **Menu.** Segundo celular manda `oi`. Esperado: menu em poucos segundos.
3. **Marcar.** Seguir até confirmar. Esperado: "Fechou, ..." com link; o horário aparece na agenda do painel; o barbeiro recebe "Novo horário" pelo número central.
4. **Menu de quem tem horário.** `oi` de novo. Esperado: "Você tem: ..." e "2 - Cancelar esse".
5. **Cancelar.** `2` → `1`. Esperado: "... cancelado" e o horário some da agenda.
6. **Resposta citando.** Responder a uma pergunta do bot segurando a mensagem → `1`. Esperado: o bot entende como `1`.
7. **Dono no celular.** Do chip, digitar qualquer coisa para o segundo celular. Depois, `oi` do segundo celular. Esperado: **nenhuma** resposta do bot.
8. **Eco.** Numa conversa nova (outro número, ou depois de o mudo vencer): as respostas do bot **não** calam o bot — a conversa segue até o fim.
9. **Zero.** `0`. Esperado: "já chamei alguém"; o dono recebe o aviso pelo número central.
10. **Ignorados.** Mandar foto e áudio ao chip, e uma mensagem num grupo em que o chip esteja. Esperado: nenhuma resposta. `docker compose logs --since 2m worker | grep tratar_mensagem` sem execução para esses.
11. **Lembrete.** Marcar pelo bot um horário 50 minutos à frente e rodar:
    ```bash
    docker compose exec -T api python manage.py shell -c "from app.tasks import lembretes; print(lembretes())"
    ```
    Esperado: lembrete com "1 - Confirmar / 2 - Não vou conseguir ir". `1` → "Combinado". Repetir com outro horário e `2` → o barbeiro recebe "Avisou que não vem".
12. **Desligar.** Painel → Desligado. `oi` do segundo celular. Esperado: nenhuma resposta; a assinatura (comando do item 1) volta a só dois eventos.

- [ ] **Step 3: Registrar e commitar**

Acrescente `## 12. Ponta a ponta local` à spec com a data, a lista acima e o resultado de cada item. Qualquer item que falhou vira um bug com teste antes de seguir para produção.

```bash
git add docs/superpowers/specs/2026-09-16-bot-agendamento-whatsapp-design.md
git commit -m "spec: ponta a ponta local do bot

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

**Produção é passo do José:** deploy no Coolify, ligar o bot numa barbearia de teste, e só depois numa real.

---

## Cobertura da spec

| Spec | Onde |
|---|---|
| §2 Menu numerado | Task 4 (`numero_escolhido`), Task 3 (textos) |
| §2 Bot cala quando a barbearia responde | Task 11 (`silenciar`, `fromMe`), Task 6 (`mudo`) |
| §2 Escopo: marcar, cancelar, lembrete | Tasks 6, 12 |
| §2 Interruptor desligado por padrão | Task 1 (`default=False`), Task 7, Task 9 |
| §2 Não guarda conversa | Task 1 (uma linha por número, sem texto), Task 8 (poda) |
| §3 Menu varia pelo que o número tem | Task 6 (`_opcoes_do_passo` MENU) |
| §3 Pula serviço/barbeiro únicos | Task 4 (`seguir_sozinho`), Task 6 |
| §3 Dia: até 5 com vaga + outros dias; Hora: até 6 + outro dia | Task 6; "Mais tarde" acrescentado para alcançar o resto do dia |
| §3 Nome só para número sem `Cliente` | Task 4, Task 6 (`test_cliente_conhecido...`) |
| §3 Regra 1: fora da lista repete, terceira oferece o 0 | Task 4, Task 6 |
| §3 Regra 2: conversa velha recomeça | Task 4 (`expirou`) |
| §3 Regra 3: opção guardada não é autoridade | Task 6 (`marcar` rechecagem; `_agendamento_do_numero`) |
| §3 Regra 4: nunca sugere cancelar | Task 3 (menu mostra, não pergunta) |
| §4 Lembrete com opções | Task 12 (com a divergência 4) |
| §5 `bot_ativo` em `WhatsappInstancia` | Task 1 |
| §5 `ConversaWhatsapp` + RLS | Task 1 |
| §6 Descartes na view | Task 11 |
| §6 Fila, 4 campos | Task 11 |
| §6 Serialização por número | Task 5 (trava consultiva, divergência 2) |
| §6 Task não retenta | Task 11 |
| §6 Dedupe | Task 6 (`ultima_mensagem_id`) |
| §6 Cliente pela instância, dono pelo central | Task 6 |
| §7 `botAtivo` em `ver()`, rota só do dono | Task 7 |
| §7 Webhook antes de gravar | Task 7 |
| §8/§11 Medições pendentes | Task 10 |
| §9 Todos os casos caros da tabela de testes | Tasks 6, 11 |
| §11 Volume e mídia | Task 7 (`base64`), Task 11 (corpo grande → 200) |
