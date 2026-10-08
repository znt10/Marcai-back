# Marcaí para outros tipos de negócio (barbearia, sobrancelha, outro) + paletas

## Contexto

O Marcaí foi vendido para a Brutus (barbearia). A esposa do dono faz design de
sobrancelha e gostou; uma vizinha que faz sobrancelha também tem agenda lotada.
Hoje tudo diz "barbearia"/"barbeiro" e a identidade é madeira e latão. Objetivo:
ao criar um estabelecimento, José escolhe o **tipo** e a **paleta**, e o que o
cliente e a profissional veem se adapta — palavras e cores. Sucesso: a cliente
da sobrancelha abre o link e não vê nada de barbearia; a profissional usa o
painel sem estranhar; a Brutus não muda nada.

## Decisões do José (07–08/10/2026)

- **Tipos, lista pronta:** `BARBEARIA`, `SOBRANCELHA`, `OUTRO`. Tipo novo
  (manicure, salão) entra quando ele pedir.
- **Palavras:** barbearia = "a barbearia" / "o barbeiro" (como hoje);
  sobrancelha = "o estúdio" / "a profissional"; outro = "o espaço" / "o
  profissional".
- **Serviços:** nascem vazios, digitados à mão (como hoje).
- **Paletas, lista pronta, escolhida ao criar; o tipo só sugere a padrão:**
  Preto e amarelo (a de hoje; padrão da barbearia), Branco e rosé (padrão da
  sobrancelha), Preto e rosé, Branco e dourado (padrão do outro).
- **Onde a paleta vale:** as telas do cliente usam a paleta inteira; o painel
  mantém claro/escuro e o desenho do Figma, trocando só a cor de destaque.
- **Estabelecimento separado:** a esposa e a vizinha ganham cada uma o seu
  Marcaí. O tipo é do estabelecimento, não do profissional.
- **Uma profissional só:** o passo "Escolha a profissional" some e ela vem
  escolhida (vale para todos os tipos).
- José escolhe tipo e paleta no admin, ao criar. Para trocar depois, usa o admin
  do Django; o dono não troca.

**Fora deste trabalho:** os textos do bot (parado por decisão do José; quando
ele voltar, alinhar), a página institucional do domínio raiz e a de
apresentação no GitHub Pages, as cores do gráfico do Resumo e a criação de
serviços sugeridos.

## Back (Marcai-back) — um PR

1. **Modelo e migration 0010** (`backend/tenant/models.py`, padrão de
   `PlanoBarbearia`): `TipoNegocio` (BARBEARIA|SOBRANCELHA|OUTRO, padrão
   BARBEARIA) e `Paleta` (PRETO_AMARELO|BRANCO_ROSE|PRETO_ROSE|BRANCO_DOURADO,
   padrão PRETO_AMARELO) em `Barbearia.tipo` e `Barbearia.paleta`. Sem GRANT
   novo: só o `brutus_admin` escreve, e o GRANT de tabela da 0004 já cobre
   coluna nova. Com os padrões, a Brutus e as barbearias de hoje ficam iguais.
2. **Vocabulário do back**: um módulo `backend/tenant/tipos.py` com a tabela
   por tipo e só os campos que o back usa (`do_lugar` para o nome do
   estabelecimento, `o_lugar`, `esse_prof`, `desativado`) e a paleta padrão de
   cada tipo.
3. **Admin da plataforma** (`views/admin_barbearias.py`,
   `services/admin_barbearias.py`):
   - `POST` aceita `tipo` e `paleta`, ambos opcionais, validados como o
     `plano` já é. A paleta, se ausente, vem do tipo.
   - O `GET` da lista passa a devolver os dois.
   - O `criar()` e o `reemitir_convite()` levam `tipo` para o convite.
4. **Leitura pelo front**: `services/barbearia.py::ler()`, `GET /api/barbearia` e
   `GET /api/painel/barbearia` passam a devolver `tipo` e `paleta`.
5. **Textos que chegam a pessoas hoje:**
   - `msg_convite`: barbearia continua "equipe da {nome}"; sobrancelha "equipe
     do estúdio {nome}"; outro "equipe do espaço {nome}". Recebe `tipo` com
     padrão BARBEARIA. Chamadores: `admin_barbearias.py` e `equipe.py`.
   - `views/agendamentos.py:139`, "Chama a barbearia no zap" → `o_lugar`.
   - `views/equipe.py:137`, "Esse barbeiro está desativado" → `esse_prof` e
     `desativado` ("Essa profissional está desativada").
   - `services/agendamentos.py:89`, "Esse barbeiro não faz esse serviço." → texto
     neutro ("Quem você escolheu não faz esse serviço."), porque `marcar()` só
     tem o id da barbearia e a frase também aparece no bot.
6. **Testes**:
   - Novos: criar com e sem tipo/paleta, tipo ou paleta inválidos (422), a
     paleta vindo do tipo, a lista e as duas leituras com os campos, o
     `msg_convite` em cada tipo, e as frases de erro de um estúdio.
   - Ajustes por campo novo: `test_barbearia_publica.py:15` (dict exato) e os
     POSTs do admin do Django em `test_admin_django_barbearia.py`, que precisam
     de `tipo` e `paleta`.
7. **Spec**: este plano vai para
   `docs/superpowers/specs/2026-10-08-tipos-de-negocio-design.md` no primeiro
   commit.

## Front (Marcai-front) — um PR, depende do back

1. **`src/lib/tipos.ts`**: a fonte única das palavras.
   - O tipo `Tipo` e a tabela `VOCABULARIO`, com os campos `lugar`, `oLugar`,
     `doLugar`, `noNome(nome)` ("na Brutus" / "no estúdio Ana" / "no espaço
     X"), `prof`, `Prof`, `profs`, `oProf`, `noProf` ("no barbeiro" / "na
     profissional"), `atendimento`/`atendimentos` ("corte"/"cortes" ou
     "atendimento"/"atendimentos"), `slogan` e `exemploServico`.
   - `vocabulario(tipo?)`, que cai na barbearia quando o tipo vier vazio (back
     antigo).
2. **`src/lib/paletas.ts`**: a fonte única das cores.
   - Por paleta: os tokens do cliente (`fundo`, `superficie`, `tinta`, `acento`,
     `latao`…), o destaque do painel no escuro e no claro, e a cor da barra do
     navegador.
   - `estiloDaPaleta(p)` devolve as variáveis CSS (`--color-*`,
     `--painel-acento-escuro`, `--painel-acento-claro`).
   - Preto e amarelo = os valores de hoje.
   - Valores iniciais propostos, ajustáveis: rosé claro `#a4505e` sobre
     `#fbf6f4`; rosé no escuro `#f0a6b4`; dourado claro `#8a6516`; dourado no
     escuro `#e8c26b`.
3. **Ler o tipo e a paleta sem quebrar telas sem tenant**: em `src/lib/tenant.ts`
   - `Barbearia` ganha `tipo` e `paleta`.
   - Uma leitura em `cache()` que devolve `null` em vez de `notFound()`, reusada
     pelo `barbeariaAtual()`, para não buscar duas vezes.
4. **Paleta aplicada**:
   - Em `src/app/layout.tsx`, o layout raiz fica `async`, lê a barbearia (ou
     nada, em admin, institucional e 404) e põe `style={estiloDaPaleta(...)}` no
     `<html>`. Assim as cores já vêm prontas do servidor, sem pisca.
   - `generateViewport` passa a usar a cor da paleta.
   - Em `globals.css`, `.painel` troca o `--color-acento` fixo por
     `var(--painel-acento-escuro, <atual>)` e, no claro, por
     `var(--painel-acento-claro, <atual>)`.
   - `miniatura/route.tsx` e `manifest.ts` usam a tabela de paletas no lugar das
     cores escritas à mão.
5. **Palavras aplicadas**: todas as telas trocam o texto fixo por
   `vocabulario(tipo)`.
   - Cliente: cada página do servidor chama `barbeariaAtual()` e passa `tipo`
     como prop para os componentes de cliente. Exemplos:
     - `src/app/page.tsx` (h1, título e "Marcar horário na…")
     - `Vitrine.tsx` (slogan, "barbeiros")
     - `agendar/page.tsx`
     - `FormAgendamento.tsx` (título do passo, notas)
     - `guia.ts`: `TEXTO_DO_PASSO` vira função do vocabulário
     - `Confirmado.tsx`
   - Sem tenant, texto neutro: `calendario/page.tsx` ("Escolhe quem vai te
     atender e o serviço antes."), `not-found.tsx` / `nao-encontrada`.
   - Painel: `src/app/painel/layout.tsx`, que é do servidor, lê o tipo e o
     entrega por um provider com o hook `useVocabulario()`. Usam:
     - `NavPainel` (selo do papel)
     - `Equipe`, `FormBarbeiro` e `FormMarcar`
     - `Resumo` e `PizzaDeCortes` ("cortes" → `atendimentos`)
     - `Servicos` (5 frases e o placeholder `exemploServico`)
     - `painel/whatsapp/page.tsx`
   - Admin: `FormBarbearia.tsx` ganha os seletores de tipo e paleta (a paleta
     acompanha o tipo até ser mexida à mão), e as frases e a lista viram
     neutras ("estabelecimento"), mostrando o tipo de cada um.
6. **Uma profissional só**: em `FormAgendamento.tsx`, com
   `barbeiros.length === 1` ela já vem escolhida e o passo 01 não aparece. As
   etapas são renumeradas, e o guia começa no serviço sem mudar
   `proximoPasso`, porque `barbeiroId` já vem preenchido. É o mesmo critério de
   `FormMarcar.tsx:95`.
7. **Testes (vitest, sem DOM)**:
   - `tipos.test.ts`: todo tipo tem todos os campos, "na Brutus" / "no estúdio
     Ana", e o tipo vazio cai na barbearia.
   - `paletas.test.ts`: contraste ≥ 4.5:1 em tinta/fundo, acento/fundo e
     texto/acento (o `Box fill` usa `text-fundo` sobre `bg-acento`), e os dois
     destaques do painel contra os fundos do painel.
   - `guia.test.ts`: os textos de cada tipo.
   - Auto-escolha da profissional única como função pura.

## Ordem e PRs

Branches criadas com `git switch -c X --no-track origin/main` (memória
`branch-sem-rastrear-main`), em worktrees.

1. **Back primeiro.** A migration 0010 roda sozinha no Deploy. No dev, rodar
   `docker exec Marcai-back-api python manage.py migrate --database=owner`
   depois do pull (memória `dev-migration-ao-vivo`).
2. **Front depois** (ou junto). Com o back antigo, `tipo` e `paleta` vêm vazios e
   tudo cai em barbearia com preto e amarelo, então não quebra.

## Verificação

- **Back**: a suíte inteira no contêiner (`docker run … marcai-back-api python -m
  pytest`) e `makemigrations --check`.
- **Front**: `next typegen`, `tsc --noEmit` e `npm test`, como no CI.
- **De ponta a ponta no dev** (docker de pé; Chrome pelo claude-in-chrome se
  estiver conectado, senão o Chrome headless, com captura do console, como no
  diagnóstico do aviso do `<script>`):
  1. No `/admin`, criar "Ana Sobrancelhas" (slug `ana`), tipo sobrancelha;
     conferir que a paleta sugerida é branco e rosé.
  2. Em `ana.localhost:3000`: fundo claro e rosé, "estúdio Ana Sobrancelhas",
     nenhum "barbeiro" na página, no agendar, no guia ou na confirmação.
  3. Com uma profissional só, o agendar começa no serviço.
  4. Painel da Ana, no claro e no escuro: destaque rosé, "Profissional" no
     selo, "atendimentos" no Resumo.
  5. O texto do convite (log do worker ou Evolution) diz "equipe do estúdio Ana
     Sobrancelhas".
  6. `brutus.localhost:3000` igual a antes, em preto e amarelo com "barbeiro".
  7. Trocar a paleta da Ana para preto e rosé pelo admin do Django e ver a
     página escura com rosé.
