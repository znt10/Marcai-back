import uuid

from tenant.identidade import normalizar_login

# Os campos que a fatia 3 MUDOU DE LUGAR: sairam de `Barbeiro` e passaram a
# morar em `Usuario`. Continuam aceitos com o mesmo nome porque o que eles
# significam nao mudou — o que mudou foi a tabela.
CAMPOS_DA_CONTA = {
    "login", "papel", "senha_hash", "token_version",
    "convite_token_hash", "convite_expira_em",
    "tentativas_login", "bloqueado_ate",
}


def criar_barbeiro(**campos):
    """Cria a identidade e o perfil de uma vez, e devolve o PERFIL.

    Existe porque `Barbeiro.usuario` virou obrigatorio: um perfil sem conta
    seria alguem que aparece na agenda e nao consegue entrar no sistema, e o
    banco passou a recusar isso. Sem uma fabrica, cada um dos 19 arquivos de
    teste que monta cenario teria de repetir as duas criacoes e inventar um
    `login` unico — e a primeira vez que alguem esquecesse, o erro viria como
    IntegrityError longe da causa.

    Aceita os campos das DUAS tabelas misturados, do jeito que os testes ja os
    escreviam antes da fatia 3 (`papel=`, `senha_hash=`, `token_version=`), e
    reparte para o lado certo. E' o que permite `criar_barbeiro(papel="DONO")`
    continuar querendo dizer a mesma coisa de sempre.

    `login` default: o whatsapp normalizado, que e' exatamente como o barbeiro
    entra em producao. Quem precisa de dois barbeiros com o MESMO whatsapp em
    barbearias diferentes (o `cenario` faz isso) tem de passar `login=`
    explicito — `Barbeiro.whatsapp` e unico por tenant, mas `Usuario.login` e
    unico no sistema inteiro.
    """
    from tenant.models import Barbeiro, PapelUsuario, Usuario

    da_conta = {c: campos.pop(c) for c in list(campos) if c in CAMPOS_DA_CONTA}
    da_conta.setdefault("papel", PapelUsuario.BARBEIRO)
    da_conta.setdefault(
        "login", normalizar_login(campos.get("whatsapp")) or str(uuid.uuid4()),
    )

    barbearia_id = campos.get("barbearia_id")
    if barbearia_id is None and campos.get("barbearia") is not None:
        barbearia_id = campos["barbearia"].id

    conta = Usuario.objects.using("owner").create(
        id=uuid.uuid4(),
        barbearia_id=barbearia_id,
        # Espelha o `ativo` do perfil. Os dois andam juntos em producao
        # (`equipe.desativar` mexe nos dois), e `sessao.da_requisicao` exige
        # ambos — um cenario com conta ativa e perfil desativado produziria um
        # 401 que o teste nao pediu.
        ativo=campos.get("ativo", True),
        # Espelhado pelo mesmo motivo do `ativo`: os dois nascem na mesma
        # transacao em producao. `reemitir_convite` escolhe "o dono ativo mais
        # antigo" pela data da IDENTIDADE, entao um cenario que envelhecesse so'
        # o perfil ordenaria diferente do sistema de verdade.
        **({"criado_em": campos["criado_em"]} if "criado_em" in campos else {}),
        **da_conta,
    )

    campos.setdefault("id", uuid.uuid4())
    return Barbeiro.objects.using("owner").create(usuario=conta, **campos)


SENHA_DO_ADMIN = "senha-do-admin-123"


def criar_admin(login="admin", senha=SENHA_DO_ADMIN):
    """O admin da plataforma, que desde a fatia 3 e uma LINHA.

    Antes ele era um par de variaveis de ambiente, e os testes o "criavam" com
    `monkeypatch.setenv`. O hash ia em BASE64 porque o argon2 em claro tem `$`,
    que o dotenv e o Compose expandiam como variavel — nada disso existe mais.

    `using("admin")`: o papel `brutus_admin` e o unico que alcanca a linha de
    `barbearia_id IS NULL` (politica `admin_da_plataforma`). Por `default` o
    INSERT morreria no WITH CHECK de `tenant_isolation`, comparando com uma
    variavel de sessao vazia. Quem usar esta fabrica precisa declarar o alias
    `admin` no marcador `django_db`.
    """
    from app.services.senha import gerar
    from tenant.models import PapelUsuario, Usuario

    return Usuario.objects.using("admin").create(
        id=uuid.uuid4(),
        login=normalizar_login(login),
        papel=PapelUsuario.ADMIN,
        barbearia=None,
        senha_hash=gerar(senha),
    )
