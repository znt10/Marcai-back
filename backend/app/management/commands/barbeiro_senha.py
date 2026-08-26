from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from app.services.senha import gerar
from app.services.trava_barbeiro import LIMPO
from tenant.config import SENHA_MINIMA
from tenant.models import Barbeiro
from tenant.telefone import formatar, normalizar


class Command(BaseCommand):
    """Porta de `scripts/barbeiro-senha.ts`, apagado na fatia 8.

    A saida de emergencia do painel: define a senha de um barbeiro direto pelo
    banco e destrava a conta.

    Existe porque **reemitir convite apaga a senha** (`senha_hash` volta a
    nulo, que e' o reset de senha do produto) e o token do convite so' existe
    em HASH no banco. Perdido o link, nao ha caminho de volta pela tela — e se
    isso acontecer com o ultimo dono ativo, a barbearia fica sem ninguem que
    consiga entrar. Nenhuma tela pode resolver isso sem virar ela mesma um
    jeito de entrar sem credencial.

    Roda pela conexao `owner`, como o `semear`: a busca e' por WHATSAPP, sem
    barbearia_id conhecido de antemao, entao nao ha como abrir um
    `com_barbearia` primeiro — e' exatamente o caso que a politica
    `owner_irrestrito` existe para servir.
    """

    help = (
        "Troca a senha de um barbeiro pelo WhatsApp, ou so' destrava a conta, "
        "direto pelo banco."
    )

    def add_arguments(self, parser):
        parser.add_argument("whatsapp", help="O WhatsApp do barbeiro (com ou sem formatação).")
        parser.add_argument(
            "senha", nargs="?", default=None,
            help="A nova senha. Omitir e usar --destravar em vez dela.",
        )
        parser.add_argument(
            "--destravar", action="store_true",
            help="So' zera tentativas de login e bloqueio, sem tocar na senha.",
        )

    def handle(self, *args, **opcoes):
        whatsapp = normalizar(opcoes["whatsapp"])
        if whatsapp is None:
            raise CommandError(f'"{opcoes["whatsapp"]}" não é um WhatsApp brasileiro válido.')

        so_destravar = opcoes["destravar"]
        senha = opcoes["senha"]
        if so_destravar and senha is not None:
            raise CommandError("Não passe senha junto com --destravar.")
        if not so_destravar and senha is None:
            raise CommandError(
                'Passe a senha, ou use --destravar para só destravar.\n'
                "Uso:\n"
                '  manage.py barbeiro_senha 11911112222 "uma senha longa"\n'
                "  manage.py barbeiro_senha 11911112222 --destravar"
            )
        if not so_destravar and len(senha) < SENHA_MINIMA:
            raise CommandError(f"A senha precisa de ao menos {SENHA_MINIMA} caracteres.")

        # `owner`, dos dois lados (leitura e escrita): o RLS filtraria a busca
        # pelo tenant errado se essa conexao passasse por ele, e aqui ainda
        # nao ha barbearia_id nenhum para escopar — e' a mesma pergunta que o
        # `findMany` sem tenant do script antigo fazia.
        achados = list(
            Barbeiro.objects.using("owner")
            .filter(whatsapp=whatsapp)
            .select_related("barbearia")
        )

        if not achados:
            raise CommandError(f"Nenhum barbeiro com {formatar(whatsapp)}.")

        # O celular e' unico POR BARBEARIA, nao globalmente: a mesma pessoa
        # pode trabalhar em duas casas. Trocar a senha das duas em silencio
        # seria errado.
        if len(achados) > 1:
            listagem = "\n".join(f"  - {b.barbearia.slug} ({b.nome})" for b in achados)
            raise CommandError(
                f"{formatar(whatsapp)} existe em mais de uma barbearia:\n{listagem}\n"
                "Este comando não escolhe por você. Resolva pelo tenant certo."
            )

        barbeiro = achados[0]

        # Incrementar o token_version derruba toda sessao daquela pessoa na
        # hora. E' o ponto: se a senha esta sendo trocada por perda de
        # acesso, quem estava dentro com o token antigo sai.
        atualizacao = dict(LIMPO)
        if not so_destravar:
            atualizacao.update(
                senha_hash=gerar(senha),
                convite_token_hash=None,
                convite_expira_em=None,
                token_version=F("token_version") + 1,
            )

        Barbeiro.objects.using("owner").filter(id=barbeiro.id).update(**atualizacao)

        acao = "destravado" if so_destravar else "senha trocada e conta destravada"
        self.stdout.write(
            f"{barbeiro.nome} ({barbeiro.papel.lower()}) na {barbeiro.barbearia.nome}: {acao}."
        )
        if not so_destravar:
            self.stdout.write("As sessões antigas dele foram derrubadas.")
        if not barbeiro.ativo:
            self.stdout.write("ATENÇÃO: este barbeiro está DESATIVADO — ele ainda não entra.")
