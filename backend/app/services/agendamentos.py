import logging
import secrets
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.db.utils import OperationalError
from django.utils import timezone

from tenant.config import PRAZO_CANCELAMENTO_MIN
from tenant.datas import como_utc, utc_para_local
from tenant.models import Agendamento, Barbearia, BarbeiroServico, Cliente, Cobranca
from tenant.rls import com_barbearia

from . import pix_agendamento
from .agenda import slots_do_dia
from .lembrete import lembrete_ao_criar
from .mensalidade import operacoes as mensalidade
from .mensalidade import pix
from .mensalidade.centavos import SemCentavoLivre
from .mensalidade.situacao import Situacao

logger = logging.getLogger(__name__)

# De onde veio o pedido. So' o SITE cobra Pix; o painel (o barbeiro marcando
# no balcao) e o bot nascem confirmados. Explicita em quem chama, sem padrao:
# esquecer de dizer viraria cobranca (ou falta dela) em silencio.
SITE = "SITE"
PAINEL = "PAINEL"
BOT = "BOT"
ORIGENS = (SITE, PAINEL, BOT)

AGUARDANDO = "AGUARDANDO_PAGAMENTO"

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
    """O NOME e' ATUALIZADO nos DOIS fluxos, publico e painel — nao e'
    diferenca exclusiva do painel como um comentario anterior desta funcao
    supunha (achado da travessia do bloco C: o `cliente.upsert` do route.ts
    publico tambem manda `update: { nome }`). Compartilhada pelos dois
    porque o motivo vale para os dois: quem digitou por ultimo sabe o nome
    melhor que o cadastro de tres meses atras."""
    atualizados = Cliente.objects.filter(barbearia_id=barbearia_id, whatsapp=whatsapp).update(nome=nome)
    if atualizados:
        return Cliente.objects.get(barbearia_id=barbearia_id, whatsapp=whatsapp).id
    novo_id = str(uuid.uuid4())
    Cliente.objects.create(id=novo_id, barbearia_id=barbearia_id, nome=nome, whatsapp=whatsapp)
    return novo_id


def eh_deadlock(exc: BaseException) -> bool:
    """40P01 = deadlock_detected. Dois INSERTs que cruzam o mesmo intervalo
    do mesmo barbeiro, na restricao de EXCLUSAO, podem se esperar um ao outro:
    cada um ja gravou a sua linha no indice e, ao conferir conflito, acha a do
    outro ainda nao confirmada e espera por ela. O Postgres derruba um dos
    dois com 40P01 em vez de 23P01. Para o cliente e' o mesmo desfecho — o
    horario foi do outro —, entao tem a mesma resposta."""
    atual: BaseException | None = exc
    for _ in range(5):
        if atual is None:
            return False
        if getattr(atual, "sqlstate", None) == "40P01":
            return True
        atual = getattr(atual, "__cause__", None)
    return False


def marcar(
    *, barbearia_id: str, barbeiro_id: str, servico_id: str, inicio: datetime,
    nome: str, whatsapp: str, agora: datetime, origem: str, aparelho: str | None = None,
) -> dict:
    """POST /painel/agendamentos — e tambem o motor de `POST /agendamentos`
    (fluxo publico, bloco C da travessia): as duas rotas chamam esta MESMA
    funcao, porque a unica diferenca real entre elas e' externa a ela — o
    oraculo `numero_existe` da Evolution, que so o fluxo publico consulta
    (o balcao do painel e' um IP so, o limite por IP morderia o uso
    legitimo) e que por isso e' conferido pela VIEW publica ANTES de chamar
    `marcar()`, nao aqui dentro.

    Levanta `ErroCliente` para os desfechos que a VIEW traduz em status —
    igual ao route.ts, que joga uma excecao dentro da transacao para poder
    decidir o codigo HTTP so depois do `try`.

    Pelo SITE, de um barbeiro que cobra, o agendamento nasce
    `AGUARDANDO_PAGAMENTO` e a cobranca Pix abre DEPOIS do commit dele (a FK da
    cobranca e' conferida no commit dela, por outra conexao). Se a cobranca nao
    abrir por qualquer motivo, o agendamento vira CONFIRMADO sem cobranca
    ("pagar no local"): o cliente ja' tem o horario, e preso sem Pix ninguem
    conseguiria pagar nem o barbeiro apertar "recebi".
    """
    if origem not in ORIGENS:
        raise ValueError(f"origem desconhecida: {origem!r}")
    _liberar_vencidos_do_barbeiro(barbearia_id, barbeiro_id, agora)
    try:
        criado = _marcar_na_transacao(
            barbearia_id=barbearia_id, barbeiro_id=barbeiro_id, servico_id=servico_id,
            inicio=inicio, nome=nome, whatsapp=whatsapp, agora=agora, aparelho=aparelho,
            origem=origem,
        )
    except OperationalError as e:
        # Fora da transacao (ja desfeita) e dentro de `marcar()`, e nao nas
        # tres views: o site, o painel e o bot respondem "horario perdido" do
        # mesmo jeito que respondem `ErroCliente` 409.
        if eh_deadlock(e):
            raise ErroCliente(409, "Esse horário não está mais disponível.") from e
        raise
    cobranca = criado.pop("a_cobrar")
    if cobranca is not None:
        _abrir_cobranca_ou_confirmar(criado, cobranca, barbearia_id, agora)
    return criado


def _liberar_vencidos_do_barbeiro(barbearia_id, barbeiro_id, agora: datetime) -> None:
    """Expira os Pix vencidos DESTE barbeiro antes de conferir a vaga, para o
    horario nao ficar preso por causa do relogio do beat. Fora da transacao do
    insert (a varredura abre as proprias, curtas) e sem zap dentro de nenhuma.
    So' olha a Cobranca (barata) antes de abrir transacao no tenant; qualquer
    falha vira log — o pedido segue e o beat acerta depois."""
    try:
        vencidas = Cobranca.objects.using("admin").filter(
            barbearia_id=barbearia_id, motivo="AGENDAMENTO", status="ABERTA",
            expira_em__lte=agora,
        ).exists()
        if vencidas:
            pix_agendamento.expirar_vencidos(
                agora, barbearia_id=barbearia_id, barbeiro_id=barbeiro_id,
            )
    except Exception:
        logger.exception("[pix] nao deu para expirar os vencidos de %s", barbeiro_id)


def _abrir_cobranca_ou_confirmar(criado: dict, a_cobrar: dict, barbearia_id, agora: datetime) -> None:
    """Fora da transacao do agendamento, que ja' comitou. Preenche
    `criado["cobranca"]` ou, se nao deu, devolve o agendamento ao fluxo normal."""
    try:
        cobranca = pix_agendamento.abrir(
            barbearia_id=barbearia_id, agendamento_id=criado["id"], agora=agora, **a_cobrar,
        )
    except SemCentavoLivre:
        logger.warning(
            "[pix] chave sem centavo livre; agendamento %s segue sem cobranca", criado["id"],
        )
    except Exception:
        logger.exception(
            "[pix] cobranca nao abriu; agendamento %s segue sem cobranca", criado["id"],
        )
    else:
        criado["cobranca"] = {
            "valor_centavos": cobranca.valor_centavos,
            "copia_e_cola": cobranca.copia_e_cola,
            "expira_em": cobranca.expira_em,
        }
        return
    # Se a cobranca chegou a comitar antes do erro, ela nao pode sobreviver ao
    # agendamento confirmado: a varredura a marcaria PAGA depois.
    pix_agendamento.cancelar_abertas([criado["id"]])
    # Dentro da janela do lembrete, a confirmacao que sai agora ja' e' o lembrete.
    with com_barbearia(barbearia_id):
        Agendamento.objects.filter(id=criado["id"], status=AGUARDANDO).update(
            status="CONFIRMADO", lembrete_enviado_em=lembrete_ao_criar(criado["inicio"], agora),
        )
    criado["status"] = "CONFIRMADO"


def _marcar_na_transacao(
    *, barbearia_id: str, barbeiro_id: str, servico_id: str, inicio: datetime,
    nome: str, whatsapp: str, agora: datetime, aparelho: str | None, origem: str,
) -> dict:
    with com_barbearia(barbearia_id):
        vinculo = (
            BarbeiroServico.objects.filter(barbeiro_id=barbeiro_id, servico_id=servico_id)
            .select_related("servico", "barbeiro")
            .first()
        )
        if vinculo is None or not vinculo.ativo or not vinculo.servico.ativo:
            # Neutra, e nao "Esse barbeiro...": `marcar()` so' tem o id da
            # barbearia (nao o ramo), e a frase tambem chega pelo bot.
            raise ErroCliente(422, "Quem você escolheu não faz esse serviço.")

        # A duracao vem do banco. O que veio no corpo e' sugestao de atacante.
        # O preco tambem — e pode ser None: o barbeiro pode nao ter
        # precificado ainda, e isso nao pode bloquear a marcacao.
        duracao_min = vinculo.duracao_min
        preco_centavos = vinculo.preco_centavos
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

        a_cobrar = _a_cobrar(vinculo, origem, barbearia_id, agora)

        novo_id = str(uuid.uuid4())
        codigo = _gerar_codigo()
        Agendamento.objects.create(
            id=novo_id, barbearia_id=barbearia_id, codigo=codigo,
            barbeiro_id=barbeiro_id, cliente_id=cliente_id, servico_id=servico_id,
            servico_nome=vinculo.servico.nome, inicio=inicio, fim=fim, duracao_min=duracao_min,
            # Snapshot do preco praticado agora — reprecar depois nao pode
            # reescrever quanto ESTE agendamento custou.
            preco_centavos=preco_centavos,
            status=AGUARDANDO if a_cobrar else "CONFIRMADO",
            # Dentro da janela do lembrete, a confirmacao que sai a seguir JA
            # e' o lembrete: nasce avisado, o cron nunca o ve. Quem espera o
            # Pix ainda nao tem confirmacao; isto se decide quando confirmar.
            lembrete_enviado_em=None if a_cobrar else lembrete_ao_criar(inicio, agora),
            aparelho=aparelho,
        )

    return {
        "id": novo_id,
        "barbeiro_id": str(barbeiro_id),
        "codigo": codigo,
        "barbeiro_nome": vinculo.barbeiro.nome,
        # O numero do barbeiro sobe junto porque quem marca e' o CLIENTE, e o
        # barbeiro so' descobriria abrindo o painel.
        "barbeiro_whatsapp": vinculo.barbeiro.whatsapp,
        "servico_nome": vinculo.servico.nome,
        "inicio": inicio,
        "preco_centavos": preco_centavos,
        "status": AGUARDANDO if a_cobrar else "CONFIRMADO",
        # Preenchido por `marcar()` depois do commit, se a cobranca abrir.
        "cobranca": None,
        "a_cobrar": a_cobrar,
    }


def _a_cobrar(vinculo, origem: str, barbearia_id, agora: datetime) -> dict | None:
    """Os dados da cobranca se este pedido deve cobrar Pix, ou None. Cobra so'
    o SITE, de um barbeiro que ligou a cobranca e tem chave, para um servico
    com preco, numa barbearia cuja mensalidade nao esta BLOQUEADA (com o
    painel travado ninguem apertaria "recebi", e o dinheiro ficaria preso).
    Falta qualquer um: nasce confirmado, como "pagar no local"."""
    barbeiro = vinculo.barbeiro
    chave = pix.normalizar_chave(barbeiro.pix_chave)
    if (
        origem != SITE
        or not barbeiro.cobra_no_agendamento
        or not chave
        or not barbeiro.pix_tipo
        or not barbeiro.pix_titular
        or not vinculo.preco_centavos
    ):
        return None
    # Mesma leitura da trava do painel, pela mesma conexao.
    if mensalidade.leitura(barbearia_id, agora=agora, using="default").situacao == Situacao.BLOQUEADA:
        return None
    cidade = Barbearia.objects.filter(id=barbearia_id).values_list("cidade", flat=True).first()
    return {
        "chave": chave,
        "titular": barbeiro.pix_titular,
        "cidade": cidade or "BRASIL",
        "base_centavos": vinculo.preco_centavos,
    }


# Os dois que seguram horario: cancelar vale para ambos.
STATUS_CANCELAVEIS = ("CONFIRMADO", AGUARDANDO)


def cancelar(barbearia_id: str, agendamento_id: str, filtro_barbeiro_id: str | None) -> dict | None:
    """POST /painel/agendamentos/<id>/cancelar. Sem conferir
    `PRAZO_CANCELAMENTO_MIN`: aquela e' regra contra o CLIENTE sumir em cima
    da hora, e o barbeiro que quebrou o braco precisa desmarcar a tarde
    inteira agora.

    Cancela tambem o que aguarda o Pix (e a cobranca dele). `aguardando` no
    retorno diz a quem chama que esse horario nunca entrou na lista do dia."""
    with com_barbearia(barbearia_id):
        # Sob a trava da linha, como o "recebi" e a varredura: o status que se
        # decide aqui e' o que vale ate o commit, e um "recebi" no meio espera.
        a = (
            Agendamento.objects.select_for_update(of=("self",))
            .filter(id=agendamento_id)
            .select_related("cliente", "barbeiro")
            .first()
        )
        if a is None or a.status not in STATUS_CANCELAVEIS:
            return None

        # Reconferencia DEPOIS de carregar: um barbeiro que forje o id do
        # agendamento do colega recebe 404 — 403 confirmaria que ele existe.
        if filtro_barbeiro_id and filtro_barbeiro_id != a.barbeiro_id:
            return None

        Agendamento.objects.filter(id=agendamento_id).update(
            status="CANCELADO_BARBEIRO", cancelado_em=timezone.now(),
        )
        dados = {
            "id": str(a.id), "barbeiro_id": str(a.barbeiro_id),
            "cliente_nome": a.cliente.nome, "cliente_whatsapp": a.cliente.whatsapp,
            "barbeiro_nome": a.barbeiro.nome, "servico_nome": a.servico_nome, "inicio": a.inicio,
            "aguardando": a.status == AGUARDANDO,
            "pago_centavos": pix_agendamento.valor_pago(a.id, a.status),
        }
        if dados["pago_centavos"]:
            pix_agendamento.marcar_pagas([a.id], timezone.now())
    if dados["aguardando"]:
        pix_agendamento.cancelar_abertas([a.id])
    if dados["pago_centavos"]:
        pix_agendamento.avisar_cancelamento_pago(barbearia_id, [{
            "cliente_nome": dados["cliente_nome"], "barbeiro_whatsapp": a.barbeiro.whatsapp,
            "inicio": a.inicio, "valor_centavos": dados["pago_centavos"],
        }], pelo_cliente=False)
    return dados


def pode_cancelar(a: Agendamento, agora: datetime) -> bool:
    """A regra do botao de cancelar, num lugar so': confirmado (ou esperando o
    Pix, `STATUS_CANCELAVEIS`) e FORA do
    prazo de `PRAZO_CANCELAMENTO_MIN`. O detalhe publico, o cancelamento pelo
    link, o cancelamento logado e o historico da conta usam esta mesma conta."""
    minutos_ate = (como_utc(a.inicio) - agora).total_seconds() / 60
    return a.status in STATUS_CANCELAVEIS and minutos_ate > PRAZO_CANCELAMENTO_MIN


def detalhe_publico(barbearia_id: str, codigo: str, agora: datetime) -> dict | None:
    """GET /agendamentos/<codigo> — sem sessao, so' o RLS garante que um
    codigo de OUTRA barbearia nao e' encontrado aqui (o codigo por si so' e'
    de 10 caracteres, sem barbeariaId embutido nele).

    `pode_cancelar` e' CALCULADO AQUI, no servidor — a tela obedece, nao
    recalcula, senao um relogio de cliente adiantado liberaria um botao que
    o back recusaria de qualquer forma.
    """
    with com_barbearia(barbearia_id):
        a = (
            Agendamento.objects.filter(codigo=codigo)
            .select_related("barbeiro", "cliente")
            .first()
        )
        if a is None:
            return None

        cobranca = None
        if a.status == AGUARDANDO:
            cobranca = (
                Cobranca.objects.filter(
                    agendamento_id=a.id, barbearia_id=barbearia_id, status="ABERTA",
                ).first()
            )
        return {
            "codigo": a.codigo,
            # O nome do cliente sai; o WhatsApp dele, nunca (§9.1).
            "cliente_nome": a.cliente.nome,
            "barbeiro_nome": a.barbeiro.nome,
            "servico_nome": a.servico_nome,
            "duracao_min": a.duracao_min,
            "preco_centavos": a.preco_centavos,
            "inicio": a.inicio,
            "fim": a.fim,
            "status": a.status,
            "pode_cancelar": pode_cancelar(a, agora),
            # O Pix so' aparece enquanto a cobranca esta aberta; vencida ou
            # cancelada, a tela cai no estado que o `status` disser.
            "pix": None if cobranca is None else {
                "copia_e_cola": cobranca.copia_e_cola,
                "qr_svg": pix.qr_svg(cobranca.copia_e_cola),
                "valor_centavos": cobranca.valor_centavos,
            },
            "expira_em": None if cobranca is None else cobranca.expira_em,
            # Para o "fale com" da tela. O numero do barbeiro so' sai por aqui,
            # que exige o codigo do agendamento — segredo do proprio cliente.
            "barbeiro": {"nome": a.barbeiro.nome, "whatsapp": a.barbeiro.whatsapp},
        }


def cancelar_publico(
    barbearia_id: str, codigo: str, agora: datetime, *, whatsapps: list[str] | None = None,
) -> dict:
    """POST /agendamentos/<codigo>/cancelar — pelo CODIGO, nao por id: e' o
    que o cliente tem em maos, sem sessao nenhuma.

    Cancelar o que ja esta cancelado devolve `{"tipo": "ok"}` de proposito
    (a VIEW trata os dois tipos da mesma forma): quem apertou o botao duas
    vezes queria o mesmo desfecho, e ele ja vale — reenviar a mensagem de
    cancelamento e' que NAO pode acontecer duas vezes, e por isso so' o
    `tipo == "ok"` de verdade (o que efetivamente cancelou agora) devolve os
    dados pro WhatsApp; o `ja_cancelado` nao.

    `whatsapps` e' o cancelamento LOGADO: so' vale se o cliente do agendamento
    for um dos numeros da conta. De outro numero, e' `nao_encontrado`, igual a
    um codigo que nao existe — nao confirma que o codigo e' de alguem.
    """
    with com_barbearia(barbearia_id):
        a = (
            Agendamento.objects.select_for_update(of=("self",))
            .filter(codigo=codigo)
            .select_related("barbeiro", "cliente")
            .first()
        )
        if a is None or (whatsapps is not None and a.cliente.whatsapp not in whatsapps):
            return {"tipo": "nao_encontrado"}
        if a.status not in STATUS_CANCELAVEIS:
            return {"tipo": "ja_cancelado"}

        # Reconferido no servidor mesmo com podeCancelar:false na tela —
        # botao desabilitado nao e' controle de acesso.
        if not pode_cancelar(a, agora):
            return {"tipo": "fora_do_prazo"}

        Agendamento.objects.filter(id=a.id).update(
            status="CANCELADO_CLIENTE", cancelado_em=timezone.now(),
        )
        resultado = {
            "tipo": "ok",
            "aguardando": a.status == AGUARDANDO,
            "id": str(a.id),
            "barbeiro_id": str(a.barbeiro_id),
            "cliente_nome": a.cliente.nome,
            "cliente_whatsapp": a.cliente.whatsapp,
            "barbeiro_nome": a.barbeiro.nome,
            # Idem `criar()`: a vaga abriu e quem precisa saber e' quem ia
            # cortar. O `select_related` acima ja trouxe o barbeiro.
            "barbeiro_whatsapp": a.barbeiro.whatsapp,
            "servico_nome": a.servico_nome,
            "inicio": a.inicio,
            "pago_centavos": pix_agendamento.valor_pago(a.id, a.status),
        }
        if resultado["pago_centavos"]:
            pix_agendamento.marcar_pagas([a.id], timezone.now())
    if resultado["aguardando"]:
        pix_agendamento.cancelar_abertas([a.id])
    if resultado["pago_centavos"]:
        pix_agendamento.avisar_cancelamento_pago(barbearia_id, [{
            "cliente_nome": resultado["cliente_nome"], "barbeiro_whatsapp": a.barbeiro.whatsapp,
            "inicio": a.inicio, "valor_centavos": resultado["pago_centavos"],
        }], pelo_cliente=True)
    return resultado
