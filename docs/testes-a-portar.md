# Testes a portar (Tarefa 1 → Tarefa 2)

Estas asserções viviam em `front/tests/ambiente.test.ts` e verificavam
decisões de infraestrutura que, na Tarefa 1, se mudaram deste lado da
fronteira (`db`, `redis`, `evolution`, `zelador`, `agendador`). Elas saíram
de lá porque a suíte do front não pode ler arquivo do repositório do back —
é exatamente o acoplamento que a separação em dois repositórios existe para
desfazer (um CI que clone só o front quebraria com `ENOENT`).

O código abaixo é o conteúdo **verbatim** removido, comentários incluídos —
os comentários carregam o incidente de 10/08 e o motivo de cada `expect`, e
são o valor real disto, não a sintaxe. Elas renascem em pytest na Tarefa 2,
lendo `back/docker-compose.yml` e `back/docker/zelador.sh` de dentro do
próprio repositório do back.

---

## Metade do teste "a chave da Evolution alimenta os dois serviços do compose"

A propriedade original era bilateral — uma variável, dois consumidores, cada
um num compose. Com dois repositórios ela não tem casa única; a metade do
`app` (que manda `EVOLUTION_API_KEY`) ficou em `front/tests/ambiente.test.ts`,
afirmando pelo nome da variável. Esta é a outra metade, a do lado que agora
mora aqui:

```ts
it('a chave da Evolution alimenta os dois serviços do compose', () => {
  const compose = readFileSync(join(RAIZ, 'docker-compose.yml'), 'utf8');
  // O `app` manda e o `evolution` exige. Se um deixar de sair da mesma
  // variável, o sintoma é 401 silencioso em todo envio.
  expect(compose).toMatch(/AUTHENTICATION_API_KEY:\s*\$\{EVOLUTION_API_KEY\}/);
  expect(compose).toMatch(/EVOLUTION_API_KEY:\s*\$\{EVOLUTION_API_KEY\}/);
});
```

(A segunda linha, `EVOLUTION_API_KEY: ${EVOLUTION_API_KEY}`, é a mesma
asserção que a metade do front faz sobre o `app` — reaparece aqui porque no
compose original as duas viviam no mesmo `it`. Ao portar, a asserção sobre
`AUTHENTICATION_API_KEY` é a que importa deste lado.)

## Teste "o agendador confere o WhatsApp no mesmo tique do lembrete"

```ts
it('o agendador confere o WhatsApp no mesmo tique do lembrete', () => {
  const compose = readFileSync(join(RAIZ, 'docker-compose.yml'), 'utf8');
  // O vínculo do WhatsApp cai sozinho (`Instance - LOGOUT`, sem ninguém
  // pedir) e depois disso a Evolution responde 201 com `status: PENDING`
  // para TUDO, sem entregar nada. Aconteceu, e ficou quase duas horas assim:
  // o sintoma é cliente deixando de receber confirmação, que ninguém
  // descobre olhando tela. O agendador não conserta — reconectar exige o QR,
  // que exige uma pessoa — mas grita, e era isso que faltava.
  expect(compose).toMatch(/connectionState/);
  expect(compose).toMatch(/WHATSAPP FORA DO AR/);
  // A cadência do aviso é a mesma do lembrete de propósito: um processo, um
  // laço, um lugar para olhar.
  expect(compose).toMatch(/EVOLUTION_API_KEY:\s*\$\{EVOLUTION_API_KEY\}/);
});
```

## Teste "o zelador alarma envio recusado e poda o histórico"

```ts
it('o zelador alarma envio recusado e poda o histórico', () => {
  const compose = readFileSync(join(RAIZ, 'docker-compose.yml'), 'utf8');
  const zelador = readFileSync(join(RAIZ, 'docker', 'zelador.sh'), 'utf8');

  // O WhatsApp rejeita de forma ASSÍNCRONA: quando a recusa chega, a Evolution
  // já devolveu 201 ao app. `status = 'ERROR'` é o único registro disso, e sem
  // alguém lendo esse registro a mensagem que não chega é invisível.
  expect(zelador).toMatch(/status = 'ERROR'/);
  expect(zelador).toMatch(/RECUSADO/);

  // A poda existe porque o rastreio de status EXIGE guardar o texto que nós
  // mandamos — medido: sem a linha da mensagem, a `MessageUpdate` fica vazia.
  // Sem poda, o histórico cresceria para sempre.
  // As aspas viajam escapadas dentro da string de shell: `\"Message\"`.
  expect(zelador).toMatch(/DELETE FROM \\"Message\\"/);
  expect(zelador).toMatch(/DIAS_DE_HISTORICO=\d+/);
  // `MessageUpdate` primeiro: ela referencia `Message`.
  expect(zelador.indexOf('DELETE FROM \\"MessageUpdate\\"'))
    .toBeLessThan(zelador.indexOf('DELETE FROM \\"Message\\"'));

  // Os dois flags andam juntos — ligar só um deixa a tabela de status vazia.
  expect(compose).toMatch(/DATABASE_SAVE_DATA_NEW_MESSAGE:\s*"true"/);
  expect(compose).toMatch(/DATABASE_SAVE_MESSAGE_UPDATE:\s*"true"/);
  // Conversa de cliente continua fora: o produto nunca recebe mensagem.
  expect(compose).toMatch(/DATABASE_SAVE_DATA_CONTACTS:\s*"false"/);
  expect(compose).toMatch(/DATABASE_SAVE_DATA_HISTORIC:\s*"false"/);
});
```

## Teste "a sessão da Evolution mora num volume nomeado"

```ts
it('a sessão da Evolution mora num volume nomeado', () => {
  const compose = readFileSync(join(RAIZ, 'docker-compose.yml'), 'utf8');
  // Sem volume, todo `docker compose down` obriga a escanear o QR de novo —
  // em produção, é o telefone da barbearia caindo a cada deploy.
  expect(compose).toMatch(/evolution_instances:\/evolution\/instances/);
});
```
