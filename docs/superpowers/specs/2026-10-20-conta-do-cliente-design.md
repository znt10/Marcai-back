# Conta do cliente — design

Data: 20/10/2026. Repositórios: Marcai-back e Marcai-front.

## Por que

Hoje o cliente agenda só com nome e WhatsApp, sem conta. O único jeito de
cancelar é o link `/agendamento/<codigo>` que chega na confirmação pelo
WhatsApp. O José percebeu, testando com mensagem temporária, que quem perde
essa mensagem (temporária, conversa apagada, celular trocado) **nunca mais
consegue cancelar**. O barbeiro fica com um horário que a pessoa não vai
usar, e ela não tem como avisar pelo site.

A solução dele é uma conta opcional do cliente, com o histórico de tudo que
ele marcou e o cancelamento a partir dali, sem depender do link.

## Objetivos

1. Quem tem conta cancela os próprios horários futuros sem precisar do link.
2. Quem tem conta vê o histórico, **separado por estabelecimento**.
3. Logado, o formulário de agendar já vem com nome e WhatsApp preenchidos.
4. A conta prova que o número é da pessoa: ninguém entra na conta de um
   WhatsApp que não é dele.

## Não-objetivos

- Tornar a conta obrigatória. Agendar sem conta continua exatamente como hoje,
  e o link de cancelamento continua funcionando.
- Remarcar pelo histórico (só cancelar). Remarcar = cancelar e agendar de novo.
- Conta para a equipe: barbeiro e dono continuam com o login do painel.
- Login por Google, e-mail, etc.

## Anti-objetivos (se acontecer, falhou mesmo funcionando)

- Alguém consegue ver ou cancelar horários de um número que não é dele.
- A conta vira jeito de furar o bloqueio de cliente
  (Marcai-back#45): bloqueado numa barbearia continua bloqueado lá, logado ou
  não.
- O pedido de código vira um jeito de mandar mensagens em massa para o
  WhatsApp de alguém pelo número central, ou de queimar o chip central.
- Agendar sem conta fica mais lento ou ganha qualquer passo a mais.

## O que o José decidiu

- **Conta única do Marcaí, global**, que vale em todas as barbearias e
  estúdios. Quem já entrou numa não entra de novo na outra.
- **Criar conta:** nome, WhatsApp e senha. Na **primeira vez** chega um
  código de confirmação no WhatsApp, e a pessoa tem de digitar o código para a
  conta passar a valer.
- **Entrar depois:** WhatsApp + senha, sem código.
- **Fica logado pelo menos 30 dias.**
- **Opcional:** ninguém é obrigado a criar conta.
- **Onde fica:** botão no canto superior direito da página do estabelecimento.
  Deslogado, leva para entrar/criar conta. Logado, abre o histórico.
- **Histórico separado por estabelecimento:** um bloco por lugar ("Brutus",
  "Cicinha"...), nunca tudo misturado.
- **Esqueci a senha, simples:** a pessoa digita o WhatsApp e recebe um
  **link** no WhatsApp para criar uma senha nova, no mesmo espírito do link de
  convite do barbeiro (`DefinirSenha.tsx`, `/auth/convite/<token>`). É
  self-service: o José não precisa resetar nada à mão. A conta e todo o
  histórico continuam como estavam. **Quem recebe a mensagem naquele WhatsApp
  é o dono da conta**, e isso vale também para número reaproveitado pela
  operadora (risco aceito pelo José em 20/10). O link vale pouco tempo (o
  builder escolhe, por exemplo 30 min), serve uma vez só e entra nos mesmos
  limites e no mesmo teto diário dos códigos.

## Escolhas minhas (o José pode mudar)

- **O histórico inclui agendamentos de antes da conta.** O vínculo é pelo
  WhatsApp confirmado. Hoje `Cliente` é por barbearia (`barbearia` +
  `whatsapp` únicos), então a conta junta todos os `Cliente` com aquele
  número.
- **Ordem do histórico:** o estabelecimento da página atual aparece primeiro.
  Dentro de cada bloco ficam os próximos em cima (com "Cancelar") e os
  passados embaixo. Cada bloco tem nome e logo do lugar. Cancelados aparecem
  como cancelados.
- **Cancelar logado segue as mesmas regras** de `cancelar_publico`: o prazo
  `PRAZO_CANCELAMENTO_MIN` (60 min) e o mesmo efeito na lista do dia e nos
  avisos. Só muda a forma de provar quem é dono do
  agendamento: a sessão em vez do código.
- **Nome:** o nome da conta preenche o formulário, mas continua editável na
  hora de agendar. O nome gravado no `Cliente` de cada barbearia segue a regra
  de hoje (`_upsert_cliente`).
- **WhatsApp logado fixo no formulário.** Para agendar com outro número, a
  pessoa sai da conta. Senão, a conta marcaria em nome de um número não
  confirmado.
- **Códigos saem pelo número central** (Evolution), como a confirmação e o
  lembrete. A mensagem diz que é do Marcaí, traz
  o código e avisa para não passar o código a ninguém.
- **Código:** 6 dígitos, vale 10 minutos, no máximo 5 tentativas erradas por
  código. Um código novo invalida o anterior.
- **Limites para pedir código:** por número (exemplo: 3 por hora, 10 por dia)
  e por IP, reaproveitando o que já existe (`trava_ip`, Redis do limite por
  IP,. Quando o limite estoura, a tela responde de um jeito
  que não deixa ninguém descobrir se o número tem conta.
- **Login com senha errada:** trava progressiva por número **e** por IP, no
  estilo de `trava_barbeiro`/`trava_ip`. A trava por número tem de ter teto
  curto, para ninguém conseguir trancar o dono do número fora da conta.
- **Senha:** mínimo de 6 caracteres, com hash do Django (o mesmo de
  `services/senha.py`). Sem regra de maiúscula ou símbolo, porque é cliente de
  barbearia.
- **Trocar a senha pelo link de "esqueci a senha" derruba as outras sessões**
  (versão do token, como o `tv` do barbeiro).
- **Número sem WhatsApp:** antes de mandar o código, usa o oráculo que já
  existe (`CHECK_NUMERO_*`). Sem WhatsApp, a tela diz isso em vez de esperar
  um código que nunca chega.

- **Teto geral de códigos por dia** saindo do número central, além dos
  limites por número e por IP. Quem troca de IP e de número a cada pedido
  passa pelos limites individuais, e só um teto geral protege o chip. Ao
  bater o teto, a tela diz "Não conseguimos mandar o código agora, tenta de
  novo mais tarde", e agendar sem conta continua funcionando. O valor do teto
  fica configurável (`tenant/config.py`), com um padrão conservador escolhido
  pelo builder.
- **Fora da v1:** apagar a conta e trocar o número da conta. Ficam para
  depois.
- **Cookie no domínio pai, aceito.** Hoje, sob `usemarcai.online`, só estão
  os estabelecimentos, o `admin` e o `www`. O `www` é a página no GitHub
  Pages, e o navegador vai mandar o cookie para lá também (httpOnly e Secure,
  então nenhum script lê). Se um dia algum estabelecimento ganhar domínio
  próprio, ou outro serviço de terceiros entrar num subdomínio, esse desenho
  precisa ser revisto. Slugs de estabelecimento não podem colidir com `www`
  nem com `admin`, e o builder confirma que isso já é barrado.
- **Ordem com a mensalidade/Pix:** esta feature parte da `main`. Se a
  `mensalidade` entrar antes, as migrations são renumeradas na hora do merge.
  O cancelamento logado reaproveita a mesma regra do cancelamento pelo link
  (uma função só), então quando a Etapa 2 (Pix no agendamento) mudar o que
  pode ser cancelado, os dois caminhos mudam juntos.

## Restrições do sistema (o que o código atual impõe)

- **O tenant é o host.** Cada estabelecimento é `<slug>.<DOMINIO_BASE>`, e os
  dados de tenant ficam atrás de RLS (`com_barbearia`). A conta global tem de
  morar **fora do RLS**, como `Barbearia`.
- **Os cookies hoje são host-only** (comentário em
  `Marcai-front/src/lib/api/client.ts`). A sessão do cliente precisa valer em
  todos os subdomínios, então o cookie dela precisa de
  `Domain=.<DOMINIO_BASE>`. Isso tem de ser um cookie **separado** dos de
  `sessao` (barbeiro) e `sessao_admin`, que continuam host-only. Em dev,
  `*.localhost` pode não aceitar cookie com `Domain`. Fica com o builder
  resolver e documentar (a ponte da 8000 e o `TENANT_PADRAO` de
  também precisam funcionar).
- **O histórico atravessa tenants.** Ler agendamentos de várias barbearias
  numa requisição só significa sair do RLS de um tenant de forma controlada.
  Uma opção é iterar os tenants onde o número tem `Cliente`, cada um dentro do
  próprio `com_barbearia`. Não pode virar uma brecha que lê tudo.
- **Barbearia inativa ou apagada** não aparece
  no histórico.
- **CSRF:** os POSTs novos passam pelo `ClienteMiddleware`
  (`X-Brutus-Cliente`), igual aos outros. Com um cookie de domínio pai, o
  builder precisa confirmar que nenhum subdomínio consegue usar a sessão de
  outro de um jeito indevido.
- **Rotas no Django**, entrando no `MIGRADAS` do front (não criar handler no
  Next).
- **Front segue o Figma do redesign** e o
  vocabulário por tipo de negócio (`src/lib/tipos.ts`: "corte", "sobrancelha"
  etc.) nos textos do histórico.
- **Nada de worktree esquecida** e branch criada com `--no-track`
 .

## O fluxo, do ponto de vista do cliente

1. **Na página do estabelecimento**, deslogado: o botão "Entrar" no canto
   superior direito. O agendamento continua exatamente igual.
2. **Entrar:** WhatsApp + senha. Links para "Criar conta" e "Esqueci a senha".
3. **Criar conta:** nome, WhatsApp e senha → "Mandamos um código no seu
   WhatsApp" → digita o código → logado. Se o número já tem conta confirmada,
   o fluxo manda para "Entrar" / "Esqueci a senha", sem criar outra.
4. **Logado:** o botão vira o nome (ou a inicial) da pessoa. Ao abrir,
   aparecem o histórico por estabelecimento e um "Sair".
5. **Agendar logado:** nome e WhatsApp já preenchidos. O resto do fluxo não
   muda.
6. **Confirmação pós-agendamento** (`Confirmado.tsx`), deslogado: um convite
   discreto para criar conta e não depender do link. Escolha minha, opcional
   para o builder.

## Fica com o builder

- O modelo de dados (por exemplo `ContaCliente` global + `CodigoVerificacao`)
  e as migrations.
- Formato da sessão (JWT como o do barbeiro ou sessão no banco) e nome do
  cookie, respeitando 30 dias, httpOnly e Secure em produção.
- Os textos exatos das telas e da mensagem do código.
- Se o histórico aparece em painel lateral, modal ou página própria
  (`/conta`), desde que siga o Figma.
- Quantos agendamentos passados mostrar por estabelecimento (paginação ou
  "ver mais").
- A divisão em PRs, back e front.

## Como saber que deu certo

- Agendar sem conta, perder o link, criar conta com o mesmo WhatsApp e
  cancelar aquele horário pelo histórico.
- Entrar na Brutus, abrir a Cicinha e já estar logado, com os dois históricos
  em blocos separados.
- Ninguém consegue criar conta, entrar ou ver histórico de um número sem
  receber o código naquele WhatsApp.
- Bloqueado na Brutus, logado, continua sem conseguir agendar na Brutus.
- Pedir código repetidamente esbarra no limite.
