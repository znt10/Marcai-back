# Lembrete por toque pela Evolution — design e plano

06/11/2026. Ainda não foi feito nada; isto é só o plano para o José aprovar.

## Por que

Desde 01/10/2026 a Meta cobra o modelo de utilidade mesmo com a conversa
aberta. O texto normal sai grátis só nas 1.000 primeiras mensagens do mês por
número (ver a memória `preco-meta-out-2026`). Hoje, depois do #69 e do #70,
todo lembrete de quem tocou sai pela Meta e é pago, salvo o caso estreito do
"tocou há menos de 23h", que vai como texto.

**Ideia do José:** na hora de marcar, levar o cliente direto ao WhatsApp para
ele mandar a mensagem pronta para o número da **Evolution**. Como foi o
cliente que escreveu primeiro, a Evolution pode responder e mandar o lembrete,
sem custo por mensagem. O número antigo foi restringido justamente por mandar
mensagem a quem nunca tinha escrito; aqui todo cliente começou a conversa.

## Decisões do José

- **Um número só por enquanto:** o chip da Evolution (83 98801-0990) atende a
  equipe e os clientes. Risco aceito: se ele cair, param juntos as listas e os
  lembretes.
- **O fluxo começa na hora de marcar:** depois de "Confirmar", a pergunta
  "Quer receber a confirmação e o lembrete no WhatsApp?" → [Sim] abre o
  WhatsApp com a mensagem pronta para o chip.
- **A Meta fica só de reserva** (ver "Quem manda o quê").

## Quem manda o quê

| Mensagem | Hoje (#69/#70) | Novo |
|---|---|---|
| Resposta ao toque (confirmação) | Meta, texto | **Evolution** |
| Lembrete 1h antes de quem tocou | Meta (modelo, ou texto se < 23h) | **Evolution**; Meta só se a Evolution estiver fora do ar |
| Cliente cancelou (quem tocou) | Meta | **Evolution** |
| Confirmação de quem marcou pelo painel | Meta, modelo com botão | Meta, igual. O cliente nunca escreveu, e mandar isso pela Evolution é o que derruba número |
| A barbearia cancelou, bloqueio | Meta, modelo | Meta se o cliente nunca escreveu; **Evolution** se ele tocou |
| Lista e avisos da equipe | Meta, ou chip com o #67 | chip (#67) |

O botão da confirmação do painel (`lembrete:<código>`) continua chegando pelo
webhook da Meta. Esse cliente pediu pela Meta, então o lembrete dele sai pela
Meta. É o único lembrete pago que sobra.

## Chave

`LEMBRETE_PELA_EVOLUTION=1` (nova). Ela exige o `lembrete_por_toque.ligado()`
de hoje e o chip conectado. Com a variável desligada, tudo continua como no
#69/#70. O número que vai no `wa.me` passa a ser o do chip:
`WHATSAPP_EVOLUTION_NUMERO` (novo), ou lido da própria instância
(`ownerJid`), se der.

## O que muda no código

### Back (Marcai-back)

1. **Campo `lembrete_canal` em `Agendamento`** (`"meta"` ou `"evolution"`,
   nulo para quem ainda não pediu), com migration 0023. Diz por onde o
   cliente escreveu e, portanto, por onde responder e lembrar.
2. **Webhook da Evolution** (`views/interno.py`, `messages.upsert`): antes do
   bot, se `lembrete_por_toque.codigos_no_texto(texto)` achar um código,
   chamar `registrar_pedido(..., canal="evolution")`.
   - Hoje o `bot_entrada.receber` descarta mensagens com o bot desligado.
     Criar um caminho próprio, sem depender de `BOT_DISPONIVEL`.
   - Atenção ao formato: o `remoteJid` pode vir `@lid`, sem número. Usar
     `remoteJidAlt` quando vier, como já aparece nos logs.
   - Ignorar `fromMe` (o próprio chip) e grupos (`@g.us`).
3. **`registrar_pedido(texto, de, agora, canal)`:** grava `lembrete_canal` e
   responde pelo mesmo canal. Pela Evolution: `whatsapp._enviar_aceita` na
   instância central, com o texto de `msg_confirmacao` com quebras de linha.
4. **Envio pelo canal:**
   - `enviar_ao_cliente(..., canal=None)`. Com `canal="evolution"`, manda pela
     Evolution e, se ela recusar ou estiver fora do ar, cai na Meta (modelo).
   - O cron do lembrete, `depois_de_cancelar`, o cancelamento pelo painel e o
     bloqueio passam `canal=a.lembrete_canal`.
5. **`GET /api/barbearia`:** `whatsappCentral` passa a ser o número do chip
   quando `LEMBRETE_PELA_EVOLUTION` está ligada. O front não muda o link, só
   o número.
6. **Healthcheck:** o "CHIP DA EQUIPE FORA DO AR" do #67 vale também para os
   clientes. Mudar o texto para "CHIP FORA DO AR — equipe e lembretes".

### Front (Marcai-front)

7. **A pergunta logo depois de marcar** (`FormAgendamento` → tela de
   agendado): em vez de um cartão no meio da tela, o primeiro bloco depois do
   cupom é "Quer receber a confirmação e o lembrete no WhatsApp?", com [Sim,
   quero] e, menor, "Não precisa". O [Sim] abre o `wa.me` (o mesmo
   `linkDoLembrete`, com o número novo).
   - Não dá para obrigar a enviar, porque o cliente pode fechar o WhatsApp.
     O "Lembrete ligado ✓" continua aparecendo sozinho quando ele volta.
   - Não abrir o WhatsApp automaticamente: no computador cai no WhatsApp Web,
     e redirecionar sem toque assusta e pode ser bloqueado pelo navegador.
8. **Texto do admin (#84):** "chip da equipe e dos lembretes".

## Testes (TDD, como no #69)

- Webhook da Evolution com o código: grava `lembrete_canal="evolution"` e
  responde pela Evolution (`requests.post` para `/message/sendText/`), não pela
  Meta.
- `@lid` com `remoteJidAlt`, `fromMe`, grupo, código inválido ou cancelado:
  ignorados.
- Cron: `canal="evolution"` sai pela Evolution; Evolution recusando (500) cai
  na Meta pelo modelo `marcai_lembrete_horario`.
- Pedido pela Meta (botão do painel) continua saindo pela Meta.
- `LEMBRETE_PELA_EVOLUTION` desligada: tudo como no #70 (os testes de hoje
  passam sem mudança).
- Barbearia cancela: com `canal="evolution"` vai pela Evolution; sem pedido,
  pela Meta.
- Front: `linkDoLembrete` com o número do chip; a pergunta aparece depois de
  marcar.

## Ordem

1. PR do back (tarefas 1–6), com a migration 0023.
2. PR do front (tarefas 7–8).
3. Deploy dos dois. O chip precisa estar conectado e aquecido.
4. No Coolify: `LEMBRETE_PELA_EVOLUTION=1` (e `WHATSAPP_EVOLUTION_NUMERO`, se
   for o caso).

## Riscos

- **Volume num chip só:** muitos clientes escrevendo e recebendo num número
  comum. Como todos escreveram primeiro, o risco é bem menor que o de antes,
  mas existe. Se cair, a Meta segura os lembretes (tarefa 4), e as listas da
  equipe param até reconectar.
- **Cliente que não envia a mensagem:** fica sem confirmação e sem lembrete,
  como já é no #69.
- **`@lid`:** se o WhatsApp esconder o número, sem `remoteJidAlt` não dá para
  saber quem é. O pedido é ignorado e o erro vai para o log.

## Fora do escopo

- Separar equipe e clientes em dois números (fica para depois, pela decisão
  do José).
- Bot de agendamento pelo chip.
- Os planos Básico, Normal e Completo.
