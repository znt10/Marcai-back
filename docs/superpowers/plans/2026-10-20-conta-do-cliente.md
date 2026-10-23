# Conta do cliente — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** conta opcional e global do cliente (nome + WhatsApp + senha, código no WhatsApp só na primeira vez), com histórico por estabelecimento e cancelamento sem o link.

**Architecture:** duas tabelas novas FORA do RLS (`ContaCliente`, `CodigoConta`), como `Barbearia`. A conta liga-se aos `Cliente` de cada barbearia pelo WhatsApp (`formas_gravadas`). Uma função SQL `SECURITY DEFINER` diz em quais barbearias o número tem cliente, e cada leitura de agendamento continua dentro de `com_barbearia`. Sessão em JWT próprio (`aud="cliente"`), num cookie separado com `Domain=.<DOMINIO_BASE>`. Rotas sob `/api/conta/*` no Django, e telas novas no Next.

**Tech Stack:** Django 6 + DRF + Postgres (RLS) + Redis (cache) + PyJWT + argon2 | Next.js (App Router) + Tailwind + vitest.

**Spec:** `Marcai-back/docs/superpowers/specs/2026-10-20-conta-do-cliente-design.md`. Leia o spec antes da primeira tarefa.

## Global Constraints

- **Nada na `main`.** Back: branch `conta-do-cliente` (já existe, com o spec). Front: `git switch -c conta-do-cliente --no-track origin/main`, e conferir com `git rev-parse --abbrev-ref @{u}` que não rastreia `origin/main`. Sem worktree esquecida.
- **O código e o link só existem no back.** Ficam guardados só como hash, e nenhuma resposta da API devolve código ou token. No dev sem `EVOLUTION_API_URL`, o texto da mensagem vai só para o log do Django.
- A conta é opcional: `POST /api/agendamentos` sem cookie de conta continua idêntico.
- Constantes em `backend/tenant/config.py`, num bloco `# ---- Conta do cliente ----`:
  `CONTA_SESSAO_COOKIE = "sessao_conta"`, `CONTA_SESSAO_DIAS = 30`, `CONTA_SENHA_MINIMA = 6`,
  `CONTA_CODIGO_VALIDADE_MIN = 10`, `CONTA_CODIGO_TENTATIVAS = 5`, `CONTA_LINK_VALIDADE_MIN = 30`,
  `CONTA_ENVIOS_POR_NUMERO_HORA = 3`, `CONTA_ENVIOS_POR_NUMERO_DIA = 10`, `CONTA_ENVIOS_POR_IP_HORA = 10`,
  `CONTA_ENVIOS_POR_DIA = 300` (teto geral do central), `CONTA_TRAVA_BASE_MS = 1_000`, `CONTA_TRAVA_TETO_MS = 30_000`,
  `CONTA_HISTORICO_POR_LUGAR = 20`.
- O WhatsApp da conta é guardado em `canonico()` (`tenant/telefone.py`). A busca de `Cliente` usa `formas_gravadas()`.
- Prazo de cancelamento = `PRAZO_CANCELAMENTO_MIN`, a mesma função do cancelamento pelo link.
- Erros em `{"erro": "<frase em português>"}`. Escrita exige `x-brutus-cliente` (já global). Rotas sem barra final.
- Textos ao cliente no tom da casa (curtos, "você"/"pra"), com o vocabulário por tipo (`palavras()` / `vocabulario()`).
- Testes do back: `docker compose run --rm api pytest -q` (ou `python -m pytest` com o banco publicado em 5433). Front: `npm test` e `npx tsc --noEmit`.
- Comentários densos e em português sem acento no back, com acento no front, como o código ao redor.

## Review Focus

1. **Número digitado de formas diferentes** (`+55 (83) 98221-7869`, `8382217869` sem o nono dígito, cliente antigo gravado sem o 9): criar, entrar, esqueci e histórico caem na mesma conta e acham os agendamentos antigos. Testes na Tarefa 4 (`test_entrar_com_numero_em_outra_forma`) e na Tarefa 5 (`test_historico_acha_cliente_gravado_sem_o_nove`).
2. **Conta não confirmada criada por outra pessoa com o meu número:** não consegue entrar, e quando eu crio a minha, ela substitui a pendente. Tarefa 4 (`test_criar_por_cima_de_conta_pendente_substitui`, `test_entrar_em_conta_pendente_e_recusado`).
3. **Cookie trocado:** o JWT do barbeiro não vale como conta, e o da conta não vale no painel. Tarefa 3 (`test_token_de_barbeiro_nao_vale_como_conta`, `test_token_de_conta_nao_vale_no_painel`).
4. **Cancelar o que não é seu:** o código de agendamento de outro número, ou `barbeariaId` de um lugar onde o número não tem cliente, dá 404 sem cancelar nada. Tarefa 5 (`test_cancelar_agendamento_de_outro_numero_da_404`).
5. **Link de nova senha:** reusar, usar vencido, ou usar depois de pedir outro dá 404. Trocar a senha derruba as sessões antigas. Tarefa 4 (`test_link_de_nova_senha_serve_uma_vez`, `test_nova_senha_derruba_sessao_antiga`).

---

### Task 1: Modelos, migration e a função que atravessa tenants

**Files:**
- Modify: `backend/tenant/models.py` (depois de `Cliente`), `backend/tenant/config.py`
- Create: `backend/tenant/migrations/0013_conta_do_cliente.py`
- Modify: `tests/conftest.py` (TRUNCATE ganha `tenant_codigoconta, tenant_contacliente`)
- Test: `tests/test_conta_modelos.py`

**Interfaces:**
- Produces:
  - `class FinalidadeCodigo(models.TextChoices)`: `CONFIRMAR`, `NOVA_SENHA`.
  - `class ContaCliente`: `id` UUID, `nome` Text, `whatsapp` Text **unique**, `senha_hash` Text, `confirmada_em` DateTime null, `token_version` int default 0, `criado_em`.
  - `class CodigoConta`: `id` UUID, `conta` FK CASCADE (`related_name="codigos"`), `finalidade`, `hash` Text **unique**, `expira_em`, `tentativas` int default 0, `usado_em` null, `criado_em`.
  - SQL: `barbearias_do_whatsapp(formas text[]) RETURNS SETOF uuid`, que devolve os `barbearia_id` distintos de `tenant_cliente` com `whatsapp = ANY(formas)`.

- [ ] **Step 1: Escrever os testes que falham.** Use `pytest.mark.django_db(databases=["default", "owner"], transaction=True)`.
  - `test_conta_fica_fora_do_rls`: cria a conta via `using("owner")` e lê com `ContaCliente.objects.get(...)` pelo `default`, **fora** de `com_barbearia`. Encontra.
  - `test_whatsapp_da_conta_e_unico`: a segunda conta com o mesmo número levanta `IntegrityError`.
  - `test_funcao_devolve_so_ids_das_barbearias_do_numero`: com `cenario`, cria `Cliente` com o número X na brutus e Y na dontony. Chamada pelo `default` com `cursor.execute("SELECT * FROM barbearias_do_whatsapp(%s)", [["X"]])`, devolve só `{brutus.id}`.
  - `test_runtime_continua_sem_ver_cliente_fora_do_tenant`: pelo `default`, `Cliente.objects.count() == 0` fora de `com_barbearia`. A função não abriu o RLS.
- [ ] **Step 2: Rodar.** `pytest tests/test_conta_modelos.py -v`. Esperado: FAIL (import/tabela inexistente).
- [ ] **Step 3: Implementar os modelos e as constantes** (lista em Global Constraints). Docstrings no estilo de `Barbearia`, dizendo por que estão fora do RLS.
- [ ] **Step 4: Gerar a migration** com `makemigrations tenant -n conta_do_cliente` e acrescentar à mão um `RunSQL`:
  ```sql
  CREATE FUNCTION barbearias_do_whatsapp(formas text[]) RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
    $$ SELECT DISTINCT barbearia_id FROM tenant_cliente WHERE whatsapp = ANY(formas) $$;
  REVOKE ALL ON FUNCTION barbearias_do_whatsapp(text[]) FROM PUBLIC;
  GRANT EXECUTE ON FUNCTION barbearias_do_whatsapp(text[]) TO brutus_app;
  ```
  A função roda como `brutus_owner`, e é a política `owner_irrestrito` da 0002 que a deixa ver todos os tenants. Ela devolve **só ids**. O comentário na migration explica isso. `reverse_sql` faz `DROP FUNCTION`. Os GRANTs de DML nas duas tabelas novas vêm do `ALTER DEFAULT PRIVILEGES` do `init-db.sh`. Não é preciso REVOKE: o runtime escreve nelas de verdade.
- [ ] **Step 5: Rodar.** O mesmo comando dá PASS, e a suíte inteira continua verde.
- [ ] **Step 6: Commit** `feat(conta): modelos e funcao barbearias_do_whatsapp`.

### Task 2: Envio do código, limites e mensagens

**Files:**
- Create: `backend/app/services/conta_limites.py`, `backend/app/services/conta_codigos.py`
- Modify: `backend/app/services/whatsapp.py`, `backend/app/services/mensagens.py`
- Test: `tests/test_conta_codigos.py`, `tests/test_conta_limites.py`, acréscimos em `tests/test_mensagens.py`

**Interfaces:**
- Consumes: `ContaCliente`, `CodigoConta`, `FinalidadeCodigo` (Task 1); `hash_de_convite` (`services/senha.py`).
- Produces:
  - `conta_limites.motivo_para_nao_enviar(whatsapp: str, ip: str) -> str | None`: devolve `None`, `"numero"`, `"ip"` ou `"teto"`. Só confere. `conta_limites.registrar_envio(whatsapp: str, ip: str) -> None` conta o envio nas quatro janelas. Os contadores ficam no `cache` (`cache.add` + `cache.incr`, com timeout igual à janela), com prefixo `conta-envio:`.
  - `conta_codigos.novo_codigo(conta_id, finalidade) -> str`: gera 6 dígitos (`secrets.randbelow(10**6)`, com zero à esquerda) para `CONFIRMAR`, ou `secrets.token_urlsafe(32)` para `NOVA_SENHA`. **Invalida** os códigos ainda abertos da mesma conta e finalidade (`usado_em=agora`), grava só o hash e devolve o valor em claro **apenas para quem vai mandar a mensagem**.
  - `conta_codigos.conferir_codigo(conta_id, digitado: str) -> bool`: só para `CONFIRMAR`. Pega o código aberto mais novo. Se estiver vencido, usado ou com `tentativas >= CONTA_CODIGO_TENTATIVAS`, devolve False. Se o hash não bater, faz `tentativas += 1` e devolve False. Se bater, faz `usado_em=agora` e devolve True. Faz tudo num `select_for_update` dentro de `transaction.atomic()`.
  - `conta_codigos.consumir_link(token: str) -> ContaCliente | None`: para `NOVA_SENHA`, busca pelo hash. Se o link estiver vencido, usado ou a conta não estiver confirmada, devolve None. Senão, marca `usado_em` e devolve a conta.
  - `whatsapp.enviar_pelo_central(whatsapp_digitos: str, mensagem: str) -> bool`: sem `EVOLUTION_API_URL`, faz `logger.info` e devolve True (dev). Senão, `_enviar_aceita(...) is not None`.
  - `mensagens.msg_codigo_conta(codigo: str) -> str` e `mensagens.msg_link_nova_senha(link: str) -> str`.

- [ ] **Step 1: Testes que falham.**
  - `test_codigo_tem_seis_digitos_e_guarda_so_o_hash`: `len == 6`, `isdigit()`, e `CodigoConta.hash != codigo`.
  - `test_codigo_novo_invalida_o_anterior`: o primeiro não confere mais depois do segundo.
  - `test_codigo_vence_em_10_min`: com `freezegun` ou `agora` injetado, aos 10 min e 1 s dá False.
  - `test_cinco_erros_queimam_o_codigo`: 5 erros e depois o certo dá False.
  - `test_link_serve_uma_vez` e `test_link_vence_em_30_min`.
  - `test_limite_por_numero_3_por_hora`: o 4º dá `"numero"`. `test_limite_por_ip_10_por_hora`: com números diferentes, o 11º dá `"ip"`. `test_teto_geral`: com `CONTA_ENVIOS_POR_DIA` patchado para 2, o 3º, de outro número e outro IP, dá `"teto"`.
  - `test_msg_codigo_conta`: assert sobre o texto exato abaixo. `test_msg_link_nova_senha` idem.
- [ ] **Step 2: Rodar.** FAIL.
- [ ] **Step 3: Implementar.** Textos exatos:
  - `msg_codigo_conta`: `"*Marcaí*\nSeu código: *{codigo}*\nVale por 10 minutos. Não passa esse código pra ninguém."`
  - `msg_link_nova_senha`: `"*Marcaí*\nPra criar uma senha nova, abre: {link}\nO link vale por 30 minutos. Se não foi você, é só ignorar."`
- [ ] **Step 4: Rodar.** PASS.
- [ ] **Step 5: Commit** `feat(conta): codigos, limites de envio e mensagens`.

### Task 3: Sessão da conta e trava de senha

**Files:**
- Create: `backend/app/services/conta_sessao.py`, `backend/app/services/trava_conta.py`
- Test: `tests/test_conta_sessao.py`

**Interfaces:**
- Produces:
  - `conta_sessao.emitir(conta_id, tv: int) -> str`: HS256 com `SESSAO_JWT_SECRET` (o `_segredo()` de `sessao.py`, importado), claims `sub`, `tv`, `aud="cliente"` e `exp` = agora + `CONTA_SESSAO_DIAS`.
  - `conta_sessao.ler(token) -> dict | None`: `jwt.decode(..., algorithms=["HS256"], audience="cliente")`, com conferência de tipos igual à de `sessao.ler`. Devolve `{"sub": UUID, "tv": int}`.
  - `conta_sessao.conta_da_requisicao(request) -> ContaCliente | None`: lê o cookie `CONTA_SESSAO_COOKIE` e carrega a conta. Recusa se ela não estiver confirmada ou se `tv` for diferente de `token_version`.
  - `conta_sessao.dominio_do_cookie() -> str | None`: `None` quando `settings.DOMINIO_BASE` é `localhost` ou termina em `.localhost`. Nesse caso o cookie fica host-only no dev, e o login não atravessa subdomínios ali; isso fica comentado. Nos outros casos devolve `f".{DOMINIO_BASE}"`.
  - `conta_sessao.plantar(resposta, conta) -> resposta` e `conta_sessao.apagar(resposta) -> resposta`: httponly, `samesite="Lax"`, `secure=not settings.DEBUG`, `path="/"`, `domain=dominio_do_cookie()`, `max_age` de 30 dias.
  - `trava_conta.espera_de(whatsapp) -> float`, `registrar_falha(whatsapp)`, `limpar(whatsapp)`: espera exponencial de `CONTA_TRAVA_BASE_MS` até `CONTA_TRAVA_TETO_MS`, **sem bloqueio longo**, no cache e com chave pelo número. É uma cópia enxuta de `trava_ip.py`.

- [ ] **Step 1: Testes que falham.**
  - `test_emitir_e_ler_ida_e_volta`.
  - `test_token_de_barbeiro_nao_vale_como_conta`: `conta_sessao.ler(sessao.emitir(...)) is None`.
  - `test_token_de_conta_nao_vale_no_painel`: `sessao.ler(conta_sessao.emitir(...)) is None`. O PyJWT recusa `aud` quando nenhuma audiência é pedida, e o teste trava esse comportamento.
  - `test_tv_diferente_derruba`.
  - `test_dominio_do_cookie`: `localhost` → None, `brutus.localhost` → None, `usemarcai.online` → `.usemarcai.online` (com `settings` patchado).
  - `test_trava_cresce_e_tem_teto`.
- [ ] **Step 2: Rodar.** FAIL. **Step 3: Implementar.** **Step 4: Rodar.** PASS.
- [ ] **Step 5: Commit** `feat(conta): sessao propria de 30 dias e trava por numero`.

### Task 4: Criar, confirmar, entrar, sair, eu, esqueci, nova senha

**Files:**
- Create: `backend/app/services/conta.py`, `backend/app/api/v1/views/conta.py`, `backend/app/api/v1/serializers/conta.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `tests/test_conta_acesso.py`

**Interfaces:**
- Consumes: Tasks 1–3; `numero_existe` (`services/whatsapp.py`), `senha.gerar/confere/hash_descartavel`, `link_da_vitrine` (`services/convite.py`), `LimitaLogin`, `ExigeTenant`, `ip_de`.
- Produces (todas `ExigeTenant`; as que mandam mensagem ou conferem senha também são `LimitaLogin`):

| Rota | Corpo | Respostas |
|---|---|---|
| `POST /api/conta/criar` | `nome, whatsapp, senha` | 202 `{ok}` (código enviado) · 409 `"Esse WhatsApp já tem conta. Entra com sua senha."` · 422 validação/sem WhatsApp · 429 limite (`"Muitos códigos pedidos. Tenta de novo mais tarde."`) · 503 teto ou central fora (`"Não conseguimos mandar o código agora. Tenta de novo mais tarde."`) |
| `POST /api/conta/reenviar` | `whatsapp` | igual ao `criar`, só para conta pendente; para número sem conta pendente também devolve 202 (neutro) |
| `POST /api/conta/confirmar` | `whatsapp, codigo` | 200 `{nome, whatsapp}` + cookie · 400 `"Código errado ou vencido."` |
| `POST /api/conta/entrar` | `whatsapp, senha` | 200 `{nome, whatsapp}` + cookie · 401 `"WhatsApp ou senha errados."` · 429 trava |
| `POST /api/conta/sair` | — | 200, apaga o cookie (sem `ExigeTenant`, como `LogoutView`) |
| `GET /api/conta/eu` | — | 200 `{nome, whatsapp}` (WhatsApp formatado) · 401 |
| `POST /api/conta/esqueci` | `whatsapp` | **sempre** 202 `{ok}`, com ou sem conta confirmada (neutro), exceto 429/503 de limite |
| `POST /api/conta/nova-senha/<str:token>` | `senha` | 200 `{nome, whatsapp}` + cookie, `token_version += 1` · 404 `"Link inválido ou vencido."` · 422 senha curta |

Regras de `services/conta.py`:
- `criar`: o número passa por `normalizar` e depois `canonico`; nome com 2 caracteres ou mais e senha com `CONTA_SENHA_MINIMA` ou mais. Se `numero_existe(request.barbearia, ...) == "nao_existe"`, responde 422. Com conta confirmada, 409. Com conta **pendente**, substitui nome e senha. Depois `motivo_para_nao_enviar` → `novo_codigo` → `enviar_pelo_central`. Só faz `registrar_envio` quando o envio saiu. Se o envio falhou, responde 503.
- `entrar`: confere `trava_conta.espera_de` antes do argon2. Conta inexistente ou pendente roda `confere(hash_descartavel(), senha)` e responde 401, com o mesmo tempo de resposta.
- `esqueci`: o link é `f"{link_da_vitrine(request.barbearia.slug)}/conta/nova-senha/{token}"`. Abre no estabelecimento de onde o pedido veio.
- `confirmar`: `confirmada_em = agora` e `token_version += 1`.

- [ ] **Step 1: Testes que falham** (com `client`, `HOST`, `CABECALHO` de `test_agendamentos`, e `enviar_pelo_central` patchado para capturar `(numero, texto)`):
  - `test_criar_manda_codigo_e_a_resposta_nao_contem_o_codigo`: extrai o código do texto capturado com `re.search(r"\*(\d{6})\*")` e assere que ele **não** aparece em `r.content`.
  - `test_confirmar_com_codigo_certo_loga`: cookie `sessao_conta` presente e `GET /api/conta/eu` devolve 200.
  - `test_confirmar_com_codigo_errado_400_e_nao_loga`.
  - `test_criar_por_cima_de_conta_pendente_substitui` e `test_entrar_em_conta_pendente_e_recusado`.
  - `test_criar_com_conta_confirmada_409`.
  - `test_entrar_com_numero_em_outra_forma`: criou com `83982217869` e entra com `+55 83 8221-7869`.
  - `test_entrar_senha_errada_401_e_trava_cresce`.
  - `test_esqueci_responde_igual_com_e_sem_conta`: mesmo status e mesmo corpo. Só com conta envia mensagem.
  - `test_link_de_nova_senha_serve_uma_vez` e `test_nova_senha_derruba_sessao_antiga` (o cookie velho dá 401 em `/eu`).
  - `test_limite_de_envio_429` e `test_teto_geral_503`.
  - `test_sair_apaga_cookie`.
- [ ] **Step 2: Rodar.** FAIL. **Step 3: Implementar** serviço, serializers, views e rotas. **Step 4: Rodar.** PASS, e a suíte inteira verde.
- [ ] **Step 5: Commit** `feat(conta): criar, confirmar, entrar e nova senha`.

### Task 5: Histórico por estabelecimento e cancelar logado

**Files:**
- Modify: `backend/app/services/agendamentos.py`, `backend/app/api/v1/views/agendamentos.py`, `backend/app/api/v1/router.py`
- Create: `backend/app/services/conta_historico.py`; views em `backend/app/api/v1/views/conta.py`
- Test: `tests/test_conta_historico.py`

**Interfaces:**
- Consumes: `conta_da_requisicao` (Task 3), `barbearias_do_whatsapp` (Task 1), `formas_gravadas`.
- Produces:
  - `agendamentos.pode_cancelar(a: Agendamento, agora) -> bool`: extraída da conta que `detalhe_publico` e `cancelar_publico` fazem hoje. As duas passam a usá-la.
  - `agendamentos.cancelar_publico(barbearia_id, codigo, agora, *, whatsapps: list[str] | None = None) -> dict`: com `whatsapps`, um agendamento cujo `cliente.whatsapp` não está na lista dá `{"tipo": "nao_encontrado"}`.
  - `views/agendamentos.py`: `def depois_de_cancelar(barbearia: Barbearia, resultado: dict, agora) -> None`. É o bloco de mensagem e `lista_do_dia` que hoje mora em `AgendamentoCancelarPublicoView.post`, movido para cá **sem mudar o comportamento**. As duas views o chamam.
  - `conta_historico.historico(conta, barbearia_atual_id, agora) -> list[dict]`: um item por barbearia **ativa** devolvida pela função SQL. Cada item é `{"barbeariaId", "slug", "nome", "tipo", "agendamentos": [{"codigo", "servicoNome", "barbeiroNome", "inicio", "status", "podeCancelar"}]}`. Os agendamentos vêm em `inicio` decrescente, no máximo `CONTA_HISTORICO_POR_LUGAR`, lidos dentro de `com_barbearia(id)` com `cliente__whatsapp__in=formas_gravadas(conta.whatsapp)`. A barbearia atual vem primeiro, e as outras pelo agendamento mais recente.
  - `GET /api/conta/historico` → 200 `{"estabelecimentos": [...]}` · 401 sem sessão.
  - `POST /api/conta/agendamentos/<str:codigo>/cancelar` com corpo `{barbeariaId}` → mesmas respostas da rota pelo link (200 / 404 / 422 fora do prazo). A barbearia precisa estar em `barbearias_do_whatsapp`. Se não estiver, responde 404.

- [ ] **Step 1: Testes que falham.**
  - `test_historico_separa_por_lugar_e_atual_primeiro`: agendamentos na brutus e na dontony, pedido pelo host `dontony.localhost`, a primeira é a dontony.
  - `test_historico_acha_cliente_gravado_sem_o_nove`.
  - `test_historico_inclui_agendamento_de_antes_da_conta`.
  - `test_historico_esconde_barbearia_inativa`.
  - `test_historico_sem_sessao_401`.
  - `test_cancelar_logado_cancela_e_avisa_como_o_link`: status `CANCELADO_CLIENTE`, mensagem de cancelamento enviada e `avisar_mudanca` chamado.
  - `test_cancelar_logado_em_outro_lugar_pelo_host_atual`: logado no host da brutus, cancela um da dontony.
  - `test_cancelar_agendamento_de_outro_numero_da_404`: mesmo lugar, outro cliente, não cancela.
  - `test_cancelar_logado_fora_do_prazo_422`.
  - `test_bloqueado_logado_continua_recusado_ao_agendar`: no estilo de `test_bloqueio_no_site.py`, com o cookie da conta presente.
  - A suíte existente de cancelamento pelo link continua verde. O refactor não muda nada ali.
- [ ] **Step 2: Rodar.** FAIL. **Step 3: Implementar.** **Step 4: Rodar.** PASS, e a suíte inteira verde.
- [ ] **Step 5: Commit** `feat(conta): historico por lugar e cancelar logado`.

### Task 6 (front): API, rota migrada e lógica pura

**Files (Marcai-front, branch `conta-do-cliente`):**
- Create: `src/lib/api/contaAPI.ts`, `src/lib/conta.ts`
- Modify: `src/lib/api/client.ts` (`'/conta'` no `MIGRADAS`, com comentário no padrão da lista), `src/lib/api/index.ts` (se houver o barril, exportar `contaApi`)
- Test: `tests/conta.test.ts`, e `tests/client-base.test.ts` ganha o caso `/conta/historico`

**Interfaces:**
- Produces:
  - `type ContaEu = { nome: string; whatsapp: string }`
  - `type ItemHistorico = { codigo: string; servicoNome: string; barbeiroNome: string; inicio: string; status: string; podeCancelar: boolean }`
  - `type Lugar = { barbeariaId: string; slug: string; nome: string; tipo: string; agendamentos: ItemHistorico[] }`
  - `contaApi`: `eu()`, `criar({nome, whatsapp, senha})`, `reenviar(whatsapp)`, `confirmar(whatsapp, codigo)`, `entrar(whatsapp, senha)`, `sair()`, `esqueci(whatsapp)`, `novaSenha(token, senha)`, `historico(): Promise<Lugar[]>` (abre o envelope `estabelecimentos`), `cancelar(barbeariaId, codigo)`. **Nenhum `loginEm`**: 401 aqui é estado normal ("não logado").
  - `conta.ts`: `separarHistorico(itens: ItemHistorico[], agora: Date): { proximos: ItemHistorico[]; passados: ItemHistorico[] }`. Os próximos são os `inicio >= agora` e `CONFIRMADO`, em ordem crescente. Os passados são o resto, em ordem decrescente. Também `SENHA_MINIMA_CONTA = 6` e `codigoValido(s: string): boolean` (exatamente 6 dígitos).
- [ ] **Step 1: Testes que falham** (`separarHistorico` com cancelado futuro indo para passados, ordem; `codigoValido`; `baseDe('/conta/historico')` aponta para o Django).
- [ ] **Step 2: Rodar** `npm test`. FAIL. **Step 3: Implementar.** **Step 4:** `npm test` e `npx tsc --noEmit` passam.
- [ ] **Step 5: Commit** `feat(conta): cliente da API e logica do historico`.

### Task 7 (front): telas da conta e botão no topo

**Files:**
- Create: `src/app/conta/page.tsx`, `src/app/conta/nova-senha/[token]/page.tsx`, `src/components/conta/BotaoConta.tsx`, `src/components/conta/PortaDaConta.tsx` (entrar / criar / confirmar / esqueci, uma etapa por vez), `src/components/conta/Historico.tsx`, `src/components/conta/NovaSenha.tsx`
- Modify: `src/app/page.tsx` (o topo ganha `<BotaoConta />` à direita do nome) e `src/app/agendar/page.tsx` (o cabeçalho ganha o mesmo botão, fora do `<Link>` de voltar)

**Interfaces:**
- Consumes: `contaApi`, `separarHistorico`, `codigoValido`, `vocabulario`, `formatar` (`@/lib/telefone`), `Marca`.
- Produces: `BotaoConta` é `'use client'`. Chama `contaApi.eu()` ao montar. Deslogado, mostra "Entrar" → `/conta`. Logado, mostra a inicial do nome em círculo → `/conta`. Enquanto carrega, ocupa o mesmo espaço vazio, sem pular layout.
- `/conta`: deslogado, mostra `PortaDaConta`, que começa em "Entrar" (WhatsApp + senha) com os links "Criar conta" e "Esqueci a senha". "Criar" leva a "Confirmar" (6 dígitos, `inputMode="numeric"`, `autoComplete="one-time-code"`, e "reenviar código" liberado depois de 30 s). Logado, mostra `Historico`: um bloco por lugar com `Marca` e "{Lugar} {nome}", "Próximos" com o botão "Cancelar" (só quando `podeCancelar`, e com confirmação "Cancelar esse horário?"), "Anteriores" e "Sair" no fim. Lugar sem nenhum agendamento não aparece. Histórico vazio mostra "Você ainda não marcou nada por aqui."
- O texto do "esqueci" depois de enviar é sempre "Se esse WhatsApp tiver conta, mandamos um link pra lá.", independente da resposta.
- `/conta/nova-senha/[token]`: `NovaSenha` no padrão de `DefinirSenha.tsx`, com mínimo de 6. Ao terminar, mostra "Senha nova criada. Você já está logado." e um link para `/conta`.
- Visual: seguir o Figma do redesign (frames do fluxo do cliente) e as classes do `.fluxo`. O que o Figma não cobrir segue os componentes `wf` e os tokens que a página de agendar já usa.

- [ ] **Step 1:** implementar as telas.
- [ ] **Step 2:** `npx tsc --noEmit` e `npm test` passam.
- [ ] **Step 3: Verificar no navegador** com o skill `run`, o back desta branch e as migrations aplicadas (rodar `migrate` antes de abrir: contêiner já de pé com migration nova dá 500 em tudo). Fazer: criar conta em `brutus.localhost:3000/conta`, pegar o código **no log do Django**, confirmar, ver o histórico, cancelar um horário futuro, sair, entrar de novo, esqueci → abrir o link do log → senha nova. Telas no celular (390 px) e no desktop.
- [ ] **Step 4: Commit** `feat(conta): telas de entrar, criar, historico e nova senha`.

### Task 8 (front): agendar logado e convite na confirmação

**Files:**
- Modify: `src/components/FormAgendamento.tsx`, `src/components/Confirmado.tsx`

**Interfaces:**
- Consumes: `contaApi.eu()`.
- `FormAgendamento`: ao montar, `contaApi.eu()`. Se logado, preenche `nome` (editável) e `whats` (formatado, **somente leitura**), com a linha "Não é você? Sair" chamando `contaApi.sair()` e limpando os dois campos. O rascunho (`salvarRascunho`) não grava o WhatsApp da conta. Deslogado, o formulário fica exatamente como hoje.
- `Confirmado`: quando `contaApi.eu()` dá 401, mostra uma linha discreta abaixo do botão de cancelar, "Crie uma conta pra cancelar sem precisar deste link", ligando para `/conta`.

- [ ] **Step 1:** implementar. **Step 2:** `npx tsc --noEmit` e `npm test`. **Step 3:** no navegador: agendar logado (campos vindos da conta), agendar deslogado (igual a antes), ver o convite na confirmação deslogado e confirmar que ele não aparece logado.
- [ ] **Step 4: Commit** `feat(conta): agendar logado e convite na confirmacao`.

### Task 9: Fechamento

- [ ] Back: suíte inteira verde (`docker compose run --rm api pytest -q`). Front: `npm test` e `npx tsc --noEmit`.
- [ ] Conferir de novo que `SUBDOMINIOS_RESERVADOS` (`tenant/config.py`) contém `www` e `admin`. Já contém, mas o cookie no domínio pai depende disso.
- [ ] `grep -rn "codigo\|token" backend/app/api/v1/views/conta.py`: nenhuma `Response` carrega o valor gerado.
- [ ] Push das duas branches (`git push -u origin conta-do-cliente`) e PRs. A descrição do PR do back lista o Deploy: migration 0013, e que nenhuma variável nova é exigida. A ordem com a branch `mensalidade` (que também cria migration) é renumerar na hora do merge de quem entrar depois.
