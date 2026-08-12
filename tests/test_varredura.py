import ast
import pathlib

# Models sujeitos ao RLS. `Barbearia` fica de fora de proposito: ela e lida
# antes de existir tenant, e por isso e protegida por GRANT, nao por politica.
MODELS_DE_TENANT = {"Barbeiro", "Servico", "BarbeiroServico", "HorarioTrabalho",
                    "Bloqueio", "Cliente", "Agendamento"}

# Arquivos que podem consultar sem o wrapper, com o motivo:
# - rls.py       e o proprio wrapper: o cur.execute(set_config(...)) que ele
#                 faz por dentro e o unico execute() legitimo fora do
#                 com_barbearia, porque e ELE quem entra no tenant
# - models.py    so declara, nunca consulta
# - __init__.py  fica vazio por convencao de pacote Python; nunca teve motivo
#                 para ganhar uma consulta e nao deveria comecar a ter
ISENTOS = {"rls.py", "models.py", "__init__.py"}

RAIZ = pathlib.Path(__file__).resolve().parent.parent / "backend" / "tenant"


def _nome_do_model(no: ast.AST) -> str | None:
    """Reduz o lado esquerdo de um `<no>.objects` ao nome final, cobrindo
    tanto `Barbeiro` (Name direto) quanto `models.Barbeiro` (Attribute
    qualificado — o caso comum quando o modulo importa `models` inteiro em
    vez do nome do model). Em ambos os casos o que importa e o ULTIMO
    segmento; `pacote.models.Barbeiro` tambem cai aqui pelo mesmo motivo.

    Nao resolve apelido de import (`as B`) nem reatribuicao (`Modelo =
    Barbeiro`): as duas exigiriam seguir fluxo de dados, nao so a forma da
    arvore, e virariam heuristica fragil. Ficam como limite documentado no
    docstring do teste, nao como bug aqui.
    """
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        return no.attr
    return None


def _dentro_do_wrapper(arvore: ast.AST) -> set[int]:
    """Linhas cobertas por um `with com_barbearia(...)`."""
    cobertas: set[int] = set()
    for no in ast.walk(arvore):
        if not isinstance(no, ast.With):
            continue
        chama_wrapper = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "com_barbearia"
            for item in no.items
        )
        if chama_wrapper:
            for filho in ast.walk(no):
                if hasattr(filho, "lineno"):
                    cobertas.add(filho.lineno)
    return cobertas


def _consultas_de_tenant(caminho: pathlib.Path) -> list[str]:
    """Acha `Model.objects` e `modulo.Model.objects` para qualquer model de
    tenant."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    cobertas = _dentro_do_wrapper(arvore)
    achados = []
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Attribute) and no.attr == "objects"):
            continue
        nome = _nome_do_model(no.value)
        if nome in MODELS_DE_TENANT and no.lineno not in cobertas:
            achados.append(f"{caminho.name}:{no.lineno} {nome}.objects")
    return achados


def _sql_cru(caminho: pathlib.Path) -> list[str]:
    """Acha `.execute(...)` — cursor.execute, connection.cursor().execute e
    afins. SQL cru fala direto com o Postgres sem passar por nenhum model,
    entao `_consultas_de_tenant` (que so olha `Model.objects`) e cego a ele;
    esta e a unica rede para esse caminho. Nao distingue SELECT de DDL nem
    olha o texto do SQL — qualquer `.execute(` fora de rls.py e motivo pra
    revisar, porque o unico lugar com licenca pra fazer isso sem o wrapper
    e o proprio wrapper.
    """
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    achados = []
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "execute"
        ):
            achados.append(f"{caminho.name}:{no.lineno} .execute(...)")
    return achados


def test_nenhuma_consulta_de_tenant_fora_do_wrapper():
    """Rede contra o esquecimento comum de deixar uma consulta de tenant fora
    do com_barbearia() — NAO e prova de isolamento. Quem prova isolamento e o
    RLS no banco (ver tests/test_rls.py); esta varredura so pega os jeitos
    mais diretos de escapar do wrapper por acidente:

      - `Barbeiro.objects...`         (Name direto)
      - `models.Barbeiro.objects...`  (Attribute qualificado — importar o
        modulo `models` inteiro e Django idiomatico comum, entao isto
        importa tanto quanto o caso direto)
      - qualquer `.execute(...)` fora de rls.py (SQL cru via cursor,
        invisivel para as duas formas acima porque nao passa por model
        nenhum)

    Varre backend/tenant/ inteiro, subpastas inclusive (rglob, nao glob).

    O que ela NAO pega, de proposito — indecidivel sem seguir o fluxo de
    dados, e uma tentativa de fechar viraria heuristica fragil, entao fica
    como limite documentado em vez de falsa promessa:

      - apelido de import:  `from .models import Barbeiro as B; B.objects`
      - reatribuicao:       `Modelo = Barbeiro; Modelo.objects`
      - `apps.get_model('tenant', 'Barbeiro').objects` (o `.value` de
        `.objects` aqui e uma Call, nao um Name/Attribute — a arvore nao
        guarda mais o nome do model depois disso)
      - qualquer uso de um model de tenant fora de backend/tenant/ — a
        varredura nunca olha para outro app Django

    Se ela falhar num arquivo novo e legitimo, a resposta certa quase nunca e
    acrescentar o arquivo a ISENTOS — e envolver a consulta no wrapper.
    """
    fora = []
    for arquivo in RAIZ.rglob("*.py"):
        if arquivo.name in ISENTOS:
            continue
        fora.extend(_consultas_de_tenant(arquivo))
        fora.extend(_sql_cru(arquivo))

    assert fora == [], (
        "consulta a model de tenant fora do com_barbearia():\n  "
        + "\n  ".join(fora)
    )
