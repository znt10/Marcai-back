"""A lista de horarios que cada barbeiro recebe as 07:00.

E a mensagem que faz o plano SEM ZAP valer alguma coisa: naquele plano o
cliente nao recebe nada, e sem isto o barbeiro tambem nao — ele so saberia da
agenda abrindo o painel. Por isso ela sai nos DOIS planos.

Por qual numero, quem decide e' `enviar_a_equipe_da`: com zap e aparelho
conectado, pelo numero da propria barbearia, que e' o que os barbeiros ja tem
salvo — e uma queda do central nao deixa a equipe sem lista. Sem zap, ou com o
aparelho fora, pelo central.

Duas regras que foram decididas e que o codigo aqui so obedece:

- **Cada um recebe so os proprios horarios, o dono inclusive.** O dono ja ve a
  agenda inteira no painel; receber por WhatsApp a agenda de todo mundo todo
  dia as sete da manha e ruido, nao servico.
- **Dia vazio nao manda nada.** "Voce nao tem horario hoje" e uma mensagem que
  so serve para a pessoa aprender a ignorar as mensagens seguintes.
"""

import logging
from datetime import datetime

from tenant.datas import dia_de_hoje, local_para_utc
from tenant.models import Agendamento, Barbearia, StatusAgendamento
from tenant.rls import com_barbearia

from .mensagens import msg_lista_do_dia
from .whatsapp import enviar_a_equipe_da

logger = logging.getLogger(__name__)


def enviar(agora: datetime) -> int:
    """Devolve quantos barbeiros receberam. `agora` entra por parametro (e nao
    sai de um `now()` la dentro) pelo mesmo motivo de `enviar_pendentes`: hora
    e a variavel que mais precisa ser fixada no teste.

    O dia e' recortado no fuso de Sao Paulo, e nao em UTC. As 07:00 daqui sao
    10:00 UTC — um recorte em UTC pegaria de 21:00 de ontem ate 21:00 de hoje
    e a lista sairia com os horarios da noite anterior dentro.
    """
    hoje = dia_de_hoje(agora)
    inicio_do_dia = local_para_utc(hoje, 0)
    fim_do_dia = local_para_utc(hoje, 24 * 60)
    enviados = 0

    for b in Barbearia.objects.filter(ativo=True):
        with com_barbearia(b.id):
            agendamentos = list(
                Agendamento.objects.filter(
                    status=StatusAgendamento.CONFIRMADO,
                    inicio__gte=inicio_do_dia,
                    inicio__lt=fim_do_dia,
                    barbeiro__ativo=True,
                )
                .select_related("barbeiro", "cliente")
                .order_by("inicio")
            )

        por_barbeiro: dict = {}
        for a in agendamentos:
            por_barbeiro.setdefault(a.barbeiro_id, []).append(a)

        # Quem nao tem horario nao aparece neste dicionario, e e assim que
        # "dia vazio nao manda nada" acontece: pela ausencia, sem um `if` que
        # alguem possa inverter sem querer.
        for agendamentos_do_barbeiro in por_barbeiro.values():
            barbeiro = agendamentos_do_barbeiro[0].barbeiro
            enviar_a_equipe_da(
                b.id,
                barbeiro.whatsapp,
                msg_lista_do_dia(
                    barbeiro_nome=barbeiro.nome,
                    agendamentos=[
                        {
                            "cliente_nome": a.cliente.nome,
                            "servico_nome": a.servico_nome,
                            "inicio": a.inicio,
                        }
                        for a in agendamentos_do_barbeiro
                    ],
                    agora=agora,
                ),
            )
            enviados += 1

    return enviados
