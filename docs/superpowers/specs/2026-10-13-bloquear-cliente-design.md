# Bloquear cliente — design

13/10/2026. Pedido do José: um barbeiro reclamou de uma cliente que marca,
marca, marca e nunca aparece. A equipe precisa poder bloquear esse número para
ele não conseguir mais marcar pelo site, **sem avisar a pessoa**. O erro tem
que levá-la, por instinto, a chamar a barbearia.

## 1. Decisões (do José, não reabrir)

- **Quem bloqueia:** qualquer um da equipe (dono ou barbeiro).
- **Vale para:** a barbearia inteira, não só para quem bloqueou.
- **O que a pessoa vê:** o site funciona normalmente até o último botão, que
  responde *"Não foi possível concluir o agendamento. Chama a barbearia:
  (83) 9 xxxx-xxxx"*. Nenhuma palavra sobre bloqueio.
- **Horários já marcados:** os futuros dela, com qualquer barbeiro, são
  cancelados na hora do bloqueio, **sem mensagem** para ela.
- **Aparelho:** bloquear o número bloqueia também o navegador de onde ela
  marcou. Trocar de número no mesmo celular não adianta.
- **Celular dividido** (família) fica bloqueado junto, e está aceito: "é
  culpa da pessoa; ela fala com o barbeiro". Bloquear alguém para sempre
  também está aceito.
- **IP não entra.** Celular troca de IP o tempo todo, e no 4G centenas de
  pessoas dividem o mesmo; bloquear IP pegaria vizinho e não pegaria ela.

## 2. O que muda para cada um

### Barbeiro / dono — bloquear
Na Agenda (`AgendaDoDia`), cada horário ganha **bloquear**, ao lado de
"cancelar" e do WhatsApp. O barbeiro só vê os horários dele, então só bloqueia
quem marcou com ele — mas o bloqueio vale para a barbearia toda.

Confirmação antes: *"Bloquear Maria (83 9 xxxx-xxxx)? Ela não vai conseguir
marcar pelo site, e os 3 horários que ela tem marcados vão ser cancelados sem
aviso."* (o número de horários vem do back; com zero, a segunda metade some).

### Dono — desbloquear
No fim da tela **Equipe**, só para o dono: "Clientes bloqueados" — nome,
número, quem bloqueou, quando, e **desbloquear**. Desbloquear libera o número
e os aparelhos dela na hora. Os horários cancelados no bloqueio **não**
voltam.

### Cliente bloqueada
Igual a hoje até "confirmar". Aí o erro da seção 1, com status 422 — o mesmo
das outras recusas, para não dar pista nenhuma.

### Painel marcando para ela
Continua liberado. Se o barbeiro marcar pelo painel (`FormMarcar`), a decisão
é dele.

## 3. Por dentro

### Banco (uma migration, só acrescenta)
- `Cliente.bloqueado_em` (datetime, nulo) e `Cliente.bloqueado_por`
  (FK `Barbeiro`, nulo, `SET_NULL`). Bloqueado = `bloqueado_em` preenchido.
  Fica no `Cliente` porque ele já é único por (barbearia, whatsapp).
- `Agendamento.aparelho` (texto, nulo): a marca do navegador que marcou pelo
  site. Agendamentos antigos ficam nulos.

### A marca do aparelho
- Cookie `aparelho`: um id aleatório, **gravado pelo Django** na resposta do
  `POST /api/agendamentos` quando ainda não existe. `httpOnly`, `SameSite=Lax`,
  `Secure` fora de DEBUG, validade de 2 anos, só do domínio da barbearia (o
  bloqueio já é por barbearia).
- Gravado pelo servidor, e não por JavaScript, por causa do iPhone: o Safari
  apaga em 7 dias o que o script grava, mas não o cookie que vem do servidor.
  O link abre sempre no Safari, então a marca fica.
- Chega ao Django pelo rewrite `/api/*` do Next, igual ao cookie de sessão do
  painel.

### A recusa (só no `POST /api/agendamentos`, a rota do site)
Antes de `marcar()`, recusa se:
1. o `Cliente` desse número nesta barbearia tem `bloqueado_em`; **ou**
2. o cookie `aparelho` aparece em algum `Agendamento` de um cliente bloqueado
   desta barbearia.

A segunda regra é uma consulta, e não uma lista de aparelhos copiada no
bloqueio: assim ela pega também o aparelho que marcou com o número bloqueado
*antes* do bloqueio, e o desbloqueio libera tudo apagando um campo só.

A recusa vem **depois** das checagens que já existem (formulário, número
válido, `numero_existe`), para o erro só aparecer no último passo, como as
outras recusas. Nada é gravado na recusa.

### Bloquear (`POST /api/painel/clientes/bloquear`, `ExigeSessao`)
- Entrada: o id do agendamento de onde o botão foi apertado. O barbeiro só
  pode usar agendamento dele (`filtro_do_barbeiro`, igual ao cancelar); o dono,
  qualquer um.
- Numa transação: marca o cliente (`bloqueado_em`, `bloqueado_por`) e cancela
  os horários futuros `CONFIRMADO` dele (status `CANCELADO_BARBEIRO`, como o
  cancelar do painel), **sem** mandar WhatsApp ao cliente.
- Depois do commit, para cada barbeiro que tinha horário de HOJE cancelado:
  `lista_do_dia.avisar_mudanca`, para a lista do dia sair refeita (a mesma
  regra de quando o painel cancela um horário de hoje).
- Bloquear quem já está bloqueado não muda nada e devolve ok.
- A prévia da confirmação (`GET .../clientes/bloquear?agendamento=<id>`)
  devolve nome, número e quantos horários futuros seriam cancelados.

### Desbloquear e listar (`ExigeDono`)
- `GET /api/painel/clientes/bloqueados` → nome, whatsapp, quem bloqueou,
  quando.
- `POST /api/painel/clientes/<id>/desbloquear` → limpa os dois campos.

### Front
- `AgendaDoDia`: botão **bloquear** + `confirm()` com a prévia.
- `Equipe`: seção "Clientes bloqueados" para o dono.
- `FormAgendamento`: nada muda — ele já mostra o `erro` que o back manda.

## 4. Testes

Back (pytest):
- número bloqueado → 422 com a frase e o número da barbearia; nada gravado;
- número NOVO vindo de aparelho que marcou com número bloqueado → 422;
- aparelho que marcou com o número **antes** do bloqueio → 422;
- primeiro agendamento sem cookie → grava o cookie e o `aparelho`;
- painel marca para número bloqueado → 201;
- bloquear cancela os futuros (não os passados), não manda WhatsApp ao
  cliente e refaz a lista de hoje;
- barbeiro não bloqueia a partir de agendamento de outro barbeiro (404);
- desbloquear libera número e aparelho; barbeiro comum não lista nem
  desbloqueia (403);
- isolamento: bloqueio numa barbearia não afeta o mesmo número em outra.

Front (vitest): o texto da confirmação (com e sem horários a cancelar).

## 5. Fora deste trabalho

- Bloquear pelo bot do WhatsApp (desligado desde 06/10). Se ele voltar, a
  mesma checagem do número entra no `_marcar` do bot.
- Contar quantas vezes a pessoa bloqueada tentou marcar.
- Aba anônima, dados do navegador apagados ou outro celular escapam — aceito.
