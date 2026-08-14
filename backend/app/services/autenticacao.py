from tenant.models import Barbeiro
from tenant.rls import com_barbearia
from tenant.telefone import normalizar

from .senha import confere, gerar, hash_de_convite, hash_descartavel
from .trava_barbeiro import LIMPO, agora_utc, apos_falha, esta_travado


def autenticar(barbearia_id: str, whatsapp_bruto: str, senha: str) -> dict:
    """O login do barbeiro. Devolve um dos tres desfechos; quem os traduz em
    HTTP e a view.

    A regra que manda em tudo aqui: numero inexistente, senha errada e barbeiro
    ainda sem senha (convite nao aceito) sao O MESMO desfecho, `invalido`. Se
    fossem tres respostas diferentes, o formulario de login viraria uma lista
    da equipe — basta iterar numeros e ler qual resposta muda.

    Por isso tambem o `confere` roda SEMPRE, inclusive quando nao ha barbeiro
    nenhum: ver `hash_descartavel` em senha.py. A resposta unica so vale
    alguma coisa se o TEMPO de resposta tambem for unico.

    Tudo dentro de UM `com_barbearia`: a leitura e o update de tentativa
    precisam do mesmo tenant e da mesma transacao. Dois blocos seriam duas
    transacoes, e entre elas cabe a corrida em que duas tentativas simultaneas
    leem `tentativasLogin = 4` e as duas gravam 5 — a quinta falha nunca
    travaria a conta.
    """
    whatsapp = normalizar(whatsapp_bruto)
    agora = agora_utc()

    with com_barbearia(barbearia_id):
        # Sem `filter(barbearia_id=...)`: o RLS ja escopa. Escrever o filtro
        # aqui criaria um segundo lugar que decide tenant (ver o comentario do
        # services/barbeiros.py). O `@@unique([barbeariaId, whatsapp])` garante
        # que dentro do tenant o `first()` e o unico.
        barbeiro = (
            Barbeiro.objects.filter(whatsapp=whatsapp).first() if whatsapp else None
        )

        if barbeiro is not None and esta_travado(barbeiro.bloqueado_ate, agora):
            return {"tipo": "travado"}

        if barbeiro is not None and barbeiro.senha_hash:
            ok = confere(barbeiro.senha_hash, senha)
        else:
            confere(hash_descartavel(), senha)
            ok = False

        if not ok:
            if barbeiro is not None:
                # `.update()` da queryset, e nao `.save()`: um `save()` de model
                # managed=False reescreve TODAS as colunas declaradas, e neste
                # caminho isso significaria regravar `senhaHash` e `papel` a
                # partir de uma instancia lida antes — perda silenciosa se algo
                # os tiver mudado no meio.
                Barbeiro.objects.filter(id=barbeiro.id).update(
                    **apos_falha(barbeiro.tentativas_login, agora)
                )
            return {"tipo": "invalido"}

        # So escreve se houver o que limpar: o login que da certo e o caminho
        # comum, e um UPDATE por login seria escrita a toa em cada pedido.
        if barbeiro.tentativas_login != 0 or barbeiro.bloqueado_ate is not None:
            Barbeiro.objects.filter(id=barbeiro.id).update(**LIMPO)

        return {"tipo": "ok", "barbeiro": barbeiro}


def aceitar_convite(barbearia_id: str, token: str, senha: str) -> bool:
    """Troca o convite pela senha. False quando o token nao existe OU venceu —
    um desfecho so, pelo mesmo motivo do login: distinguir "nao existe" de
    "venceu" diria a quem chuta tokens que ele acertou um dia.

    A busca e PELO HASH, nunca pelo token. O banco guarda so o hash; o token em
    claro existiu uma vez, no link que foi pelo WhatsApp.

    Apagar `conviteTokenHash` e `conviteExpiraEm` no mesmo update e o que torna
    o link de uso unico. Sem isso, quem tivesse o link poderia trocar a senha
    do barbeiro de novo depois — inclusive depois de ele ja estar usando a
    conta.
    """
    with com_barbearia(barbearia_id):
        barbeiro = (
            Barbeiro.objects.filter(
                convite_token_hash=hash_de_convite(token),
                convite_expira_em__gt=agora_utc(),
            )
            .values("id")
            .first()
        )
        if barbeiro is None:
            return False

        Barbeiro.objects.filter(id=barbeiro["id"]).update(
            senha_hash=gerar(senha),
            convite_token_hash=None,
            convite_expira_em=None,
        )
        return True


def quem_e(barbearia_id: str, barbeiro_id: str) -> dict | None:
    """Os tres campos que a tela do painel mostra. Nada mais sai daqui: `eu` e
    uma rota de identidade, nao um dump do proprio cadastro.
    """
    with com_barbearia(barbearia_id):
        return (
            Barbeiro.objects.filter(id=barbeiro_id)
            .values("id", "nome", "papel")
            .first()
        )
