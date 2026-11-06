# Lembrete por toque — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O cliente toca em "Quero o lembrete no WhatsApp", manda a mensagem pronta ao número central, e só então recebe confirmação (grátis, dentro das 24h) e lembrete; sem toque, o site não manda nada ao cliente.

**Architecture:** Um módulo novo no back, `services/lembrete_por_toque.py`, concentra a chave (`ligado()`), o número central, o link `wa.me`, a leitura do código no texto e o registro do pedido. O webhook da Meta chama esse módulo; os envios (marcar, cron, cancelar) consultam `ligado()`. O front ganha o botão na tela de agendado, com o número central vindo de `GET /api/barbearia`.

**Tech Stack:** Back: Django 5 + DRF, pytest (`docker compose run --rm api pytest -q`). Front: Next.js (App Router), vitest (`npm test`), `npx tsc --noEmit`, `npm run lint`.

**Spec:** `docs/superpowers/specs/2026-11-03-lembrete-por-toque-design.md` (Marcai-back)

## Global Constraints

- **A chave é `lembrete_por_toque.ligado()`**, que vale `whatsapp_meta.ligado()` E `WHATSAPP_CENTRAL_NUMERO` preenchido. Com ela desligada, todo envio é o de hoje, linha por linha. Isso deixa o José fazer o deploy dos dois repos e só depois ligar.
- `WHATSAPP_CENTRAL_NUMERO`: dígitos nacionais (ex.: `83988982852`). O `wa.me` leva `55` na frente.
- O texto pronto da mensagem é `Quero o lembrete do meu horário na {nome}. Código: {codigo}`, igual no back e no front.
- O código do agendamento tem 10 caracteres do alfabeto `23456789abcdefghjkmnpqrstuvwxyz` (`agendamentos._ALFABETO_CODIGO`).
- O aceite vale por agendamento. Não passa de um agendamento para outro do mesmo cliente.
- **Ligado:**
  - Site: não manda confirmação.
  - Painel: manda a confirmação de sempre com uma linha a mais no fim, com o link.
  - Lembrete: só para quem tem `lembrete_pedido_em`, e vai para `lembrete_para`.
  - Cancelamento pelo cliente: só avisa quem tocou, em `lembrete_para`.
  - Cancelamento pela barbearia e bloqueio: sempre avisam, em `cliente.whatsapp`, como hoje.
- A janela do lembrete continua `LEMBRETE_ANTECEDENCIA_MIN` (60). A regra das 3h fica fora.
- Ordem de deploy: back, depois front, e só então a variável no Coolify. O front sem `whatsappCentral` se comporta como hoje.
- Branches novas com `--no-track` nos dois repos (memória do projeto).

## Review Focus

1. **Cliente apaga ou muda parte da mensagem pronta.** Exemplos: só o código, código em MAIÚSCULA, "Código:K7P2Q9ABCD" colado, texto antes. Ele espera que funcione. → teste em Task 2.
2. **Mesmo toque mandado duas vezes, ou a Meta reenviando o webhook.** Não pode gravar de novo nem mudar `lembrete_para`. Pode responder de novo. → teste em Task 2.
3. **Toque num agendamento cancelado, passado ou de outra barbearia com o mesmo texto.** Não grava e não responde. → teste em Task 2.
4. **Chave ligada pela metade** (Meta ligada e `WHATSAPP_CENTRAL_NUMERO` vazio). Tudo como hoje: confirmação no site e lembrete para todos. → teste em Task 3.
5. **Cliente toca quando faltam menos de 60 min.** O agendamento já nasceu com `lembrete_enviado_em` e o cron não manda de novo. A resposta ao toque é a única mensagem. → teste em Task 3.

---

## Back (Marcai-back)

### Task 0: Branch

- [ ] `git fetch origin && git switch -c lembrete-por-toque --no-track origin/main`
- [ ] Commit do spec e deste plano: `git add docs/superpowers/specs/2026-11-03-lembrete-por-toque-design.md docs/superpowers/plans/2026-11-03-lembrete-por-toque.md && git commit -m "Design e plano do lembrete por toque"` (+ `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`)

### Task 1: Campos, migration e o módulo da chave

**Files:**
- Modify: `backend/tenant/models.py` (`Agendamento`, ao lado de `lembrete_enviado_em`)
- Create: `backend/tenant/migrations/0020_lembrete_por_toque.py` (via `makemigrations`; conferir que só adiciona as duas colunas)
- Create: `backend/app/services/lembrete_por_toque.py`
- Modify: `docker-compose.yml` (os dois blocos com `WHATSAPP_PROVEDOR`), `docker-compose.prod.yml`, `docker-compose.preview.yml`, `.env.example`, com `WHATSAPP_CENTRAL_NUMERO: ${WHATSAPP_CENTRAL_NUMERO:-}`
- Test: `tests/test_lembrete_por_toque.py` (novo)

**Interfaces:**
- Produces:
  - `Agendamento.lembrete_pedido_em: DateTimeField(null=True)`
  - `Agendamento.lembrete_para: TextField(null=True)` (dígitos nacionais)
  - `lembrete_por_toque.ligado() -> bool`
  - `lembrete_por_toque.numero_central() -> str | None`: dígitos, ou None se vazio
  - `lembrete_por_toque.texto_pronto(barbearia_nome: str, codigo: str) -> str`
  - `lembrete_por_toque.link(barbearia_nome: str, codigo: str) -> str | None`: `https://wa.me/55<central>?text=<texto_pronto urlencoded>`, ou None sem o número
  - `lembrete_por_toque.codigos_no_texto(texto: str) -> list[str]`: tokens de 10 caracteres do alfabeto, em minúscula, na ordem, sem repetir

- [ ] **Step 1: testes que falham**

```python
def test_ligado_exige_meta_e_numero(monkeypatch): ...
    # (meta, numero) -> esperado: (sim, "83988982852") True; (sim, "") False; (não, "83988982852") False
def test_link_monta_o_wa_me_com_o_texto_pronto(monkeypatch):
    # numero "83988982852"
    assert lembrete_por_toque.link("Brutus", "k7p2q9abcd") == (
        "https://wa.me/5583988982852?text=" + quote("Quero o lembrete do meu horário na Brutus. Código: k7p2q9abcd"))
def test_link_sem_numero_e_none(): ...
@pytest.mark.parametrize("texto", [
    "Quero o lembrete do meu horário na Brutus. Código: k7p2q9abcd",
    "K7P2Q9ABCD", "Código:k7p2q9abcd", "oi\nk7p2q9abcd obrigado"])
def test_codigos_no_texto_acha_o_codigo(texto):
    assert lembrete_por_toque.codigos_no_texto(texto) == ["k7p2q9abcd"]
def test_codigos_no_texto_ignora_o_que_nao_e_codigo():
    assert lembrete_por_toque.codigos_no_texto("oi, tudo bem? lembrete") == []
```

- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_lembrete_por_toque.py`. Esperado: FAIL (módulo não existe).
- [ ] **Step 3: implementar.** Campos no model e `makemigrations tenant --name lembrete_por_toque`. Para `codigos_no_texto`, usar `re.findall(r"(?<![0-9a-z])[2-9a-hjkmnp-z]{10}(?![0-9a-z])", texto.lower())`, sem repetição. A docstring do módulo resume a spec: por que só quem toca, e a janela de 24h grátis.
- [ ] **Step 4:** `docker compose run --rm api pytest -q`. Esperado: tudo passa.
- [ ] **Step 5: commit** `"Lembrete por toque: campos, chave e link"`

### Task 2: O webhook registra o pedido e responde

**Files:**
- Modify: `backend/app/services/lembrete_por_toque.py`
- Modify: `backend/app/services/whatsapp_meta.py` (`registrar_evento`)
- Test: `tests/test_lembrete_por_toque.py`, `tests/test_whatsapp_meta.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `lembrete_por_toque.registrar_pedido(texto: str, de_internacional: str, agora: datetime) -> str`. Devolve `"pedido"` (gravou e respondeu), `"repetido"` (já tinha pedido e respondeu de novo) ou `"ignorado"`.

Comportamento:
1. Para cada `codigo` em `codigos_no_texto(texto)`, percorrer as barbearias ativas (`Barbearia.objects.filter(ativo=True)`, como em `lembrete.enviar_pendentes`). Dentro de `com_barbearia(b.id)`, buscar `Agendamento` com aquele código, `status=CONFIRMADO` e `inicio > agora`. Parar no primeiro encontrado.
2. Se `lembrete_pedido_em` for nulo, gravar `lembrete_pedido_em=agora` e `lembrete_para=<nacional de de_internacional>`, usando `tenant.telefone` (`canonico`/`do_jid`, o que já converte `55…`). Se não for nulo, não gravar nada.
3. Responder com `whatsapp.enviar_ao_cliente(b, <lembrete_para gravado>, msg_confirmacao(..., link=convite.link_do_agendamento(b.slug, a.codigo), barbearia_nome=b.nome, contato=b.whatsapp_contato), tipo=TipoMensagem.CONFIRMACAO, cliente_nome=a.cliente.nome)`.
4. No `registrar_evento`, para cada mensagem com `type == "text"` e a chave ligada, chamar `registrar_pedido(msg["text"]["body"], msg["from"], agora)`. Envolver em try/except com log, porque uma falha não pode virar 500 no webhook. O retorno do `registrar_evento` ganha `pedidos=<n>`.

- [ ] **Step 1: testes que falham** (Meta ligada, `WHATSAPP_CENTRAL_NUMERO` preenchido, `requests.post` trocado uma vez só e separado pela URL, como em `tests/test_whatsapp_equipe.py`)

```python
def test_toque_grava_e_responde_com_a_confirmacao(cenario, ...):
    # agendamento CONFIRMADO amanhã; registrar_pedido("Quero ... Código: <cod>", "5583977776666", agora)
    # == "pedido"; lembrete_pedido_em == agora; lembrete_para == "83977776666";
    # 1 post na Meta para "5583977776666" com o link /agendamento/<cod> no texto
def test_toque_repetido_responde_sem_regravar(...): ...   # 2ª vez de outro número: "repetido", lembrete_para não muda
def test_toque_em_cancelado_passado_ou_inexistente_e_ignorado(...): ...  # parametrizado: "ignorado", 0 posts
def test_codigo_de_outra_barbearia_acha_a_barbearia_certa(cenario, ...): ...  # agendamento na dontony: grava lá
def test_webhook_com_texto_de_toque_registra(client, ...): ...
    # POST assinado (mesmo jeito de test_webhook_assinado_e_aceito_sem_x_brutus_cliente) com
    # entry[].changes[].value.messages=[{"from": "5583977776666", "type": "text", "text": {"body": "...<cod>"}}]
    # -> 200, resultado contém "pedidos=1"
def test_webhook_com_chave_desligada_nao_registra(...): ...  # sem WHATSAPP_CENTRAL_NUMERO: "pedidos=0", nada gravado
```

- [ ] **Step 2:** rodar os dois arquivos. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `docker compose run --rm api pytest -q`. Esperado: tudo passa.
- [ ] **Step 5: commit** `"Webhook da Meta liga o lembrete de quem tocou"`

### Task 3: Os envios obedecem à chave

**Files:**
- Modify: `backend/app/api/v1/views/agendamentos.py` (confirmação do site, ~linha 128; `depois_de_cancelar`)
- Modify: `backend/app/api/v1/views/agendamentos_painel.py` (confirmação do painel, ~linha 61)
- Modify: `backend/app/services/agendamentos.py` (o dict de `cancelar_publico`, ~linha 269, ganha `lembrete_pedido_em` e `lembrete_para`)
- Modify: `backend/app/services/lembrete.py` (`enviar_pendentes`)
- Modify: `backend/app/services/mensagens.py`: `msg_confirmacao(..., link_do_lembrete: str | None = None)` acrescenta ao fim `"\n\nQuer o lembrete 1h antes? Toque e envie a mensagem: {link_do_lembrete}"`
- Test: `tests/test_lembrete_por_toque.py` (os casos de envio), e os arquivos existentes que quebrarem

**Interfaces:**
- Consumes: `ligado()` e `link()` da Task 1, e os campos.

- [ ] **Step 1: testes que falham** (chave ligada, salvo onde está escrito; contar os posts da Meta)

```python
def test_marcar_pelo_site_nao_manda_confirmacao(client, cenario, ...): ...       # POST /api/agendamentos -> 201, 0 posts ao cliente
def test_marcar_pelo_painel_manda_confirmacao_com_o_link(client, cenario, ...): ...  # 1 post; texto contém link("…", codigo)
def test_cron_sem_toque_nao_manda_lembrete(cenario, ...): ...                    # enviar_pendentes -> 0
def test_cron_com_toque_manda_para_quem_tocou(cenario, ...): ...                 # lembrete_para "83977776666" -> post para 5583977776666
def test_cliente_cancela_sem_toque_nao_avisa(client, cenario, ...): ...
def test_cliente_cancela_com_toque_avisa_quem_tocou(client, cenario, ...): ...
def test_barbearia_cancela_sem_toque_avisa_o_numero_digitado(client, cenario, ...): ...
def test_meio_ligado_tudo_como_hoje(client, cenario, monkeypatch, ...): ...
    # Meta ligada, sem WHATSAPP_CENTRAL_NUMERO: site manda confirmação; cron manda lembrete sem toque
def test_toque_dentro_da_janela_nao_gera_segundo_lembrete(cenario, ...): ...
    # agendamento para daqui a 40 min (nasce com lembrete_enviado_em); registrar_pedido; enviar_pendentes -> 0
```

- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3: implementar.**
  - Os três pontos de envio perguntam `lembrete_por_toque.ligado()`. O cron, ligado, filtra `lembrete_pedido_em__isnull=False` e manda para `a.lembrete_para`.
  - `depois_de_cancelar`, ligado: só manda se `resultado["lembrete_pedido_em"]`, e manda para `resultado["lembrete_para"]`.
  - O aviso ao barbeiro (`lista_do_dia.avisar_mudanca`) não muda.
- [ ] **Step 4:** `docker compose run --rm api pytest -q`. Esperado: tudo passa.
- [ ] **Step 5: commit** `"Confirmação e lembrete só para quem tocou"`

### Task 4: O que o front lê

**Files:**
- Modify: `backend/app/api/v1/views/barbearia.py`: `whatsappCentral` recebe `lembrete_por_toque.numero_central() if lembrete_por_toque.ligado() else None`
- Modify: `backend/app/services/agendamentos.py` (`detalhe_publico` devolve `lembrete_pedido: bool`) e `backend/app/api/v1/serializers/agendamentos.py` (`lembretePedido = serializers.BooleanField(source="lembrete_pedido")`)
- Test: `tests/test_lembrete_por_toque.py`

- [ ] **Step 1: testes que falham.**
  - `test_barbearia_expoe_o_central_so_com_a_chave`: ligado mostra `"83988982852"`, desligado mostra `None`.
  - `test_detalhe_diz_se_o_lembrete_foi_pedido`: `False`, e `True` depois de `registrar_pedido`.
  - O detalhe não pode expor `lembrete_para`, porque o WhatsApp do cliente nunca sai (§9.1). Conferir que a chave não está na resposta.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `docker compose run --rm api pytest -q`. Esperado: tudo passa.
- [ ] **Step 5: commit** `"API mostra o número central e o lembrete pedido"`

### Task 5: PR do back

- [ ] `git push -u origin lembrete-por-toque`. Depois `gh pr create`, com o porquê, a chave, a ordem de deploy (back, front, variável) e a migration 0020. O corpo termina com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- [ ] Esperar o CI verde. O merge é do José.

## Front (Marcai-front)

### Task 6: O botão

**Files:**
- Create: `src/lib/lembrete.ts`
- Test: `tests/lembrete.test.ts`
- Modify: `src/lib/tenant.ts` (tipo `Barbearia`: `whatsappCentral?: string | null`)
- Modify: `src/app/agendamento/[codigo]/page.tsx` (tipo `Detalhe` ganha `lembretePedido?: boolean`; passar `whatsappCentral={b.whatsappCentral ?? null}`, `lembretePedido={ag.lembretePedido === true}` e o nome da barbearia)
- Modify: `src/components/Confirmado.tsx`
- Modify: `src/app/agendar/page.tsx` e `src/components/FormAgendamento.tsx` (prop `lembretePorToque: boolean`)

**Interfaces:**
- Produces:
  - `textoProntoDoLembrete(barbeariaNome: string, codigo: string): string`, o mesmo texto do back
  - `linkDoLembrete(central: string, barbeariaNome: string, codigo: string): string`, `https://wa.me/55${central}?text=${encodeURIComponent(texto)}`

Comportamento:
- **`Confirmado`**, com `whatsappCentral` e status `CONFIRMADO`:
  - **Sem `lembretePedido`:** no lugar de "Mandamos o lembrete…", um botão destacado (`Box variante="fill"`, `<a href={linkDoLembrete(...)}>`) com o texto **"Quero o lembrete no WhatsApp"**. Embaixo, em `Sub`: "Toque, envie a mensagem que aparece, e a gente te lembra 1h antes."
  - **Com `lembretePedido`:** `Sub` com "Lembrete ligado ✓ · chega no WhatsApp 1h antes".
  - Ao voltar para a aba (`visibilitychange` com `visible`), chamar `router.refresh()` para buscar o `lembretePedido` novo.
  - **Sem `whatsappCentral`:** o texto de hoje, sem mudança.
- **`FormAgendamento`**, com `lembretePorToque`: a nota "A confirmação chega no seu WhatsApp" vira "Depois de confirmar, você escolhe receber o lembrete no WhatsApp". Sem a prop, fica como hoje.

- [ ] **Step 1: teste que falha.** `linkDoLembrete("83988982852", "Brutus", "k7p2q9abcd")` tem que ser igual a `"https://wa.me/5583988982852?text=" + encodeURIComponent("Quero o lembrete do meu horário na Brutus. Código: k7p2q9abcd")`. E com nome com acento e `&` ("Barbearia & Cia"), o `text=` decodificado volta igual.
- [ ] **Step 2:** `npm test -- tests/lembrete.test.ts`. Esperado: FAIL.
- [ ] **Step 3:** implementar a lib e os componentes.
- [ ] **Step 4:** `npm test`, `npx tsc --noEmit` e `npm run lint`. Esperado: tudo limpo.
- [ ] **Step 5: commit** `"Botão Quero o lembrete no WhatsApp"`, na branch `lembrete-por-toque` (criada com `git switch -c lembrete-por-toque --no-track origin/main`).

### Task 7: PR do front

- [ ] `git push -u origin lembrete-por-toque`. Depois `gh pr create`, dizendo que depende do PR do back e que, sem `whatsappCentral`, o comportamento é o de hoje. O corpo termina com a linha do Claude Code.
- [ ] Esperar o CI verde.
