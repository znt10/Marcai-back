"""Os parametros dos templates proprios da Meta (03/11), na ordem das
variaveis de cada um. O texto fixo mora no template, aprovado na WABA:

- `marcai_confirmado` (`META_TEMPLATE_CONFIRMACAO`):
  "Seu horário na {{1}} está confirmado:\\n{{2}}\\n\\nDúvida? Chama: {{3}}\\n\\n
  Se precisar cancelar: {{4}}\\n\\nAté lá!" + botao "Quero lembrete 1h antes".
- `marcai_lembrete_1h` (`META_TEMPLATE_LEMBRETE`):
  "Lembrete do seu horário na {{1}}:\\n{{2}} hoje às {{3}}, com {{4}}.\\n
  Endereço: {{5}}\\n\\nCaso não possa ir, chama: {{6}}\\n\\nEste número só envia avisos."
- `marcai_cancelado` (`META_TEMPLATE_CANCELADO`):
  "Oi, {{1}}. A {{2}} cancelou seu {{3}} de {{4}} às {{5}}. Desculpa!\\n\\n
  Pra remarcar, chama: {{6}}\\n\\nAté a próxima!"

Mudar o texto de um template na Meta sem mudar aqui (ou o contrario)
desalinha as variaveis: e' a mesma mensagem nos dois lugares.
"""

from tenant.datas import formatar_dia_com_semana, formatar_hora_falada
from tenant.telefone import formatar

from .mensagens import _capitalizar
from .whatsapp_meta import Modelo

PREFIXO_DO_BOTAO = "lembrete:"


def _contato(contato: str | None) -> str:
    return formatar(contato) if contato else ""


def confirmacao(
    *, cliente_nome: str, barbeiro_nome: str, servico_nome: str, inicio, link: str,
    barbearia_nome: str, contato: str | None, codigo: str,
) -> Modelo:
    """A confirmacao do PAINEL com o botao do lembrete por toque: o toque
    volta no webhook com `lembrete:<codigo>`."""
    frase = (
        f"Fechou, {cliente_nome.split(' ')[0]}! {_capitalizar(servico_nome)} "
        f"{formatar_dia_com_semana(inicio)} às {formatar_hora_falada(inicio)}, "
        f"com {barbeiro_nome}."
    )
    return Modelo(
        "META_TEMPLATE_CONFIRMACAO",
        [barbearia_nome, frase, _contato(contato), link],
        payload=f"{PREFIXO_DO_BOTAO}{codigo}",
    )


def lembrete(
    *, servico_nome: str, barbeiro_nome: str, inicio, endereco: str,
    barbearia_nome: str, contato: str | None,
) -> Modelo:
    return Modelo("META_TEMPLATE_LEMBRETE", [
        barbearia_nome, _capitalizar(servico_nome), formatar_hora_falada(inicio),
        barbeiro_nome, endereco, _contato(contato),
    ])


def cancelado(
    *, cliente_nome: str, servico_nome: str, inicio, barbearia_nome: str, contato: str | None,
) -> Modelo:
    """O cancelamento PELA barbearia (painel e bloqueio)."""
    return Modelo("META_TEMPLATE_CANCELADO", [
        cliente_nome.split(" ")[0], barbearia_nome, servico_nome.lower(),
        formatar_dia_com_semana(inicio), formatar_hora_falada(inicio), _contato(contato),
    ])
