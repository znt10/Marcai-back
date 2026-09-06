import re
from urllib.parse import urlsplit

# Espelha o SUBDOMINIOS_RESERVADOS de front/src/lib/config.ts. Divergir daqui
# significa um subdominio que um lado trata como barbearia e o outro nao.
SUBDOMINIOS_RESERVADOS = frozenset(
    {"www", "api", "app", "admin", "painel", "static", "assets", "cdn", "mail"}
)

# Espelha o SLUG_REGEX. Note que a forma exige no minimo 3 caracteres: uma
# letra, de 1 a 30 do miolo, e uma letra final.
#
# `fullmatch` sem `$`, e nao `match` com `$`: em Python o `$` tambem casa antes
# de um \n final, entao "brutus\n" passaria por um regex ancorado com `$`.
SLUG_REGEX = re.compile(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]")

# 60_000 ms do lado Next. Aqui em segundos, porque e o que o time.monotonic()
# devolve.
TTL_CACHE_TENANT_S = 60.0

# ---- Sessao do barbeiro (front/src/lib/config.ts, cliente 9.5, painel 3) ----
#
# Os tres espelham SESSAO_BARBEIRO_HORAS, BARBEIRO_TRAVA_TENTATIVAS e
# BARBEIRO_TRAVA_MIN. Divergir aqui nao quebra nada de imediato, e esse e o
# problema: com 12h de um lado e 2h do outro, o barbeiro seria deslogado no
# meio do turno dependendo de QUAL lado emitiu o cookie naquele dia.
SESSAO_BARBEIRO_HORAS = 12
SESSAO_BARBEIRO_COOKIE = "sessao"
BARBEIRO_TRAVA_TENTATIVAS = 5
BARBEIRO_TRAVA_MIN = 15

# ---- A grade de horarios (front/src/lib/config.ts) ----
#
# GRANULARIDADE e o passo da grade e e INDEPENDENTE da duracao do servico: um
# corte de 40 min comeca de 30 em 30 minutos, nao de 40 em 40.
GRANULARIDADE_MIN = 30
# Quanto tempo tem que faltar para um horario ainda poder ser oferecido. Zero
# hoje — o cliente pode marcar para daqui a cinco minutos.
ANTECEDENCIA_MINIMA_MIN = 0
# Quantos dias a home mostra por padrao, e o teto que uma query pode pedir.
DIAS_NA_HOME = 2
JANELA_MAXIMA_DIAS = 60

# Espelha SENHA_MINIMA. E o unico numero desta lista que o usuario LE (a rota
# do convite o cita na mensagem de erro), entao divergir daqui vira uma tela
# que promete 8 e um back que exige 10.
SENHA_MINIMA = 8

# ---- Servicos (front/src/lib/config.ts) ----
#
# Os limites de duracao que o catalogo do painel confere. Duplicados aqui
# porque a mensagem de recusa precisa ser legivel na tela — a mesma razao que
# o CHECK do banco existe e nao basta sozinho.
DURACAO_MINIMA_MIN = 10
DURACAO_MAXIMA_MIN = 60

# ---- Convite (front/src/lib/config.ts) ----
#
# Quanto tempo o link do convite vale. Citado na propria mensagem que o
# WhatsApp manda, entao divergir daqui e uma mensagem que promete um numero e
# um back que aplica outro.
CONVITE_VALIDADE_HORAS = 48

# ---- Lembrete (front/src/lib/config.ts) ----
#
# So a metade que `lembrete_ao_criar` usa: dentro de quantos minutos antes do
# horario um agendamento nasce JA avisado, para o cron do lembrete nunca o
# ver — sem isso, todo encaixe de balcao (o painel marca a 30 min de
# antecedencia por padrao) mandaria confirmacao e "Lembrete:" em minutos.
LEMBRETE_ANTECEDENCIA_MIN = 60

# ---- Cancelamento pelo cliente (front/src/lib/config.ts) ----
#
# So o fluxo PUBLICO confere isto — o painel cancela sem prazo de proposito
# (o barbeiro que quebrou o braco precisa desmarcar a tarde inteira agora).
PRAZO_CANCELAMENTO_MIN = 60

# ---- Verificacao de numero no WhatsApp (front/src/lib/config.ts) ----
#
# So o fluxo PUBLICO chama o oraculo — o painel nao, porque o barbeiro esta
# com o cliente na frente e o balcao e' um IP so, que o limite morderia.
CHECK_NUMERO_TIMEOUT_MS = 3_000
CHECK_NUMERO_TTL_MS = 86_400_000        # 24h
CHECK_NUMERO_LIMITE_POR_IP_HORA = 10

# ---- Sessao do admin da plataforma (front/src/lib/config.ts, admin §4) ----
#
# Curta de proposito: uso do admin e' em rajadas de minutos pra cadastrar uma
# barbearia, nao um turno inteiro como o barbeiro (12h).
ADMIN_SESSAO_HORAS = 2
ADMIN_SESSAO_COOKIE = "sessao_admin"

# ---- Trava do login do admin — POR IP, e' o OPOSTO da do barbeiro ----
#
# So existe UMA conta de admin: travar por conta deixaria qualquer um
# trancar o dono do site fora do proprio painel com cinco requisicoes. Antes
# do limite a espera so CRESCE (exponencial: 1s, 2s, 4s, 8s, 16s, 32s, teto
# 60s); passou do limite, o IP fica de castigo por 10 minutos inteiros.
ADMIN_TRAVA_BASE_MS = 1_000
ADMIN_TRAVA_TETO_MS = 60_000
ADMIN_TRAVA_TENTATIVAS = 5
ADMIN_TRAVA_BLOQUEIO_MS = 10 * 60_000

# ---- Zelador do historico da Evolution (docker/zelador.sh, fatia 7) ----
#
# O rastreio de status EXIGE guardar o texto que a Evolution mandou — sem a
# linha da mensagem, o status nao tem onde pousar (medido em 10/08). Como o
# historico nao pode crescer para sempre, poda-se o que passou deste prazo.
ZELADOR_DIAS_DE_HISTORICO = 7


# ---- Barbearia padrao: so' para testar pelo celular, so' em dev ----
#
# O endereco E a barbearia neste produto: `brutus.localhost` quer dizer "a
# barbearia brutus", e o subdominio e' o UNICO canal que carrega isso (nao ha
# `?barbearia=`, nem cabecalho — este middleware le do Host real de proposito).
#
# Isso cobra um preco em dev: `localhost` no celular e' o proprio celular, e um
# IP nu (`10.0.0.7`) nao tem onde por subdominio. Sem uma saida, testar no
# aparelho exige DNS curinga (nip.io) e, com ele, internet.
#
# A saida e' esta: com TENANT_PADRAO setado, um host SEM subdominio cai numa
# barbearia escolhida. Ai `http://10.0.0.7:3000` funciona no celular como
# qualquer app de um tenant so'.
#
# O gate e' `debug`, e nao um "se estiver em producao": variavel que ninguem
# leu nao pode ligar isto. Em producao DJANGO_DEBUG nao e' "1", entao a funcao
# devolve "" por mais que a variavel exista no ambiente — e' o que impede um
# `TENANT_PADRAO` esquecido num .env de servir a MESMA barbearia para todo
# host que nao casar com nenhuma.
def tenant_padrao(bruto: str, debug: bool) -> str:
    """O slug da barbearia padrao — ou "" quando o modo nao vale.

    Funcao pura para que a trava seja TESTAVEL: a alternativa era um `if` solto
    dentro do settings.py, que so' se verifica recarregando modulo.
    """
    if not debug:
        return ""
    return bruto.strip().lower()


def sem_subdominio(host: str, dominio_base: str) -> bool:
    """True quando o host nao carrega subdominio nenhum sob o dominio base.

    E' a UNICA porta por onde `tenant_padrao` entra, e o recorte importa: sao
    os dois casos em que nao ha subdominio para ler — o dominio nu
    (`localhost`) e um host de fora dele (`10.0.0.7`, o celular na rede).

    Fica de fora, de proposito, todo host que TEM subdominio e mesmo assim nao
    vira barbearia: `www.localhost` (reservado), `a.b.localhost` (subdominio de
    subdominio), `naoexiste.localhost` (slug sem dono). Esses continuam 404 ate'
    em dev — se caissem no padrao, um erro de digitacao no subdominio abriria
    silenciosamente a barbearia errada, que e' exatamente o acidente que o
    multi-tenant existe para tornar impossivel.

    Espelha `semSubdominio` do front/src/lib/config.ts.
    """
    sem_porta = host.split(":")[0].lower()
    return sem_porta == dominio_base or not sem_porta.endswith(f".{dominio_base}")


def regex_de_origem(dominio_base: str) -> str:
    """Regex de origem para o django-cors-headers.

    A biblioteca so aceita lista estatica ou lista de regex, e aqui a origem
    varia por barbearia — entao e regex. O `slug.py` nao pode ser chamado de
    dentro dela, e por isso a regra e reconstruida aqui.

    O que NAO se pode fazer e reescrever a lista de reservados a mao: ela sai
    de SUBDOMINIOS_RESERVADOS, para que um nome novo la feche a porta aqui
    sozinho. Duas listas separadas param de acompanhar uma a outra em silencio.

    `admin` sai da exclusao: ele e reservado como SLUG (nao e barbearia), mas e
    uma origem legitima — o painel da plataforma chama a API a partir dele.
    """
    proibidos = "|".join(sorted(SUBDOMINIOS_RESERVADOS - {"admin"}))
    base = re.escape(dominio_base)
    # (?!…) recusa os reservados; [a-z0-9-]+ sem ponto recusa subdominio de
    # subdominio; a ancora de fim recusa sufixo forjado (…localhost.malicioso.com).
    #
    # `\Z`, e nao `$`: em Python o `$` tambem casa antes de um \n final (mesma
    # pegadinha do comentario do SLUG_REGEX acima), e quem chama este regex e
    # o django-cors-headers com `re.match` — nunca `re.fullmatch`. O truque do
    # SLUG_REGEX (fullmatch sem ancora) nao serve aqui porque quem decide o
    # metodo de match e a biblioteca, nao este modulo; a unica defesa
    # disponivel e trocar a ancora por uma que nao cede ao \n.
    return rf"^https?://(?!(?:{proibidos})\.)[a-z0-9-]+\.{base}(:\d+)?\Z"


def origem_e_permitida(
    origem: str, host: str, dominio_base: str, padrao: str = ""
) -> bool:
    """Decide se uma Origin pode ler a resposta desta requisicao — a checagem
    completa que o django-cors-headers usa via `check_request_enabled`
    (backend/tenant/cors.py conecta o receiver; leia o comentario de la antes
    de mexer aqui, ele explica por que o regex NAO fica mais em
    CORS_ALLOWED_ORIGIN_REGEXES).

    Dois filtros, os dois obrigatorios:

    1. FORMA (`regex_de_origem`): a origem precisa ter cara de subdominio nao
       reservado de `dominio_base` — ou `admin.<dominio_base>`, a excecao que
       a propria funcao acima documenta. Fecha a porta pra dominio alheio,
       sufixo forjado e subdominio de subdominio.

    2. PAR: o hostname da origem tem que ser IGUAL ao hostname do Host real
       da requisicao. Comparar os dois inteiros (com porta) falha para todo
       pedido legitimo — a origem chega em `:3000` (Next) e o Host em `:8000`
       (Django) — por isso os dois lados sao truncados na porta antes de
       comparar. Isto e o que a FORMA sozinha nao sabe fazer: sem o par,
       `dontony.localhost:3000` (forma valida) lia `brutus.localhost:8000`
       (achado da revisao final). `admin.<dominio_base>` nao precisa de
       excecao extra aqui: seu hostname so bate com o hostname do proprio
       host do admin, entao a mesma regra de igualdade ja cobre o caso.
    """
    origem_host = (urlsplit(origem).hostname or "").lower()
    host_sem_porta = host.split(":")[0].lower()

    # Modo barbearia-padrao (dev): o host e' um IP nu, entao o filtro de FORMA
    # recusaria tudo — ele so' sabe reconhecer subdominio de `dominio_base`. O
    # filtro de PAR continua valendo e e' o que segue protegendo: a origem tem
    # que ser o MESMO host que atendeu o pedido. Sem ele, qualquer pagina da
    # rede leria a API. Vale so' sob `debug` (ver `tenant_padrao`).
    if padrao and sem_subdominio(host, dominio_base):
        return origem_host == host_sem_porta

    if not re.match(regex_de_origem(dominio_base), origem):
        return False
    return origem_host == host_sem_porta


# Foto do barbeiro. Ela mora na coluna `foto_url` como data URL, sem storage
# de arquivo — ver app/services/foto.py.
#
# O teto e' apertado de PROPOSITO: a vitrine e' renderizada no servidor, entao
# cada foto entra embutida no HTML da primeira tela que o cliente abre na
# calcada.
#
# 192 e nao 128: a vitrine desenha o circulo com 72px, e num aparelho retina
# (2x) isso pede 144 pixels de verdade — 128 seria ampliado, e foto de rosto
# ampliada e' o tipo de borrao que se ve. 192 cobre ate' 96px de tela com
# folga. Em WebP da' 8-14 KB, ainda dentro do teto, e a queda de qualidade
# por degraus de `lib/foto.ts` cuida da foto que insistir em passar.
FOTO_LADO_PX = 192
FOTO_TAMANHO_MAXIMO_BYTES = 20 * 1024
# SVG fica de fora: e' imagem que carrega script.
FOTO_MIMES = ("image/webp", "image/jpeg", "image/png")

# ---- Resumo de cortes por barbeiro (painel do dono) ----
#
# Teto da janela que `/api/painel/resumo` aceita. Nao existe para proteger o
# banco — sao tres consultas (ver `resumo.py`), e elas custam praticamente o
# mesmo numa janela de um ano ou de um seculo. Existe para que um
# `?de=1900-01-01` (digitado errado, ou herdado de um link velho) apareca
# como periodo recusado em vez de devolver um numero que ninguem pediu e
# parece certo.
#
# 366 e nao 365: um intervalo de "um ano inteiro" que cruze ano bissexto tem
# 366 dias, e recusar exatamente esse caso seria a regra falhando na unica
# vez em que ela nao deveria.
RESUMO_JANELA_MAXIMA_DIAS = 366
