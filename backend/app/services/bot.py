"""A casca do bot de agendamento: banco, Evolution e as acoes.

A regra da conversa NAO mora aqui — mora em `conversa.py`, pura. Este modulo
le o estado, executa a decisao (buscar opcoes, marcar, cancelar, chamar gente)
e grava o estado novo.

Tudo dentro de `trava_da_conversa`: `marcar`, `cancelar_publico` e
`dias_com_horarios` abrem o proprio `com_barbearia`, que nao pode ser
aninhado, entao uma trava de linha nao seguraria a conversa inteira.

Nenhuma funcao daqui e' chamada de dentro de um `com_barbearia`.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import IntegrityError, OperationalError

from tenant.config import (
    BOT_DIAS_OFERECIDOS,
    BOT_ESPERA_TRAVA_S,
    BOT_HORAS_OFERECIDAS,
    BOT_IDS_GUARDADOS,
    BOT_JANELA_DIAS,
    BOT_MUDO_HORAS,
    BOT_TENTATIVAS_ANTES_DO_ZERO,
)
from tenant.datas import como_utc, dia_de_hoje, formatar_instante_iso
from tenant.models import (
    Agendamento,
    Barbearia,
    Barbeiro,
    BarbeiroServico,
    Cliente,
    ConversaWhatsapp,
    EstadoInstancia,
    PapelBarbeiro,
    PlanoBarbearia,
    Servico,
    WhatsappInstancia,
)
from tenant.rls import com_barbearia
from tenant.telefone import formas_gravadas, formatar, nacional_canonico

from . import conversa as c
from .agenda import dias_com_horarios
from .agendamentos import ErroCliente, cancelar_publico, eh_sobreposicao, marcar
from .convite import link_do_agendamento
from .mensagens import (
    msg_barbeiro_cancelado,
    msg_barbeiro_desistiu,
    msg_barbeiro_novo,
    msg_bot_chamou_humano,
    msg_bot_desistencia_avisada,
    msg_bot_fora_do_prazo,
    msg_bot_lembrete_confirmado,
    msg_bot_nao_achei_agendamento,
    msg_bot_nao_entendi,
    msg_bot_nao_entendi_nome,
    msg_bot_pediu_humano,
    msg_bot_pergunta,
    msg_bot_pergunta_do_lembrete,
    msg_bot_sem_opcoes,
    msg_cancelamento,
    msg_confirmacao,
    msg_lembrete_com_opcoes,
    rotulo_da_hora,
    rotulo_do_agendamento,
)
from .servicos import QUALQUER
from .servicos import listar_para_agendamento as servicos_para_agendamento
from .trava_conversa import trava_da_conversa
from .whatsapp import _enviar, enviar_a_equipe_da

logger = logging.getLogger(__name__)


@dataclass
class _Contexto:
    barbearia: Barbearia
    instancia: WhatsappInstancia
    numero: str
    agora: datetime

    @property
    def bid(self) -> str:
        return str(self.barbearia.id)


@dataclass
class _Saida:
    """O que sai de um passo: o estado novo da conversa e o que o cliente le."""

    desfecho: str
    passo: str
    textos: list
    opcoes: list = field(default_factory=list)
    rascunho: dict = field(default_factory=dict)
    tentativas: int = 0
    pergunta: str | None = None
    mudo_ate: datetime | None = None


def processar(barbearia_id: str, numero: str, texto: str, mensagem_id: str, agora: datetime) -> str:
    """Uma mensagem de cliente. `numero` ja vem normalizado (`do_jid`).

    Confere de novo o que a entrada ja conferiu (plano, bot ligado, conectado):
    entre enfileirar e rodar, o dono pode ter desligado o bot, e o bot nao fala
    onde deixou de ser convidado.
    """
    barbearia = Barbearia.objects.filter(
        id=barbearia_id, ativo=True, plano=PlanoBarbearia.COM_ZAP,
    ).first()
    if barbearia is None:
        return "ignorado"
    with com_barbearia(barbearia_id):
        instancia = WhatsappInstancia.objects.filter(barbearia_id=barbearia_id).first()
    if (
        instancia is None
        or not instancia.bot_ativo
        or instancia.estado != EstadoInstancia.CONECTADO
    ):
        return "ignorado"

    ctx = _Contexto(barbearia, instancia, numero, agora)
    with trava_da_conversa(ctx.bid, numero):
        linha = _conversa(ctx.bid, numero)
        if linha is not None and linha.ultima_mensagem_id == mensagem_id:
            return "duplicada"
        if linha is not None and linha.mudo_ate and como_utc(linha.mudo_ate) > agora:
            with com_barbearia(ctx.bid):
                ConversaWhatsapp.objects.filter(id=linha.id).update(
                    ultima_mensagem_id=mensagem_id,
                )
            return "mudo"

        estado = _estado_de(linha)
        decisao = c.decidir(estado, texto, agora)
        saida = _executar(ctx, estado, linha.pergunta if linha else None, decisao)
        ids = [i for i in (_enviar(instancia.nome, numero, t) for t in saida.textos) if i]
        _gravar(ctx, linha, saida, mensagem_id, ids)
        return saida.desfecho


# ---- leitura e gravacao ----


def _conversa(barbearia_id: str, numero: str):
    with com_barbearia(barbearia_id):
        return ConversaWhatsapp.objects.filter(whatsapp=numero).first()


def _estado_de(linha) -> c.Estado:
    if linha is None:
        return c.Estado(c.MENU, [], {}, 0, None)
    return c.Estado(
        linha.estado, linha.opcoes or [], linha.rascunho or {},
        linha.tentativas, como_utc(linha.atualizado_em),
    )


# Desfechos onde algo ja aconteceu (agendamento criado/cancelado, dono
# avisado, desistencia avisada, lembrete confirmado) ANTES de qualquer envio
# ao cliente, ou cujo efeito nao depende do envio. Para esses, o estado avanca
# mesmo que o `_enviar` ao cliente falhe — nao ha o que "desfazer", e travar o
# estado no passo anterior arriscaria uma segunda tentativa de marcar.
_ACOES_JA_ACONTECERAM = frozenset({
    "marcou", "cancelou", "humano", "desistencia_avisada", "lembrete_confirmado",
})


def _gravar(ctx: _Contexto, linha, saida: _Saida, mensagem_id: str, ids_novos: list) -> None:
    anteriores = list(linha.ids_do_bot or []) if linha is not None else []
    sem_entrega = (
        saida.textos and not ids_novos and saida.desfecho not in _ACOES_JA_ACONTECERAM
    )
    if sem_entrega:
        # Nenhuma mensagem chegou ao cliente (recusa, timeout ou excecao no
        # `_enviar`). Avancar o estado aqui deixaria uma pergunta — ou pior,
        # o resumo de "Confere:" — respondivel sem o cliente ter lido: um "1"
        # seguinte cairia na opcao 1 do passo NOVO, nao do que ele via na
        # tela. Guarda so o id da mensagem recebida, para nao reprocessa-la,
        # e mantem a conversa exatamente onde estava.
        campos = {
            "estado": linha.estado if linha is not None else c.MENU,
            "opcoes": linha.opcoes if linha is not None else [],
            "rascunho": linha.rascunho if linha is not None else {},
            "tentativas": linha.tentativas if linha is not None else 0,
            "pergunta": linha.pergunta if linha is not None else None,
            "ultima_mensagem_id": mensagem_id,
            "ids_do_bot": anteriores,
            "mudo_ate": linha.mudo_ate if linha is not None else None,
            "atualizado_em": ctx.agora,
        }
    else:
        campos = {
            "estado": saida.passo,
            "opcoes": saida.opcoes,
            "rascunho": saida.rascunho,
            "tentativas": saida.tentativas,
            "pergunta": saida.pergunta,
            "ultima_mensagem_id": mensagem_id,
            "ids_do_bot": (anteriores + ids_novos)[-BOT_IDS_GUARDADOS:],
            "mudo_ate": saida.mudo_ate,
            "atualizado_em": ctx.agora,
        }
    with com_barbearia(ctx.bid):
        if linha is None:
            ConversaWhatsapp.objects.create(
                id=str(uuid.uuid4()), barbearia_id=ctx.bid, whatsapp=ctx.numero, **campos,
            )
        else:
            ConversaWhatsapp.objects.filter(id=linha.id).update(**campos)


# ---- executar a decisao ----


def _executar(ctx: _Contexto, estado: c.Estado, pergunta_anterior, decisao) -> _Saida:
    if isinstance(decisao, c.Repetir):
        mostrar_zero = decisao.tentativas >= BOT_TENTATIVAS_ANTES_DO_ZERO
        if estado.passo == c.NOME:
            # NOME e' texto livre: "responde so com o numero" contradiria a
            # propria pergunta que se repete logo depois.
            texto = msg_bot_nao_entendi_nome(mostrar_zero=mostrar_zero)
        else:
            texto = msg_bot_nao_entendi(
                pergunta=pergunta_anterior or "", mostrar_zero=mostrar_zero,
            )
        return _Saida(
            "repetiu", estado.passo, [texto], estado.opcoes, estado.rascunho,
            decisao.tentativas, pergunta_anterior,
        )
    if isinstance(decisao, c.ChamarHumano):
        _avisar_donos(ctx)
        return _Saida(
            "humano", c.MENU, [msg_bot_chamou_humano()],
            mudo_ate=ctx.agora + timedelta(hours=BOT_MUDO_HORAS),
        )
    if isinstance(decisao, c.Marcar):
        return _marcar(ctx, decisao.rascunho)
    if isinstance(decisao, c.Cancelar):
        return _cancelar(ctx, decisao.codigo)
    if isinstance(decisao, c.ConfirmarLembrete):
        return _confirmar_lembrete(ctx, decisao.codigo)
    if isinstance(decisao, c.NaoVou):
        return _nao_vou(ctx, decisao.codigo)
    return _ir(ctx, decisao.passo, decisao.rascunho)


def _ir(ctx: _Contexto, passo: str, rascunho: dict, prefixo: str | None = None) -> _Saida:
    opcoes, contexto, rascunho = _opcoes_do_passo(ctx, passo, rascunho)
    pulo = c.seguir_sozinho(passo, rascunho, opcoes)
    while pulo is not None:
        passo = pulo.passo
        opcoes, contexto, rascunho = _opcoes_do_passo(ctx, passo, pulo.rascunho)
        pulo = c.seguir_sozinho(passo, rascunho, opcoes)

    if passo != c.NOME and not opcoes:
        return _Saida("sem_opcoes", c.MENU, [msg_bot_sem_opcoes(passo=passo)])

    pergunta = msg_bot_pergunta(passo=passo, opcoes=opcoes, contexto=contexto)
    texto = f"{prefixo}\n\n{pergunta}" if prefixo else pergunta
    return _Saida("perguntou", passo, [texto], opcoes, rascunho, 0, pergunta)


def _opcoes_do_passo(ctx: _Contexto, passo: str, r: dict):
    """(opcoes, contexto do texto, rascunho). Os ids produzidos aqui sao os que
    `conversa._escolheu` entende — mudar um lado exige mudar o outro."""
    if passo == c.MENU:
        nome, marcados = _cliente_e_marcados(ctx)
        opcoes = [{
            "id": "marcar",
            "rotulo": "Marcar outro horário" if marcados else "Marcar horário",
        }]
        if len(marcados) == 1:
            opcoes.append({"id": f"cancelar:{marcados[0]['id']}", "rotulo": "Cancelar esse"})
        elif marcados:
            opcoes.append({"id": "cancelar", "rotulo": "Cancelar um deles"})
        contexto = {
            "barbearia_nome": ctx.barbearia.nome,
            "agendamentos": [m["rotulo"] for m in marcados],
        }
        return opcoes, contexto, {"cliente_nome": nome}

    if passo == c.SERVICO:
        itens = servicos_para_agendamento(ctx.bid)
        return [{"id": str(s["servico_id"]), "rotulo": s["servico__nome"]} for s in itens], {}, r

    if passo == c.BARBEIRO:
        with com_barbearia(ctx.bid):
            vinculos = list(
                BarbeiroServico.objects.filter(
                    servico_id=r["servico_id"], ativo=True,
                    barbeiro__ativo=True, servico__ativo=True,
                )
                .order_by("barbeiro__ordem", "barbeiro__nome")
                .values("barbeiro_id", "barbeiro__nome")
            )
        opcoes = [{"id": str(v["barbeiro_id"]), "rotulo": v["barbeiro__nome"]} for v in vinculos]
        if len(opcoes) > 1:
            opcoes.append({"id": QUALQUER, "rotulo": "Tanto faz"})
        return opcoes, {}, r

    if passo == c.DIA:
        de = r.get("de") or dia_de_hoje(ctx.agora)
        dias = dias_com_horarios(
            ctx.bid, r["barbeiro_id"], r["servico_id"], de, BOT_JANELA_DIAS, ctx.agora,
        )
        com_vaga = [d for d in dias if d["slots"]][: BOT_DIAS_OFERECIDOS + 1]
        opcoes = [{"id": d["data"], "rotulo": d["rotulo"]} for d in com_vaga[:BOT_DIAS_OFERECIDOS]]
        if len(com_vaga) > BOT_DIAS_OFERECIDOS:
            opcoes.append({
                "id": f"mais:{com_vaga[BOT_DIAS_OFERECIDOS]['data']}", "rotulo": "Outros dias",
            })
        return opcoes, {}, r

    if passo == c.HORA:
        [dia] = dias_com_horarios(ctx.bid, r["barbeiro_id"], r["servico_id"], r["dia"], 1, ctx.agora)
        slots = dia["slots"]
        if r.get("depois"):
            slots = [s for s in slots if formatar_instante_iso(s["inicio"]) > r["depois"]]
        mostrados = slots[:BOT_HORAS_OFERECIDAS]
        tanto_faz = r["barbeiro_id"] == QUALQUER
        opcoes = [
            {
                "id": f"{formatar_instante_iso(s['inicio'])}|{s['barbeiroId']}",
                "rotulo": rotulo_da_hora(
                    inicio=s["inicio"], barbeiro_nome=s["barbeiroNome"] if tanto_faz else None,
                ),
            }
            for s in mostrados
        ]
        if len(slots) > BOT_HORAS_OFERECIDAS:
            opcoes.append({
                "id": f"depois:{formatar_instante_iso(mostrados[-1]['inicio'])}",
                "rotulo": "Mais tarde",
            })
        opcoes.append({"id": "outro_dia", "rotulo": "Outro dia"})
        return opcoes, {"dia_rotulo": dia["rotulo"]}, r

    if passo == c.NOME:
        return [], {}, r

    if passo == c.CONFIRMA:
        with com_barbearia(ctx.bid):
            servico = Servico.objects.filter(id=r["servico_id"]).values_list("nome", flat=True).first()
            barbeiro = (
                Barbeiro.objects.filter(id=r["barbeiro_escolhido"])
                .values_list("nome", flat=True).first()
            )
        opcoes = [
            {"id": "confirmar", "rotulo": "Confirmar"},
            {"id": "recomecar", "rotulo": "Começar de novo"},
        ]
        contexto = {
            "servico_nome": servico or "",
            "barbeiro_nome": barbeiro or "",
            "inicio": datetime.fromisoformat(r["inicio"]),
        }
        return opcoes, contexto, r

    if passo == c.QUAL_AGENDAMENTO:
        _, marcados = _cliente_e_marcados(ctx)
        return marcados, {}, r

    if passo == c.CONFIRMA_CANCEL:
        a = _agendamento_do_numero(ctx, r["codigo"])
        if a is None:
            return [], {}, r
        opcoes = [{"id": "sim", "rotulo": "Sim, cancelar"}, {"id": "nao", "rotulo": "Não"}]
        rotulo = rotulo_do_agendamento(barbeiro_nome=a.barbeiro.nome, inicio=a.inicio)
        return opcoes, {"agendamento_rotulo": rotulo}, r

    raise ValueError(f"passo sem opcoes: {passo}")


def _cliente_do_numero(numero: str):
    """O `Cliente` deste numero em qualquer das formas gravadas (`8382217869`
    ou `83982217869`), preferindo a canonica. Chame DENTRO de `com_barbearia`.
    """
    formas = formas_gravadas(numero)
    por_forma = {cl.whatsapp: cl for cl in Cliente.objects.filter(whatsapp__in=formas)}
    return next((por_forma[f] for f in formas if f in por_forma), None)


def _cliente_e_marcados(ctx: _Contexto):
    with com_barbearia(ctx.bid):
        cliente = _cliente_do_numero(ctx.numero)
        if cliente is None:
            return None, []
        marcados = list(
            Agendamento.objects.filter(
                cliente__whatsapp__in=formas_gravadas(ctx.numero),
                status="CONFIRMADO", inicio__gt=ctx.agora,
            )
            .select_related("barbeiro")
            .order_by("inicio")[:BOT_HORAS_OFERECIDAS]
        )
    return cliente.nome, [
        {"id": a.codigo, "rotulo": rotulo_do_agendamento(barbeiro_nome=a.barbeiro.nome, inicio=a.inicio)}
        for a in marcados
    ]


def _agendamento_do_numero(ctx: _Contexto, codigo: str):
    """O horario so' e' deste numero se o CLIENTE dele tem este whatsapp (em
    qualquer das formas gravadas do mesmo celular). E' a unica barreira entre
    um codigo guardado e o horario de outra pessoa."""
    with com_barbearia(ctx.bid):
        return (
            Agendamento.objects.filter(
                codigo=codigo, status="CONFIRMADO",
                cliente__whatsapp__in=formas_gravadas(ctx.numero),
            )
            .select_related("barbeiro", "cliente")
            .first()
        )


def _marcar(ctx: _Contexto, r: dict) -> _Saida:
    nome = r.get("cliente_nome") or ""
    volta = {k: v for k, v in r.items() if k not in ("inicio", "barbeiro_escolhido", "depois")}
    # Cliente ja gravado com 10 digitos: `marcar` faz o upsert pelo whatsapp
    # EXATO, entao passar a forma gravada evita um `Cliente` duplicado.
    with com_barbearia(ctx.bid):
        existente = _cliente_do_numero(ctx.numero)
    whatsapp = existente.whatsapp if existente is not None else ctx.numero
    try:
        criado = marcar(
            barbearia_id=ctx.bid, barbeiro_id=r["barbeiro_escolhido"],
            servico_id=r["servico_id"], inicio=datetime.fromisoformat(r["inicio"]),
            nome=nome, whatsapp=whatsapp, agora=ctx.agora,
        )
    except ErroCliente as e:
        return _ir(ctx, c.HORA, volta, prefixo=e.mensagem)
    except IntegrityError as e:
        if not eh_sobreposicao(e):
            raise
        return _ir(ctx, c.HORA, volta, prefixo="Esse horário acabou de ser pego.")

    enviar_a_equipe_da(
        ctx.bid,
        criado["barbeiro_whatsapp"],
        msg_barbeiro_novo(
            cliente_nome=nome, servico_nome=criado["servico_nome"],
            inicio=criado["inicio"], agora=ctx.agora,
        ),
    )
    confirmacao = msg_confirmacao(
        cliente_nome=nome, barbeiro_nome=criado["barbeiro_nome"],
        servico_nome=criado["servico_nome"], inicio=criado["inicio"],
        endereco=ctx.barbearia.endereco,
        link=link_do_agendamento(ctx.barbearia.slug, criado["codigo"]),
    )
    return _Saida("marcou", c.MENU, [confirmacao])


def _cancelar(ctx: _Contexto, codigo: str) -> _Saida:
    if _agendamento_do_numero(ctx, codigo) is None:
        return _Saida("nao_e_seu", c.MENU, [msg_bot_nao_achei_agendamento()])
    resultado = cancelar_publico(ctx.bid, codigo, ctx.agora)
    if resultado["tipo"] == "fora_do_prazo":
        return _Saida("fora_do_prazo", c.MENU, [msg_bot_fora_do_prazo()])
    if resultado["tipo"] != "ok":
        return _Saida("nao_e_seu", c.MENU, [msg_bot_nao_achei_agendamento()])
    enviar_a_equipe_da(
        ctx.bid,
        resultado["barbeiro_whatsapp"],
        msg_barbeiro_cancelado(
            cliente_nome=resultado["cliente_nome"], servico_nome=resultado["servico_nome"],
            inicio=resultado["inicio"], agora=ctx.agora,
        ),
    )
    texto = msg_cancelamento(barbeiro_nome=resultado["barbeiro_nome"], inicio=resultado["inicio"])
    return _Saida("cancelou", c.MENU, [texto])


def _confirmar_lembrete(ctx: _Contexto, codigo: str) -> _Saida:
    """Mesma conferencia de `_nao_vou`: entre o lembrete e a resposta o
    horario pode ter sido desmarcado pelo painel, e opcao guardada nao e'
    autoridade — "Combinado" mandaria o cliente para uma cadeira que nao e'
    mais dele."""
    if _agendamento_do_numero(ctx, codigo) is None:
        return _Saida("nao_e_seu", c.MENU, [msg_bot_nao_achei_agendamento()])
    return _Saida("lembrete_confirmado", c.MENU, [msg_bot_lembrete_confirmado()])


def _nao_vou(ctx: _Contexto, codigo: str) -> _Saida:
    a = _agendamento_do_numero(ctx, codigo)
    if a is None:
        return _Saida("nao_e_seu", c.MENU, [msg_bot_nao_achei_agendamento()])
    enviar_a_equipe_da(
        ctx.bid,
        a.barbeiro.whatsapp,
        msg_barbeiro_desistiu(
            cliente_nome=a.cliente.nome, servico_nome=a.servico_nome,
            inicio=a.inicio, agora=ctx.agora,
        ),
    )
    return _Saida("desistencia_avisada", c.MENU, [msg_bot_desistencia_avisada()])


def _avisar_donos(ctx: _Contexto) -> None:
    with com_barbearia(ctx.bid):
        donos = list(
            Barbeiro.objects.filter(papel=PapelBarbeiro.DONO, ativo=True)
            .values_list("whatsapp", flat=True)
        )
        cliente = _cliente_do_numero(ctx.numero)
    nome = cliente.nome if cliente is not None else None
    texto = msg_bot_pediu_humano(cliente=nome or formatar(ctx.numero))
    for whatsapp in donos:
        enviar_a_equipe_da(ctx.bid, whatsapp, texto)


def silenciar(barbearia_id: str, numero: str, mensagem_id: str, agora: datetime) -> str:
    """Alguem da barbearia respondeu pelo celular: o bot fica quieto nessa
    conversa por BOT_MUDO_HORAS.

    Espera a MESMA trava da conversa. O eco de uma resposta do bot pode chegar
    ao webhook antes de `processar` gravar o id dela; esperando a trava, o id
    ja esta gravado quando esta funcao olha, e o bot nao se cala sozinho.

    Uma conversa presa alem do limite nao pode segurar o webhook: devolve
    "ignorado:trava" e segue.
    """
    try:
        with trava_da_conversa(barbearia_id, numero, espera_s=BOT_ESPERA_TRAVA_S):
            with com_barbearia(barbearia_id):
                linha = ConversaWhatsapp.objects.filter(whatsapp=numero).first()
                if linha is not None and mensagem_id in (linha.ids_do_bot or []):
                    return "eco"
                ate = agora + timedelta(hours=BOT_MUDO_HORAS)
                if linha is None:
                    ConversaWhatsapp.objects.create(
                        id=str(uuid.uuid4()), barbearia_id=barbearia_id, whatsapp=numero,
                        mudo_ate=ate, atualizado_em=agora,
                    )
                else:
                    ConversaWhatsapp.objects.filter(id=linha.id).update(mudo_ate=ate)
    except OperationalError:
        logger.warning(
            "[bot] silenciar travado (barbearia=%s, mensagem=%s)", barbearia_id, mensagem_id,
        )
        return "ignorado:trava"
    return "silenciado"


def enviar_lembrete_pelo_bot(
    barbearia_id: str, instancia_nome: str, numero: str, codigo: str,
    lembrete: str, agora: datetime,
) -> None:
    """O lembrete de sempre, com as respostas que o bot entende.

    Dentro da trava da conversa, pelas mesmas duas razoes de `silenciar`: nao
    atropelar uma conversa que acontece agora, e gravar o id do lembrete antes
    de o eco dele chegar — senao o bot se calaria justo quando o cliente vai
    responder.

    Conversa ocupada (escolhendo horario, ou muda porque alguem da barbearia
    esta falando) recebe o lembrete SEM opcoes, e o estado dela fica.

    `numero` e' o gravado em `Cliente.whatsapp`, que pode ter 10 digitos; a
    resposta chega com 11 (`do_jid`). Conversa, trava e envio usam a forma
    canonica, ou o "1" do cliente cairia numa conversa vazia.
    """
    numero = nacional_canonico(numero)
    enviado = False
    try:
        with trava_da_conversa(barbearia_id, numero, espera_s=BOT_ESPERA_TRAVA_S):
            linha = _conversa(barbearia_id, numero)
            ocupada = linha is not None and (
                (linha.mudo_ate is not None and como_utc(linha.mudo_ate) > agora)
                or (bool(linha.opcoes) and not c.expirou(_estado_de(linha), agora))
            )
            texto = lembrete if ocupada else msg_lembrete_com_opcoes(lembrete=lembrete)
            mensagem_id = _enviar(instancia_nome, numero, texto)
            enviado = True
            _registrar_lembrete(
                barbearia_id, numero, linha, mensagem_id, None if ocupada else codigo, agora,
            )
    except OperationalError:
        if enviado:
            logger.error(
                "[bot] lembrete de %s saiu, mas a conversa nao foi gravada (agendamento=%s)",
                barbearia_id, codigo,
            )
            return
        logger.warning(
            "[bot] conversa de %s presa: lembrete sai sem opcoes (agendamento=%s)",
            barbearia_id, codigo,
        )
        _enviar(instancia_nome, numero, lembrete)


def _registrar_lembrete(barbearia_id, numero, linha, mensagem_id, codigo, agora) -> None:
    """Grava o id do lembrete e, se ele tinha opcoes (`codigo` presente), o
    estado `AGUARDANDO_LEMBRETE`.

    Se `_enviar` nao devolveu id, a mensagem nao chegou ao cliente — nao ha
    opcoes na tela dele para responder, e avancar o estado aqui deixaria a
    conversa esperando um "1"/"2" que nunca vai fazer sentido (mesma regra de
    `_gravar`, Tarefa 6: sem entrega, o estado nao avanca). Sem id e sem linha
    anterior tambem nao ha o que gravar.
    """
    if not mensagem_id:
        return
    ids = list(linha.ids_do_bot or []) if linha is not None else []
    ids = (ids + [mensagem_id])[-BOT_IDS_GUARDADOS:]
    campos = {"ids_do_bot": ids}
    if codigo is not None:
        campos.update(
            estado=c.AGUARDANDO_LEMBRETE,
            opcoes=[
                {"id": f"confirmar:{codigo}", "rotulo": "Confirmar"},
                {"id": f"nao_vou:{codigo}", "rotulo": "Não vou conseguir ir"},
            ],
            rascunho={}, tentativas=0,
            pergunta=msg_bot_pergunta_do_lembrete(),
            atualizado_em=agora,
        )
    with com_barbearia(barbearia_id):
        if linha is None:
            ConversaWhatsapp.objects.create(
                id=str(uuid.uuid4()), barbearia_id=barbearia_id, whatsapp=numero, **campos,
            )
        else:
            ConversaWhatsapp.objects.filter(id=linha.id).update(**campos)
