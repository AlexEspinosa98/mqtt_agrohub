import json
import logging
import threading

import psycopg2
import psycopg2.extras
import psycopg2.pool

from . import config

logger = logging.getLogger(__name__)

# Un pool pequeño de conexiones — cada proceso que importa este módulo (el servicio de ingesta,
# la API) arma el suyo propio. Dentro del servicio de ingesta on_message puede llegar desde el
# hilo de red de paho-mqtt mientras el hilo del heartbeat también usa la base, así que no puede
# ser una sola conexión compartida sin lock.
_pool = psycopg2.pool.ThreadedConnectionPool(1, 5, config.DATABASE_URL)
_pool_lock = threading.Lock()


def _ejecutar(sql, params):
    with _pool_lock:
        conn = _pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
    finally:
        with _pool_lock:
            _pool.putconn(conn)


def _consultar(sql, params=()):
    """SELECT — devuelve una lista de dicts (una fila = un dict, columna -> valor)."""
    with _pool_lock:
        conn = _pool.getconn()
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
    finally:
        with _pool_lock:
            _pool.putconn(conn)


def _consultar_una(sql, params=()):
    filas = _consultar(sql, params)
    return filas[0] if filas else None


def registrar_dispositivo_visto(device_id, base_topic):
    _ejecutar(
        """
        INSERT INTO dispositivos (device_id, base_topic, ultima_vez_visto)
        VALUES (%s, %s, now())
        ON CONFLICT (device_id) DO UPDATE
        SET base_topic = EXCLUDED.base_topic, ultima_vez_visto = now()
        """,
        (device_id, base_topic),
    )


# ---------------------------------------------------------------------------
# CRUD de dispositivos — usado por la API de administración (ver api/), no por el servicio de
# ingesta (que solo usa registrar_dispositivo_visto de arriba, sin conocer client_id).
# ---------------------------------------------------------------------------

def crear_dispositivo(device_id, base_topic, client_id, nombre=None):
    _ejecutar(
        """
        INSERT INTO dispositivos (device_id, base_topic, client_id, nombre, activo)
        VALUES (%s, %s, %s, %s, TRUE)
        ON CONFLICT (device_id) DO UPDATE
        SET base_topic = EXCLUDED.base_topic, client_id = EXCLUDED.client_id,
            nombre = EXCLUDED.nombre, activo = TRUE
        """,
        (device_id, base_topic, client_id, nombre),
    )


def marcar_dispositivo_inactivo(device_id):
    _ejecutar('UPDATE dispositivos SET activo = FALSE WHERE device_id = %s', (device_id,))


def obtener_dispositivo(device_id):
    return _consultar_una('SELECT * FROM dispositivos WHERE device_id = %s', (device_id,))


def listar_dispositivos(solo_activos=False):
    if solo_activos:
        return _consultar('SELECT * FROM dispositivos WHERE activo = TRUE ORDER BY device_id')
    return _consultar('SELECT * FROM dispositivos ORDER BY device_id')


# ---------------------------------------------------------------------------
# Lecturas para el dashboard — todas de solo lectura.
# ---------------------------------------------------------------------------

def ultima_lectura_ambiente(device_id):
    return _consultar_una(
        'SELECT * FROM lecturas_ambiente WHERE device_id = %s ORDER BY medido_en DESC LIMIT 1',
        (device_id,),
    )


def ultima_lectura_suelo(device_id):
    return _consultar_una(
        'SELECT * FROM lecturas_suelo WHERE device_id = %s ORDER BY medido_en DESC LIMIT 1',
        (device_id,),
    )


def ultimo_estado_valvula(device_id):
    return _consultar_una(
        'SELECT * FROM estados_valvula WHERE device_id = %s ORDER BY medido_en DESC LIMIT 1',
        (device_id,),
    )


def ultimo_health(device_id):
    return _consultar_una(
        'SELECT * FROM healthchecks WHERE device_id = %s ORDER BY medido_en DESC LIMIT 1',
        (device_id,),
    )


def ultimo_estado_conexion(device_id):
    return _consultar_una(
        'SELECT * FROM estados_conexion WHERE device_id = %s ORDER BY recibido_en DESC LIMIT 1',
        (device_id,),
    )


def lecturas_ambiente_rango(device_id, desde, hasta, limite=1000):
    return _consultar(
        """
        SELECT * FROM lecturas_ambiente
        WHERE device_id = %s AND medido_en BETWEEN %s AND %s
        ORDER BY medido_en DESC LIMIT %s
        """,
        (device_id, desde, hasta, limite),
    )


def lecturas_suelo_rango(device_id, desde, hasta, limite=1000):
    return _consultar(
        """
        SELECT * FROM lecturas_suelo
        WHERE device_id = %s AND medido_en BETWEEN %s AND %s
        ORDER BY medido_en DESC LIMIT %s
        """,
        (device_id, desde, hasta, limite),
    )


def insertar_lectura_ambiente(device_id, payload):
    _ejecutar(
        """
        INSERT INTO lecturas_ambiente
            (device_id, dev_eui, medido_en, temperatura, humedad,
             recuperado, guardado_en, reenviado_en, payload_crudo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            device_id,
            payload.get('devEUI'),
            payload.get('measured_at') or payload.get('ts'),
            payload.get('temperatura'),
            payload.get('humedad'),
            bool(payload.get('recuperado', False)),
            payload.get('guardado_en'),
            payload.get('reenviado_en'),
            json.dumps(payload),
        ),
    )


def insertar_lectura_suelo(device_id, payload):
    _ejecutar(
        """
        INSERT INTO lecturas_suelo
            (device_id, dev_eui, medido_en, humedad_suelo, temperatura_suelo, conductividad,
             recuperado, guardado_en, reenviado_en, payload_crudo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            device_id,
            payload.get('devEUI'),
            payload.get('measured_at') or payload.get('ts'),
            payload.get('humedad_suelo'),
            payload.get('temperatura_suelo'),
            payload.get('conductividad'),
            bool(payload.get('recuperado', False)),
            payload.get('guardado_en'),
            payload.get('reenviado_en'),
            json.dumps(payload),
        ),
    )


def insertar_estado_valvula(device_id, payload):
    _ejecutar(
        """
        INSERT INTO estados_valvula (device_id, medido_en, ro1, ro2, origen, ultimo_comando, payload_crudo)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            device_id,
            payload.get('ts'),
            payload.get('RO1'),
            payload.get('RO2'),
            payload.get('origen', 'desconocido'),
            payload.get('ultimo_comando'),
            json.dumps(payload),
        ),
    )


def insertar_healthcheck(device_id, payload):
    _ejecutar(
        """
        INSERT INTO healthchecks
            (device_id, medido_en, mqtt_conectado, ultimo_uplink, modo_control,
             override_manual, valvulas, payload_crudo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            device_id,
            payload.get('measured_at') or payload.get('ts'),
            payload.get('mqtt_conectado'),
            payload.get('ultimo_uplink'),
            payload.get('modo_control'),
            payload.get('override_manual'),
            json.dumps(payload.get('valvulas')) if payload.get('valvulas') is not None else None,
            json.dumps(payload),
        ),
    )


def insertar_estado_conexion(device_id, estado):
    _ejecutar(
        'INSERT INTO estados_conexion (device_id, estado) VALUES (%s, %s)',
        (device_id, estado),
    )


def registrar_comando_enviado(device_id, valvula, accion, payload):
    _ejecutar(
        """
        INSERT INTO comandos_enviados (device_id, valvula, accion, payload_crudo)
        VALUES (%s, %s, %s, %s)
        """,
        (device_id, valvula, accion, json.dumps(payload)),
    )
