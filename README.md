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
mqtt_agrohub/           paquete Python compartido (lo usan tanto el daemon de ingesta como la API)
  config.py             configuración desde variables de entorno
  db.py                 conexión a Postgres (psycopg2), inserts de la ingesta + queries de la API
  topics.py             parseo de tópicos ahub/<device_id>/<resto>
  handlers.py           qué hacer con cada tipo de mensaje (data/valvulas/health/status)
  heartbeat.py          hilo que publica iotunimagdalena/cloud/health cada 60s
  commands.py           enviar_comando_valvula(device_id, valvula, accion) — para quien
                         necesite mandar comandos (otro servicio, un script, etc.)
  client.py             arma el cliente MQTT, conecta, suscribe, arranca el heartbeat
  mosquitto_admin.py     crea/elimina/rota credenciales de gateways — usado por la API
main.py                 punto de entrada del daemon de ingesta — python main.py
api/                    API de administración (FastAPI) — servicio HTTP aparte, ver más abajo
  main.py               arma la app, monta los routers
  auth.py               autenticación por API key (header X-API-Key)
  schemas.py             modelos de request/response
  routers/
    dispositivos.py      alta/baja/rotar contraseña de gateways
    dashboard.py          última lectura, histórico, estado de conexión por dispositivo
schema.sql              esquema de las tablas en Postgres (auto-aplicado por docker-compose)
migrations/              cambios de esquema para bases ya provisionadas (sin framework, a mano)
docker-compose.yml      Postgres para este servicio (mismo patrón que backed_aluna_kunsama)
mosquitto/               config del broker para producción
  mosquitto.conf
  acl.conf.example
  agregar_gateway.sh      da de alta un gateway por SSH: credencial + ACL + recarga, un comando
                          (la API hace lo mismo por HTTP — usar el que sea más cómodo)
  certbot-deploy-hook.sh  reusa el cert de back.alunaia.co, sin pedir subdominio nuevo
systemd/
  mqtt-agrohub.service       unit file del daemon de ingesta (no el broker, Mosquitto trae el suyo)
  mqtt-agrohub-api.service   unit file de la API de administración
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
4. **Daemon de ingesta**: `venv` + `pip install -r requirements.txt`, variables de entorno reales en
   `.env` (nunca commiteado, con `DATABASE_URL` apuntando al Postgres de Docker del paso 1), y
   el unit file de `systemd/mqtt-agrohub.service` — mismo patrón que los otros backends del
   servidor (`aluna-kunsama-backend`, etc.): `Restart=always`, logs propios.
5. **API de administración**: ver la sección siguiente — necesita un paso de seguridad adicional
   (permisos + sudoers) antes de poder crear/eliminar/rotar credenciales de gateways.

## API de administración

Servicio HTTP aparte (`api/`, uvicorn en `127.0.0.1:8006`, `systemd/mqtt-agrohub-api.service`) —
alta/baja/rotación de gateways y dashboard de telemetría, para no tener que hacerlo por SSH con
`mosquitto/agregar_gateway.sh` cada vez. Documentación interactiva automática en `/docs` (Swagger)
una vez arriba.

Toda ruta requiere el header `X-API-Key: <ADMIN_API_KEY>` (generar con `openssl rand -hex 32` y
ponerlo en `.env` — es la única credencial de esta API, pensada para un puñado de operadores
internos, no para usuarios finales).

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/dispositivos` | Lista todos los gateways (`?solo_activos=true` para filtrar) |
| `POST` | `/dispositivos` | Da de alta uno nuevo — `{"device_id": "device0017", "client_id": "ug56-agrohub17", "nombre": "..."}`. Crea la credencial en Mosquitto y devuelve la contraseña **una sola vez** |
| `DELETE` | `/dispositivos/{device_id}` | Revoca su acceso al broker de inmediato y lo marca inactivo (sus lecturas históricas NO se borran) |
| `POST` | `/dispositivos/{device_id}/rotar-password` | Genera una contraseña nueva para ese gateway — la anterior deja de servir |
| `GET` | `/dashboard/resumen` | Todos los gateways activos con su último dato de cada tipo (ambiente, suelo, válvulas, health, en línea/fuera de línea) |
| `GET` | `/dashboard/{device_id}` | Lo mismo, para un solo gateway |
| `GET` | `/dashboard/{device_id}/lecturas/ambiente` | Histórico (`?desde=&hasta=&limite=`, por defecto últimos 7 días) |
| `GET` | `/dashboard/{device_id}/lecturas/suelo` | Igual, para lecturas de suelo |

### Permisos que necesita — leer antes de arrancar el servicio

La API edita `/etc/mosquitto/passwd` y `/etc/mosquitto/acl.conf`, y necesita recargar Mosquitto
después de cada cambio. Esto es una **decisión de seguridad real** — dejo los comandos listos
pero no los corro yo (necesitan tu sudo):

```bash
# 1. Permiso de escritura de grupo sobre los dos archivos que la API edita.
sudo groupadd -f mosquitto-admin
sudo usermod -aG mosquitto-admin hubambiental002
# El propio proceso de Mosquitto (usuario 'mosquitto') TAMBIÉN necesita estar en el grupo —
# si se omite esto, Mosquitto sigue funcionando mientras tenga el archivo ya abierto, pero en
# el próximo restart real no puede reabrir su propio passwd file y no arranca (nos pasó:
# "Error: Unable to open pwfile", servicio caído hasta agregar esto).
sudo usermod -aG mosquitto-admin mosquitto
sudo chgrp mosquitto-admin /etc/mosquitto/passwd /etc/mosquitto/acl.conf
sudo chmod 660 /etc/mosquitto/passwd /etc/mosquitto/acl.conf   # sin lectura para "otros" —
    # Mosquitto avisa (y en versiones futuras rechaza cargar) un passwd file world-readable
# mosquitto_passwd escribe primero un archivo temporal (passwd.tmp) en el mismo directorio y
# luego lo renombra sobre el original — sin permiso de escritura en el DIRECTORIO (no solo en
# el archivo), falla con "Error creating backup password file".
sudo chgrp mosquitto-admin /etc/mosquitto
sudo chmod g+w /etc/mosquitto

# 2. Regla de sudoers ACOTADA a un solo comando — la API la usa para que Mosquitto tome los
#    cambios sin reiniciar el broker entero. No es sudo general: solo permite ESE comando exacto.
echo 'hubambiental002 ALL=(root) NOPASSWD: /bin/systemctl reload mosquitto' | sudo tee /etc/sudoers.d/mqtt-agrohub-api
sudo chmod 440 /etc/sudoers.d/mqtt-agrohub-api
sudo visudo -c   # valida la sintaxis antes de confiar en el archivo

# 3. Cerrar sesión y volver a entrar por SSH para que el nuevo grupo tome efecto (para
#    hubambiental002 — mosquitto y agrohub-backend son servicios systemd, ya lo recogen en su
#    próximo restart sin necesitar esto), o:
newgrp mosquitto-admin
```

Sin el paso 2, todo lo demás funciona pero cada `POST`/`DELETE`/rotar-password deja el cambio
escrito en disco y responde `502` — Mosquitto no lo toma hasta un reinicio manual.

### Exponer la API por nginx

Por defecto la API solo escucha en `127.0.0.1:8006` — nadie fuera del servidor puede llamarla.
Para que quede alcanzable como los demás backends (`https://back.alunaia.co/api/agrohub-mqtt/...`),
agregar un `location` más al mismo archivo de nginx donde ya conviven `/api/agrohub/`,
`/api/agrohub-rs/`, `/api/aluna/`, `/api/cienared/` y `/api/aluna-kunsama/` — **no es una decisión
de mezclar código con ninguno de esos backends**, nginx no le importa qué corre detrás de cada
puerto, solo agrega una entrada más a la misma lista. Esto necesita tu sudo (edita
`/etc/nginx/sites-available/backend`, compartido por todos los backends del servidor):

```nginx
# --- mqtt_agrohub (gateways de riego + dashboard) ---
location /api/agrohub-mqtt/ {
    proxy_pass http://127.0.0.1:8006/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;
}
```

Agregar este bloque **dos veces** — dentro del `server` de `listen 80 default_server` (acceso
directo por IP) y dentro del `server` de `listen 443 ssl; server_name back.alunaia.co;` (el que
importa de verdad, con TLS) — mismo patrón que ya siguen los otros cinco. Después:

```bash
sudo nginx -t   # valida la sintaxis antes de recargar
sudo systemctl reload nginx
```

El `--root-path /api/agrohub-mqtt` que ya trae `systemd/mqtt-agrohub-api.service` (mismo truco que
usa CienaNet con `/api/cienared`) hace que `/docs` y el JSON de OpenAPI que genera FastAPI
funcionen bien detrás de ese prefijo — sin eso, la documentación cargaría pero los links y
ejemplos de la UI de Swagger apuntarían a rutas rotas.

Una vez recargado nginx, la API completa queda en `https://back.alunaia.co/api/agrohub-mqtt/` —
mismo header `X-API-Key` de siempre, y `https://back.alunaia.co/api/agrohub-mqtt/docs` para la
documentación interactiva.

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
