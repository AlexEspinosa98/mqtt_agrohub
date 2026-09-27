#!/bin/bash
# Crea el usuario ahub-monitor: para probar/monitorear el broker sin usar la credencial de un
# gateway real. Lee TODO el namespace ahub/# y puede publicar en los tres tópicos de
# comando/latido (control/valvulas, config/set, cloud/health) -- igual que hace nuestro propio
# persister, pero como una identidad separada para pruebas manuales.
#
# Correr como root (o con sudo), en el servidor. Se corre UNA sola vez -- si ya existe el
# usuario en /etc/mosquitto/passwd, mosquitto_passwd -b simplemente le cambia la contraseña
# (no rompe nada, pero entonces hay que actualizar donde sea que se esté usando la vieja).
#
# Uso: sudo ./crear_usuario_monitor.sh

set -euo pipefail

PASSWD_FILE="/etc/mosquitto/passwd"
ACL_FILE="/etc/mosquitto/acl.conf"
USUARIO="ahub-monitor"
PASSWORD=$(openssl rand -hex 16)

mosquitto_passwd -b "$PASSWD_FILE" "$USUARIO" "$PASSWORD"

if ! grep -q "^user ${USUARIO}$" "$ACL_FILE" 2>/dev/null; then
    cat >> "$ACL_FILE" << EOF

# --- ${USUARIO} (app de monitoreo/pruebas, no es un gateway) ---
user ${USUARIO}
topic read  ahub/#
topic write ahub/+/control/valvulas
topic write ahub/+/config/set
topic write ahub/+/cloud/health
EOF
fi

systemctl reload mosquitto

cat << EOF

Usuario de monitoreo creado.

  Usuario:  ${USUARIO}
  Password: ${PASSWORD}

Conectar a: back.alunaia.co, puerto 8883, TLS sí.

Guarda esta contraseña ahora -- no vuelve a mostrarse (mosquitto_passwd solo guarda el hash).
Si ya existía el usuario, esta es la contraseña NUEVA -- actualízala donde sea que la app de
monitoreo la tenga guardada.
EOF
