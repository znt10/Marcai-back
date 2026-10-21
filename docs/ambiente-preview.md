# Ambiente de teste (`*.preview.usemarcai.online`)

Um segundo Marcaí na mesma VPS, num recurso próprio do Coolify, para abrir
uma branch no celular antes do merge. Ele tem banco próprio e domínio próprio,
e não manda WhatsApp. O compose é o `docker-compose.preview.yml`, e o cabeçalho
dele explica cada diferença em relação à produção.

Por que não usar o "Preview Deployments" do Coolify: ele sobe uma cópia do
compose por PR com as **mesmas** etiquetas do Traefik da produção, e as
barbearias de verdade poderiam cair no site do PR. Além disso, o endereço
`48.usemarcai.online` seria lido como a barbearia "48", e o front viria da
`main` (`FRONT_BRANCH`), não do PR.

## Uma vez só

### 1. DNS (hPanel da Hostinger, zona `usemarcai.online`)

Acrescente **um** registro. Não mexa nos outros.

| Tipo | Nome | Aponta para | TTL |
|---|---|---|---|
| A | `*.preview` | `187.127.255.216` | 300 |

Para conferir, `dig +short brutus.preview.usemarcai.online` tem que devolver o
IP da VPS.

O certificado `*.preview.usemarcai.online` sai sozinho no primeiro deploy, pelo
mesmo resolvedor `letsencrypt-dns` da produção. Ele grava em
`_acme-challenge.preview.usemarcai.online`, que é outro registro: não briga com
o da produção. Se a emissão falhar, a armadilha é a mesma da produção (sobra
de TXT `_acme-challenge.preview` de tentativa anterior). Apague à mão no hPanel
e faça o deploy de novo.

### 2. Recurso novo no Coolify

1. **Projects**, no mesmo projeto da produção, depois **+ New**, depois
   **Public/Private Repository**. Use a mesma fonte do `marcai-back`.
2. Repositório `znt10/Marcai-back`. Em **Branch**, a branch a testar (ou
   `main`).
3. **Build Pack**: Docker Compose. **Docker Compose Location**:
   `/docker-compose.preview.yml`.
4. Nome do recurso: `marcai-preview`.
5. No serviço **front**, campo **Domains**:
   `https://admin.preview.usemarcai.online`. Os outros serviços ficam sem
   domínio.
   - Não use o raiz `preview.usemarcai.online`: a regra da produção o casa como
     a barbearia de slug "preview".
6. **Environment Variables**. Gere segredos **novos**, não copie os da
   produção. O teste é outro banco e outra sessão.

   | Variável | Valor |
   |---|---|
   | `DOMINIO_BASE` | `preview.usemarcai.online` |
   | `FRONT_BRANCH` | `main` (ou a branch do front a testar) |
   | `POSTGRES_PASSWORD`, `PGPASSWORD_OWNER`, `PGPASSWORD_APP`, `PGPASSWORD_ADMIN` | `openssl rand -hex 24` para cada um |
   | `DJANGO_SECRET_KEY`, `SESSAO_JWT_SECRET`, `ADMIN_JWT_SECRET`, `PROXY_SEGREDO` | `openssl rand -hex 32` para cada um |
   | `ADMIN_USUARIO` | o mesmo usuário de admin que você usa |
   | `ADMIN_SENHA_HASH_B64` | gere com `docker compose run --rm api python manage.py admin_hash 'a-senha'` |

7. **Deploy**. O primeiro demora, porque constrói o back e o front.

### 3. Primeira barbearia

1. Abra `https://admin.preview.usemarcai.online` e entre com o admin.
2. Crie uma barbearia, por exemplo de slug `brutus`. O convite do dono não
   chega por WhatsApp. O link aparece no log do `api`, conforme o passo 4 de
   "Testar uma branch".
3. Abra `https://brutus.preview.usemarcai.online`.

## Testar uma branch

1. No `marcai-preview`, troque **Branch** (back) e `FRONT_BRANCH` (front) pelas
   branches do PR. Exemplo: as duas `conta-do-cliente-de-volta`.
2. Faça o **Deploy**. O `api` roda as migrations da branch ao subir.
3. Teste no celular em `https://<slug>.preview.usemarcai.online`.
4. O que sairia pelo WhatsApp (código da conta, link de senha nova,
   confirmação, convite) aparece no log do `api`. No Coolify, abra o serviço
   `api`, depois **Logs**, e procure por `[whatsapp] sem EVOLUTION_API_URL`.

## Cuidados

- **Migration de branch fica no banco do teste.** Se depois você voltar o
  teste para a `main` ou para outra branch sem aquela migration, o banco fica
  com tabelas sobrando. Nada quebra, mas uma migration com o **mesmo número**
  e outro conteúdo (o caso da `0013` da conta e da mensalidade) dá erro no
  `migrate`. Nesse caso, zere o banco do teste: pare o recurso, apague o
  volume `pgdata` dele em **Storages**, e faça o deploy de novo.
- **Nunca apague volume do recurso da produção.** Os dois recursos ficam lado
  a lado no Coolify. Confira o nome do recurso antes de qualquer remoção.
- **Ninguém pode criar barbearia de slug `preview` na produção.** O raiz do
  teste viraria ela. Se um dia isso incomodar, ponha `preview` em
  `SUBDOMINIOS_RESERVADOS` (back e front).
- **O teste divide a VPS com a produção.** Pare o recurso no Coolify
  (**Stop**) quando não estiver usando.
