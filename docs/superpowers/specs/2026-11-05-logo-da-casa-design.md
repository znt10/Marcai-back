# Logo da casa nas telas do cliente — design

Data: 05/11/2026. Decidido com o José no brainstorming, com rascunhos das telas.

## Por quê

Outros apps de agendamento (o José citou o app Barba) mostram a cara do
negócio na tela do cliente. Hoje a vitrine e o cupom do Marcaí mostram só o
desenho do tipo de negócio (poste, estética, manicure, maquiagem, tesoura, ou a
inicial no "Outro") e uma frase do ramo igual para todo mundo. O dono quer ver a
logo dele ali, e o cliente que tira print do cupom leva a marca da casa junto.

## Objetivos

- O dono sobe a logo do negócio pelo painel, se quiser. Ninguém é obrigado.
- Com logo, ela aparece em destaque na vitrine e na tela de agendado.
- Sem logo, a casa continua com o desenho do tipo de negócio, como hoje.

## Fora do escopo

- **Foto do profissional.** Já existe de ponta a ponta (`Barbeiro.foto_url`,
  `PUT /api/painel/foto`, botão no cabeçalho do painel, `Avatar` na vitrine e
  no agendamento). Decisão do José: **cada um põe a sua**. O dono não ganha
  botão para pôr a foto dos outros. Nada muda aqui.
- Storage de arquivo (volume no Coolify, S3 ou similar).
- A prévia do link no WhatsApp (`src/app/miniatura/route.tsx`) continua com o
  desenho do tipo. Decisão do José: fica para depois.
- Plaquinha ou fundo forçado atrás da logo. Logo escura e transparente sobre
  paleta escura aparece como foi enviada; a prévia no painel é o que avisa o
  dono (decisão do José).
- Logo em outros lugares: o topo pequeno, o histórico da conta, o cabeçalho de
  `/agendar`, o ícone de instalar e o favicon continuam com o desenho do tipo.
- Textos do bot e mensagens de WhatsApp.

## Anti-objetivos

- A logo cortada em círculo ou esticada. Uma logo comprida tem que aparecer
  comprida, e uma redonda, redonda.
- Uma casa sem logo com tela pior que a de hoje.
- A vitrine pesada: ela é renderizada no servidor e aberta no 4G na calçada.

## O que muda nas telas (decisões do José)

### Vitrine (`src/components/Vitrine.tsx`)

Dentro do cartaz (o quadrado), de cima para baixo:

1. **Logo da casa**, se houver, senão o desenho do tipo (o `Marca` de hoje).
2. A rua (e o `horarioResumo`, se houver, como hoje).
3. A equipe e o resto, sem mudança.

**A frase do ramo (`v.slogan`, "CORTE DE HOMEM, HORA MARCADA.") sai sempre,
com ou sem logo.** O nome da casa **não** se repete embaixo da logo (opção A
do rascunho): ele já está no topo.

O topo da página (`src/app/page.tsx`: desenho pequeno de 30px + "barbearia
teste" + botão da conta) fica como está. O desenho pequeno continua sendo o do
tipo, nunca a logo da casa.

A logo segue a proporção que o dono subiu (`object-contain`), dentro de uma
caixa de mais ou menos 120px de altura e com largura máxima de toda a largura
útil do cartaz. Comprida fica comprida, redonda fica redonda, sem corte e sem
borda arredondada forçada.

### Agendado (`src/app/agendamento/[codigo]/page.tsx` + `Confirmado.tsx`)

Opção A do rascunho:

1. **Topo igual ao da vitrine**: desenho pequeno do tipo + nome da casa. Hoje
   essa tela não tem topo.
2. **Logo da casa** (ou o desenho do tipo, sem logo), centralizada, um pouco
   menor que na vitrine (mais ou menos 96px de altura, mesma regra de
   proporção).
3. "Tá marcado, Ana." e o cupom, como hoje.

Vale também para o estado "Horário cancelado." da mesma tela.

### Painel, tela Equipe (`src/app/painel/equipe/page.tsx`)

No alto da tela, antes da lista da equipe, **dois blocos lado a lado**
(rascunho 4, aprovado pelo José). Eles aparecem só para o dono, porque a tela
já só mostra conteúdo ao dono:

- **Logo da casa:** a logo atual, ou o desenho padrão do tipo quando não há
  logo, desenhada **sobre a cor de fundo da paleta das telas do cliente**,
  para o dono ver como o cliente vai ver. O botão **trocar** abre o seletor de
  arquivo. O botão **tirar** aparece só quando há logo.
- **Sua foto:** a foto do próprio dono, com **trocar** e **tirar**. É a mesma
  foto e a mesma rota do botão do cabeçalho (`PUT /api/painel/foto`, sem
  `barbeiroId`). O botão do cabeçalho continua, e os dois lugares têm de
  mostrar a mesma foto depois de uma troca (o cabeçalho lê `eu` do
  `SessaoDoPainel`).

Embaixo, a lista da equipe como já é hoje. O barbeiro que não é dono segue
pondo a foto pelo cabeçalho.

O visual segue as peças do painel (`components/painel/pecas.tsx`) e a paleta
`.painel` do redesign do Figma. O Figma não tem esses blocos: o builder segue
o estilo das outras seções da Equipe. No celular, os dois blocos podem
empilhar.

## Guardar a imagem (decisão do José)

Igual à foto do profissional (ver `app/services/foto.py` e `src/lib/foto.ts`):

- **Peso na página:** a logo **não** vai embutida no HTML. Uma rota do front,
  `GET /logo`, lê a data URL do Django (servidor com servidor, como o
  `/miniatura` faz) e devolve os bytes da imagem, com cache longo. As telas
  usam `<img src="/logo?v=<versão>">`, e a versão é um resumo do conteúdo:
  trocar a logo muda o endereço, e o cache antigo não aparece. Motivo: no App
  Router, todo `<img>` com data URL vai duas vezes para o navegador (no HTML e
  no payload do RSC), seja Server ou Client Component. Com a rota, ele vai
  uma vez só, e o celular guarda a logo entre visitas. A imagem continua
  guardada no banco. (Decisão minha, depois da revisão.)
- **No banco**, como data URL num campo de texto novo em `Barbearia` (por
  exemplo `logo_url`, `TextField(null=True)`). Sem volume e sem rota de
  arquivo no disco. O backup do banco leva a logo junto, e o deploy no Coolify não muda.
- **Formatos aceitos:** JPG, PNG e WebP. **SVG recusado** (carrega script).
  URL `https://` recusada, pelo mesmo motivo da foto.
- **O navegador reduz antes de enviar e não corta:** mantém a proporção, com
  no máximo 512px no lado maior, e reencoda em WebP preservando a
  transparência (PNG com fundo transparente continua transparente). Imagem
  menor que 512px não é ampliada.
- **O servidor é a regra:** recusa acima de **60 KB** decodificados, recusa
  mime fora da lista e recusa base64 quebrado, com mensagens curtas em
  português no tom das da foto. O navegador escolhe a qualidade para caber.
- Constantes no `tenant/config.py` (por exemplo `LOGO_LADO_MAXIMO_PX = 512`,
  `LOGO_TAMANHO_MAXIMO_BYTES = 60 * 1024`), espelhadas no front com comentário,
  como a foto faz.

Trade-off aceito: com milhares de casas, o banco cresce alguns MB. Se um dia
isso pesar, troca-se para storage externo sem mexer nas telas.

## API (back)

- `GET /api/barbearia` (público, o que `barbeariaAtual()` usa) passa a devolver
  `logoUrl: string | null`.
- Rota nova do painel, só para o dono: `PUT /api/painel/logo` com
  `{ "logo": "<data URL>" | null }`. `null` tira a logo. Barbeiro que não é
  dono recebe a mesma resposta das outras rotas "só o dono" do painel. Fica no
  mesmo molde do `FotoView` (PUT idempotente e sem DELETE separado).
- Migration nova em `tenant` (a última na `main` é a `0019`). Se outro PR com
  migration entrar antes, renumerar.
- Admin do Django: mostrar se a casa tem logo é opcional, a critério do builder.

## Front

- `Marca.tsx` ganha a variante com a logo da casa, ou um componente vizinho
  (por exemplo `LogoDaCasa`) que recebe `logoUrl`, `tipo` e `nome` e cai no
  `Marca` quando não há logo. O builder escolhe.
- `src/lib/foto.ts` ganha uma função irmã para a logo (reduzir sem cortar),
  ou a lógica comum é extraída. O builder escolhe.
- `painelAPI` ganha `definirLogo(logo: string | null)`.

## Testes

- Back: o validador (mime, SVG, URL, base64 quebrado, tamanho), a rota (dono
  sim; barbeiro não; `null` tira) e o `GET /api/barbearia` com e sem logo.
- Front: a vitrine com e sem logo (a frase não aparece em nenhum dos dois),
  o agendado com o topo e a logo, o bloco da Equipe (trocar, tirar, erro do
  servidor) e a redução sem corte (proporção mantida, lado maior ≤ 512).

## Como trabalhar (regras do José)

- Branches `logo-da-casa` nos dois repos, criadas com
  `git switch -c ... --no-track origin/main` (aqui, em worktree, a pedido do
  José nesta tarefa). Remover a worktree quando o PR subir.
- PRs separados: back primeiro, front depois. O merge é do José.
- Antes de rodar a suíte inteira do back, trazer para a branch o commit do
  `Marcai-back#68` (a suíte não manda WhatsApp de verdade), se ele ainda não
  estiver na `main`. Em 05/11 ele ainda não estava.
- Back: `docker compose run --rm api pytest -q`. Front: `npm test` e
  `npx next typegen && npx tsc --noEmit`.

## Decisões minhas (o José pode revisar)

- Nome do campo `logo_url` e da rota `/api/painel/logo`.
- Tamanhos aproximados: 120px na vitrine e 96px no agendado.
- O topo pequeno continua com o desenho do tipo, não com a logo da casa.
- O cancelado também ganha topo e logo.
- A logo chega ao cliente pela rota `/logo?v=<versão>`, e não embutida no HTML.
