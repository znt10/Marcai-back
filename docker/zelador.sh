#!/bin/sh
# Zelador do histórico da Evolution: alarma envio recusado e poda o que
# envelhece. Roda no contêiner `zelador` do docker-compose, de hora em hora.
#
# Mora num arquivo, e não numa linha de `command:` no compose, porque SQL com
# aspas dentro de YAML dentro de shell é ilegível — e a primeira tentativa
# quebrou o parser do compose em silêncio até o `docker compose config` reclamar.

set -u

DIAS_DE_HISTORICO=7
INTERVALO_SEGUNDOS=3600

consultar() {
  psql -h db -U evolution -d evolution -qtAc "$1"
}

while true; do
  # O WhatsApp rejeita de forma ASSÍNCRONA: quando a recusa chega, a Evolution
  # já devolveu 201 ao app e ninguém mais está olhando. `status = 'ERROR'` é o
  # único registro de que a mensagem não foi entregue.
  #
  # Em 10/08 a falta desse alarme custou horas: log limpo dos dois lados,
  # instância `open`, soquete respondendo, e nenhuma mensagem chegando.
  recusados=$(consultar "SELECT count(*) FROM \"MessageUpdate\" WHERE status = 'ERROR';" 2>/dev/null || echo erro)

  if [ "$recusados" = "erro" ]; then
    echo "[zelador] não consegui falar com o banco"
  elif [ "$recusados" = "0" ]; then
    echo "[zelador] nenhum envio recusado"
  else
    echo "[zelador] !!! $recusados ENVIO(S) RECUSADO(S) PELO WHATSAPP"
    echo "[zelador]     o vínculo aceita e não transmite — confira Aparelhos conectados no celular"
    echo "[zelador]     e depois: npm run whatsapp:qr"
  fi

  # A poda existe porque o rastreio de status EXIGE guardar o texto que nós
  # mandamos: medido em 10/08 — com `DATABASE_SAVE_DATA_NEW_MESSAGE=false`, a
  # `MessageUpdate` fica vazia também. Não existe "só o status", então o
  # histórico não pode crescer para sempre.
  #
  # `MessageUpdate` primeiro: ela referencia `Message`.
  consultar "
    DELETE FROM \"MessageUpdate\"
     WHERE \"messageId\" IN (
       SELECT id FROM \"Message\"
        WHERE to_timestamp(\"messageTimestamp\") < now() - interval '$DIAS_DE_HISTORICO days');
    DELETE FROM \"Message\"
     WHERE to_timestamp(\"messageTimestamp\") < now() - interval '$DIAS_DE_HISTORICO days';
  " >/dev/null 2>&1 || echo "[zelador] a poda falhou"

  sleep "$INTERVALO_SEGUNDOS"
done
