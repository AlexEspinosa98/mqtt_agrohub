# Reenvío de telemetría a ThingsBoard (Energesis)

Nuestro Mosquitto es la fuente de verdad. Este reenvío es **opcional, apagado por defecto y de una
sola vía** (nosotros → ThingsBoard): copia a ThingsBoard lo que el daemon `mqtt-agrohub` ya recibe de
los gateways. No recibe comandos de ThingsBoard — la configuración y las válvulas siguen saliendo
solo de nuestro backend. Código: `mqtt_agrohub/thingsboard.py`.

## Cómo activarlo

En el `.env` del servidor (los tokens son credenciales, nunca van al repo):

```
THINGSBOARD_ENABLED=true
THINGSBOARD_HOST=iot.energesis.tech
THINGSBOARD_PORT=1884
THINGSBOARD_USE_TLS=false
# Elegir UNO de los dos modos:
THINGSBOARD_GATEWAY_TOKEN=<token de un dispositivo tipo "gateway">
THINGSBOARD_TOKENS={"device0014":"<token>","device0002":"<token>"}
```

Luego `sudo systemctl restart mqtt-agrohub` y revisar el log: debe decir
`reenvío a ThingsBoard activo (...)` y `ThingsBoard conectado`. Si dice `rechazó la conexión (rc=4/5)`,
el token está mal o es de otro dispositivo.

| Modo | Cuándo | Qué publica |
|---|---|---|
| **dispositivo** | Energesis da un token por gateway | `v1/devices/me/telemetry` con `{"ts":ms,"values":{...}}`, una conexión por token |
| **gateway** | Energesis crea un dispositivo "gateway" | `v1/gateway/telemetry` con `{"device0014":[{"ts":ms,"values":{...}}]}`, una sola conexión para los 16 |

Con token de gateway, el modo por dispositivo se ignora. En modo dispositivo, un gateway sin token no se reenvía.

## Qué se manda

| Tópico nuestro | Claves en ThingsBoard |
|---|---|
| `data` (suelo) | `z1_humedad_suelo`, `z1_temperatura_suelo`, `z1_conductividad`, `z1_sonda_ok`, `z1_bateria_v`, `z1_radio_rssi`… (prefijo = zona, porque un gateway tiene varias) |
| `data` (ambiente) | `temperatura`, `humedad` |
| `valvulas/state` | `z1_RO1`, `z1_RO2`, `z1_origen`, `z1_ultimo_comando`, `z1_confirmada` |
| `health` | `modo_control`, `config_rev`, `zonas_auto_z1`… (un nivel de anidamiento se aplana con `_`; listas como texto JSON) |
| `status` | `estado_conexion` = `online` / `offline` |

El `ts` es el `measured_at` (o `ts`) del gateway, en milisegundos; sin fecha utilizable se usa la hora actual.

## Garantías

- Va **después** de guardar en nuestra base y por una cola aparte: si ThingsBoard está caído, lento o
  rechaza el token, el guardado no se ve afectado. Cola máxima 2000 mensajes (si se llena, descarta y avisa en el log).
- Apagado = no hace nada (no abre ninguna conexión).

## Límites conocidos

- **El puerto 1884 de Energesis no usa TLS** (el handshake falla): el token viaja sin cifrar. Pedirles un
  puerto seguro y poner `THINGSBOARD_USE_TLS=true`.
- No hay reintento persistente: si la conexión está caída, paho conserva hasta 1000 mensajes en memoria;
  al reiniciar el daemon se pierden. ThingsBoard es una copia, la base nuestra es la que manda.
- Solo telemetría. Atributos de ThingsBoard, RPC y alarmas no están implementados.

## Pruebas

`venv/bin/python -m unittest tests.test_thingsboard` — usa un Mosquitto **local** que imita a ThingsBoard
(se salta si no hay `mosquitto`); nunca habla con Energesis ni usa tokens reales.

## Transporte HTTPS (recomendado) y enlaces desde la API

- `THINGSBOARD_TRANSPORT=http` + `THINGSBOARD_PORT=443` + `THINGSBOARD_USE_TLS=true`: cada medición se manda con
  `POST https://iot.energesis.tech/api/v1/<token>/telemetry` (cuerpo `{"ts":ms,"values":{...}}`). Es cifrado y
  evita el 1884 sin TLS. Solo modo por dispositivo.
- Los enlaces dispositivo nuestro ↔ dispositivo de Energesis viven en la tabla `enlaces_energesis` y se administran
  por la API del backend (`/riego-iot/dispositivos/{id}/energesis/`, `.../probar/`, `/riego-iot/energesis/`).
- Para enlazar varios de una vez: `scripts/enlazar_energesis.sh`.
