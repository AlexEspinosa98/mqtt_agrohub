import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


MQTT_HOST = os.environ.get('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
MQTT_USE_TLS = _env_bool('MQTT_USE_TLS', False)
MQTT_USERNAME = os.environ.get('MQTT_USERNAME') or None
MQTT_PASSWORD = os.environ.get('MQTT_PASSWORD') or None
MQTT_CLIENT_ID = os.environ.get('MQTT_CLIENT_ID', 'iotunimagdalena-persister')

# Ver docs/TOPICS.md — nunca publicar este tópico con retain=True.
CLOUD_HEALTH_TOPIC = os.environ.get('CLOUD_HEALTH_TOPIC', 'iotunimagdalena/cloud/health')
CLOUD_HEALTH_INTERVAL_SECONDS = int(os.environ.get('CLOUD_HEALTH_INTERVAL_SECONDS', '60'))

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError('Falta DATABASE_URL en el entorno — copia .env.example a .env y complétalo.')

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# Tópicos de los gateways AgroHub — baseTopic = ahub/<device_id>, ver docs/TOPICS.md.
TOPICS_SUSCRIPCION = [
    'ahub/+/data',
    'ahub/+/valvulas/state',
    'ahub/+/health',
    'ahub/+/status',
]

# --- API de administración (ver api/) ---
ADMIN_API_KEY = os.environ.get('ADMIN_API_KEY')
API_HOST = os.environ.get('API_HOST', '127.0.0.1')
API_PORT = int(os.environ.get('API_PORT', '8005'))

# Rutas de los archivos de Mosquitto que la API edita al crear/eliminar/rotar credenciales —
# ver mosquitto_admin.py y README ("API de administración") para los permisos que necesita.
MOSQUITTO_PASSWD_FILE = os.environ.get('MOSQUITTO_PASSWD_FILE', '/etc/mosquitto/passwd')
MOSQUITTO_ACL_FILE = os.environ.get('MOSQUITTO_ACL_FILE', '/etc/mosquitto/acl.conf')
