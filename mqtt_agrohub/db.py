import json
import logging
import threading

import psycopg2
import psycopg2.pool

from . import config

logger = logging.getLogger(__name__)

# Un pool pequeño de conexiones — el servicio es single-process pero on_message puede llegar
# desde el hilo de red de paho-mqtt mientras el hilo del heartbeat también usa la base, así que
# no puede ser una sola conexión compartida sin lock.
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
