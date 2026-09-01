#!/bin/bash
# Da de alta un gateway AgroHub nuevo: genera su credencial y su bloque de ACL en el broker.
# Correr como root (o con sudo), en el servidor, después de instalar Mosquitto.
#
# Uso: sudo ./agregar_gateway.sh <client_id> <device_id>
# Ejemplo: sudo ./agregar_gateway.sh ug56-agrohub3 device0003
#
# client_id: identificador único del gateway en el broker (ver manual sección 05/11 — debe ser
#            único, dos gateways con el mismo Client ID se expulsan mutuamente).
# device_id: el mismo device00xx que se configura en el nodo "Config inicial" del gateway
#            (baseTopic=ahub/<device_id>) — deben coincidir siempre, ver manual sección 05 Paso 2.

set -euo pipefail

CLIENT_ID="${1:?Uso: $0 <client_id> <device_id>}"
DEVICE_ID="${2:?Uso: $0 <client_id> <device_id>}"
PASSWD_FILE="/etc/mosquitto/passwd"
ACL_FILE="/etc/mosquitto/acl.conf"
PASSWORD=$(openssl rand -hex 16)

if grep -q "^user ${CLIENT_ID}$" "$ACL_FILE" 2>/dev/null; then
    echo "Ya existe un bloque ACL para '${CLIENT_ID}' en ${ACL_FILE} — revisa antes de continuar." >&2
    exit 1
fi

mosquitto_passwd -b "$PASSWD_FILE" "$CLIENT_ID" "$PASSWORD"

cat >> "$ACL_FILE" << EOF

# --- ${CLIENT_ID} (${DEVICE_ID}) ---
user ${CLIENT_ID}
topic write ahub/${DEVICE_ID}/data
topic read  ahub/${DEVICE_ID}/data
topic write ahub/${DEVICE_ID}/valvulas/state
topic read  ahub/${DEVICE_ID}/valvulas/state
topic write ahub/${DEVICE_ID}/health
topic read  ahub/${DEVICE_ID}/health
topic write ahub/${DEVICE_ID}/status
topic read  ahub/${DEVICE_ID}/status
topic read  ahub/${DEVICE_ID}/control/valvulas
topic read  iotunimagdalena/cloud/health
EOF

systemctl reload mosquitto

cat << EOF

Gateway agregado.

  Client ID / usuario MQTT: ${CLIENT_ID}
  Password:                 ${PASSWORD}
  device_id:                ${DEVICE_ID}

Configurar en el gateway (UI web del UG56 -> Node-RED -> nodo "Servidor MQTT", ver manual
sección 03 Paso 3):
  Host: back.alunaia.co    Puerto: 8883    TLS: sí
  Usuario: ${CLIENT_ID}    Password: ${PASSWORD}    Client ID: ${CLIENT_ID}
  Keepalive: 15s    Clean session: DESACTIVADO

Configurar en el nodo "Config inicial (EDITAR AQUI)" del mismo gateway (manual sección 05):
  baseTopic: ahub/${DEVICE_ID}
  device_id: ${DEVICE_ID}

Guarda esta contraseña ahora — no vuelve a mostrarse (mosquitto_passwd solo guarda el hash).
EOF
