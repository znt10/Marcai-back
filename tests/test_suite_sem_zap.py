"""A suite nunca fala com o WhatsApp de verdade.

O `.env` de quem desenvolve aponta `EVOLUTION_API_URL` para a Evolution do
compose, conectada a um chip de verdade, e tem o numero do Jose em
`MENSALIDADE_WHATSAPP_AVISO`. Em 03/11 cada rodada da suite mandou uns seis
"avisou que pagou a mensalidade" para ele.
"""

import os


def test_suite_nao_enxerga_a_evolution_do_ambiente():
    assert "EVOLUTION_API_URL" not in os.environ
