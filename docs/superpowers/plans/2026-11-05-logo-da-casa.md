# Logo da casa — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o dono sobe a logo do negócio pela tela Equipe e ela aparece em destaque na vitrine e no agendado; sem logo, fica o desenho do tipo.

**Architecture:** a logo é uma data URL em `Barbearia.logo_url` (como `Barbeiro.foto_url`), escrita por `PUT /api/painel/logo` (só o dono) e lida por `GET /api/barbearia` e `GET /api/painel/barbearia`. No front, o navegador reduz a imagem sem cortar, e as telas do cliente apontam para a rota `GET /logo?v=<versão>` do Next, que devolve os bytes com cache longo em vez de embutir a data URL no HTML.

**Tech Stack:** Django + DRF + Postgres com RLS e GRANT por coluna (back), Next.js App Router + Tailwind + Vitest (front).

**Spec:** `docs/superpowers/specs/2026-11-05-logo-da-casa-design.md` (neste repo, branch `logo-da-casa`).

## Global Constraints

- Repos e worktrees: back em `Marcai-back/.claude/worktrees/logo-da-casa` (branch `logo-da-casa`, já criada, sem upstream); front em `Marcai-front/.claude/worktrees/logo-da-casa`, criada com `git worktree add -b logo-da-casa --no-track .claude/worktrees/logo-da-casa origin/main`. Primeiro push com `git push -u origin logo-da-casa`. Conferir que `@{u}` nunca é `origin/main`.
- Nunca commitar na `main`. PRs separados, back primeiro. O merge é do José.
- Formatos aceitos: `image/webp`, `image/jpeg`, `image/png`. SVG e `https://` recusados.
- `LOGO_LADO_MAXIMO_PX = 512` (lado maior, sem ampliar e sem cortar). `LOGO_TAMANHO_MAXIMO_BYTES = 60 * 1024` (bytes decodificados).
- Mensagens ao usuário em português, curtas, no tom de `app/services/foto.py`.
- A frase do ramo (`v.slogan`) sai da vitrine sempre. O nome não se repete embaixo da logo.
- A foto do profissional não muda de regra: cada um põe a sua.
- Back: `docker compose run --rm api pytest -q` (rodado de dentro da worktree do back). Front: `npm test` e `npx next typegen && npx tsc --noEmit` (na worktree do front, depois de `npm ci`).
- Comentários no estilo do repo: o porquê, em português.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. PNG com fundo transparente tem de continuar transparente na vitrine (o WebP do canvas guarda alfa; o JPEG não, então ele só entra como última saída). Checagem manual na Task 7.
2. Logo pequena (por exemplo 80×80) não pode ser ampliada, e logo muito comprida (2000×100) não pode ser cortada nem achatada. Teste em `medidasDaLogo` (Task 3).
3. Trocar a logo tem de aparecer na hora para o cliente, sem cache velho: a versão na URL muda com o conteúdo. Teste em `versaoDaLogo` (Task 3).
4. Tirar a logo volta ao desenho do tipo, e `/logo` responde 404, nunca 500. O mesmo vale para uma data URL estragada no banco. Teste em `respostaDaLogo` (Task 4).
5. Barbeiro que não é dono, ou sem sessão, não troca a logo. Teste no back (Task 1).

---

### Task 0: trazer o `Marcai-back#68` para a branch

**Files:** nenhum novo.

- [ ] **Step 1:** `git fetch origin && git merge-base --is-ancestor origin/suite-sem-zap origin/main && echo ja-na-main`. Se não imprimir `ja-na-main`, `git cherry-pick ca72202` (commit "Suite de testes nao fala com a Evolution do ambiente").
- [ ] **Step 2:** `grep -n EVOLUTION_API_URL tests/conftest.py` mostra o `delenv`. Só depois disso rodar a suíte inteira.

### Task 1: back — campo, validação e `PUT /api/painel/logo`

**Files:**
- Create: `backend/tenant/migrations/0020_logo_da_casa.py` (renumerar se outra 0020 entrar antes)
- Modify: `backend/tenant/models.py` (`Barbearia`, perto de `horario_resumo`)
- Modify: `backend/tenant/config.py` (ao lado de `FOTO_*`)
- Create: `backend/app/services/logo.py`
- Create: `backend/app/api/v1/views/logo.py`
- Modify: `backend/app/api/v1/router.py` (perto de `painel/foto`)
- Test: `tests/test_logo.py`

**Interfaces:**
- Produces: coluna `Barbearia.logo_url = models.TextField(null=True)`; `LOGO_LADO_MAXIMO_PX = 512`, `LOGO_TAMANHO_MAXIMO_BYTES = 60 * 1024`, `LOGO_MIMES = FOTO_MIMES`; `logo_invalida(valor: str) -> str | None`; `definir_logo(barbearia_id: str, logo: str | None) -> None`; rota `PUT /api/painel/logo` com corpo `{"logo": "<data URL>" | null}` → `200 {"ok": true}`, `422 {"erro": ...}`, `403 {"erro": "Só o dono muda a logo."}`.

- [ ] **Step 1: testes que falham** em `tests/test_logo.py`, no molde de `tests/test_foto.py` (mesmo `pytestmark`, `CABECALHO`, `_barbeiro`, `_logar`, `_data_url`, fixture `cenario`):
  - `test_dono_poe_a_logo`: PUT com `_data_url()` → 200; `Barbearia.objects.using("owner").get(id=...).logo_url` começa com `data:image/webp;base64,`.
  - `test_tirar_a_logo_volta_ao_padrao`: depois de pôr, PUT `{"logo": None}` → 200 e `logo_url is None`.
  - `test_barbeiro_nao_troca_a_logo`: papel `BARBEIRO` → 403, `{"erro": "Só o dono muda a logo."}`, coluna intacta.
  - `test_sem_sessao_nao_entra`: sem cookie → 401 (o mesmo status que `test_foto.py::test_sem_sessao_nao_entra` espera).
  - `test_svg_e_recusado`: `_data_url("image/svg+xml", b"<svg/>")` → 422, `"Essa imagem não serve. Manda a logo em JPG, PNG ou WebP."`.
  - `test_url_comum_e_recusada`: `"https://exemplo.com/logo.png"` → 422, `"Manda a logo pelo botão da tela."`.
  - `test_logo_grande_demais_e_recusada`: `bytes_=b"x" * (60 * 1024 + 1)` → 422, `"A logo ficou grande demais. Tenta outra?"`; e exatamente `60 * 1024` bytes → 200.
  - `test_base64_quebrado_e_recusado`: `"data:image/png;base64,@@@"` → 422 (qualquer `erro`).
  - `test_logo_que_nao_e_texto_e_recusada`: `{"logo": 123}` → 422, `"Manda a logo pelo botão da tela."`.
- [ ] **Step 2:** `docker compose run --rm api pytest -q tests/test_logo.py` → FAIL (404 na rota).
- [ ] **Step 3: migration** `0020_logo_da_casa`: `AddField` de `logo_url` + `RunSQL(["GRANT UPDATE (logo_url) ON tenant_barbearia TO brutus_app;"], ["REVOKE UPDATE (logo_url) ON tenant_barbearia FROM brutus_app;"])`, como a `0009_hora_da_lista.py`. Sem o GRANT, o painel (que roda como `brutus_app`) leva `permission denied`.
- [ ] **Step 4: `app/services/logo.py`.** `logo_invalida` repete a regra de `foto_invalida` com as constantes e as frases da logo (reaproveite o `_DATA_URL` de `foto.py`, importando). `definir_logo` faz `Barbearia.objects.filter(id=...).update(logo_url=...)` dentro de `com_barbearia`.
- [ ] **Step 5: `LogoView(ExigeDono, APIView)`** com `mensagem_papel_insuficiente = "Só o dono muda a logo."` e `put` no molde do `FotoView`, sem `barbeiroId`. Registrar `path("painel/logo", LogoView.as_view(), name="painel-logo")`.
- [ ] **Step 6:** `docker compose run --rm api pytest -q tests/test_logo.py` → PASS.
- [ ] **Step 7: commit** `logo: o dono sobe a logo da casa pelo painel`.

### Task 2: back — `logoUrl` nas leituras

**Files:**
- Modify: `backend/app/services/barbearia.py` (`ler()` inclui `"logo_url"`)
- Modify: `backend/app/api/v1/views/barbearia.py` e `barbearia_painel.py` (`"logoUrl": dados["logo_url"]`)
- Modify: `backend/app/admin.py` (opcional: `logo_url` só de leitura ou fora do form; não deixar um textarea de 80 KB no admin)
- Test: `tests/test_barbearia_publica.py`, `tests/test_barbearia_painel.py`

**Interfaces:**
- Produces: `GET /api/barbearia` e `GET /api/painel/barbearia` com `logoUrl: string | null`.

- [ ] **Step 1: testes que falham:** `test_vitrine_sem_logo_devolve_logo_url_nulo` (`logoUrl is None`) e `test_vitrine_devolve_a_logo` (gravada pelo `owner` → igual ao valor gravado) no público; `test_painel_devolve_a_logo` no painel.
- [ ] **Step 2:** rodar os dois arquivos → FAIL (`KeyError`/chave ausente).
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar os dois arquivos → PASS. Depois a suíte inteira `docker compose run --rm api pytest -q` → tudo verde (só com a Task 0 feita).
- [ ] **Step 5: commit** `logo: vitrine e painel leem a logo`.
- [ ] **Step 6: PR do back.** `git push -u origin logo-da-casa`, `gh pr create` com o resumo, a ordem do deploy (back antes do front, migration 0020) e o rodapé `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Esperar o CI.

### Task 3: front — preparar a logo no navegador (lógica pura)

Worktree do front: `git worktree add -b logo-da-casa --no-track .claude/worktrees/logo-da-casa origin/main`, `npm ci`, copiar o `.env` do checkout principal (o `npm test` usa `dotenv -e .env`).

**Files:**
- Create: `src/lib/logo.ts`
- Modify: `src/lib/tenant.ts` (`Barbearia.logoUrl?: string | null`)
- Modify: `src/lib/api/painelAPI.ts` (`DadosDaBarbearia.tipo`, `paleta`, `logoUrl: string | null`; `painelApi.definirLogo`)
- Test: `tests/logo.test.ts`

**Interfaces:**
- Produces:
  - `LADO_MAXIMO = 512`, `TETO_BYTES = 60 * 1024` (espelham o `tenant/config.py`, com comentário dizendo isso)
  - `medidasDaLogo(largura: number, altura: number): { largura: number; altura: number }`
  - `versaoDaLogo(dataUrl: string): string` (12 caracteres hex, estável e sem `crypto` do Node, porque roda nos dois lados; FNV-1a ou similar)
  - `class ErroDeLogo extends Error`
  - `prepararLogo(arquivo: File): Promise<string>` (navegador)
  - `painelApi.definirLogo(logo: string | null) => Promise<{ ok: true }>` (`PUT /painel/logo`)

- [ ] **Step 1: testes que falham** em `tests/logo.test.ts`:
  - `medidasDaLogo(1024, 1024)` → `{ largura: 512, altura: 512 }`
  - `medidasDaLogo(2000, 100)` → `{ largura: 512, altura: 26 }` (arredonda, mínimo 1)
  - `medidasDaLogo(300, 900)` → `{ largura: 171, altura: 512 }`
  - `medidasDaLogo(80, 80)` → `{ largura: 80, altura: 80 }` (não amplia)
  - `versaoDaLogo(a) === versaoDaLogo(a)`, `versaoDaLogo(a) !== versaoDaLogo(b)` para duas data URLs que diferem em um caractere, e `/^[0-9a-f]{12}$/`.
- [ ] **Step 2:** `npx vitest run tests/logo.test.ts` → FAIL.
- [ ] **Step 3: implementar.** `prepararLogo` segue `prepararFoto` (`src/lib/foto.ts`): mesma checagem de tipo e de leitura, mas desenha a imagem INTEIRA em `medidasDaLogo(...)`, sem recorte e sem preencher o fundo. Tenta `image/webp` (guarda alfa) e depois `image/png` (alfa, sem qualidade), e só então `image/jpeg`, com a mesma queda de qualidade por degraus e a mesma medida de bytes. Se nada couber: `ErroDeLogo('Essa logo é pesada demais. Tenta uma mais simples?')`.
- [ ] **Step 4:** `npx vitest run tests/logo.test.ts` → PASS.
- [ ] **Step 5: commit** `logo: preparar a logo no navegador sem cortar`.

### Task 4: front — rota `GET /logo`

**Files:**
- Create: `src/app/logo/route.ts`
- Modify: `src/lib/logo.ts`
- Test: `tests/logo.test.ts`

**Interfaces:**
- Consumes: `buscarNoDjango` e `Barbearia` de `@/lib/tenant` (como `src/app/miniatura/route.tsx`, que não usa `barbeariaAtual()` porque ela chama `notFound()`).
- Produces:
  - `respostaDaLogo(logoUrl: string | null | undefined): { tipo: string; bytes: Uint8Array } | null` (pura: `null` para ausente, mime fora da lista ou base64 estragado)
  - `srcDaLogo(logoUrl: string | null | undefined): string | null` → `` `/logo?v=${versaoDaLogo(logoUrl)}` `` ou `null`
  - `GET /logo`: 200 com `Content-Type` do mime e `Cache-Control: public, max-age=31536000, immutable`; 404 sem logo, com logo estragada ou se o Django falhar.

- [ ] **Step 1: testes que falham:** `respostaDaLogo(null)` e `respostaDaLogo(undefined)` → `null`; `respostaDaLogo('data:image/svg+xml;base64,PHN2Zy8+')` → `null`; `respostaDaLogo('data:image/png;base64,@@@')` → `null`; com uma data URL PNG válida → `tipo === 'image/png'` e os bytes decodificados iguais aos originais; `srcDaLogo(null) === null`; `srcDaLogo(x)` começa com `/logo?v=`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3: implementar** `respostaDaLogo`, `srcDaLogo` e o `GET`. O `proxy.ts` casa `/logo` (o matcher pega quase tudo): conferir que ele só repassa e não reescreve para o Django.
- [ ] **Step 4:** rodar → PASS.
- [ ] **Step 5: commit** `logo: rota /logo serve a imagem com cache longo`.

### Task 5: front — vitrine e agendado

**Files:**
- Create: `src/components/LogoDaCasa.tsx`
- Modify: `src/components/Vitrine.tsx` (prop `logoSrc: string | null`; troca o `<Marca ... tamanho={96}>` por `<LogoDaCasa>`; tira o `<p>` do `v.slogan` e o comentário dele)
- Modify: `src/app/page.tsx` (passa `logoSrc={srcDaLogo(b.logoUrl)}`)
- Modify: `src/app/agendamento/[codigo]/page.tsx` (topo + logo acima do `<Confirmado>`)
- Test: tipagem, mais a checagem na Task 7

**Interfaces:**
- Consumes: `srcDaLogo` (Task 4), `Marca` (`src/components/Marca.tsx`).
- Produces: `LogoDaCasa({ src, tipo, nome, altura }: { src: string | null; tipo?: Tipo; nome: string; altura: number })`. Sem hook, para servir ao Server e ao Client Component. Com `src`: `<img src alt={`logo ${nome}`} style={{ maxHeight: altura }} className="max-w-full w-auto h-auto object-contain mx-auto">`, sem `rounded` e sem fundo. Sem `src`: `<Marca tipo nome tamanho={altura === 120 ? 96 : altura} className="rounded-wf">` (o desenho mantém os 96px de hoje na vitrine).

- [ ] **Step 1:** `LogoDaCasa`. Vitrine com `altura={120}`; o resto do cartaz (rua, horário, equipe, preços) fica igual.
- [ ] **Step 2:** página de agendado. Antes do `<Confirmado>`, o mesmo topo da vitrine (o `div` de `page.tsx` com `<Marca tamanho={30}>` e o nome `{v.lugar} {b.nome}`, sem o `BotaoConta`), extraído para `src/components/TopoDaCasa.tsx` e usado nas duas páginas. Depois, `<LogoDaCasa altura={96}>` centralizada. Vale também no estado cancelado, porque está na página e não dentro do `Confirmado`.
- [ ] **Step 3:** `npm test` e `npx next typegen && npx tsc --noEmit` → verdes. Se algum teste citava `slogan` na vitrine, ajustar à regra nova (a frase não aparece).
- [ ] **Step 4: commit** `vitrine e agendado: a logo da casa no lugar do desenho e da frase`.

### Task 6: front — os dois blocos no alto da Equipe

**Files:**
- Create: `src/components/painel/LogoDaCasaPainel.tsx`
- Create: `src/components/painel/SuaFoto.tsx`
- Create: `src/components/painel/useTrocarMinhaFoto.ts`
- Modify: `src/components/painel/NavPainel.tsx` (passa a usar o hook)
- Modify: `src/app/painel/equipe/page.tsx`

**Interfaces:**
- Consumes: `prepararLogo`, `ErroDeLogo`, `painelApi.definirLogo`, `barbeariaApi.ver` (agora com `tipo`, `paleta` e `logoUrl`), `paleta()` de `@/lib/paletas` (cor `fundo` da paleta do cliente), `prepararFoto`, `painelApi.definirFoto`, `useEu()`/`lembrar` do `SessaoDoPainel`.
- Produces: `useTrocarMinhaFoto(): { trocar(arquivo: File | undefined): Promise<void>; tirar(): Promise<void>; erro: string }`, que é a lógica que hoje mora em `NavPainel.trocarFoto`, extraída sem mudar o comportamento, mais `tirar` (`definirFoto(null)`, mesma atualização de `eu` e `lembrar`).

- [ ] **Step 1:** extrair o hook e passar o `NavPainel` a usá-lo. O botão do cabeçalho continua igual.
- [ ] **Step 2:** `LogoDaCasaPainel`: busca `barbeariaApi.ver()`, desenha a logo (data URL direto, é o painel) ou `<Marca>` dentro de uma caixa com `style={{ background: paleta(dados.paleta).fundo }}` (usar o nome real do campo em `lib/paletas.ts`), a frase "assim ela aparece para o cliente", **trocar** (input `file` escondido, `accept="image/png,image/jpeg,image/webp"`) e **tirar** (só com logo). Erro em `ErroDeLogo` ou `mensagemDoErro`, como a foto faz.
- [ ] **Step 3:** `SuaFoto`: o `Avatar` do `eu`, a frase "aparece na hora de escolher com quem marcar", **trocar** e **tirar** pelo hook.
- [ ] **Step 4:** na Equipe, no ramo do dono, antes de `<Equipe>`: um `grid grid-cols-1 sm:grid-cols-2 gap-3` com os dois blocos, depois um `<Fio>`. Títulos e botões com as peças de `components/painel/pecas.tsx`.
- [ ] **Step 5:** `npm test` e `npx next typegen && npx tsc --noEmit` → verdes.
- [ ] **Step 6: commit** `equipe: logo da casa e sua foto no alto`.

### Task 7: ver de verdade e abrir o PR do front

- [ ] **Step 1:** subir o dev com o back da branch (migration 0020 aplicada: `docker compose run --rm api python manage.py migrate`; ver a memória "Migration no dev ao vivo") e o front da worktree.
- [ ] **Step 2:** como dono no painel, pôr uma logo PNG transparente comprida, uma redonda e uma de 80×80. Conferir no navegador:
  - a Equipe mostra a prévia sobre o fundo da paleta;
  - a vitrine mostra a logo sem corte e sem ampliar, sem a frase e sem o nome embaixo;
  - o agendado tem o topo e a logo;
  - o `curl -sI <host>/logo?v=...` dá 200, `image/webp` e o cache longo;
  - tirar a logo volta ao desenho, e `/logo` dá 404;
  - uma casa sem logo continua igual à de hoje, menos a frase.
- [ ] **Step 3:** se algo falhar, voltar à task dona do problema.
- [ ] **Step 4: PR do front.** `git push -u origin logo-da-casa`, `gh pr create` dizendo que depende do back (link do PR) e com o rodapé do Claude Code. Esperar o CI.
- [ ] **Step 5:** remover as duas worktrees (o `__pycache__` do root sai com o `docker run --rm --entrypoint "" -v <pasta>:/w marcai-back-api rm -rf /w/<nome>`, ver a memória "Sem worktree aberta"), depois de conferir que não sobrou nada sem push.
