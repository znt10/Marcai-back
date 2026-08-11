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


def test_o_agendador_confere_o_whatsapp_no_mesmo_tique_do_lembrete():
    """O vínculo do WhatsApp cai sozinho (`Instance - LOGOUT`, sem ninguém
    pedir) e depois disso a Evolution responde 201 com `status: PENDING`
    para TUDO, sem entregar nada. Aconteceu, e ficou quase duas horas assim:
    o sintoma é cliente deixando de receber confirmação, que ninguém
    descobre olhando tela. O agendador não conserta — reconectar exige o QR,
    que exige uma pessoa — mas grita, e era isso que faltava.
    """
    compose = _ler("docker-compose.yml")
    assert "connectionState" in compose
    assert "WHATSAPP FORA DO AR" in compose
    # A cadência do aviso é a mesma do lembrete de propósito: um processo, um
    # laço, um lugar para olhar.
    assert "EVOLUTION_API_KEY: ${EVOLUTION_API_KEY}" in compose


def test_o_zelador_alarma_envio_recusado_e_poda_o_historico():
    compose = _ler("docker-compose.yml")
    zelador = _ler("docker/zelador.sh")

    # O WhatsApp rejeita de forma ASSÍNCRONA: quando a recusa chega, a
    # Evolution já devolveu 201 ao app. `status = 'ERROR'` é o único registro
    # disso, e sem alguém lendo esse registro a mensagem que não chega é
    # invisível.
    assert "status = 'ERROR'" in zelador
    assert "RECUSADO" in zelador

    # A poda existe porque o rastreio de status EXIGE guardar o texto que nós
    # mandamos — medido: sem a linha da mensagem, a MessageUpdate fica vazia.
    # Sem poda, o histórico cresceria para sempre.
    # As aspas viajam escapadas dentro da string de shell: \"Message\".
    assert 'DELETE FROM \\"Message\\"' in zelador
    assert "DIAS_DE_HISTORICO=" in zelador
    # MessageUpdate primeiro: ela referencia Message.
    assert zelador.index('DELETE FROM \\"MessageUpdate\\"') < zelador.index(
        'DELETE FROM \\"Message\\"'
    )

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
