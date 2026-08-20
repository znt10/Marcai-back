from tenant.identidade import normalizar_login
from tenant.models import PapelUsuario, Usuario

from .senha import confere, hash_descartavel


def autenticar_admin(login_bruto: str, senha: str) -> Usuario | None:
    """O login do admin da plataforma, agora contra uma LINHA e nao contra
    variavel de ambiente.

    O que morreu aqui foi o `admin_senha.py` inteiro: ele comparava o usuario
    com `ADMIN_USUARIO` e a senha com `ADMIN_SENHA_HASH_B64` — um hash argon2
    guardado em BASE64 porque o hash em claro tem `$` (`$argon2id$v=19$m=...`)
    e tanto o dotenv quanto o Compose expandiam aquilo como inicio de variavel,
    entregando um valor truncado ao processo sem avisar nada. Com a conta no
    banco, a gambiarra deixa de ter motivo.

    Sem `com_barbearia`, e isso NAO e um esquecimento do wrapper: o admin da
    plataforma nao pertence a barbearia nenhuma, e nao ha tenant a fixar. Quem
    escopa e a politica `admin_da_plataforma` (migration 0006), que sobre a
    conexao `admin` alcanca exatamente as linhas de `barbearia_id IS NULL`.
    Fora de `com_barbearia_admin()`, `tenant_isolation` nao casa (a variavel de
    sessao esta vazia), entao o que sobra e' so' o admin. O filtro por `papel` e
    `barbearia__isnull` e cinto e suspensorio sobre isso — barato, e torna a
    intencao legivel sem depender de saber o RLS de cor.

    `confere` roda SEMPRE, mesmo com login errado, pelo mesmo motivo do login
    do barbeiro: a resposta unica so vale alguma coisa se o TEMPO tambem for
    unico. Aqui isso vale ainda mais, porque so existe UMA conta — medir a
    diferenca revelaria o nome dela.
    """
    login = normalizar_login(login_bruto)

    usuario = (
        Usuario.objects.using("admin")
        .filter(login=login, papel=PapelUsuario.ADMIN, barbearia__isnull=True)
        .first()
        if login
        else None
    )

    if usuario is not None and usuario.senha_hash and usuario.ativo:
        if confere(usuario.senha_hash, senha):
            return usuario
        return None

    confere(hash_descartavel(), senha)
    return None
