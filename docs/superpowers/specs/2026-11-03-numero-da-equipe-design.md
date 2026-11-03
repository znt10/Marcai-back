# Número da equipe separado (Evolution) — design

03/11/2026. PR próprio, só back, desligado por padrão. O José liga quando quiser.

## Por que

Desde 31/10 o número central está na API oficial da Meta, e tudo sai por ele:
o que vai para o cliente e o que vai para a equipe. Para a equipe, a Meta é
ruim de dois jeitos:

1. **Cobra cada mensagem** (~R$ 0,035, utilidade). A lista do dia é refeita
   de 5 a 7 vezes por dia nas sextas e sábados (contado pelo José na
   Evolution), e cada lista refeita sai como mensagem nova e paga.
2. **Não apaga mensagem.** O `apagar_para_todos` devolve False com a Meta
   ligada (PR #66). A lista velha fica no celular do barbeiro, e num dia
   movimentado ele acaba com dez listas empilhadas.

A Evolution não cobra e apaga. O risco de bloqueio para a equipe é baixo:
são poucos números, que conhecem o remetente, salvaram o contato e mandaram
um "oi". Se o chip da equipe cair, o cliente não percebe nada, porque ele
continua sendo atendido pela Meta.

## Objetivo

Com uma variável ligada, **tudo o que vai para a equipe sai pela Evolution**,
mesmo com `WHATSAPP_PROVEDOR=meta`. Tudo o que vai para o cliente continua
pela Meta.

## Fora do escopo

- Os planos Básico, Normal e Completo, e a cobrança por eles.
- O lembrete por toque, que é outro design (`2026-11-03-lembrete-por-toque-design.md`).
- Notificação do painel ou app do barbeiro.
- Conferir se o barbeiro mandou mesmo o "oi" (ver as decisões abaixo).

## O que já existe (03/11, main em 5ffe499)

- `whatsapp.py` já separa os dois destinos:
  - **equipe:** `enviar_a_equipe`, `enviar_a_equipe_da` e `enviar_a_equipe_aceita` (esta é a da lista do dia).
  - **cliente:** `enviar_ao_cliente` e `enviar_pelo_central` (código da conta do cliente).
- Os dois caminhos chegam em `_enviar_aceita`. Com `whatsapp_meta.ligado()`, ela desvia para a Meta.
- `apagar_para_todos` devolve False com a Meta ligada.
- Quem chama a equipe:
  - lista do dia e lista refeita (`lista_do_dia.py`);
  - aviso de horário novo e de cancelado (`views/agendamentos.py`);
  - convite e reenvio de convite (`views/admin_barbearias.py`, `views/equipe.py`);
  - avisos do bot para a equipe (`bot.py`);
  - avisos da mensalidade ao dono (`mensalidade/avisos.py`, `mensalidade/operacoes.py`).
- `EVOLUTION_API_URL`, `EVOLUTION_INSTANCE` e `EVOLUTION_API_KEY` já existem e já apontam para a instância central antiga.

## Comportamento

### A chave

Variável nova: `WHATSAPP_EQUIPE_PELA_EVOLUTION=1`.

- **Ausente:** nada muda. É o comportamento de hoje, linha por linha.
- **Ligada:** os envios de equipe e o `apagar_para_todos` ignoram a Meta e
  vão para a Evolution, na instância `EVOLUTION_INSTANCE`. Os envios ao
  cliente seguem a regra de hoje: Meta se ligada, senão Evolution.

A chave é lida a cada chamada, como `whatsapp_meta.ligado()`, para que os
testes possam trocá-la.

### Qual chip

O chip da equipe é o que estiver conectado na instância `EVOLUTION_INSTANCE`.
Pode ser o número central antigo, se ele ainda estiver conectado, ou um chip
novo conectado nessa instância pelo QR do Evolution Manager. Trocar o chip
é operação, não código.

### Convite

O convite continua como está hoje: pela Meta, mesmo com a chave ligada. É a
primeira mensagem que um barbeiro novo recebe, e mandar isso de um chip que
ele não conhece é justamente o padrão que mais derruba número na Evolution.

### O primeiro contato com o chip é feito à mão

O José pega o número do barbeiro, manda a primeira mensagem do próprio
celular do chip ("salva esse contato, a sua agenda vai chegar por aqui") e
espera o "oi". Só então a conversa passa a existir para a Evolution. Isso não
tem código: não há cartão no painel nem linha nova no convite.

### Falha

Se o envio pela Evolution falhar, **não volta para a Meta.** A Meta cobraria
e não apagaria, que é exatamente o que este PR evita. O erro fica no log,
como já acontece hoje com o envio à equipe. O barbeiro continua vendo a
agenda no painel.

## Decisões

Do José:
- Dois números separados. A coexistência da Meta foi descartada: o número
  central já está só na API, a Meta escolhe quem pode entrar, e a Evolution
  pendurada no número oficial arriscaria derrubar todos os clientes.
- O primeiro contato é dele, à mão, do celular do chip. O barbeiro responde com "oi".
- É um PR separado, para ligar quando ele quiser.

Minhas, para o José conferir:
- A chave é booleana e reaproveita `EVOLUTION_INSTANCE`, em vez de criar uma instância nova por variável.
- O convite continua na Meta, sem mudança.
- O sistema não confere se o barbeiro respondeu o "oi".
- Não existe volta automática para a Meta quando a Evolution falha.

## O que fica com quem implementa

- Onde exatamente ler a chave: um `equipe_pela_evolution()` em `whatsapp.py` ou no módulo de config.

## Testes

- Chave desligada: a suíte atual passa sem mudança.
- Chave ligada e Meta ligada:
  - lista do dia, lista refeita, aviso de horário e avisos da mensalidade chamam a Evolution, não a Meta;
  - `apagar_para_todos` chama a Evolution;
  - `enviar_ao_cliente` e `enviar_pelo_central` continuam chamando a Meta;
  - o convite continua chamando a Meta.

## Para ligar em produção

1. Conectar o chip na instância `EVOLUTION_INSTANCE`.
2. Do celular do chip, mandar a primeira mensagem para cada barbeiro e esperar o "oi".
3. No Coolify: `WHATSAPP_EQUIPE_PELA_EVOLUTION=1`.
4. Deploy.
