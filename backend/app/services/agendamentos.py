import secrets
import uuid
from datetime import datetime, timedelta

from django.utils import timezone

from tenant.datas import utc_para_local
from tenant.models import Agendamento, BarbeiroServico, Cliente
from tenant.rls import com_barbearia

from .agenda import slots_do_dia
from .lembrete import lembrete_ao_criar

# Alfabeto sem 0/O e 1/l/I — o codigo e' lido em voz alta e digitado a mao.
_ALFABETO_CODIGO = "23456789abcdefghjkmnpqrstuvwxyz"


def _gerar_codigo() -> str:
    return "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(10))


class ErroCliente(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def eh_sobreposicao(exc: BaseException) -> bool:
    """23P01 = exclusion_violation, disparado por
    `agendamento_sem_sobreposicao` (§5.4). NAO e' 23505 (unique_violation): a
    garantia e' uma restricao de EXCLUSAO sobre intervalos.

    O nome da constraint mora em `diag.constraint_name`, dentro de
    `__cause__` (o `IntegrityError` do Django embrulha o erro nativo do
    psycopg) — procurado em ate 5 niveis pelo mesmo motivo do `ehSobreposicao`
    do TypeScript: o driver pode mudar onde embrulha isso numa atualizacao de
    dependencia, e o silencio ali seria um 500 no lugar de um 409."""
    atual: BaseException | None = exc
    for _ in range(5):
        if atual is None:
            return False
        diag = getattr(atual, "diag", None)
        if diag is not None and getattr(diag, "constraint_name", None) == "agendamento_sem_sobreposicao":
            return True
        atual = getattr(atual, "__cause__", None)
    return "agendamento_sem_sobreposicao" in str(exc)


def _upsert_cliente(barbearia_id: str, whatsapp: str, nome: str) -> str:
    """O NOME e' ATUALIZADO — diferenca do fluxo publico: o barbeiro esta
    com a pessoa na frente e sabe o nome melhor que o formulario de tres
    meses atras."""
    atualizados = Cliente.objects.filter(barbearia_id=barbearia_id, whatsapp=whatsapp).update(nome=nome)
    if atualizados:
        return Cliente.objects.get(barbearia_id=barbearia_id, whatsapp=whatsapp).id
    novo_id = str(uuid.uuid4())
    Cliente.objects.create(id=novo_id, barbearia_id=barbearia_id, nome=nome, whatsapp=whatsapp)
    return novo_id


def marcar(
    *, barbearia_id: str, barbeiro_id: str, servico_id: str, inicio: datetime,
    nome: str, whatsapp: str, agora: datetime,
) -> dict:
    """POST /painel/agendamentos. Tres diferencas do fluxo publico, todas
    porque o barbeiro esta com o cliente na frente:

    1. sem `numero_existe` — o oraculo da Evolution nao e' necessario aqui
       (o balcao e' um IP so, o limite morderia o uso legitimo).
    2. sem antecedencia minima — marcar para daqui a 5 minutos e' permitido;
       marcar no PASSADO continua recusado, agenda nao e' historico.
    3. o nome do cliente e' ATUALIZADO no upsert.

    Levanta `ErroCliente` para os desfechos que a VIEW traduz em status —
    igual ao route.ts, que joga uma excecao dentro da transacao para poder
    decidir o codigo HTTP so depois do `try`.
    """
    with com_barbearia(barbearia_id):
        vinculo = (
            BarbeiroServico.objects.filter(barbeiro_id=barbeiro_id, servico_id=servico_id)
            .select_related("servico", "barbeiro")
            .first()
        )
        if vinculo is None or not vinculo.ativo or not vinculo.servico.ativo:
            raise ErroCliente(422, "Esse barbeiro não faz esse serviço.")

        # A duracao vem do banco. O que veio no corpo e' sugestao de atacante.
        duracao_min = vinculo.duracao_min
        fim = inicio + timedelta(minutes=duracao_min)

        if inicio <= agora:
            raise ErroCliente(422, "Esse horário já passou.")

        dia, _ = utc_para_local(inicio)
        livres = slots_do_dia(barbeiro_id, servico_id, dia, agora)
        if not any(s.inicio == inicio for s in livres):
            # 409, mesmo status da restricao de exclusao logo abaixo: esta
            # checagem pega o caso sequencial, a restricao pega a corrida
            # real entre duas transacoes que leram antes de qualquer uma
            # gravar.
            raise ErroCliente(409, "Esse horário não está mais disponível.")

        cliente_id = _upsert_cliente(barbearia_id, whatsapp, nome)

        novo_id = str(uuid.uuid4())
        codigo = _gerar_codigo()
        Agendamento.objects.create(
            id=novo_id, barbearia_id=barbearia_id, codigo=codigo,
            barbeiro_id=barbeiro_id, cliente_id=cliente_id, servico_id=servico_id,
            servico_nome=vinculo.servico.nome, inicio=inicio, fim=fim, duracao_min=duracao_min,
            status="CONFIRMADO",
            # Dentro da janela do lembrete, a confirmacao que sai a seguir JA
            # e' o lembrete: nasce avisado, o cron nunca o ve.
            lembrete_enviado_em=lembrete_ao_criar(inicio, agora),
        )

    return {
        "codigo": codigo,
        "barbeiro_nome": vinculo.barbeiro.nome,
        "servico_nome": vinculo.servico.nome,
        "inicio": inicio,
    }


def cancelar(barbearia_id: str, agendamento_id: str, filtro_barbeiro_id: str | None) -> dict | None:
    """POST /painel/agendamentos/<id>/cancelar. Sem conferir
    `PRAZO_CANCELAMENTO_MIN`: aquela e' regra contra o CLIENTE sumir em cima
    da hora, e o barbeiro que quebrou o braco precisa desmarcar a tarde
    inteira agora."""
    with com_barbearia(barbearia_id):
        a = (
            Agendamento.objects.filter(id=agendamento_id)
            .select_related("cliente", "barbeiro")
            .first()
        )
        if a is None or a.status != "CONFIRMADO":
            return None

        # Reconferencia DEPOIS de carregar: um barbeiro que forje o id do
        # agendamento do colega recebe 404 — 403 confirmaria que ele existe.
        if filtro_barbeiro_id and filtro_barbeiro_id != a.barbeiro_id:
            return None

        Agendamento.objects.filter(id=agendamento_id).update(
            status="CANCELADO_BARBEIRO", cancelado_em=timezone.now(),
        )
        return {
            "cliente_nome": a.cliente.nome, "cliente_whatsapp": a.cliente.whatsapp,
            "barbeiro_nome": a.barbeiro.nome, "servico_nome": a.servico_nome, "inicio": a.inicio,
        }
