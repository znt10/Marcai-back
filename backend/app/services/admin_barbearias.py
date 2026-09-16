import uuid

from django.db import connections, transaction
from django.db.models import F

from tenant.config import SLUG_REGEX, SUBDOMINIOS_RESERVADOS
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    PlanoBarbearia,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia_admin
from tenant.telefone import normalizar

from .convite import gerar_convite
from .whatsapp_instancias import apagar_instancia, garantir_instancia, nome_da_instancia


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
                "plano": b.plano,
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

    plano = str(dados.get("plano") or PlanoBarbearia.SEM_ZAP)
    if plano not in PlanoBarbearia.values:
        return {"tipo": "plano_invalido"}

    contato = normalizar(dados.get("whatsappContato"))
    nome = dados.get("nome")
    dono_nome = dados.get("donoNome")
    endereco = dados.get("endereco")
    if not contato or not nome or not dono_nome or not endereco:
        return {"tipo": "faltou_campo"}

    if Barbearia.objects.using("admin").filter(slug=slug).exists():
        return {"tipo": "slug_duplicado", "slug": slug}

    convite = gerar_convite()

    # UMA transacao: se a criacao do dono falhar, a barbearia NAO pode
    # sobrar — barbearia sem dono e' orfa, ninguem entra nela para cadastrar
    # ninguem. Por isso nao usa `com_barbearia_admin()` aqui: aquele helper
    # abre a PROPRIA transacao, e o `set_config` precisa acontecer DENTRO
    # desta, depois que a barbearia passa a existir e antes do INSERT do
    # dono.
    with transaction.atomic(using="admin", durable=True):
        barbearia = Barbearia.objects.using("admin").create(
            id=str(uuid.uuid4()),
            slug=slug,
            nome=nome,
            endereco=endereco,
            horario_resumo=None,  # sem horario: o dono preenche pela tela dele.
            whatsapp_contato=contato,
            plano=plano,
        )
        with connections["admin"].cursor() as cur:
            cur.execute(
                "SELECT set_config('app.barbearia_id', %s, true)", [str(barbearia.id)]
            )
        Barbeiro.objects.using("admin").create(
            id=str(uuid.uuid4()),
            barbearia_id=barbearia.id,
            nome=dono_nome,
            whatsapp=contato,
            papel="DONO",
            senha_hash=None,
            convite_token_hash=convite["hash"],
            convite_expira_em=convite["expira_em"],
        )
        if plano == PlanoBarbearia.COM_ZAP:
            _criar_linha_da_instancia(barbearia.id)

    # DEPOIS do commit, e nao dentro dele: a Evolution fora do ar nao pode
    # impedir o cadastro de uma barbearia. O que fica gravado e a linha
    # `PENDENTE` acima — a conferencia periodica termina o servico no proximo
    # tique, e o `garantir_instancia` e idempotente justamente para isso.
    #
    # O `using="admin"` importa: o gancho tem que pendurar no commit da
    # conexao que a transacao de cima abriu. Registrado na `default` (o padrao
    # do `on_commit`), que esta em autocommit, ele dispararia NA HORA — antes
    # de a barbearia existir para quem le por outra conexao.
    if plano == PlanoBarbearia.COM_ZAP:
        transaction.on_commit(lambda: garantir_instancia(barbearia), using="admin")

    return {
        "tipo": "ok",
        "id": barbearia.id,
        "slug": barbearia.slug,
        "nome": barbearia.nome,
        "contato": contato,
        "dono_nome": dono_nome,
        "convite": convite,
    }


def _criar_linha_da_instancia(barbearia_id) -> None:
    """A linha do lado de ca, sempre `PENDENTE`. `get_or_create` e nao
    `create`: sair e voltar para o plano com zap e um caminho normal, e o
    segundo INSERT morreria no UNIQUE do `nome`.

    Escreve pela conexao `admin` e com o RLS apontado a mao, e nao por
    `com_barbearia_admin`, porque quem chama PODE ja estar dentro de uma
    transacao dessa conexao (`criar()` esta) — e aquele helper abre a propria
    transacao `durable=True`, que aninhada estoura de proposito.

    O `atomic()` liso aqui nao e zelo: `set_config(..., true)` e' LOCAL a
    transacao, e em autocommit ele morre junto com o proprio SELECT — o INSERT
    seguinte chega sem tenant nenhum e o banco o recusa com "new row violates
    row-level security policy". Vindo de `criar()` este bloco e' so' um
    SAVEPOINT dentro da transacao de la, e aponta o RLS para a MESMA barbearia
    que ela ja tinha apontado; vindo da troca de plano, ele e' a transacao de
    verdade que faltava.
    """
    with transaction.atomic(using="admin"):
        with connections["admin"].cursor() as cur:
            cur.execute(
                "SELECT set_config('app.barbearia_id', %s, true)", [str(barbearia_id)]
            )
        WhatsappInstancia.objects.using("admin").get_or_create(
            barbearia_id=barbearia_id,
            defaults={"id": str(uuid.uuid4()), "nome": nome_da_instancia(barbearia_id)},
        )


def atualizar_ativo(barbearia_id: str, ativo: bool) -> bool:
    """`update()`, nao `get()+save()`: um id inexistente so' precisa virar
    `count == 0`, nao uma excecao pra' distinguir de qualquer outra falha —
    mesmo raciocinio do `updateMany` do route.ts.

    O gancho do WhatsApp so olha para barbearia COM ZAP: desativada com o
    vinculo de pe, ela continuaria ocupando um numero que o Marcai paga e
    continuaria conectada ao celular de alguem que saiu. Reativar refaz o
    caminho do cadastro — instancia nova, QR novo.
    """
    barbearia = Barbearia.objects.using("admin").filter(id=barbearia_id).first()
    if barbearia is None:
        return False

    Barbearia.objects.using("admin").filter(id=barbearia_id).update(ativo=ativo)

    if barbearia.plano == PlanoBarbearia.COM_ZAP:
        if ativo:
            _criar_linha_da_instancia(barbearia.id)
            garantir_instancia(barbearia)
        else:
            apagar_instancia(barbearia)
    return True


def atualizar_plano(barbearia_id: str, plano: str) -> bool:
    """Sobe e desce entre os dois planos comerciais.

    Plano repetido nao faz nada, e isso importa: derrubar e recriar a
    instancia porque alguem clicou duas vezes obrigaria o dono a escanear o QR
    de novo, sem nada ter mudado.
    """
    barbearia = Barbearia.objects.using("admin").filter(id=barbearia_id).first()
    if barbearia is None:
        return False
    if barbearia.plano == plano:
        return True

    Barbearia.objects.using("admin").filter(id=barbearia_id).update(plano=plano)
    barbearia.plano = plano

    if plano == PlanoBarbearia.COM_ZAP:
        _criar_linha_da_instancia(barbearia.id)
        garantir_instancia(barbearia)
    else:
        apagar_instancia(barbearia)
    return True


def reemitir_convite(barbearia_id: str) -> dict:
    barbearia = Barbearia.objects.using("admin").filter(id=barbearia_id).first()
    if barbearia is None:
        return {"tipo": "barbearia_nao_encontrada"}

    convite = gerar_convite()

    with com_barbearia_admin(barbearia.id):
        atual = (
            Barbeiro.objects.using("admin")
            .filter(papel="DONO", ativo=True)
            .order_by("criado_em")
            .first()
        )
        if atual is None:
            return {"tipo": "sem_dono_ativo"}

        Barbeiro.objects.using("admin").filter(id=atual.id).update(
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
        "dono_nome": atual.nome,
        "dono_whatsapp": atual.whatsapp,
        "convite": convite,
    }
