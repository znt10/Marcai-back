# Lembrete por toque ("Quero o lembrete no WhatsApp") — design

03/11/2026. Back e front. É um PR separado do número da equipe
(`2026-11-03-numero-da-equipe-design.md`) e não depende dele.

## Por que

Pela Meta, cada confirmação e cada lembrete que o Marcaí manda por conta
própria custa cerca de R$ 0,035 (utilidade). Na Brutus, com 1 cadeira, foram
279 agendamentos em outubro: 279 confirmações, 232 lembretes e 38
cancelamentos, uns R$ 19 por cadeira por mês. Uma loja de 8 cadeiras daria
uns R$ 150, quase o preço do plano.

O que a Meta não cobra: **quando o cliente escreve para o número, tudo o que
o Marcaí manda a ele nas 24 horas seguintes é de graça.** Na Brutus:
- 48% dos agendamentos são para até 25 horas depois de marcados, então o lembrete (1 hora antes) cai dentro dessas 24 horas;
- 24 dos 38 cancelamentos aconteceram em até 24 horas.

Na Evolution, 25% a 30% dos clientes já escreviam sem ninguém pedir.

**Decisão do José:** só recebe WhatsApp quem tocar no botão e mandar a
mensagem. O toque também é o aceite que a Meta exige para receber mensagens.
E quem escreveu prova que tem internet, que o número é dele e que não
bloqueou o Marcaí.

Custo estimado com 60% tocando: uns R$ 2,80 por cadeira por mês, contra R$ 19 hoje.

## Objetivo

1. A tela de agendado mostra um botão que abre o WhatsApp com uma mensagem pronta para o número central.
2. Quando essa mensagem chega pelo webhook da Meta, o agendamento passa a "ter lembrete", e o Marcaí responde na hora com a confirmação. A resposta é grátis, porque está dentro das 24 horas.
3. O lembrete de 1 hora antes só sai para agendamento que "tem lembrete".
4. Agendamento marcado pelo site sem toque não gera nenhuma mensagem ao cliente, a não ser o cancelamento pela barbearia (ver abaixo).

## Fora do escopo

- Os planos Básico, Normal e Completo.
- A regra de "lembrete só se marcou com mais de 3 horas". Os dados mostraram que economiza menos de R$ 1 por mês.
- Bot de agendamento no número central.
- Guardar a entrega e a leitura de cada mensagem (os eventos de status da Meta). Fica para depois.

## O que já existe (03/11, main em 5ffe499)

- **Confirmação ao marcar pelo site:** `views/agendamentos.py`, depois do commit. Usa `enviar_ao_cliente` e `msg_confirmacao`, com o link `<origin>/agendamento/<codigo>`.
- **Confirmação ao marcar pelo painel:** `views/agendamentos_painel.py`, igual.
- **Cancelamentos:**
  - pelo cliente: `depois_de_cancelar` (`msg_cancelamento`);
  - pela barbearia: `agendamentos_painel.py` (`msg_cancelamento_pela_barbearia`);
  - por bloqueio do cliente: `bloqueios.py`.
- **Lembrete:** `services/lembrete.py`. O cron, a cada 10 minutos, pega os agendamentos `CONFIRMADO`, com `lembrete_enviado_em` nulo e início dentro de `LEMBRETE_ANTECEDENCIA_MIN` (60). `lembrete_ao_criar` faz o agendamento marcado já dentro da janela nascer com o lembrete dado.
- **Webhook da Meta:** `whatsapp_meta.registrar_evento`. Hoje só conta e loga as mensagens recebidas.
- **Agendamento:**
  - `codigo` é único no banco inteiro;
  - a `Barbearia` fica fora do RLS, e o `Agendamento` fica dentro;
  - `barbearias_do_whatsapp` é o jeito de cruzar barbearias pelo número.
- **Front:**
  - `Confirmado.tsx` diz "Mandamos o lembrete no WhatsApp 1h antes";
  - `FormAgendamento.tsx` diz "A confirmação chega no seu WhatsApp";
  - os dois leem `whatsappAoCliente`.

## Comportamento

### O botão

Na tela de agendado (`Confirmado.tsx`), no lugar da frase do lembrete,
enquanto o agendamento não tem lembrete:

> **[Quero o lembrete no WhatsApp]**
> Toque, envie a mensagem que aparece, e a gente te lembra 1h antes.

O botão abre `https://wa.me/55<central>?text=<mensagem>`. A mensagem pronta é
legível para o cliente e carrega o código, por exemplo:

> Quero o lembrete do meu horário na Brutus. Código: K7P2Q9

Depois que o agendamento ganhou lembrete, a tela mostra
"Lembrete ligado ✓ · chega no WhatsApp 1h antes".

- **O número central** vem do back, por exemplo `whatsappCentral` em `GET /api/barbearia`.
- **O botão só existe com a Meta ligada.** Sem a Meta não há webhook, e o toque não faria nada. Nesse caso fica o texto de hoje.
- **A frase do formulário** ("A confirmação chega no seu WhatsApp") troca para algo que não prometa a mensagem, por exemplo "Depois de confirmar, você escolhe receber o lembrete no WhatsApp".

### A chegada da mensagem

`registrar_evento` passa a olhar o texto de cada mensagem recebida.

- **Se achar um código** de agendamento `CONFIRMADO` e com início no futuro:
  1. grava no agendamento `lembrete_pedido_em` (agora) e `lembrete_para` (os dígitos nacionais de quem escreveu). É um campo novo, com migration nova;
  2. responde a quem escreveu com o texto de `msg_confirmacao`, com o link do agendamento montado a partir do slug e do domínio. Aqui não existe `Origin`;
  3. se o agendamento já tinha lembrete, só responde de novo, sem gravar outra vez.
- **Sem código, código desconhecido, agendamento cancelado ou passado:** não grava nada e não responde. Fica como hoje, só no log.

O lembrete vai para `lembrete_para`, o número que provou que funciona. Esse
número pode ser diferente do número que o cliente digitou ao marcar.

### O lembrete

O cron passa a exigir `lembrete_pedido_em` não nulo. O resto não muda:
1 hora antes, `lembrete_ao_criar`, e a marcação antes de enviar.

### Cancelamentos

- **Pela barbearia** (painel ou bloqueio): **sempre avisa**, mesmo sem toque, pelo número que o cliente digitou. Se não avisar, o cliente aparece para um horário que não existe mais. São poucos e o custo é pequeno.
- **Pelo próprio cliente** no site: só avisa se o agendamento tem lembrete, para `lembrete_para`. Ele mesmo cancelou e viu na tela.

### Marcado pelo painel

Decisão do José: a confirmação sai como hoje, paga, e o texto ganha no fim
o mesmo link do botão ("Quer o lembrete 1h antes? Toque aqui e envie a
mensagem: wa.me/..."). O lembrete só sai se o cliente tocar e mandar.

### Cada agendamento pede o seu toque

Decisão do José: o aceite vale para aquele agendamento e não passa para os
próximos. Quem marca para esta semana e para a semana que vem toca nos
dois, e recebe os dois lembretes. Quem marca com mais de um dia de
antecedência recebe o lembrete pago, e tudo bem: lembrete é para lembrar. O
barbeiro orienta os clientes a sempre tocar em confirmar.

## Decisões

Do José:
- Lembrete só para quem tocou.
- A confirmação no WhatsApp sai como resposta ao toque.
- Marcado pelo painel: confirmação paga com o link do botão no texto, e lembrete só com o toque.
- O aceite vale por agendamento.
- É um PR próprio.

Minhas, para o José conferir:
- O lembrete vai para o número que escreveu.
- O cancelamento pela barbearia sempre avisa. O cancelamento pelo cliente só avisa quem tocou.
- O botão some sem a Meta.
- A regra das 3 horas fica fora.

## O que fica com quem implementa

- Os nomes dos campos e da migration. Ver a numeração da main na hora.
- Como achar o agendamento pelo código atravessando o RLS. O código é único no banco. Pode ser uma função no banco como `barbearias_do_whatsapp`, ou o slug na mensagem.
- Aceitar o código com espaço, minúscula ou texto em volta. O cliente pode apagar parte da mensagem.
- O texto final do botão e das frases, no tom do site.
- Se a tela de agendado atualiza sozinha para "Lembrete ligado ✓" ou só ao recarregar.

## Testes

Back:
- Webhook com código válido: grava, responde pela Meta, e o lembrete sai.
- Webhook com código inválido, cancelado ou passado: não grava e não responde.
- Mensagem repetida: não duplica.
- Cron: agendamento sem toque não recebe lembrete.
- Marcar pelo site não manda confirmação.
- Marcar pelo painel manda a confirmação com o link do botão, e sem toque não há lembrete.
- Um toque num agendamento não liga o lembrete de outro do mesmo cliente.
- Cancelamento pela barbearia sem toque avisa. Cancelamento pelo cliente sem toque não avisa.

Front:
- O botão monta o `wa.me` certo.
- O botão some sem a Meta.
- A tela mostra "Lembrete ligado" quando o back diz que o agendamento tem lembrete.

## Riscos

- Quem não toca não recebe nada no WhatsApp e pode faltar. É o preço de economizar, e é escolha do José.
- O cliente precisa apertar enviar no WhatsApp. Tocar no botão não basta.
- As respostas dentro das 24 horas não contam no limite de 250 pessoas por dia da Meta. Isso é uma vantagem.
