import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _ler(nome):
    return (RAIZ / nome).read_text(encoding="utf-8")


def test_a_chave_da_evolution_exigida_pelo_servico_evolution():
    """Metade do teste "a chave da Evolution alimenta os dois serviÃ§os do compose".

    A propriedade original era bilateral â€” uma variÃ¡vel, dois consumidores,
    cada um num compose. Com dois repositÃ³rios ela nÃ£o tem casa Ãºnica; a
    metade do `app` (que manda EVOLUTION_API_KEY) ficou em
    front/tests/ambiente.test.ts, afirmando pelo nome da variÃ¡vel. Esta Ã© a
    outra metade, a do lado que agora mora aqui: o `evolution` EXIGE a
    mesma chave como AUTHENTICATION_API_KEY. Se um deixar de sair da mesma
    variÃ¡vel, o sintoma Ã© 401 silencioso em todo envio.
    """
    compose = _ler("docker-compose.yml")
    assert "AUTHENTICATION_API_KEY: ${EVOLUTION_API_KEY}" in compose


def test_o_worker_fala_com_a_evolution_desde_a_fatia_7():
    """Antes da fatia 7, so' o `agendador` (contÃªiner de `curl`) conferia
    `connectionState` â€” comportamento hoje testado de verdade em
    `test_whatsapp.py::test_estado_da_instancia_*` e
    `test_celery.py::test_whatsapp_healthcheck_*`, nao mais por grep neste
    arquivo. O que resta verificar aqui e' so' a fiacao do compose: o
    `worker` (que executa a tarefa) precisa das MESMAS credenciais que o
    `api` ja tinha.
    """
    compose = _ler("docker-compose.yml")
    assert "EVOLUTION_API_URL: http://evolution:8080" in compose
    assert "EVOLUTION_API_KEY: ${EVOLUTION_API_KEY}" in compose


def test_evolution_guarda_so_o_texto_que_o_produto_manda():
    """As propriedades do ZELADOR em si (conta recusado, poda o que
    envelhece, MessageUpdate antes de Message) viraram testes de
    comportamento de verdade em `test_zelador.py`, contra um banco real â€”
    nao mais grep num script de shell que nao existe mais
    (`docker/zelador.sh`, apagado na fatia 7: a logica virou
    `app/services/zelador.py`, tarefa de beat).

    O que resta aqui e' so' a config do `evolution` que nao mudou: os dois
    flags que fazem o rastreio de status existir andam juntos, e conversa de
    cliente continua fora.
    """
    compose = _ler("docker-compose.yml")
    # Os dois flags andam juntos â€” ligar sÃ³ um deixa a tabela de status vazia.
    assert 'DATABASE_SAVE_DATA_NEW_MESSAGE: "true"' in compose
    assert 'DATABASE_SAVE_MESSAGE_UPDATE: "true"' in compose
    # Conversa de cliente continua fora: o produto nunca recebe mensagem.
    assert 'DATABASE_SAVE_DATA_CONTACTS: "false"' in compose
    assert 'DATABASE_SAVE_DATA_HISTORIC: "false"' in compose


def test_a_sessao_da_evolution_mora_num_volume_nomeado():
    """Sem volume, todo `docker compose down` obriga a escanear o QR de novo â€”
    em produÃ§Ã£o, Ã© o telefone da barbearia caindo a cada deploy.
    """
    compose = _ler("docker-compose.yml")
    assert "evolution_instances:/evolution/instances" in compose


# --------------------------------------------------- as variaveis que o codigo EXIGE
#
# A fatia 5 comecou com o login do admin devolvendo "Nao deu certo. Tenta de
# novo?" — a frase de senha errada. Nao era: a rota autenticava, chegava em
# `emitir()` e morria com 500 porque `ADMIN_JWT_SECRET` nao existia em lugar
# nenhum do back. Nem no `.env`, nem no `.env.example`, nem no compose. Faltava
# desde a fatia 3, quando o login do admin passou a ser Django.
#
# Nenhum teste podia ter pego isso, porque todos rodam DENTRO do contentor com
# o ambiente ja montado, e nenhum olhava para como ele e montado. Os tres
# abaixo olham.

PADRAO_SEM_DEFAULT = re.compile(r'os\.environ\.get\("([A-Z_]+)"\)')

def _exigidas():
    achadas = set()
    for arq in (RAIZ / "backend").rglob("*.py"):
        achadas |= set(PADRAO_SEM_DEFAULT.findall(arq.read_text(encoding="utf-8")))
    return achadas


def test_ha_o_que_conferir():
    """Guarda do proprio teste. Se o padrao parar de casar — alguem trocou por
    `os.getenv`, ou quebrou a linha — os dois testes abaixo passariam vazios e
    diriam que esta tudo bem.
    """
    assert "ADMIN_JWT_SECRET" in _exigidas()
    assert len(_exigidas()) >= 3


def test_toda_variavel_exigida_esta_documentada():
    """O `.env.example` e a unica instrucao de como subir isto. Uma variavel
    que o codigo exige e ele nao cita e um deploy que sobe e quebra na
    primeira vez que alguem usa a tela."""
    exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    faltando = sorted(v for v in _exigidas() if f"{v}=" not in exemplo)
    assert not faltando, f"exigidas pelo codigo e ausentes do .env.example: {faltando}"


def test_toda_variavel_exigida_chega_no_api():
    """Documentar nao basta: o `.env` e lido pelo HOST, e o Django roda dentro
    do contentor. Sem a linha no `environment:` do servico, o valor fica no
    host e o processo nunca o ve — que foi exatamente o caso.

    Confere so' o `api`: worker e beat nao servem rota de sessao.
    """
    compose = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    bloco = compose[compose.index("\n  api:"):compose.index("\n  evolution:")]
    faltando = sorted(v for v in _exigidas() if f"{v}:" not in bloco)
    assert not faltando, f"exigidas pelo codigo e ausentes do environment do api: {faltando}"
