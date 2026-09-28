# Limite por IP na API

Toda rota da API tem um teto de pedidos por IP. As rotas de login têm um
segundo teto, mais apertado. Este documento explica o desenho e serve de
receita para levar a mesma coisa a outro projeto Django + DRF (Unistock,
FechaCaixa).

## O que existe no Marcaí

| Taxa    | Onde vale                               | Por quê                                              |
|---------|-----------------------------------------|------------------------------------------------------|
| `geral` | toda view da API (120/min)              | uma rajada não ocupa os 3 workers do gunicorn        |
| `login` | login do barbeiro e do admin (10/min)   | cada tentativa roda o argon2, que é caro de propósito |

Ficam **de fora** só o webhook da Evolution e o cron: vêm de dentro da rede,
sempre do mesmo IP, e têm credencial própria. Um 429 ali seria mensagem ou
lembrete perdido.

Quem passa do teto recebe `429 {"erro": "Muitas tentativas..."}` com
`Retry-After`. O throttle roda no `initial()` do DRF, antes do `post`, então o
pedido barrado não chega ao argon2 nem ao banco.

Os arquivos:

- `backend/app/api/v1/limite.py`: `LimitePorIP` (teto geral), `LimitaLogin`
  (mixin das rotas de login) e `tratar_excecao` (o formato do 429).
- `backend/backend/settings.py`: `REST_FRAMEWORK` (classes, taxas,
  `NUM_PROXIES`, `EXCEPTION_HANDLER`) e `CACHES`.
- `docker-compose.prod.yml`: `CACHE_REDIS_URL`.
- No front, `src/lib/ip-do-cliente.ts`: o IP que vai no `x-marcai-ip`, tanto
  pelo `proxy.ts` quanto pelo SSR (`buscarNoDjango`).

## As três armadilhas

Um throttle do DRF que parece ligado pode não estar limitando nada. As três
abaixo valiam aqui, e valem nos outros projetos:

1. **Sem `CACHES`, o contador é por worker.** O padrão do Django é o
   `LocMemCache`, que vive na memória de cada processo. Com `--workers 3`,
   cada IP tem três contadores e o limite vale o triplo. O contador precisa
   morar no Redis.
2. **Sem `NUM_PROXIES`, o IP é forjável.** Com o padrão (`None`), o DRF usa
   o `X-Forwarded-For` **inteiro** como identidade. Quem manda um valor novo
   nesse cabeçalho a cada pedido ganha um contador novo a cada pedido, e
   nunca bate no limite. O IP confiável é o que o **último** proxy
   acrescentou ao fim da lista, nunca o começo dela.
3. **Um salto interno junta todo mundo num IP só.** Quando um servidor (o
   SSR do Next, um rewrite) chama o Django em nome do navegador, o Django vê
   o IP desse servidor. Sem repassar o IP do visitante, o site inteiro divide
   um só contador, e um pico de acesso vira 429 para todo mundo.

## Receita para o Unistock e o FechaCaixa

Os dois já têm `AnonRateThrottle`/`UserRateThrottle` e `ScopedRateThrottle`
no login, mas caem nas três armadilhas: sem `CACHES`, sem `NUM_PROXIES`, e o
`next.config.ts` reescreve `/backend/*` para a **URL pública** da API. Esse
último ponto muda a receita. O pedido do navegador faz
`Traefik → Next → internet → Traefik → Django`, então o último IP da lista é
o do **próprio servidor**, para todo visitante. `NUM_PROXIES = 1` sozinho
juntaria o site inteiro num contador só.

A saída é a mesma do Marcaí: o Next manda o IP do visitante num cabeçalho
assinado por um segredo, e o Django só acredita nele com o segredo certo.

### 1. Redis para o cache

- **Unistock**: já tem Redis (o banco 0 é o Celery, o 1 é a Evolution). Use
  o banco 2.
- **FechaCaixa**: não tem Redis em produção. Acrescente o serviço ao
  `docker-compose.prod.yml`:

  ```yaml
  redis:
    image: redis:7-alpine
    restart: unless-stopped
  ```

  e `depends_on: [redis]` no `api`. O pacote `redis` já está no
  `requirements.txt` dos dois.

No `api` do compose de produção:

```yaml
CACHE_REDIS_URL: redis://redis:6379/2
PROXY_SEGREDO: ${PROXY_SEGREDO:?}
```

### 2. `settings.py`

```python
_cache_redis = os.environ.get("CACHE_REDIS_URL", "")
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": _cache_redis}
        if _cache_redis
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
}

PROXY_SEGREDO = os.environ.get("PROXY_SEGREDO", "")

REST_FRAMEWORK = {
    # ... o que já existe ...
    "NUM_PROXIES": 1,
}
```

Inclua a middleware do passo 3 como **primeira** da lista `MIDDLEWARE`.

### 3. Middleware que confia no IP só com o segredo

```python
import hmac

from django.conf import settings


class IpDoProxyMiddleware:
    """Troca o X-Forwarded-For pelo IP que o Next mandou, SE vier com o
    segredo certo. Sem o segredo, o cabecalho e' ignorado e vale o que o
    Traefik escreveu no fim da lista."""

    IP = "HTTP_X_CLIENTE_IP"
    SEGREDO = "HTTP_X_PROXY_SEGREDO"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = request.META.pop(self.IP, "")
        recebido = request.META.pop(self.SEGREDO, "")
        segredo = settings.PROXY_SEGREDO
        if segredo and ip and hmac.compare_digest(recebido.encode(), segredo.encode()):
            request.META["HTTP_X_FORWARDED_FOR"] = ip
        return self.get_response(request)
```

### 4. No `proxy.ts` do front

O `proxy.ts` do Next roda antes do rewrite. Nos pedidos a `/backend/*`,
apague os dois cabeçalhos que vierem de fora e escreva os seus:

```ts
const headers = new Headers(req.headers);
headers.delete('x-cliente-ip');
headers.delete('x-proxy-segredo');
const segredo = process.env.PROXY_SEGREDO; // sem NEXT_PUBLIC_
if (segredo && req.nextUrl.pathname.startsWith('/backend/')) {
  const ip = req.headers.get('x-forwarded-for')?.split(',').at(-1)?.trim();
  if (ip) {
    headers.set('x-cliente-ip', ip);
    headers.set('x-proxy-segredo', segredo);
  }
}
return NextResponse.next({ request: { headers } });
```

Se o front também chama o Django no servidor (SSR, rotas de API do Next),
esse fetch precisa mandar os mesmos dois cabeçalhos: é a armadilha 3.

`PROXY_SEGREDO` precisa ser **igual** no front e no back. Gere com
`openssl rand -hex 32`.

### 5. Limite geral por IP, com ou sem login (opcional)

`UserRateThrottle` limita por **usuário**, então quem está logado não tem
teto por IP. Para ter o mesmo do Marcaí, copie `LimitePorIP` de
`backend/app/api/v1/limite.py` e ponha-o em `DEFAULT_THROTTLE_CLASSES` no
lugar das duas classes, com uma taxa `geral`. Webhooks e rotas internas
ficam de fora com `throttle_classes = []`.

### 6. Testes

Uma fixture `autouse` que roda `cache.clear()` antes e depois de cada teste.
Sem ela, as tentativas de um teste contam no seguinte. O FechaCaixa já
tropeçou nisso (`test_cancelamento.py`).

### 7. Conferir em produção

Depois do deploy, confira que o limite está valendo e que visitantes
diferentes não dividem um contador. Com `curl` de fora, 11 POSTs no login
seguidos: o 11º tem de ser 429. Em seguida, de **outra rede** (o 4G do
celular, por exemplo), o login ainda tem de responder normalmente.
