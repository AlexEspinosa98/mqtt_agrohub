# mqtt_agrohub

Broker MQTT + servicio de ingesta para los gateways AgroHub (Milesight UG56) del proyecto
AgroHub — Universidad del Magdalena. Este repo es **solo la capa MQTT**: el broker que reciben
las conexiones de los gateways, y un servicio Python que se suscribe, valida y persiste los
mensajes, y mantiene el latido de nube que el firmware de cada gateway necesita para saber que
"la nube" sigue viva.

La lógica de campo (lectura de sensores, control de válvulas, respaldo en microSD, failover
local) ya está resuelta **dentro del gateway** — corre como un flujo Node-RED embebido en el
propio UG56. Ver el manual `SL-ENT-2026-001 Manual de Usuario - Gateway Riego UG56 - AgroHub.pdf`
en la raíz de este repo para el detalle completo de esa parte; este README solo cubre lo que
vive en el servidor.

## Arquitectura

```
Gateway(s) AgroHub (UG56, uno por sitio, internet público)
        │  MQTT sobre TLS, puerto 8883
        │  usuario/contraseña por gateway, sesión persistente, QoS 1
        ▼
   Mosquitto (broker)  ──  systemd, ver mosquitto/
        │  el persister se conecta en localhost:1883 (solo tráfico interno)
        ▼
   mqtt_agrohub (este servicio Python)  ──  systemd, ver systemd/
        │  paho-mqtt → valida → persiste
        ▼
   PostgreSQL (ver schema.sql)
```

Dos responsabilidades separadas a propósito:
- **Mosquitto** es la pieza crítica de "aceptar conexiones 24/7 sin caerse" — software maduro en
  C, no reinventado. Su config vive en `mosquitto/`.
- **Este servicio Python** es la lógica de negocio: qué hacer con cada mensaje. No necesita ser
  tan robusto para sostener miles de conexiones (eso lo hace el broker) — solo necesita
  reconectarse solo si se cae y no perder datos.

## Por qué el latido de nube (`iotunimagdalena/cloud/health`) es la parte más delicada

Según el manual (sección 08, "Control de Riego: Modos y Prioridades"): mientras el gateway reciba
este latido cada ≤3 minutos y tenga conexión MQTT, la lógica de riego la controla **la nube**
(nosotros, publicando en `ahub/<device_id>/control/valvulas`). Si el latido deja de llegar, el
gateway asume control local automáticamente (failover por humedad de suelo) — es el
comportamiento correcto y deseado, pero significa que **si este servicio se cae, todos los
gateways pasan a modo local silenciosamente**. Por eso el latido corre en su propio hilo con
`Restart=always` a nivel de systemd, y **nunca debe publicarse con `retain=True`** (un latido
retenido haría creer al gateway que la nube sigue viva tras una reconexión aunque no lo esté —
advertencia explícita del manual, sección 09).

## Estructura

```
mqtt_agrohub/           paquete Python del servicio
  config.py             configuración desde variables de entorno
  db.py                 conexión a Postgres (psycopg2) y helpers de upsert
  topics.py             parseo de tópicos ahub/<device_id>/<resto>
  handlers.py           qué hacer con cada tipo de mensaje (data/valvulas/health/status)
  heartbeat.py          hilo que publica iotunimagdalena/cloud/health cada 60s
  commands.py           enviar_comando_valvula(device_id, valvula, accion) — para quien
                         necesite mandar comandos (otro servicio, un script, etc.)
  client.py             arma el cliente MQTT, conecta, suscribe, arranca el heartbeat
main.py                 punto de entrada — python main.py
schema.sql              esquema de las tablas en Postgres (auto-aplicado por docker-compose)
docker-compose.yml      Postgres para este servicio (mismo patrón que backed_aluna_kunsama)
mosquitto/               config del broker para producción
  mosquitto.conf
  acl.conf.example
  agregar_gateway.sh      da de alta un gateway nuevo: credencial + ACL + recarga, un comando
  certbot-deploy-hook.sh  reusa el cert de back.alunaia.co, sin pedir subdominio nuevo
systemd/
  mqtt-agrohub.service   unit file del servicio Python (no el broker — Mosquitto trae el suyo)
docs/
  TOPICS.md              referencia rápida de tópicos y payloads (extraída del manual)
.env.example
requirements.txt
```

## Puesta en marcha (desarrollo local)

```bash
cp .env.example .env      # completar POSTGRES_PASSWORD, MQTT_*, etc.
docker compose up -d      # levanta Postgres (puerto 5434) y aplica schema.sql automáticamente

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Con un Mosquitto local para probar (o docker run -p 1883:1883 eclipse-mosquitto):
python main.py
```

`docker compose up -d` monta `schema.sql` como script de inicialización — Postgres lo corre
solo la primera vez que crea el volumen. Si cambias el esquema después, aplícalo a mano:
`docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < schema.sql`.

## Despliegue en producción (servidor hubambiental)

1. **Postgres**: igual que en desarrollo — `docker compose up -d` en el servidor, mismo patrón
   que ya usa `backed_aluna_kunsama` para su propia base (ver `docker-compose.yml` de ese repo).
   Puerto 5434 (no 5432/5433, que ya están tomados en ese servidor — ver `.env.example`),
   publicado solo en `127.0.0.1`, nunca expuesto fuera del servidor.
2. **Mosquitto**: instalar (`apt install mosquitto`) directo en el sistema — no en Docker, es la
   pieza que debe sostener miles de conexiones 24/7 y conviene tenerla como servicio systemd
   nativo, igual que Postgres via Docker pero Mosquitto no lo justifica (no necesita
   aislamiento, sí necesita máximo rendimiento de red). Reemplazar
   `/etc/mosquitto/mosquitto.conf` por `mosquitto/mosquitto.conf`, generar credenciales por
   gateway con `mosquitto_passwd -b /etc/mosquitto/passwd <usuario> <password>`, copiar
   `mosquitto/acl.conf.example` a `/etc/mosquitto/acl.conf` con un bloque por gateway real, e
   instalar `mosquitto/certbot-deploy-hook.sh` (ver ese archivo para el paso a paso) — **no hace
   falta pedir un subdominio nuevo**, ver la nota siguiente.
3. **Puerto 8883**: debe abrirse en el firewall del sistema operativo y, si aplica, en el
   firewall/security group del proveedor de hosting — **pendiente de confirmar**, no se pudo
   verificar por SSH sin acceso root.
4. **Este servicio**: `venv` + `pip install -r requirements.txt`, variables de entorno reales en
   `.env` (nunca commiteado, con `DATABASE_URL` apuntando al Postgres de Docker del paso 1), y
   el unit file de `systemd/mqtt-agrohub.service` — mismo patrón que los otros backends del
   servidor (`aluna-kunsama-backend`, etc.): `Restart=always`, logs propios.

### Por qué no hace falta pedir un subdominio nuevo

MQTT (incluso sobre TLS, puerto 8883) es un protocolo TCP crudo, no HTTP — no tiene "rutas" como
`/mqtt`, así que no se puede enrutar por path detrás de nginx como sí se hace con
`/api/aluna-kunsama/` para los backends Django/FastAPI. Nginx no interviene en absoluto: Mosquitto
escucha directo en el puerto 8883 del servidor.

En vez de tramitar un subdominio nuevo (`mqtt.alunaia.co` o similar) solo para tener dónde colgar
un certificado, **reutiliza el dominio y el certificado que ya existen** (`back.alunaia.co`) — los
gateways se conectan a `back.alunaia.co:8883` en vez de a un subdominio nuevo. El único detalle es
de permisos, no de DNS: Let's Encrypt guarda el certificado donde solo root puede leerlo, y
Mosquitto corre con su propio usuario del sistema — `mosquitto/certbot-deploy-hook.sh` resuelve
eso copiando el certificado a un sitio que Mosquitto sí puede leer, y recargándolo, cada vez que
certbot renueva (automático, sin volver a tocarlo).

Si en el futuro conviene separar el tráfico MQTT del HTTP en un hostname propio (por ejemplo, para
poder mover el broker a otro servidor sin coordinar con los demás backends), ahí sí valdría la
pena pedir el subdominio — pero no es necesario para arrancar.

### Agregar un gateway AgroHub nuevo

Instalar Mosquitto y arrancar este servicio deja el broker funcionando, pero **sin ningún
gateway dado de alta** — solo existe el usuario de nuestro propio servicio
(`iotunimagdalena-persister`). Cada gateway físico necesita su propia credencial y su propio
bloque de ACL (ver la nota de seguridad más abajo — nunca un usuario compartido).

```bash
sudo mosquitto/agregar_gateway.sh ug56-agrohub3 device0003
```

Un solo comando: genera la contraseña, crea el usuario en `/etc/mosquitto/passwd`, agrega su
bloque de ACL en `/etc/mosquitto/acl.conf`, recarga Mosquitto, e imprime exactamente qué poner
en el gateway. Ese último paso — configurar el gateway — **pasa del otro lado, en el propio
UG56** (su UI web → Node-RED → nodo "Servidor MQTT" y nodo "Config inicial", ver manual secciones
03 y 05): ahí es donde se ingresan el host (`back.alunaia.co`), el puerto (`8883`), el
usuario/contraseña que acaba de imprimir el script, y el `device_id`/`baseTopic`. Ese paso no se
puede hacer desde este servidor — lo hace quien tenga acceso a la interfaz de ese gateway físico
(instalador de campo o el administrador del proyecto, ver manual sección 02 "Roles de usuario").

### Nota de seguridad — internet público, múltiples sistemas IoT

El broker va a recibir conexiones de gateways por internet público, y a futuro de otros sistemas
IoT además de AgroHub. Reglas no negociables:
- **Nunca** exponer el puerto 1883 (sin cifrar) a internet — solo 8883 con TLS.
- Un usuario/contraseña **por gateway**, nunca uno compartido — permite revocar acceso a uno sin
  tocar los demás.
- ACL por tópico (ver `mosquitto/acl.conf.example`): cada gateway solo puede publicar en su
  propio `ahub/<device_id>/...` y leer únicamente su propio tópico de control y el latido de
  nube — nunca los datos de otro gateway.
