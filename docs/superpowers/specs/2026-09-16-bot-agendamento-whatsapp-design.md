# Bot de agendamento pelo WhatsApp da barbearia

Desenho aprovado em 16/09/2026. Abrange os dois repositorios
(`Marcai-back` e `Marcai-front`).

## 1. O que e

Hoje o Marcai so' MANDA mensagem. Este desenho o faz RECEBER: o cliente
escreve para o WhatsApp da propria barbearia, um bot de menu numerado
pergunta servico, barbeiro, dia e hora, pede confirmacao, e grava o
agendamento.

Tres coisas ja existentes tornam isso pequeno, e e' por causa delas que o
projeto cabe:

- **`marcar()`** (`app/services/agendamentos.py`) ja' e' o motor dos dois
  fluxos atuais, painel e publico. O bot vira um terceiro chamador. Conflito
  de horario, snapshot de preco e codigo publico saem iguais, de graca.
- **`Cliente` e' unico por `(barbearia, whatsapp)`** (`tenant/models.py`). O
  numero de quem escreveu E' a identidade. Sem cadastro, sem senha, sem token.
- **`slots_livres()`** ja' calcula os horarios livres com `agora` injetado.

O que falta e' so' a porta de entrada: o webhook hoje assina apenas
`CONNECTION_UPDATE` e `QRCODE_UPDATED`.

### Dependencia que bloqueia a construcao

Isto se apoia inteiramente no plano **com zap** (uma instancia da Evolution
por barbearia), que esta' pronto em codigo mas **ainda nao subiu**. Nao ha
como testar de ponta a ponta antes daqueles dois PRs serem revisados e de um
numero real ser ligado. Spec e plano podem ficar prontos; a construcao espera.

## 2. Decisoes

| Decisao | Escolha | Por que |
|---|---|---|
| Como entende o texto | **Menu numerado** | Deterministico, testavel sem rede, custo zero por mensagem, funciona para cliente que nao e' bom de celular |
| Bot x humano no mesmo numero | **Cala quando alguem da barbearia responde** | O numero e' o da barbearia; o dono conversa por ele |
| Escopo | Marcar, cancelar, responder ao lembrete | "Ver meus horarios" cortado — volta de graca (secao 4) |
| Ativacao | Interruptor no painel, **desligado por padrao** | Da' para soltar para uma barbearia so'; ninguem acorda com robo no numero do negocio |
| Historico de conversa | **Nao guarda** | Nenhum texto de cliente no banco. Nada a vazar |
| Encanamento | Webhook enfileira, worker Celery responde | Secao 6 |

### O que ficou de fora, de proposito

- **Remarcar.** Cancelar + marcar resolve, com menos estado.
- **Leitura de texto livre / IA.** Custo por mensagem, latencia, chave nova,
  e muito mais dificil de testar.
- **Item de menu "meus horarios".** Ver secao 4.
- **Audio, figura, sticker.** Descartados na entrada.

## 3. A maquina de conversa

A regra que faz a parte pura ser pura: **o bot guarda as opcoes que ofereceu.**
Ao mandar "1 - Joao / 2 - Pedro" ele grava
`[{"id": "<uuid>", "rotulo": "Joao"}, ...]`. Entender a resposta vira
`texto -> opcoes[n-1]` e nao consulta banco nenhum. O banco entra so' para
MONTAR a proxima pergunta, nunca para ENTENDER a anterior.

```
entender(estado, texto, opcoes) -> Escolha | NaoEntendi      # puro
   (a casca busca o que o proximo passo precisa)             # unica parte suja
montar(passo, dados)            -> Fala(texto, opcoes)       # puro
```

Modulo novo: `app/services/conversa.py`. Sem import de `django.db`, sem
`requests`. Espelha `whatsapp_eventos.py` e o `faixaDoWhatsapp` do front.

### Estados

`MENU`, `SERVICO`, `BARBEIRO`, `DIA`, `HORA`, `NOME`, `CONFIRMA`,
`QUAL_AGENDAMENTO`, `CONFIRMA_CANCEL`, `AGUARDANDO_LEMBRETE`.

**Nao existe estado `MUDO`.** O silencio e' a coluna `mudo_ate`, e nao um
estado, porque entrar em mudo nao pode apagar onde a conversa estava: o
cliente que escolheu barbeiro, falou com o dono e voltou tem que continuar de
onde parou, nao recomecar do menu.

### Fluxo

```
chega mensagem de <numero>
        |
   busca Cliente (barbearia, whatsapp) e agendamentos futuros
        |
   +----+--------------------------------+
   |                                     |
nenhum agendamento               tem agendamento
   |                                     |
 MENU                                 MENU
  1 - Marcar horario                   "Voce tem: Pedro, qui 17/09 09:00"
  0 - Falar com a barbearia             1 - Marcar outro horario
                                        2 - Cancelar esse
                                        0 - Falar com a barbearia

  1 -> SERVICO -> BARBEIRO -> DIA -> HORA -> [NOME] -> CONFIRMA -> marcar()
  2 -> [QUAL_AGENDAMENTO] -> CONFIRMA_CANCEL -> cancelar_publico()
  0 -> muda o bot + avisa a equipe pelo numero central
```

- **`SERVICO` e `BARBEIRO` sao pulados quando so' ha uma opcao.** Perguntar
  "1 - Corte" e' fazer o cliente trabalhar para responder o obvio.
- **`DIA`** oferece ate' 5 proximos dias COM horario livre, mais "outro dia",
  que avanca a janela. Dia sem vaga nunca aparece.
- **`HORA`** oferece ate' 6 horarios, mais "outro dia".
- **`NOME`** e' o unico passo de texto livre, e so' existe para numero sem
  `Cliente`. Todo agendamento exige um `Cliente`, e todo `Cliente` tem nome:
  logo numero com agendamento SEMPRE tem nome, e nunca cai aqui.
- **`QUAL_AGENDAMENTO`** so' existe com mais de um agendamento futuro.
- **`AGUARDANDO_LEMBRETE`**: ver secao 4.

### Regras que moram na funcao pura

1. **Numero fora da lista repete a pergunta**, nao avanca. Na terceira vez
   seguida oferece `0 - falar com a barbearia` e para de insistir. Bot que
   repete o mesmo menu para sempre e' pior que bot nenhum.
2. **Conversa parada ha mais de 20 minutos volta ao `MENU`.** Sem isso, um
   "2" digitado no dia seguinte marcaria um horario que o cliente nao lembra
   ter escolhido. A conta sai de `atualizado_em`, com `agora` injetado.
3. **As opcoes gravadas nao sao autoridade.** Um id de horario guardado vale
   como intencao, nao como reserva: quem decide e' o `marcar()`, que recheca
   conflito no banco. Horario que sumiu entre oferecer e confirmar vira
   mensagem honesta ("esse acabou de ser pego"), nunca `500`.
4. **O bot nunca sugere cancelar.** Mostra o que a pessoa tem e deixa a opcao
   na lista. "Quer cancelar?" planta a ideia.

## 4. O lembrete, sem codigo novo de bot

O lembrete que o Marcai ja' manda (`app/services/lembrete.py`) passa a
terminar com `1 - confirmar / 2 - cancelar` e deixa a conversa parada em
`AGUARDANDO_LEMBRETE`, com `opcoes` apontando para aquele agendamento. A
resposta cai no mesmo `entender()`.

O lembrete nao ganha maquina; ganha duas opcoes.

**"Ver meus horarios" volta de graca**, sem ser item de menu: o `MENU` de quem
tem agendamento ja' comeca dizendo o que a pessoa tem. Isso responde a
pergunta mais comum que chega no WhatsApp de barbearia — "que horas mesmo e' o
meu?" — sem um passo dedicado.

## 5. Dados

### `WhatsappInstancia` ganha uma coluna

`bot_ativo` — booleano, `default False`.

**Vai aqui e nao em `Barbearia`** porque `brutus_app` (o papel do runtime) NAO
tem `UPDATE` em `tenant_barbearia`, so' na coluna `horario_resumo`
(`0002_rls.py`). Quem escreve la' e' `brutus_admin` — e' por isso que `plano`
funciona, ja' que plano quem troca e' o admin da plataforma. O interruptor do
bot quem liga e' o DONO, pelo painel, que e' runtime: uma coluna em
`Barbearia` morreria com `permission denied` em producao, na hora do primeiro
clique. `WhatsappInstancia` e' a tabela que existe exatamente porque o runtime
escreve nela, e semanticamente fecha: o bot e' propriedade do numero.

### `ConversaWhatsapp` — tabela nova

Uma linha por `(barbearia, whatsapp)`, sobrescrita a cada passo.

| Campo | Tipo | Nota |
|---|---|---|
| `barbearia` | FK | |
| `whatsapp` | text | unique junto com `barbearia` |
| `estado` | text | choices `EstadoConversa` |
| `opcoes` | jsonb | `[{"id": "...", "rotulo": "Pedro"}]` |
| `rascunho` | jsonb | `{"servico_id": "...", "dia": "2026-09-17"}` |
| `ultima_mensagem_id` | text, nulo | dedupe do `messages.upsert` |
| `mudo_ate` | timestamp, nulo | nulo = o bot fala |
| `atualizado_em` | timestamp | origem da expiracao de 20 min |

**Uma linha por conversa, nao por mensagem.** Uma tabela que crescesse por
mensagem seria ilimitada e cheia de texto de cliente. Aqui o volume e' o
numero de clientes.

**`jsonb` e' o primeiro do projeto.** Nao normalizado porque as opcoes mudam de
forma a cada estado e vivem 20 minutos: uma tabela-filha custaria um join por
mensagem para guardar o que expira.

**O `zelador` apaga conversa parada ha dias**, no mesmo lugar e no mesmo
formato de `_podar_nao_enviadas()`.

### RLS

Migracao nova, copia estrutural da `0005`: `ENABLE` + `FORCE ROW LEVEL
SECURITY`, politica `tenant_isolation TO brutus_app, brutus_admin`, politica
`owner_irrestrito TO brutus_owner`, os quatro GRANTs, e `reverse_sql`
completo. `conftest.py` ganha a tabela na lista de `TRUNCATE`.

## 6. Entrada: webhook e fila

`MESSAGES_UPSERT` entra na lista de eventos de `_aplicar_webhook()`. A
`WhatsappEventoView` desvia por nome de evento: conexao e QR continuam indo
para `whatsapp_eventos`; mensagem vai para a fila.

### Descartes na view, do mais barato ao mais caro

```
@g.us                    -> descarta   (grupo, nunca)
sem texto                -> descarta   (audio, figura, sticker)
instancia desconhecida   -> descarta
fromMe                   -> mudo_ate = agora + 4h, NAO enfileira
bot_ativo = false        -> descarta
                         -> enfileira (barbearia_id, numero, texto, mensagem_id)
```

`fromMe` E' o sinal de "o dono respondeu": ele digitou do celular, a Evolution
manda o eco para ca'. Nao precisa de task — e' um `UPDATE` de uma coluna.

**Enfileira quatro campos, nao o payload.** A assinatura da task fica testavel
sem inventar um JSON da Evolution inteiro.

### Por que fila e nao processamento direto

Responder ao cliente exige uma chamada HTTP para a Evolution. Nos MEDIMOS
essa API levar 5,3 s num endpoint para o qual eu tinha dado 5 s de limite. Se
a resposta for montada dentro do webhook, a Evolution espera por ela mesma,
estoura, e **reenvia o evento** — e reenvio no meio de conversa com estado
significa o bot repetindo ou pulando um passo. Enfileirar faz o `200` sair em
milissegundos, muito antes de qualquer retentativa.

O Celery ja' esta' de pe' e ja' sabe entrar em contexto de tenant
(`conferir_instancias`, `lista_do_dia`).

### Tres protecoes obrigatorias

- **`select_for_update()` na conversa.** Cliente ansioso manda "1" e "2" com
  meio segundo de diferenca: duas tasks, mesma linha. Sem a trava, as duas
  leem o mesmo estado e as duas avancam.
- **A task NAO retenta.** Retentar rodaria a maquina de novo, e no `CONFIRMA`
  isso e' uma segunda tentativa de marcar. O banco recusaria com `23P01` pela
  restricao de exclusao, entao nao viraria agendamento duplo — viraria um erro
  em cima de um horario que JA' foi marcado com sucesso, e o cliente leria
  "nao deu certo" depois de ter dado certo. Mesma escolha ja' escrita em
  `MensagemNaoEnviada`: nada aqui e' reenviado depois.
- **Dedupe por `ultima_mensagem_id`**, conferido dentro da transacao que trava
  a linha.

### Canais

A resposta ao cliente sai pela instancia DA BARBEARIA (`_enviar`). O aviso de
`0 - falar com a barbearia` sai pelo numero CENTRAL, via `enviar_a_equipe` —
o numero da barbearia nao serve para avisar a barbearia.

## 7. Painel

`ver()` passa a devolver `botAtivo` (`false` tambem no ramo sem zap, como os
outros campos ja' fazem). Nasce `POST /api/painel/whatsapp/bot`, no formato de
`desconectar`: `ExigeDono`, `422` quando nao ha o que ligar.

**So' o dono**, pela razao ja' escrita no cabecalho de `whatsapp_painel.py`:
um barbeiro que desligasse o bot mudaria como TODO cliente da barbearia e'
atendido, sem o dono saber.

No front, um interruptor em `/painel/whatsapp`, visivel so' para o dono.
`/painel/whatsapp` ja' esta' em `MIGRADAS` e o casamento e' por segmento,
entao `/painel/whatsapp/bot` ja' vai para o Django sem alteracao.

### O interruptor aplica o webhook ANTES de gravar

A lista de eventos e' gravada na instancia, la' na Evolution, nao no nosso
codigo. As instancias que ja' existem assinaram so' dois eventos: ligar o bot
no banco nao faz mensagem nenhuma comecar a chegar.

A alternativa seria assinar `MESSAGES_UPSERT` para todas as instancias sempre
e filtrar por `bot_ativo` aqui. Mais simples, e nunca haveria interruptor
ligado sem webhook. Foi recusada porque toda mensagem de todo cliente de toda
barbearia com zap passaria pelo nosso servidor, inclusive das que nunca
quiseram bot — o que contradiz a decisao de nao guardar conversa.

Entao: aplica o webhook, e so' grava se a Evolution aceitar. Falhou, `422`, e
o bot continua desligado. **Nunca existe interruptor mentindo** — ligado na
tela e mudo na pratica seria o pior defeito possivel, porque o dono pararia de
responder cliente achando que o robo responde.

Barbearia sem bot nunca manda uma mensagem de cliente para o Marcai.

## 8. Fatia 0: o que e' medido antes de escrever a maquina

Mesmo formato da fatia 0 anterior, e pela mesma razao: ela achou que
`/instance/create` leva 5,3 s, derrubando um palpite de 5 s.

1. **A Evolution 2.3.7 entrega `fromMe`?** Se nao entregar, "cala quando o
   dono responde" nao existe e a secao 6 precisa ser redecidida. E' a premissa
   mais cara do desenho.
2. **Qual a forma do corpo?** Texto simples vive em `message.conversation`;
   resposta CITANDO outra mensagem vive em
   `message.extendedTextMessage.text`. Ler o campo errado da' um bot que
   ignora justamente quem responde citando o lembrete (secao 4).
3. **`webhook/set` aceita reescrever os eventos de uma instancia que ja'
   existe e ja' esta' conectada?** A secao 7 inteira depende disso.
4. **Qual e' o `remoteJid` de grupo de verdade?** Descartar por `@g.us` e' o
   que se supoe bastar.
5. **Quanto leva `sendText`?** Define o limite de tempo da task.

Saida: numeros e formatos medidos, nao supostos.

## 9. Testes

O grosso em `tests/test_conversa.py`, que **nao toca banco nem rede** — a
maquina e' pura, entao o arquivo e' grande e roda em milissegundos. Depois
`test_bot_entrada.py` (os descartes da view), `test_bot_tarefa.py` (a task com
a Evolution dublada), `test_bot_painel.py` (o interruptor e a ordem
webhook-antes-de-gravar), mais `test_rls.py` e a lista de `TRUNCATE` do
`conftest.py`.

Os casos que existem porque sao os caros:

| Caso | O que impede |
|---|---|
| Mensagem de grupo | Bot dando menu no grupo da familia |
| Dono digitou do celular (`fromMe`) | Bot atropelando conversa humana |
| Duas mensagens no mesmo segundo | Dois agendamentos de um "sim" so' |
| Mesmo `mensagem_id` duas vezes | Bot repetindo o passo |
| "9" num menu de 3, tres vezes | Laco infinito de menu |
| Conversa de ontem | "2" de ontem marcando hoje |
| Horario sumiu entre oferecer e confirmar | `500` no lugar de "esse acabou de ser pego" |
| `bot_ativo = false` | Bot falando onde nao foi convidado |
| Cancelar horario de OUTRO numero | O pior de todos — e' o `test_rls` deste projeto |
| Cliente novo vs cliente conhecido | Onde `marcar()` explode se o desenho estiver errado |
| So' um servico / so' um barbeiro | O passo e' pulado |

### O que teste nenhum cobre

Conversa de verdade, no celular, com a Evolution de pe'. Automatizado prova
que o bot responde certo ao que ACHA que o WhatsApp manda. So' o aparelho
prova que o WhatsApp manda aquilo.

## 10. Riscos em aberto

- **Premissa 1 da secao 8.** Se `fromMe` nao chegar, a decisao "bot x humano"
  volta a mesa antes de qualquer codigo de maquina.
- **A fatia com zap nao subiu.** Nada aqui e' verificavel de ponta a ponta ate'
  la'.
- **Limite de tempo da Evolution na VPS.** O `/instance/create` foi medido em
  5,3 s local; falta confirmar se 15 s bastam no servidor mais lento. Vale
  para o `sendText` do bot tambem.
- **Tres testes do backend dependem de relogio** (derivam dia da semana de uma
  data em UTC enquanto o motor usa Sao Paulo; so' falham entre 00:00 e 03:00
  UTC). Pre-existentes, fora do escopo, cartao separado.
