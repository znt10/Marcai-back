# Número da equipe separado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Com `WHATSAPP_EQUIPE_PELA_EVOLUTION` ligada, tudo o que vai para a equipe (menos o convite) sai pela Evolution e a lista refeita volta a ser apagada, mesmo com `WHATSAPP_PROVEDOR=meta`; o cliente continua pela Meta.

**Architecture:** Uma chave lida a cada chamada em `whatsapp.py`. `_enviar_aceita` ganha um parâmetro que diz se a Meta pode ser usada; os envios de equipe passam "não" quando a chave está ligada, e `apagar_para_todos` deixa de recusar. O convite ganha uma função própria que mantém o caminho de hoje (Meta quando ligada).

**Tech Stack:** Django 5 + DRF, pytest (`docker compose run --rm api pytest -q`), `unittest.mock.patch` sobre `requests`.

**Spec:** `docs/superpowers/specs/2026-11-03-numero-da-equipe-design.md`

## Global Constraints

- Nome da variável: `WHATSAPP_EQUIPE_PELA_EVOLUTION`. Ausente ⇒ comportamento de hoje, linha por linha.
- Instância usada: a de `EVOLUTION_INSTANCE` (`whatsapp._config()["instancia"]`). Nenhuma variável nova de instância ou de número.
- Envio ao cliente (`enviar_ao_cliente`, `enviar_pelo_central`) não muda.
- Convite (criação de barbearia, reemissão do convite do dono, convite e reenvio de barbeiro) continua pela Meta quando ela está ligada.
- Falha da Evolution não cai para a Meta.
- Nada no front.
- Branch nova a partir da main com `--no-track` (memória do projeto: o Sync do VS Code já empurrou branch para a main).

## Review Focus

1. **Valor da chave escrito de outro jeito no Coolify** (`true`, `TRUE`, ` 1 `): quem liga espera que funcione; `""`, `0`, `false` devem deixar desligada. → teste em Task 1.
2. **Chave ligada sem `EVOLUTION_API_URL`** (desenvolvimento, ou esquecimento em produção): a equipe não pode cair na Meta por acidente; fica no log, como a Evolution sem URL já faz. → teste em Task 1.
3. **Variável não chega ao contêiner** porque o compose lista as variáveis uma a uma: ligar no Coolify e nada mudar. → Task 1, passo de compose.
4. **Lista refeita com a chave ligada**: a Evolution devolve jid, a lista é guardada e a próxima mudança apaga a anterior pela Evolution. → teste em Task 1.
5. **Convite de barbeiro novo com a chave ligada** saindo pelo chip (o padrão de risco que a spec quer evitar). → teste em Task 2.

---

### Task 0: Branch

- [ ] **Step 1:** `git fetch origin && git switch -c numero-da-equipe --no-track origin/main`
- [ ] **Step 2:** `git add docs/superpowers/specs/2026-11-03-numero-da-equipe-design.md docs/superpowers/plans/2026-11-03-numero-da-equipe.md && git commit -m "Design e plano do número da equipe"` (com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`)

### Task 1: A chave e o roteamento da equipe

**Files:**
- Modify: `backend/app/services/whatsapp.py` (`enviar_a_equipe`, `enviar_a_equipe_aceita`, `_enviar_aceita`, `apagar_para_todos`; função nova perto de `_config`)
- Modify: `docker-compose.yml` (os dois blocos que têm `WHATSAPP_PROVEDOR`), `docker-compose.prod.yml`, `docker-compose.preview.yml`, `.env.example` (ao lado de `WHATSAPP_PROVEDOR`, com comentário de uma linha)
- Test: `tests/test_whatsapp_equipe.py` (novo)

**Interfaces:**
- Produces: `whatsapp.equipe_pela_evolution() -> bool`; `_enviar_aceita(instancia, whatsapp_digitos, mensagem, *, digitando_ms=None, pela_meta: bool | None = None) -> Aceita | None` — `None` significa "decide pela regra de hoje" (`whatsapp_meta.ligado()`), `False` força a Evolution.

- [ ] **Step 1: Write the failing tests** em `tests/test_whatsapp_equipe.py`. Fixture autouse com a Meta ligada (mesmas variáveis do `_meta_ligada` de `test_whatsapp_meta.py`) **e** `EVOLUTION_API_URL=http://evolution:8080`, `EVOLUTION_API_KEY=chave`, `EVOLUTION_INSTANCE=central`. Patch em `whatsapp.requests` (Evolution) e `whatsapp_meta.requests` (Meta) separados, para saber quem foi chamado.

```python
@pytest.mark.parametrize("valor", ["1", "true", "TRUE", " 1 "])
def test_chave_ligada_reconhece(monkeypatch, valor):
    monkeypatch.setenv("WHATSAPP_EQUIPE_PELA_EVOLUTION", valor)
    assert whatsapp.equipe_pela_evolution() is True

@pytest.mark.parametrize("valor", ["", "0", "false"])
def test_chave_desligada(monkeypatch, valor): ...  # is False; e também com delenv

def test_sem_chave_equipe_vai_pela_meta(): ...
    # enviar_a_equipe_aceita → meta post chamado 1x, evolution post 0x

def test_com_chave_equipe_vai_pela_evolution(monkeypatch): ...
    # enviar_a_equipe e enviar_a_equipe_aceita → evolution post em
    # ".../message/sendText/central", meta post 0x; aceita traz o jid da resposta

def test_com_chave_cliente_continua_pela_meta(monkeypatch): ...  # barbearia montada como em test_envio_por_plano.py (`_para_o_cliente`)
    # enviar_ao_cliente e enviar_pelo_central → meta post 1x cada, evolution 0x

def test_com_chave_apagar_vai_pela_evolution(monkeypatch): ...
    # apagar_para_todos("jid", "ID") → True; requests.delete em
    # ".../chat/deleteMessageForEveryone/central"

def test_sem_chave_apagar_continua_recusando(): ...  # False, delete 0x

def test_com_chave_sem_evolution_url_nao_cai_na_meta(monkeypatch, caplog): ...
    # delenv EVOLUTION_API_URL; enviar_a_equipe_aceita → None, meta post 0x,
    # log "sem EVOLUTION_API_URL"

def test_com_chave_falha_da_evolution_nao_cai_na_meta(monkeypatch): ...
    # evolution post devolve ok=False → None, meta post 0x
```

Mais um, de ponta, em `tests/test_lista_do_dia.py` (reaproveita a fixture `cenario` e o jeito do `_refazer` de lá, mas **sem** patch em `apagar_para_todos`; patch só em `requests`):

```python
def test_com_chave_e_meta_a_lista_refeita_apaga_a_anterior_pela_evolution(cenario, monkeypatch): ...
    # Meta ligada + chave + Evolution configurada; lista anterior guardada com
    # jid/id; refazer → requests.delete em deleteMessageForEveryone com
    # {"id": "ID-ANTIGA", "remoteJid": "jid-antiga", "fromMe": True};
    # a nova ListaDoDiaEnviada fica com o jid devolvido pela Evolution
```

- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_whatsapp_equipe.py tests/test_lista_do_dia.py` — Expected: FAIL (`equipe_pela_evolution` não existe).

- [ ] **Step 3: Implement.** `equipe_pela_evolution()` lê a variável a cada chamada, `strip().lower() in {"1", "true"}`. `_enviar_aceita` usa `pela_meta if pela_meta is not None else whatsapp_meta.ligado()` no desvio para a Meta. `enviar_a_equipe` e `enviar_a_equipe_aceita` passam `pela_meta=False` quando a chave está ligada (e `None` quando não). Em `enviar_a_equipe` isso exige trocar o `_enviar(...)` por `_enviar_aceita(...)` ou dar a `_enviar` o mesmo parâmetro — escolha do implementador. `apagar_para_todos` só recusa pela Meta quando `whatsapp_meta.ligado() and not equipe_pela_evolution()`. Atualizar as docstrings que dizem "Pela Meta devolve False sempre". Compose/.env.example: `WHATSAPP_EQUIPE_PELA_EVOLUTION: ${WHATSAPP_EQUIPE_PELA_EVOLUTION:-}`.

- [ ] **Step 4:** `docker compose run --rm api pytest -q` — Expected: tudo passa, inclusive `test_whatsapp_meta.py` sem mudança.

- [ ] **Step 5: Commit** — `git commit -m "Equipe pela Evolution com WHATSAPP_EQUIPE_PELA_EVOLUTION"` (+ Co-Authored-By).

### Task 2: O convite fica na Meta

**Files:**
- Modify: `backend/app/services/whatsapp.py` (função nova ao lado de `enviar_a_equipe_da`)
- Modify: `backend/app/api/v1/views/admin_barbearias.py` (as duas chamadas com `msg_convite`, ~linhas 52 e 104), `backend/app/api/v1/views/equipe.py` (as duas chamadas com `msg_convite`, ~linhas 62 e 149). As outras chamadas de `enviar_a_equipe_da` nesses arquivos, se houver, não mudam.
- Modify: `tests/test_admin_barbearias.py`, `tests/test_equipe.py` — os `patch("...views.<modulo>.enviar_a_equipe_da")` que cobrem convite passam a mirar `enviar_convite`.
- Test: `tests/test_whatsapp_equipe.py`

**Interfaces:**
- Consumes: `_enviar_aceita(..., pela_meta=None)` da Task 1.
- Produces: `whatsapp.enviar_convite(whatsapp_digitos: str, mensagem: str) -> None` — sai pela regra de hoje (Meta quando ligada, senão Evolution na instância central), ignorando a chave. Nunca levanta.

- [ ] **Step 1: Write the failing tests**

```python
def test_com_chave_convite_vai_pela_meta(monkeypatch): ...
    # chave ligada; enviar_convite → meta post 1x, evolution 0x

def test_sem_meta_convite_vai_pela_evolution(monkeypatch): ...
    # delenv WHATSAPP_PROVEDOR; enviar_convite → evolution post em sendText/central

def test_convite_de_barbeiro_com_chave_sai_pela_meta(client, ..., monkeypatch): ...
    # ponta: POST do convite em views/equipe (mesmo setup do teste de convite
    # que já existe em test_equipe.py), chave ligada → meta post 1x com o
    # número do barbeiro, evolution 0x
```

- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_whatsapp_equipe.py` — Expected: FAIL (`enviar_convite` não existe).
- [ ] **Step 3: Implement** `enviar_convite` e troque as quatro chamadas de convite. Docstring: por que o convite não vai pelo chip (primeira mensagem para quem não conhece o número).
- [ ] **Step 4:** `docker compose run --rm api pytest -q` — Expected: tudo passa.
- [ ] **Step 5: Commit** — `git commit -m "Convite continua pela Meta com a equipe na Evolution"` (+ Co-Authored-By).

### Task 3: PR

- [ ] **Step 1:** `git push -u origin numero-da-equipe`
- [ ] **Step 2:** `gh pr create` com corpo: o porquê (custo da lista refeita pela Meta e a lista que não some), o que liga e o que não muda, e os quatro passos de "Para ligar em produção" da spec. Termina com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- [ ] **Step 3:** Esperar o CI verde (`gh pr checks`). Não fazer merge: é do José.
