# Mensalidade pela InfinitePay — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a mensalidade que a barbearia paga ao Marcai vira um link do Checkout Integrado da InfinitePay (Pix a 0% ou cartão), com o valor redondo, e se confirma sozinha quando a InfinitePay avisa que foi paga — sem centavos, sem "Já paguei", sem o José conferir o banco.

**Architecture:** um cliente HTTP pequeno (`services/infinitepay.py`) cria o link e confere o pagamento. `operacoes._abrir_cobranca` passa a criar a cobrança por ele quando a InfinitePay está configurada; sem a configuração, tudo continua como hoje (Pix estático com centavos). Um webhook `POST /api/interno/infinitepay` recebe o aviso — que **não é assinado** — e só confirma depois de perguntar à InfinitePay (`payment_check`); aí chama o `operacoes.confirmar` que já existe. Uma varredura do Celery a cada 10 min cobre aviso perdido.

**Tech Stack:** Django 6 + DRF, Celery beat, `requests` (já no requirements), pytest com Postgres real. Front: Next.js (Marcai-front), só o portão da mensalidade e a lista do admin.

**Spec:** não há documento de spec; as decisões vêm da conversa de 2026-10-23 e estão fixadas em **Decisões** abaixo. Substitui o plano `2026-10-23-mensalidade-mercado-pago.md`.

## Decisões

- **Base:** branch `mensalidade-infinitepay` saindo de `origin/mensalidade` (PR #55) no back; no front, da mensalidade separada do #64. PR contra `main` depois que o #55 entrar. A migration nova é a `0017`, depois da `0016_mensalidade`.
- **Só a mensalidade.** O Pix do agendamento continua estático, na chave do próprio barbeiro.
- **Ciclo continua do Marcai.** A InfinitePay não tem recorrência no checkout integrado: cada ciclo abre uma cobrança e a cobrança tem o seu link. Vencimento, avisos, `isenta`, `nunca_bloquear` e bloqueio **não mudam**.
- **Liga e desliga pelo ambiente:** com `INFINITEPAY_HANDLE` preenchido, cobrança nova de mensalidade vai pela InfinitePay; vazio, cai no Pix estático de hoje. Cobrança aberta que já existe não muda de caminho.
- **Valor exato:** `valor_centavos == valor_base_centavos`.
- **Índice de centavos:** a cobrança da InfinitePay grava `chave_pix = "ip:" + str(cobranca.id)`. O índice único `cobranca_aberta_por_chave_e_valor` não faz duas barbearias de mesmo preço disputarem nada, e `centavos.ocupados(PIX_CHAVE)` não enxerga essas linhas. `copia_e_cola` fica `""`.
- **Identificador:** `order_nsu = str(cobranca.id)`.
- **Aviso sem assinatura:** a `webhook_url` leva `?t=<INFINITEPAY_WEBHOOK_SEGREDO>`; sem o `t` certo, 401. Mesmo com o `t` certo, nada confirma sem o `payment_check` responder `paid: true`.
- **Conferência:** só confirma se `payment_check` diz `paid: true` **e** `amount == cobranca.valor_centavos` (o `paid_amount` pode ser maior no cartão parcelado; o que vale é o `amount`).
- **"Já paguei":** some da tela quando a cobrança é da InfinitePay. A rota responde 400 com `"A confirmação deste pagamento é automática."`.
- **Tela:** no lugar do QR e do copia e cola, um botão **"Pagar mensalidade"** que abre o link numa aba nova, e a frase `"Pix ou cartão. Assim que o pagamento cair, o painel libera sozinho."`.

## Global Constraints

- Variáveis novas: `INFINITEPAY_HANDLE` (a InfiniteTag sem o `$`), `INFINITEPAY_API_KEY` (pode ficar vazia; ver Task 2), `INFINITEPAY_WEBHOOK_SEGREDO`, `MARCAI_API_URL_PUBLICA` (a URL pública da API, para montar a `webhook_url`), `MARCAI_FRONT_URL_PUBLICA` (para a `redirect_url`, que volta ao painel) — em `settings.py`, `.env.example`, `docker-compose.yml` e `docker-compose.prod.yml` (serviços `api`, `worker`, `beat`). Se o projeto já tiver variável com a URL pública de algum dos dois, usar essa em vez de criar outra.
- API: `POST https://api.checkout.infinitepay.io/links` e `POST https://api.checkout.infinitepay.io/payment_check`, timeout de 10 s. **Antes da Task 2, conferir na documentação oficial** (infinitepay.io/checkout-documentacao e o artigo "Como usar o Checkout Integrado" da ajuda) os nomes dos campos, o caminho do `payment_check` e se a autenticação é `handle` no corpo, `X-Api-Key` no cabeçalho ou os dois. O cliente manda os dois quando `INFINITEPAY_API_KEY` existir.
- Toda escrita de `Assinatura`/`Cobranca` pelo alias `admin`, como o resto de `operacoes`.
- Comentários e textos de tela em português, no tom do código vizinho.
- Testes: `docker compose run --rm api pytest -q`. Nenhum teste fala com a InfinitePay de verdade: o cliente é trocado por `monkeypatch`.

## Review Focus

1. **Pago depois de cancelado** (o link não expira: admin registrou na mão, a barbearia ficou isenta, e o link velho ainda foi pago): não confirma, avisa `MENSALIDADE_WHATSAPP_AVISO` com "Pagamento da InfinitePay numa cobrança cancelada: <barbearia> R$ X — conferir ou devolver", uma vez só, e responde 200. Teste na Task 4.
2. **Aviso falso** (alguém descobre a URL e manda um POST com `order_nsu` de uma cobrança aberta): com `t` errado, 401; com `t` certo mas `payment_check` dizendo `paid: false`, nada muda. Testes na Task 4.
3. **Aviso repetido:** o segundo não avança o `paga_ate` de novo. Teste na Task 4.
4. **InfinitePay fora do ar ao abrir a cobrança:** o portão responde com `pixErro = "Não foi possível gerar o link de pagamento agora. Tente de novo em alguns minutos."` em vez de 500, e nenhuma cobrança fica gravada sem link. Teste na Task 3.
5. **Valor que não bate** (link de outra coisa na mesma InfiniteTag com o mesmo `order_nsu` não existe, mas o valor errado sim — ex.: admin mudou o preço depois do link criado): ignorado com `logger.warning`, sem confirmar. Teste na Task 4.

---

### Task 1: Modelo e configuração

**Files:**
- Create: `backend/tenant/migrations/0019_cobranca_infinitepay.py`
- Modify: `backend/tenant/models.py` (`ComoFoiPaga`, `Cobranca`)
- Modify: `backend/backend/settings.py`, `.env.example`, `docker-compose.yml`, `docker-compose.prod.yml`
- Test: `tests/test_mensalidade_modelos.py`

**Interfaces:**
- Produces: `ComoFoiPaga.INFINITEPAY = "INFINITEPAY"`; `Cobranca.link_pagamento: TextField(blank=True, default="")`; `Cobranca.ip_transacao: TextField(blank=True, default="")` (o `transaction_nsu` que o aviso traz); os settings das Global Constraints, strings com default `""`.

- [ ] **Step 1:** teste `test_cobranca_guarda_o_link_da_infinitepay`: cria uma `Cobranca` com `link_pagamento`, `ip_transacao` e `como_foi_paga=ComoFoiPaga.INFINITEPAY` e relê igual.
- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_mensalidade_modelos.py` → FAIL.
- [ ] **Step 3:** campos, choice, migration (`makemigrations tenant -n cobranca_infinitepay`; só adiciona colunas, os GRANTs da 0016 valem), settings com comentário no estilo dos de `PIX_*`, variáveis no `.env.example` e nos composes.
- [ ] **Step 4:** o mesmo comando → PASS; `makemigrations --check` → "No changes detected".
- [ ] **Step 5:** commit `mensalidade-infinitepay: campos do link e variaveis`.

### Task 2: Cliente da InfinitePay

**Files:**
- Create: `backend/app/services/infinitepay.py`
- Test: `tests/test_infinitepay.py`

**Interfaces:**
- Produces:
  - `class ErroDaInfinitePay(Exception)`
  - `def configurada() -> bool` — `INFINITEPAY_HANDLE`, `INFINITEPAY_WEBHOOK_SEGREDO` e `MARCAI_API_URL_PUBLICA` preenchidos.
  - `def criar_link(*, valor_centavos: int, descricao: str, referencia: str) -> str` — corpo `{"handle", "items": [{"quantity": 1, "price": valor_centavos, "description": descricao}], "order_nsu": referencia, "redirect_url": f"{MARCAI_FRONT_URL_PUBLICA}/painel", "webhook_url": f"{MARCAI_API_URL_PUBLICA}/api/interno/infinitepay?t={INFINITEPAY_WEBHOOK_SEGREDO}"}`; devolve a `url` da resposta.
  - `def conferir(*, referencia: str, transacao: str, slug: str) -> dict` — `payment_check` com `handle`, `order_nsu`, `transaction_nsu`, `slug`; devolve `{"pago": bool, "valor_centavos": int, "meio": str}` (de `paid`, `amount`, `capture_method`).
  - `def segredo_confere(t: str) -> bool` — `hmac.compare_digest` em bytes contra `INFINITEPAY_WEBHOOK_SEGREDO`; segredo vazio → `False`.
- Com `INFINITEPAY_API_KEY` preenchida, as duas chamadas levam `X-Api-Key`.
- Não-2xx, timeout, JSON sem os campos → `ErroDaInfinitePay`.

- [ ] **Step 1:** testes com `requests` trocado por `monkeypatch`:
  - `test_criar_link_manda_preco_em_centavos_e_order_nsu` — `price == 6000`, `order_nsu` igual à referência, `webhook_url` termina em `?t=<segredo>`, `timeout == 10`.
  - `test_criar_link_manda_api_key_so_quando_existe`.
  - `test_criar_link_devolve_a_url`.
  - `test_resposta_500_vira_erro` e `test_timeout_vira_erro`.
  - `test_conferir_traduz_a_resposta` — `{"paid": true, "amount": 6000, "capture_method": "pix"}` → `{"pago": True, "valor_centavos": 6000, "meio": "pix"}`.
  - `test_segredo_confere_so_o_certo` e `test_segredo_vazio_nunca_confere`.
- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_infinitepay.py` → FAIL.
- [ ] **Step 3:** implementar como nas Interfaces.
- [ ] **Step 4:** o mesmo comando → PASS.
- [ ] **Step 5:** commit `mensalidade-infinitepay: cliente do checkout integrado`.

### Task 3: A cobrança da mensalidade pela InfinitePay

**Files:**
- Modify: `backend/app/services/mensalidade/operacoes.py` (`cobravel`, `_abrir_cobranca`, `informar_pagamento`)
- Modify: `backend/app/api/v1/views/mensalidade_painel.py` (`_corpo`)
- Test: `tests/test_mensalidade_operacoes.py`, `tests/test_mensalidade_painel.py`

**Interfaces:**
- Consumes: `infinitepay.configurada`, `infinitepay.criar_link`, `ErroDaInfinitePay` (Task 2).
- Produces: `operacoes.eh_da_infinitepay(cobranca) -> bool` (`chave_pix.startswith("ip:")`); no corpo do portão, `pix` ganha `"link": str | None` e `"automatico": bool`; com InfinitePay, `copiaECola` e `qrSvg` vêm `None`.

- [ ] **Step 1:** testes, com `criar_link` trocado por um falso que devolve `"https://checkout.infinitepay.io/x/abc"`:
  - `test_com_infinitepay_a_cobranca_sai_com_valor_redondo` — `valor_centavos == valor_base_centavos == 10000`, `chave_pix == f"ip:{c.id}"`, `link_pagamento` gravado, falso chamado com `referencia == str(c.id)`.
  - `test_duas_barbearias_mesmo_preco_nao_disputam_centavo`.
  - `test_sem_infinitepay_continua_o_pix_com_centavo` — `valor_centavos == 10001`, `link_pagamento == ""`.
  - `test_isenta_nao_gera_link` e `test_nunca_bloquear_continua_sem_bloquear_com_infinitepay` — o falso não é chamado para a isenta; a de `nunca_bloquear` vencida não lê como BLOQUEADA.
  - `test_infinitepay_fora_do_ar_nao_grava_cobranca` — o falso levanta: `RecusaDaMensalidade` com a mensagem do Review Focus 4 e nenhuma `Cobranca` aberta.
  - `test_ja_paguei_recusado_quando_e_automatico`.
  - em `test_mensalidade_painel.py`: `test_portao_manda_o_link_e_diz_que_e_automatico`.
- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_mensalidade_operacoes.py tests/test_mensalidade_painel.py` → os novos FAIL.
- [ ] **Step 3:** implementar.
  - `cobravel`: valor > 0, não isenta, e (`infinitepay.configurada()` **ou** o Pix estático completo).
  - `_abrir_cobranca`: com `configurada()`, gera o `id`, chama `criar_link(valor_centavos=base, descricao=f"Mensalidade Marcaí - {nome}", referencia=str(id))` e só então cria a linha (falha da API não deixa linha nenhuma).
  - `informar_pagamento`: depois de `_garantir_cobranca`, se `eh_da_infinitepay(cobranca)` → `RecusaDaMensalidade`.
- [ ] **Step 4:** suíte inteira `docker compose run --rm api pytest -q` → PASS (os testes antigos rodam sem `INFINITEPAY_HANDLE` e não mudam).
- [ ] **Step 5:** commit `mensalidade-infinitepay: cobranca da mensalidade pelo link, com valor redondo`.

### Task 4: Aviso da InfinitePay e varredura

**Files:**
- Create: `backend/app/services/mensalidade/infinitepay_retorno.py`
- Modify: `backend/app/api/v1/views/interno.py`, `backend/app/api/v1/router.py` (bloco E), `backend/app/tasks.py`, `backend/backend/settings.py` (`CELERY_BEAT_SCHEDULE`), `backend/app/services/mensagens.py`
- Test: `tests/test_mensalidade_infinitepay_retorno.py`

**Interfaces:**
- Consumes: `infinitepay.conferir`, `infinitepay.segredo_confere` (Task 2); `operacoes.confirmar(cobranca_id, *, agora, como)` — aceitar também `ComoFoiPaga.INFINITEPAY`.
- Produces:
  - `def processar(*, referencia: str, transacao: str, slug: str, agora) -> str` — `"confirmada"`, `"ja_resolvida"`, `"paga_em_cancelada"`, `"ignorada"` ou `"pendente"`.
  - `InfinitePayRetornoView` em `POST /api/interno/infinitepay` (name `interno-infinitepay`): `t` da query string errado → 401; corpo sem `order_nsu` → 200 e nada; senão `processar(referencia=order_nsu, transacao=transaction_nsu, slug=invoice_slug)` e 200. `ErroDaInfinitePay` → 503 (para a InfinitePay tentar de novo).
  - task `conferir_pagamentos_infinitepay() -> dict`, beat a cada `600.0` s: para cada cobrança de mensalidade ABERTA com `chave_pix` começando em `ip:` **e** `ip_transacao` preenchido, chama `processar`; erro numa não para as outras.
  - `mensagens.msg_infinitepay_pago_em_cancelada(nome, valor_centavos) -> str`.
- Regras de `processar`: acha a cobrança por `id == referencia` e `chave_pix` em `ip:`; não achou → `"ignorada"`. Grava `ip_transacao` se estiver vazio (é o que deixa a varredura conferir depois). `conferir(...)["pago"]` falso → `"pendente"`. Valor diferente → `"ignorada"` com `logger.warning`. ABERTA → `confirmar(..., como=INFINITEPAY)` → `"confirmada"`. PAGA → `"ja_resolvida"`. CANCELADA → aviso a `MENSALIDADE_WHATSAPP_AVISO` depois do commit e `observacao = "pago na InfinitePay depois de cancelada"`; se a observação já estiver lá, não avisa de novo → `"paga_em_cancelada"`.
- A varredura só alcança cobrança que já recebeu pelo menos um aviso (o `payment_check` pede `transaction_nsu` e `slug`). Aviso que nunca chegou fica para o "registrar na mão" do admin — registrar isso num comentário da task.

- [ ] **Step 1:** testes, com `conferir` trocado por falso:
  - `test_pago_confirma_e_avanca_paga_ate` — `como_foi_paga == INFINITEPAY`, `paga_ate` avançou um mês.
  - `test_aviso_repetido_nao_avanca_duas_vezes`.
  - `test_nao_pago_nao_confirma` e `test_nao_pago_ainda_guarda_a_transacao`.
  - `test_valor_diferente_e_ignorado`.
  - `test_pago_em_cancelada_avisa_uma_vez` — `enviar_a_equipe` trocado; dois avisos, um envio.
  - view: `test_aviso_com_segredo_errado_da_401_e_nao_confere` (o falso levanta se for chamado), `test_aviso_certo_confirma`, `test_aviso_sem_order_nsu_responde_200`, `test_infinitepay_fora_do_ar_da_503`.
  - task: `test_varredura_confirma_o_que_ficou_pendente`.
- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_mensalidade_infinitepay_retorno.py` → FAIL.
- [ ] **Step 3:** implementar. A view fica no bloco E do `router.py`, ao lado de `interno/whatsapp/evento`, sem sessão e sem crivo posicional, com autenticação e CSRF do DRF desligados como na view do WhatsApp.
- [ ] **Step 4:** suíte inteira → PASS.
- [ ] **Step 5:** commit `mensalidade-infinitepay: aviso e varredura confirmam o pagamento sozinhos`.

### Task 5: Tela (Marcai-front)

**Files:**
- Modify: `src/lib/mensalidade.ts` (tipo do corpo: `pix.link: string | null`, `pix.automatico: boolean`, `copiaECola`/`qrSvg` anuláveis)
- Modify: `src/components/painel/PortaoDaMensalidade.tsx`
- Modify: `src/components/admin/Mensalidades.tsx` (rótulo `INFINITEPAY` → "InfinitePay")
- Test: `tests/mensalidade.test.ts`

- [ ] **Step 1:** teste do helper que decide o bloco de pagamento: com `link` → botão "Pagar mensalidade" (abre em aba nova, `rel="noopener noreferrer"`), a frase da Decisão e sem "Já paguei"; sem `link` → QR, copia e cola e "Já paguei" como hoje.
- [ ] **Step 2:** `npm test` → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `npm test` e a checagem de tipos do projeto → PASS.
- [ ] **Step 5:** commit `mensalidade-infinitepay: portao com o link de pagamento`.

### Task 6: Ligar em produção (manual, com o José e o cunhado)

- [ ] App da InfinitePay (CNPJ do cunhado): copiar a **InfiniteTag** sem o `$`; ver se há área de Checkout/Integrações com **chave de API**.
- [ ] Gerar o segredo do aviso: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- [ ] No Coolify: `INFINITEPAY_HANDLE`, `INFINITEPAY_API_KEY` (se houver), `INFINITEPAY_WEBHOOK_SEGREDO`, as URLs públicas; redeploy de api, worker e beat.
- [ ] Teste de verdade com uma barbearia de teste a R$ 1,00 no Pix: abrir o portão, pagar pelo link, ver o painel liberar e a Plataforma mostrar "InfinitePay".
