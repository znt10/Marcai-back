from tenant.identidade import normalizar_login
from tenant.models import Usuario
from tenant.rls import com_barbearia

from .senha import confere, gerar, hash_de_convite, hash_descartavel
from .trava_barbeiro import LIMPO, agora_utc, apos_falha, esta_travado


def autenticar(barbearia_id: str, login_bruto: str, senha: str) -> dict:
    """O login do painel. Devolve um dos tres desfechos; quem os traduz em
    HTTP e a view.

    Procura `Usuario` por `login`, e nao mais `Barbeiro` por whatsapp. E' a
    virada inteira da fatia 3: o dono entra pelo EMAIL dele, o barbeiro pelo
    numero, e nenhum dos dois depende mais de uma coluna que a barbearia usa
    para outra coisa. Antes, `whatsappContato` era ao mesmo tempo o telefone
    publico da barbearia e o login do dono — trocar um derrubava o outro.

    `normalizar_login` canoniza pela FORMA antes de procurar, e isso importa
    mais do que parece: sem ele, quem digita o email com maiuscula ou o numero
    com parentese nao acha a propria conta e erra a senha sem ter errado a
    senha — com cada tentativa dessas contando para a trava de 5.

    A regra que manda em tudo aqui NAO mudou: login inexistente, senha errada
    e conta ainda sem senha (convite nao aceito) sao O MESMO desfecho,
    `invalido`. Se fossem tres respostas diferentes, o formulario de login
    viraria uma lista da equipe — basta iterar valores e ler qual resposta
    muda. Por isso tambem o `confere` roda SEMPRE, inclusive quando nao ha
    conta nenhuma (ver `hash_descartavel` em senha.py): a resposta unica so
    vale alguma coisa se o TEMPO de resposta tambem for unico.

    Tudo dentro de UM `com_barbearia`: a leitura e o update de tentativa
    precisam do mesmo tenant e da mesma transacao. Dois blocos seriam duas
    transacoes, e entre elas cabe a corrida em que duas tentativas simultaneas
    leem `tentativas_login = 4` e as duas gravam 5 — a quinta falha nunca
    travaria a conta.
    """
    login = normalizar_login(login_bruto)
    agora = agora_utc()

    with com_barbearia(barbearia_id):
        # Sem `filter(barbearia_id=...)`: o RLS ja escopa. Escrever o filtro
        # aqui criaria um segundo lugar que decide tenant.
        #
        # O `login` e unico GLOBALMENTE, mas a busca continua escopada pelo
        # tenant de proposito — e' o que faz o login de uma barbearia nao valer
        # no subdominio de outra. Fora do escopo certo, o `first()` nao acha e
        # o desfecho e `invalido`, igual a um login que nao existe.
        # `select_related("perfil")` NAO e otimizacao: e correcao.
        #
        # Quem chama esta funcao le `usuario.perfil.nome` para montar a
        # resposta, e faz isso DEPOIS que o `with` fechou. Uma relacao lazy
        # dispararia a consulta ali fora, sem `app.barbearia_id` definido — o
        # RLS entao nao casa linha nenhuma e o acesso estoura com
        # "Usuario has no perfil", num login que esta perfeitamente certo.
        #
        # Trazer o perfil junto, aqui dentro, mantem toda leitura de tenant do
        # lado de dentro do wrapper, que e a regra deste repo.
        usuario = (
            Usuario.objects.select_related("perfil").filter(login=login).first()
            if login
            else None
        )

        if usuario is not None and esta_travado(usuario.bloqueado_ate, agora):
            return {"tipo": "travado"}

        if usuario is not None and usuario.senha_hash:
            ok = confere(usuario.senha_hash, senha)
        else:
            confere(hash_descartavel(), senha)
            ok = False

        if not ok:
            if usuario is not None:
                # `.update()` da queryset, e nao `.save()`: um `save()`
                # reescreve todas as colunas a partir de uma instancia lida
                # antes, e neste caminho isso significaria regravar `senha_hash`
                # e `papel` — perda silenciosa se algo os tiver mudado no meio.
                Usuario.objects.filter(id=usuario.id).update(
                    **apos_falha(usuario.tentativas_login, agora)
                )
            return {"tipo": "invalido"}

        # So escreve se houver o que limpar: o login que da certo e o caminho
        # comum, e um UPDATE por login seria escrita a toa em cada pedido.
        if usuario.tentativas_login != 0 or usuario.bloqueado_ate is not None:
            Usuario.objects.filter(id=usuario.id).update(**LIMPO)

        return {"tipo": "ok", "usuario": usuario}


def aceitar_convite(barbearia_id: str, token: str, senha: str) -> bool:
    """Troca o convite pela senha. False quando o token nao existe OU venceu —
    um desfecho so, pelo mesmo motivo do login: distinguir "nao existe" de
    "venceu" diria a quem chuta tokens que ele acertou um dia.

    A busca e PELO HASH, nunca pelo token. O banco guarda so o hash; o token em
    claro existiu uma vez, no link que foi pelo WhatsApp.

    Apagar `convite_token_hash` e `convite_expira_em` no mesmo update e o que
    torna o link de uso unico. Sem isso, quem tivesse o link poderia trocar a
    senha de novo depois — inclusive depois de a conta ja estar em uso.
    """
    with com_barbearia(barbearia_id):
        usuario = (
            Usuario.objects.filter(
                convite_token_hash=hash_de_convite(token),
                convite_expira_em__gt=agora_utc(),
            )
            .values("id")
            .first()
        )
        if usuario is None:
            return False

        Usuario.objects.filter(id=usuario["id"]).update(
            senha_hash=gerar(senha),
            convite_token_hash=None,
            convite_expira_em=None,
        )
        return True


def quem_e(barbearia_id: str, usuario_id: str) -> dict | None:
    """Os tres campos que a tela do painel mostra. Nada mais sai daqui: `eu` e
    uma rota de identidade, nao um dump do proprio cadastro.

    O `nome` vem do PERFIL e o `papel` da IDENTIDADE — a divisao que a fatia 2
    criou.

    `id` continua sendo o do PERFIL, e nao o do usuario, apesar de ser o
    usuario que o cookie carrega. E' contrato com o front: a tela usa esse id
    para pedir a propria agenda, e agenda referencia `Barbeiro`. Trocar por
    baixo o significado de um campo que ja esta em uso e' o tipo de mudanca que
    nao quebra teste nenhum aqui e quebra a tela la.
    """
    with com_barbearia(barbearia_id):
        # Montado a mao em vez de `values(id=F("perfil__id"))` porque o Django
        # recusa uma anotacao com o nome de um campo que o model ja tem
        # ("conflicts with a field on the model") — e `Usuario` tem `id`.
        achado = (
            Usuario.objects.filter(id=usuario_id)
            .values("papel", "perfil__id", "perfil__nome")
            .first()
        )

    if achado is None:
        return None
    return {
        "id": achado["perfil__id"],
        "nome": achado["perfil__nome"],
        "papel": achado["papel"],
    }
