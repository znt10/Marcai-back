import ast
import pathlib

# Models sujeitos ao RLS. `Barbearia` fica de fora de proposito: ela e lida
# antes de existir tenant, e por isso e protegida por GRANT, nao por politica.
MODELS_DE_TENANT = {"Barbeiro", "Servico", "BarbeiroServico", "HorarioTrabalho",
                    "Bloqueio", "Cliente", "Agendamento"}

# Arquivos que podem consultar sem o wrapper, com o motivo:
# - rls.py     e o proprio wrapper
# - models.py  so declara
ISENTOS = {"rls.py", "models.py", "__init__.py"}

RAIZ = pathlib.Path(__file__).resolve().parent.parent / "backend" / "tenant"


def _consultas_de_tenant(caminho: pathlib.Path) -> list[str]:
    """Acha `Model.objects` para qualquer model de tenant."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    achados = []
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Attribute)
            and no.attr == "objects"
            and isinstance(no.value, ast.Name)
            and no.value.id in MODELS_DE_TENANT
        ):
            achados.append(f"{caminho.name}:{no.lineno} {no.value.id}.objects")
    return achados


def test_nenhuma_consulta_de_tenant_fora_do_wrapper():
    """A garantia de isolamento vale exatamente enquanto TODA consulta passar
    pelo com_barbearia(). Este teste e o que impede a proxima fatia de abrir um
    caminho lateral sem ninguem perceber.

    Se ele falhar num arquivo novo e legitimo, a resposta certa quase nunca e
    acrescentar o arquivo a ISENTOS — e envolver a consulta no wrapper.
    """
    fora = []
    for arquivo in RAIZ.glob("*.py"):
        if arquivo.name in ISENTOS:
            continue
        fora.extend(_consultas_de_tenant(arquivo))

    assert fora == [], (
        "consulta a model de tenant fora do com_barbearia():\n  "
        + "\n  ".join(fora)
    )
