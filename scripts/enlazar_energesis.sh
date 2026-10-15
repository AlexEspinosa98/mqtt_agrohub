#!/usr/bin/env bash
# Enlaza varios dispositivos nuestros con sus dispositivos de Energesis (ThingsBoard) por la API.
# Uso:  API=https://<dominio>/api/agrohub SESION=<token de sesión admin> ./scripts/enlazar_energesis.sh enlaces.csv
# enlaces.csv (una línea por dispositivo, sin cabecera):  device0001,<access token de ThingsBoard>,Device 1
set -euo pipefail
: "${API:?falta API}"; : "${SESION:?falta SESION}"
archivo="${1:?uso: $0 enlaces.csv}"
while IFS=, read -r device token nombre; do
  [ -z "${device// }" ] && continue
  cuerpo=$(printf '{"thingsboard_token":"%s","thingsboard_nombre":"%s"}' "$token" "${nombre:-$device}")
  codigo=$(curl -s -o /tmp/enlace_resp.json -w '%{http_code}' -X PUT "$API/riego-iot/dispositivos/$device/energesis/" \
    -H "Authorization: Token $SESION" -H 'Content-Type: application/json' -d "$cuerpo")
  echo "$device -> HTTP $codigo $(head -c 200 /tmp/enlace_resp.json)"
done < "$archivo"
rm -f /tmp/enlace_resp.json
