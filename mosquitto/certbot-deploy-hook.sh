#!/bin/bash
# Hook de renovación de certbot para Mosquitto — reusa el certificado ya existente de
# back.alunaia.co (ver mosquitto.conf) en vez de pedir un subdominio propio para MQTT.
#
# Por qué hace falta: /etc/letsencrypt/live/back.alunaia.co/ solo lo puede leer root, y
# Mosquitto corre con su propio usuario del sistema — así que cada vez que certbot renueva el
# certificado (cada ~60 días), hay que copiarlo a un sitio que Mosquitto sí pueda leer y avisarle
# que recargue. Sin esto, el certificado se vence en producción sin que nadie lo note hasta que
# los gateways empiezan a fallar el TLS handshake.
#
# Instalación (una sola vez, como root):
#   cp mosquitto/certbot-deploy-hook.sh /etc/letsencrypt/renewal-hooks/deploy/mosquitto.sh
#   chmod +x /etc/letsencrypt/renewal-hooks/deploy/mosquitto.sh
#   mkdir -p /etc/mosquitto/certs
#   /etc/letsencrypt/renewal-hooks/deploy/mosquitto.sh   # correrlo una vez a mano para poblar
#                                                          /etc/mosquitto/certs/ de inmediato
#   systemctl restart mosquitto
#
# Certbot corre automáticamente TODOS los scripts en renewal-hooks/deploy/ después de cada
# renovación exitosa (de cualquier dominio) — no hace falta registrar nada más.

set -euo pipefail

DOMINIO="back.alunaia.co"
ORIGEN="/etc/letsencrypt/live/${DOMINIO}"
DESTINO="/etc/mosquitto/certs"

cp "${ORIGEN}/fullchain.pem" "${DESTINO}/fullchain.pem"
cp "${ORIGEN}/privkey.pem" "${DESTINO}/privkey.pem"

chown mosquitto:mosquitto "${DESTINO}"/*.pem
chmod 640 "${DESTINO}/privkey.pem"
chmod 644 "${DESTINO}/fullchain.pem"

systemctl reload mosquitto || systemctl restart mosquitto
