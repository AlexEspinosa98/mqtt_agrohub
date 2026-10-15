#!/usr/bin/env bash
# Enlaza UN dispositivo nuestro con uno de Energesis, lo prueba y muestra el estado.
# Pide por teclado (sin mostrarlos) tu contraseña y el access token de ThingsBoard: no quedan en historial ni en archivos.
# Uso: ./scripts/enlazar_uno.sh device0015 "Device 15 (812e45a0-c8c2-11f1-a031-3bc781290fbc)"
set -uo pipefail
DEVICE="${1:?uso: $0 device00XX [nombre]}"; NOMBRE="${2:-$DEVICE}"
API="${API:-https://back.alunaia.co/api/agrohub}"; USUARIO="${USUARIO:-1083034205}"
read -rsp "Contraseña de $USUARIO: " PASS; echo
read -rsp "Access token de ThingsBoard para $DEVICE: " TB; echo
SESION=$(curl -s -X POST "$API/user-activity/users/login" -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"phone_or_identification":sys.argv[1],"password":sys.argv[2]}))' "$USUARIO" "$PASS")" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('data') or d).get('token',''))" 2>/dev/null)
unset PASS
[ -z "$SESION" ] && { echo "Login falló: revisa usuario y contraseña."; exit 1; }
H=(-H "Authorization: Token $SESION" -H 'Content-Type: application/json')
echo "--- crear enlace"
curl -s -X PUT "$API/riego-iot/dispositivos/$DEVICE/energesis/" "${H[@]}" \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"thingsboard_token":sys.argv[1],"thingsboard_nombre":sys.argv[2]}))' "$TB" "$NOMBRE")"; echo
unset TB
echo "--- probar (manda un dato de prueba)"; curl -s -X POST "$API/riego-iot/dispositivos/$DEVICE/energesis/probar/" "${H[@]}"; echo
echo "--- estado"; curl -s "$API/riego-iot/dispositivos/$DEVICE/energesis/" "${H[@]}"; echo
