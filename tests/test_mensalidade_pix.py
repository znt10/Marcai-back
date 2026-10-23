import uuid
from decimal import Decimal

from app.services.mensalidade.pix import (
    copia_e_cola,
    crc16,
    identificador,
    qr_svg,
)


def campos(texto):
    """Le o TLV do BR Code: ID de 2, tamanho de 2, valor."""
    lidos, i = {}, 0
    while i < len(texto):
        id_, tamanho = texto[i:i + 2], int(texto[i + 2:i + 4])
        lidos[id_] = texto[i + 4:i + 4 + tamanho]
        i += 4 + tamanho
    return lidos


def gerar(**mudanca):
    dados = {
        "chave": "+5511999998888",
        "nome": "Maria da Silva",
        "cidade": "Patos",
        "valor": Decimal("100.00"),
        "identificador": "MC123",
    }
    dados.update(mudanca)
    return copia_e_cola(**dados)


def test_crc16_valor_de_verificacao_padrao():
    # CRC-16/CCITT-FALSE de "123456789" e 0x29B1 em toda implementacao.
    assert crc16("123456789") == "29B1"


def test_campos_no_lugar_certo():
    lido = campos(gerar())

    assert lido["00"] == "01"
    assert campos(lido["26"]) == {"00": "br.gov.bcb.pix", "01": "+5511999998888"}
    assert lido["52"] == "0000"
    assert lido["53"] == "986"
    assert lido["54"] == "100.00"
    assert lido["58"] == "BR"
    assert lido["59"] == "MARIA DA SILVA"
    assert lido["60"] == "Patos"
    assert campos(lido["62"]) == {"05": "MC123"}


def test_termina_com_o_crc_do_que_vem_antes():
    texto = gerar()
    assert texto[:-4].endswith("6304")
    assert texto[-4:] == crc16(texto[:-4])


def test_centavos():
    assert campos(gerar(valor=Decimal("0.01")))["54"] == "0.01"
    assert campos(gerar(valor=Decimal("99.9")))["54"] == "99.90"


def test_nome_e_cidade_com_acento_e_compridos():
    lido = campos(gerar(
        nome="José Cícero da Silva Neto Júnior",
        cidade="São José do Rio Preto",
    ))
    assert lido["59"] == "JOSE CICERO DA SILVA NETO"
    assert lido["60"] == "Sao Jose do Rio"


def test_identificador_so_letras_e_numeros_ate_25():
    ident = identificador(uuid.UUID("12345678-1234-5678-1234-567812345678"))
    assert ident == "MC12345678123456781234567"
    assert len(ident) <= 25
    assert ident.isalnum()


def test_identificador_vem_em_maiuscula():
    ident = identificador(uuid.UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"))
    assert ident == ident.upper()
    assert ident.startswith("MCABCDEFABCDEF")


def test_qr_devolve_um_svg_pronto_para_img():
    assert qr_svg(gerar()).startswith("data:image/svg+xml")


def test_normalizar_chave_tira_espaco_e_caixa():
    from app.services.mensalidade.pix import normalizar_chave

    assert normalizar_chave("  Dono@Marcai.COM ") == "dono@marcai.com"
    assert normalizar_chave("1234 5678-aBcD") == "12345678-abcd"
    assert normalizar_chave("") == ""
