"""As transicoes de estado da instancia, num lugar so.

Duas coisas escrevem esse estado: o webhook (instantaneo) e a conferencia
periodica (rede de seguranca). Escrever as regras duas vezes seria ter duas
regras — e o modo de falha e cruel, porque as duas so divergem quando o
webhook se perde, que e justamente quando ninguem esta olhando. Por isso o
webhook e a tarefa entram pelas MESMAS funcoes daqui.

Toda escrita acontece dentro de `com_barbearia`: o nome da instancia chega da
rede, e o que se faz com ele e uma escrita em tabela de tenant.
"""

import logging

from django.utils import timezone

from tenant.models import EstadoInstancia, WhatsappInstancia
from tenant.rls import com_barbearia
from tenant.telefone import canonico

from .whatsapp_instancias import barbearia_id_do_nome, consultar_dono

logger = logging.getLogger(__name__)

# Os nomes como eles CHEGAM, e nao como sao assinados. A assinatura pede
# `CONNECTION_UPDATE` e `QRCODE_UPDATED`; o corpo traz `connection.update` e
# `qrcode.updated`. Medido na 2.3.7 (fatia 0) — casar com a forma assinada
# faria todo evento ser ignorado em silencio, com a instancia conectando de
# verdade e o painel jurando que nao.
EVENTO_CONEXAO = "connection.update"
EVENTO_QR = "qrcode.updated"


def _linha(barbearia_id, nome):
    with com_barbearia(barbearia_id):
        return WhatsappInstancia.objects.filter(
            barbearia_id=barbearia_id, nome=nome
        ).first()


def _gravar(barbearia_id, nome, **campos) -> None:
    with com_barbearia(barbearia_id):
        WhatsappInstancia.objects.filter(barbearia_id=barbearia_id, nome=nome).update(
            atualizado_em=timezone.now(), **campos
        )


def marcar_conectado(barbearia_id, nome, numero: str | None) -> None:
    """O QR e a hora da queda sao LIMPOS junto. Um QR guardado depois de
    conectar e um codigo morto que alguem ainda vai tentar escanear; uma hora
    de queda que sobra faz a faixa do painel continuar contando um tempo que
    acabou."""
    _gravar(
        barbearia_id, nome,
        estado=EstadoInstancia.CONECTADO,
        numero_conectado=numero,
        qr_base64=None,
        desconectado_desde=None,
    )


def marcar_desconectado(barbearia_id, nome, estado_atual: str) -> None:
    """`desconectado_desde` so na TRANSICAO. A Evolution repete `close` a cada
    tentativa de reconexao, e a conferencia periodica passa a cada cinco
    minutos: reescrever a hora em todo evento faria o painel dizer "desde
    agora" para sempre, que e' exatamente a informacao que o dono precisa e
    nao teria."""
    campos = {"estado": EstadoInstancia.DESCONECTADO, "qr_base64": None}
    if estado_atual != EstadoInstancia.DESCONECTADO:
        campos["desconectado_desde"] = timezone.now()
    _gravar(barbearia_id, nome, **campos)


def marcar_qr(barbearia_id, nome, base64: str) -> None:
    _gravar(barbearia_id, nome, estado=EstadoInstancia.AGUARDANDO_QR, qr_base64=base64)


def marcar_pendente(barbearia_id, nome) -> None:
    """A instancia sumiu do lado de la. `PENDENTE` e o unico estado que faz a
    conferencia periodica recria-la."""
    _gravar(
        barbearia_id, nome,
        estado=EstadoInstancia.PENDENTE, qr_base64=None, numero_conectado=None,
    )


def aplicar_estado(barbearia_id, linha, estado: str | None) -> bool:
    """A ponte da conferencia periodica: um estado lido da Evolution vira a
    mesma transicao que o webhook faria.

    `None` quer dizer "nao sei" (rede fora, resposta estranha, `connecting`) e
    nao muda nada — indisponibilidade nao e' resposta. Devolve se mexeu.
    """
    if estado is None:
        return False

    if estado == EstadoInstancia.CONECTADO:
        # O numero vem da Evolution a cada conferencia, e nao da linha. Reusar
        # o `numero_conectado` guardado era o bug: quando o `open` do celular
        # novo se perdia, a conferencia regravava o numero do ANTERIOR, e o
        # "estado igual, nao mexe" o mantinha ali para sempre. Sem resposta
        # (rede fora) fica o que ja estava — indisponibilidade nao e' resposta.
        numero = _numero_do_jid(consultar_dono(linha.nome)) or linha.numero_conectado
        if linha.estado == EstadoInstancia.CONECTADO and numero == linha.numero_conectado:
            return False
        marcar_conectado(barbearia_id, linha.nome, numero)
        return True

    if estado == linha.estado:
        return False
    if estado == EstadoInstancia.DESCONECTADO:
        marcar_desconectado(barbearia_id, linha.nome, linha.estado)
    elif estado == EstadoInstancia.PENDENTE:
        marcar_pendente(barbearia_id, linha.nome)
    else:
        return False
    return True


def _numero_do_jid(bruto) -> str | None:
    """`558399990000@s.whatsapp.net` -> `83999990000`: a forma nacional
    canonica, a mesma de `Barbeiro.whatsapp`. Guardar o JID cru fazia o painel
    mostrar a conta antiga sem o nono digito — um numero que o dono nao
    reconhece — e impedia comparar com o cadastro da equipe. Numero de fora do
    Brasil fica nos digitos crus: o painel ainda consegue mostra-lo."""
    if not isinstance(bruto, str) or not bruto:
        return None
    return canonico(bruto) or bruto.split("@")[0] or None


def _numero_do_wuid(data: dict) -> str | None:
    """`5583999990000@s.whatsapp.net` -> `83999990000` (ver `_numero_do_jid`).

    Este e o UNICO campo do webhook que a fatia 0 nao conseguiu medir: o
    `open` so acontece com um celular de verdade escaneando o QR. Por isso a
    leitura e tolerante — ausente, vazio ou de outro tipo devolve `None`, e o
    estado da conexao (que e' o que decide se a mensagem sai) nao depende
    disto.
    """
    return _numero_do_jid(data.get("wuid"))


def aplicar_evento(corpo: dict) -> str:
    """O que o webhook faz com um corpo cru. Devolve um rotulo so' para o log
    e para o teste; a resposta HTTP e' sempre 200.

    Nada aqui levanta, e toda saida e' "ignorei": a Evolution REENVIA o que
    nao foi aceito, entao um corpo estranho que virasse 500 voltaria em laco.
    """
    if not isinstance(corpo, dict):
        return "ignorado"

    nome = corpo.get("instance")
    if not isinstance(nome, str):
        return "ignorado"

    barbearia_id = barbearia_id_do_nome(nome)
    if barbearia_id is None:
        return "ignorado"

    evento = str(corpo.get("event") or "").lower()
    if evento not in (EVENTO_CONEXAO, EVENTO_QR):
        return "ignorado"

    linha = _linha(barbearia_id, nome)
    if linha is None:
        # Instancia de uma barbearia que saiu do plano (ou que nunca foi
        # nossa). Sem log de erro: isto acontece de verdade na janela entre o
        # `delete` na Evolution e o ultimo evento em voo.
        return "ignorado"

    data = corpo.get("data")
    if not isinstance(data, dict):
        return "ignorado"

    if evento == EVENTO_QR:
        base64 = (data.get("qrcode") or {}).get("base64")
        if not isinstance(base64, str) or not base64:
            # Um evento de QR sem base64 (por exemplo quando a Evolution
            # bate o limite de QRs) nao traz codigo novo. Ignorar em silencio
            # deixaria o painel preso no QR anterior, que ja morreu, e o dono
            # nunca conseguiria reconectar depois de "Trocar de celular".
            # Limpar o campo faz o proximo `ver()` pedir um QR novo de
            # verdade via `pedir_qr`. (A assinatura pede `base64: true`
            # sempre, com ou sem bot.)
            _gravar(barbearia_id, nome, qr_base64=None)
            return "qr_sem_base64"
        marcar_qr(barbearia_id, nome, base64)
        return "qr"

    estado = str(data.get("state") or "").lower()
    if estado == "open":
        marcar_conectado(barbearia_id, nome, _numero_do_wuid(data))
        return "conectado"
    if estado in ("close", "refused"):
        marcar_desconectado(barbearia_id, nome, linha.estado)
        return "desconectado"
    # `connecting` e qualquer coisa que a Evolution invente depois: nao muda
    # nada. Ver o comentario de `consultar_estado`.
    return "ignorado"
