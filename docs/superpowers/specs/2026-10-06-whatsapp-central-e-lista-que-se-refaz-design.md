# WhatsApp so' pelo numero central e a lista do dia que se refaz (etapa 1)

Desenho aprovado em 06/10/2026. Abrange os dois repositorios
(`Marcai-back` e `Marcai-front`).

## 1. Por que

O Jose ouviu que o WhatsApp apertou o bloqueio de numero ligado por API nao
oficial. Hoje a Evolution — que imita o WhatsApp Web — fica ligada ao numero
de CADA barbearia com zap. Um bloqueio ali derruba o numero do negocio do
cliente do Marcai, nao o do Marcai.

A saida definitiva e' a API oficial da Meta, e ela ficou para a etapa 2 por
dois motivos:

- o chip pre-pago comprado para o numero do Marcai foi recusado no cadastro
  da Meta;
- para o numero da barbearia ficar no celular do atendente E na API ao mesmo
  tempo ("coexistencia"), o Marcai precisa ser provedor verificado na Meta, o
  que pede CNPJ verificado (secao 10).

Esta etapa tira a Evolution do numero da barbearia JA, e concentra o risco num
numero so': o do Marcai. Se ele cair, o Jose troca o chip.

## 2. Decisoes

| Decisao | Escolha | Por que |
|---|---|---|
| Numero da barbearia | **Sai da Evolution** | Bloqueio deixa de atingir o negocio do cliente |
| Link quando o cliente escreve para a barbearia | **Mensagem de saudacao do WhatsApp Business**, que o dono configura no proprio celular | Nenhum sistema ligado ao numero da barbearia, risco zero |
| Bot de agendamento | **Desligado; o codigo fica** | Volta no futuro plano de agendar pelo WhatsApp, com a API oficial |
| Quem manda para a equipe | **Numero central** | Desfaz a decisao de 17/09 (pelo numero da barbearia quando conectado) |
| Quem manda para o cliente | **Numero central** | Desfaz a regra "o central nunca fala com cliente". Risco aceito: o chip caiu, equipe e clientes param juntos ate a troca |
| Planos com/sem zap | **Toda barbearia vira com zap**; o seletor sai do admin | "Sempre vai ter com zap". O campo `plano` fica para os planos futuros (WhatsApp x API) |
| Lista do dia quando a agenda de hoje muda | **Apaga a anterior e manda de novo** | A Evolution apaga mensagem — a API oficial nao apagaria |

### Fora desta etapa

- API oficial, conectar o numero da barbearia por ela, resposta automatica
  pelo sistema, agendamento pelo WhatsApp: etapa 2, com desenho proprio.
- Ler o que o cliente responder ao numero central. A mensagem diz com quem
  falar (secao 5); nada le o que chega ali.

## 3. O numero da barbearia sai da Evolution

**Interruptor unico.** `WHATSAPP_POR_BARBEARIA = False` em `tenant/config.py`.
Todo caminho que cria ou confere instancia de barbearia o respeita:

- `criar()` e `atualizar_plano()` (`app/services/admin_barbearias.py`) nao
  criam linha nem instancia. Desativar continua chamando `apagar_instancia`,
  que nao acha linha e sai.
- `conferir_instancias` (`app/tasks.py`) sai sem fazer nada.
- `enviar_ao_cliente`, `enviar_a_equipe_da` e `numero_existe` param de olhar
  `WhatsappInstancia` (secao 4).

**Comando de uma vez so'**: `desligar_instancias_das_barbearias`. Para cada
`WhatsappInstancia`, chama `apagar_instancia(barbearia)` — logout, delete na
Evolution e a linha some. Rodar de novo nao acha nada. Roda no terminal do
conteiner `api` depois do deploy.

**Bot.** `BOT_DISPONIVEL = False` em `tenant/config.py`. `bot_entrada.receber`
devolve `ignorado:desligado` antes de qualquer consulta, e `ligar_bot` recusa
ligar. Sem instancia de barbearia o webhook ja' nao recebe mensagem de
cliente; a constante e' o ponto unico para religar quando a etapa 2 chegar.
No `lembrete.enviar_pendentes`, o ramo `pelo_bot` deixa de ser escolhido.

## 4. Tudo pelo numero central

A instancia central e' a que ja' existe: `EVOLUTION_INSTANCE` ("Marcai" em
producao). Nenhuma variavel nova.

- **Equipe.** `enviar_a_equipe_da(barbearia_id, ...)` passa a chamar
  `enviar_a_equipe` direto. A assinatura fica, para nao mexer nos chamadores.
- **Cliente.** `enviar_ao_cliente(barbearia, ...)`:
  - plano diferente de `COM_ZAP`: nao manda e nao registra, como hoje (depois
    da migracao ninguem cai aqui, mas o caminho fica);
  - senao: manda pelo central. Envio que falha (rede, 4xx, 5xx) registra
    `MensagemNaoEnviada`, como hoje. Sem `EVOLUTION_API_URL` (desenvolvimento)
    nao registra — nao houve queda, so' nao ha servidor.
- **"Esse numero tem WhatsApp?"** `numero_existe` pergunta pela central. Cache
  e limite por IP iguais; a chave do cache deixa de levar a barbearia.
- **`_enviar`** passa a devolver o `id` E o `remoteJid` da mensagem aceita. A
  secao 6 precisa dos dois para apagar.

**Migracao de dados.** Toda barbearia vira `COM_ZAP`; o default do campo e o
de `criar()` passam a `COM_ZAP`. No admin, o seletor de plano sai do
formulario de criar e da lista; a API continua aceitando o campo.

**Card "WhatsApp do Marcai" no admin.** Hoje nao ha como escanear o QR do
central em producao sem expor o manager da Evolution, e uma queda dele so'
aparece no log do `whatsapp_healthcheck`. Agora que o central carrega tudo, o
admin ganha um card com o estado (conectado / desconectado / aguardando QR), o
numero conectado e, quando nao conectado, o QR.

- `GET /api/admin/whatsapp-central`, so' admin. Reusa `consultar_estado`,
  `consultar_dono` e `pedir_qr` com o nome da central.
- Se a instancia central nao existir na Evolution, a rota a cria (sem
  webhook: o central so' manda).
- O `whatsapp_healthcheck` continua logando a cada 10 minutos.

## 5. O que o cliente le

O numero agora e' do Marcai, que o cliente nao conhece. Toda mensagem abre com
o nome da barbearia em negrito, e as que pedem resposta apontam para o numero
dela (`whatsapp_contato`, formatado). Sem "na"/"no" antes do nome: o genero do
nome da barbearia nao e' conhecido ("na Dom Tony" soaria errado).

Confirmacao:

```
*{Barbearia}*
Fechou, {Primeiro}! {Servico} {quinta 10/09} às {9:00}, com {barbeiro}.

Cancelar: {link}
Dúvida? Chama: {(83) 99999-0000}
```

Lembrete:

```
*{Barbearia} — lembrete: {servico} hoje às {15:00}*
com {barbeiro}
Endereço: {endereco}
Não vai dar? Chama: {(83) 99999-0000}
```

Cancelamento pela barbearia:

```
*{Barbearia}*
Oi, {Primeiro}. Cancelamos seu {servico} de {quinta 10/09} às {9:00}. Desculpa! Pra remarcar, chama: {(83) 99999-0000}
```

Cancelamento pelo proprio cliente:

```
*{Barbearia}*
Horário de {quinta 10/09} às {9:00}, com {barbeiro} cancelado. Até a próxima!
```

As mensagens da equipe nao mudam de texto: os barbeiros sabem que o numero e'
do Marcai, e o convite ja' traz o nome da barbearia.

## 6. A lista do dia que se refaz

**Modelo novo** `ListaDoDiaEnviada`, tabela de tenant com RLS como as outras:
`barbearia`, `barbeiro`, `dia` (data local), `mensagem_id`, `remote_jid`,
`enviada_em`. Unica por `(barbeiro, dia)`. O zelador apaga as de mais de 7
dias.

**As 07:00** a lista sai como hoje (`lista_do_dia.enviar`), e cada envio
aceito grava ou atualiza a linha do barbeiro naquele dia.

**Quando a agenda de HOJE de um barbeiro muda** (dia local de Sao Paulo, o
mesmo recorte de `lista_do_dia`):

- Gatilhos:
  1. marcar pelo site (`AgendamentosView.post`);
  2. marcar pelo painel (`AgendamentosPainelView.post`);
  3. cancelar pelo site (`AgendamentoCancelarPublicoView`, so' no `ok`);
  4. cancelar pelo painel (`AgendamentoCancelarView`);
  5. bloqueio que cancelou horarios (`BloqueiosView.post`) — um disparo so'
     com todos os cancelados.
- Antes das 07:00 locais: nada. A mudanca entra na lista das 07:00.
- De 07:00 em diante: enfileira a task
  `refazer_lista(barbearia_id, barbeiro_id, novos, cancelados)`, fora do
  pedido HTTP.
- Nos gatilhos 1 e 3, isto SUBSTITUI o aviso curto "Novo horário"/"Cancelou".
  Para outro dia, o aviso curto continua como hoje; painel e bloqueio de outro
  dia continuam sem aviso, como hoje.
- Quem mexe no proprio horario pelo painel tambem recebe a lista nova: como a
  antiga e' apagada, a que fica no WhatsApp precisa estar sempre certa.

**A task:**

1. trava a linha `(barbeiro, hoje)` (`select_for_update`) — duas mudancas
   seguidas saem em ordem, e a segunda apaga a lista da primeira;
2. monta a lista com os `CONFIRMADO` de hoje, em ordem de horario, marcando
   os `novos` e intercalando os `cancelados` no lugar deles;
3. manda a nova e grava `mensagem_id`/`remote_jid`. Falhou: loga, e a
   anterior fica como esta (nada e' apagado);
4. so' depois disso, se havia linha, apaga a mensagem anterior para todos
   (`DELETE /chat/deleteMessageForEveryone/{central}` com `id`, `remoteJid`,
   `fromMe: true`). Falhou: loga e segue.

   (Ordem trocada na revisao final de 06/10: apagando primeiro, um envio que
   falhasse deixava o barbeiro sem lista e, pelo site, sem o aviso curto.)

A marca de novo e o riscado valem so' na lista daquela mudanca; na seguinte,
o novo vira linha comum e o cancelado some.

**Formato** — a das 07:00 nao muda:

```
Bom dia, Zeca! Hoje você tem:
João Silva · hoje 9:00 · Corte
Pedro Lima · hoje 15:00 · Barba
```

A refeita:

```
Zeca, sua agenda de hoje mudou:
João Silva · hoje 9:00 · Corte
🆕 Pedro Lima · hoje 15:00 · Barba
~Ana Souza · hoje 16:00 · Corte~ cancelou
```

Se nao sobrar horario confirmado, a ultima linha e' `Não sobrou horário hoje.`

No WhatsApp a lista antiga vira "Mensagem apagada"; isso nao tem como evitar.

**Premissa a medir antes de construir (tarefa 0 do plano).** Apagar para
todos na Evolution 2.3.7, numa conversa 1:1, uma mensagem que a propria
instancia mandou. Ha relato de falha (evolution-api#592). Se nao funcionar, a
etapa sai com "so' manda de novo", sem apagar; o resto do desenho nao muda.

## 7. O painel da barbearia

`GET /api/painel/whatsapp` passa a devolver
`{ "saudacao": "<texto>", "naoEnviadas": n }`. O texto:

```
Oi! Pra marcar seu horário, é só tocar no link: {link}
Se preferir, espera uns minutinhos que já vamos te responder.
```

`{link}` e' `https://{slug}.{DOMINIO_BASE}`, a mesma base de
`link_do_convite`. Sem o nome da barbearia: o texto sai do numero dela.

Tela `/painel/whatsapp`:

- o texto pronto, com botao Copiar;
- o passo a passo: no WhatsApp Business, Ferramentas comerciais → Mensagem de
  saudação → ativar → colar o texto → destinatarios: todos;
- a nota: "O WhatsApp manda a saudação na primeira mensagem de cada pessoa, ou
  depois de 14 dias sem conversa.";
- quando `naoEnviadas > 0`: "N clientes não receberam a mensagem — o WhatsApp
  do Marcaí estava fora do ar."

Saem da tela o QR, o estado da conexao, o "trocar de celular" e o interruptor
do bot. A `FaixaDoWhatsapp` deixa de aparecer: sem instancia da barbearia, nao
ha queda dela para mostrar. As rotas `desconectar` e `bot` ficam, mas o front
para de chama-las (sem instancia, `desconectar` ja' devolve 422; `bot` recusa
pelo `BOT_DISPONIVEL`).

## 8. Testes

Back (pytest, escritos antes do codigo, `requests` mockado como nos testes
atuais):

- equipe: todo aviso sai pela instancia central, exista ou nao linha de
  instancia da barbearia;
- cliente: sai pelo central; falha registra nao enviada; sem URL nao registra;
  plano sem zap nao manda;
- `numero_existe` pergunta pela central;
- os quatro textos novos do cliente;
- lista: as 07:00 grava id e jid; cada um dos 5 gatilhos enfileira de 07:00 em
  diante e nao enfileira antes; outro dia mantem o aviso curto; a task apaga e
  manda, marca o novo e o cancelado, manda mesmo se apagar falhar, sem linha
  anterior so' manda, e sem horario restante escreve "Não sobrou horário
  hoje.";
- `WHATSAPP_POR_BARBEARIA`: criar, trocar plano e conferir nao criam
  instancia; o comando apaga todas e e' idempotente;
- bot: `receber` ignora e `ligar_bot` recusa;
- migracao: toda barbearia termina `COM_ZAP`;
- card do central: so' admin; QR so' quando nao conectado; cria a instancia
  que falta.

Front (testes de tela atuais + `tsc`): a tela do WhatsApp com a saudacao e o
Copiar; a faixa nao aparece; o admin sem seletor de plano e com o card do
central.

Medicao manual: a premissa da secao 6 e o QR do central pelo card do admin.

## 9. Ordem de subida

1. Back e front mergeados juntos — o front novo le o formato novo de
   `/painel/whatsapp`.
2. Deploy no Coolify.
3. No admin, escanear o QR do central com o chip do Marcai. Ate isso, aviso de
   equipe falha so' no log e mensagem de cliente vira "nao enviada".
4. Rodar `desligar_instancias_das_barbearias` no conteiner `api`.
5. Cada dono cola a saudacao no WhatsApp Business.

## 10. Para a etapa 2 (registro, nao escopo)

- O chip recusado pela Meta: causa provavel, o numero ainda tinha conta de
  WhatsApp. A Meta so' aceita numero sem conta — apagar a conta no app antes.
- O MEI do Jose serve para a verificacao na Meta. Antes, colocar "Marcai"
  como nome fantasia (atualizacao cadastral no Portal do Empreendedor), para
  o nome de exibicao bater com a empresa. Faturar as barbearias por esse MEI
  (atividades de malote e transporte, limite ja' ocupado) e' assunto para
  contador.
- Regras da Meta medidas em 04–06/10/2026: mensagem iniciada pela empresa so'
  por modelo aprovado, e a parte variavel do modelo nao aceita quebra de
  linha; texto livre so' na janela de 24h depois que a pessoa escreveu; desde
  01/10/2026, 1.000 mensagens de atendimento gratis por numero por mes, depois
  uns US$ 0,0068 cada no Brasil; a API oficial nao apaga mensagem enviada;
  coexistencia exige o Marcai como provedor (Tech Provider) e o proprio dono
  conectando pela janela da Meta; conta sem verificacao: 2 numeros e 250
  pessoas por dia.
