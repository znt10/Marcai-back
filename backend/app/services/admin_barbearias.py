import uuid

from django.db import connections, transaction
from django.db.models import F

from tenant.config import SLUG_REGEX, SUBDOMINIOS_RESERVADOS
from tenant.identidade import normalizar_login
from tenant.models import (
    Agendamento, Barbearia, Barbeiro, PapelUsuario, Usuario,
)
from tenant.rls import com_barbearia_admin
from tenant.telefone import normalizar

from .convite import gerar_convite


def listar_com_contagem() -> list[dict]:
    """Porte fiel do `GET` de route.ts: tenant a tenant, e nao numa agregacao
    so, porque `brutus_admin` esta sujeito ao MESMO RLS que `brutus_app` em
    toda tabela de tenant — um `count()` fora de `com_barbearia_admin`
    devolveria zero, nao um erro, o que faria o bug passar batido num teste
    apressado."""
    barbearias = Barbearia.objects.using("admin").order_by("criado_em")
    resultado = []
    for b in barbearias:
        with com_barbearia_admin(b.id):
            barbeiros = Barbeiro.objects.using("admin").count()
            agendamentos = Agendamento.objects.using("admin").filter(
                status="CONFIRMADO"
            ).count()
        resultado.append(
            {
                "id": b.id,
                "slug": b.slug,
                "nome": b.nome,
                "ativo": b.ativo,
                "barbeiros": barbeiros,
                "agendamentos": agendamentos,
            }
        )
    return resultado


def criar(dados: dict) -> dict:
    """`dados` chega cru do corpo JSON (chaves camelCase, tudo string ou
    ausente) — a mesma forma que o `Partial<Corpo>` do route.ts recebe, e
    por isso a validacao mora aqui e nao num serializer: cada recusa tem
    mensagem e status PROPRIOS (422 de forma, 422 de campo faltando, 409 de
    slug repetido), e o corpo malformado do fetch (`.catch(() => ({}))`)
    tem que cair no mesmo caminho de "faltou preencher".
    """
    slug = str(dados.get("slug") or "").strip().lower()
    if not SLUG_REGEX.fullmatch(slug) or slug in SUBDOMINIOS_RESERVADOS:
        return {"tipo": "slug_invalido"}

    contato = normalizar(dados.get("whatsappContato"))
    nome = dados.get("nome")
    dono_nome = dados.get("donoNome")
    endereco = dados.get("endereco")
    # `donoEmail` e o campo novo da fatia 3, e ele e' o motivo da fatia existir:
    # ate aqui o login do dono ERA o `whatsappContato` da barbearia (o INSERT
    # abaixo gravava `whatsapp=contato`), entao trocar o telefone publico
    # derrubava o acesso dele. Sao duas coisas diferentes e agora tem duas
    # colunas diferentes.
    dono_login = normalizar_login(dados.get("donoEmail"))
    if not contato or not nome or not dono_nome or not endereco or not dono_login:
        return {"tipo": "faltou_campo"}

    if Barbearia.objects.using("admin").filter(slug=slug).exists():
        return {"tipo": "slug_duplicado", "slug": slug}

    convite = gerar_convite()

    # UMA transacao para as TRES linhas: se a criacao do dono falhar, a
    # barbearia NAO pode sobrar — barbearia sem dono e' orfa, ninguem entra
    # nela para cadastrar ninguem. Sao tres desde a fatia 3 (Barbearia,
    # Usuario e o perfil Barbeiro) e a regra de ouro nao mudou: ou as tres, ou
    # nenhuma.
    #
    # Por isso nao usa `com_barbearia_admin()` aqui: aquele helper abre a
    # PROPRIA transacao, e o `set_config` precisa acontecer DENTRO desta,
    # depois que a barbearia passa a existir e antes dos INSERTs que o RLS
    # vai conferir no WITH CHECK.
    with transaction.atomic(using="admin", durable=True):
        barbearia = Barbearia.objects.using("admin").create(
            id=str(uuid.uuid4()),
            slug=slug,
            nome=nome,
            endereco=endereco,
            horario_resumo=None,  # sem horario: o dono preenche pela tela dele.
            whatsapp_contato=contato,
        )
        with connections["admin"].cursor() as cur:
            cur.execute(
                "SELECT set_config('app.barbearia_id', %s, true)", [str(barbearia.id)]
            )
        # A IDENTIDADE do dono. `senha_hash=None` ate ele aceitar o convite —
        # e' esse nulo que o login recusa sem revelar que a conta existe.
        dono = Usuario.objects.using("admin").create(
            id=uuid.uuid4(),
            login=dono_login,
            papel=PapelUsuario.DONO,
            barbearia_id=barbearia.id,
            senha_hash=None,
            convite_token_hash=convite["hash"],
            convite_expira_em=convite["expira_em"],
        )
        # O PERFIL. O dono atende: ele nasce na agenda como barbeiro, senao a
        # barbearia abriria sem ninguem para marcar horario.
        #
        # `whatsapp=contato` continua aqui, e agora e' so' o telefone dele —
        # nao e' mais o login. Trocar o `whatsapp_contato` da barbearia deixou
        # de mexer em como o dono entra no sistema, que e' o teste que prova
        # esta fatia.
        Barbeiro.objects.using("admin").create(
            id=uuid.uuid4(),
            barbearia_id=barbearia.id,
            usuario=dono,
            nome=dono_nome,
            whatsapp=contato,
        )

    return {
        "tipo": "ok",
        "id": barbearia.id,
        "slug": barbearia.slug,
        "nome": barbearia.nome,
        "contato": contato,
        "dono_nome": dono_nome,
        "dono_login": dono_login,
        "convite": convite,
    }


def atualizar_ativo(barbearia_id: str, ativo: bool) -> bool:
    """`update()`, nao `get()+save()`: um id inexistente so' precisa virar
    `count == 0`, nao uma excecao pra' distinguir de qualquer outra falha —
    mesmo raciocinio do `updateMany` do route.ts."""
    alteradas = Barbearia.objects.using("admin").filter(id=barbearia_id).update(ativo=ativo)
    return alteradas > 0


def reemitir_convite(barbearia_id: str) -> dict:
    barbearia = Barbearia.objects.using("admin").filter(id=barbearia_id).first()
    if barbearia is None:
        return {"tipo": "barbearia_nao_encontrada"}

    convite = gerar_convite()

    with com_barbearia_admin(barbearia.id):
        # O papel mora na IDENTIDADE desde a fatia 2, entao a busca entra por
        # `Usuario` e alcanca o perfil pelo `select_related` — antes era o
        # contrario, com `papel` sendo coluna de `Barbeiro`.
        #
        # `perfil__ativo` e nao `Usuario.ativo`: o dono cuja identidade foi
        # desativada tambem nao serve, e os dois andam juntos (equipe.py mexe
        # nos dois de uma vez). Conferir o perfil cobre o caso que importa
        # para reemitir convite — alguem que ainda atende naquela barbearia.
        atual = (
            Usuario.objects.using("admin")
            .filter(papel=PapelUsuario.DONO, ativo=True, perfil__ativo=True)
            .select_related("perfil")
            .order_by("criado_em")
            .first()
        )
        if atual is None:
            return {"tipo": "sem_dono_ativo"}

        Usuario.objects.using("admin").filter(id=atual.id).update(
            senha_hash=None,
            convite_token_hash=convite["hash"],
            convite_expira_em=convite["expira_em"],
            # Derruba na hora qualquer sessao ativa daquele dono — o reset
            # existe justamente para o caso em que alguem tomou a conta, e
            # deixa-la valida por ate 12h depois do reset anularia o motivo
            # de reemitir.
            token_version=F("token_version") + 1,
        )

    return {
        "tipo": "ok",
        "slug": barbearia.slug,
        "nome": barbearia.nome,
        "dono_nome": atual.perfil.nome,
        "dono_whatsapp": atual.perfil.whatsapp,
        "convite": convite,
    }
