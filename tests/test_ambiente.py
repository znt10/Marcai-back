from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _ler(nome):
    return (RAIZ / nome).read_text(encoding="utf-8")


def test_a_chave_da_evolution_exigida_pelo_servico_evolution():
    """Metade do teste "a chave da Evolution alimenta os dois serviços do compose".

    A propriedade original era bilateral — uma variável, dois consumidores,
    cada um num compose. Com dois repositórios ela não tem casa única; a
    metade do `app` (que manda EVOLUTION_API_KEY) ficou em
    front/tests/ambiente.test.ts, afirmando pelo nome da variável. Esta é a
    outra metade, a do lado que agora mora aqui: o `evolution` EXIGE a
    mesma chave como AUTHENTICATION_API_KEY. Se um deixar de sair da mesma
    variável, o sintoma é 401 silencioso em todo envio.
    """
    compose = _ler("docker-compose.yml")
    assert "AUTHENTICATION_API_KEY: ${EVOLUTION_API_KEY}" in compose


def test_o_worker_fala_com_a_evolution_desde_a_fatia_7():
    """Antes da fatia 7, so' o `agendador` (contêiner de `curl`) conferia
    `connectionState` — comportamento hoje testado de verdade em
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
    comportamento de verdade em `test_zelador.py`, contra um banco real —
    nao mais grep num script de shell que nao existe mais
    (`docker/zelador.sh`, apagado na fatia 7: a logica virou
    `app/services/zelador.py`, tarefa de beat).

    O que resta aqui e' so' a config do `evolution` que nao mudou: os dois
    flags que fazem o rastreio de status existir andam juntos, e conversa de
    cliente continua fora.
    """
    compose = _ler("docker-compose.yml")
    # Os dois flags andam juntos — ligar só um deixa a tabela de status vazia.
    assert 'DATABASE_SAVE_DATA_NEW_MESSAGE: "true"' in compose
    assert 'DATABASE_SAVE_MESSAGE_UPDATE: "true"' in compose
    # Conversa de cliente continua fora: o produto nunca recebe mensagem.
    assert 'DATABASE_SAVE_DATA_CONTACTS: "false"' in compose
    assert 'DATABASE_SAVE_DATA_HISTORIC: "false"' in compose


def test_a_sessao_da_evolution_mora_num_volume_nomeado():
    """Sem volume, todo `docker compose down` obriga a escanear o QR de novo —
    em produção, é o telefone da barbearia caindo a cada deploy.
    """
    compose = _ler("docker-compose.yml")
    assert "evolution_instances:/evolution/instances" in compose
