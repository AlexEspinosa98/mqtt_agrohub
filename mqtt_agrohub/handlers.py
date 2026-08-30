"""Qué hacer con cada mensaje entrante, según el sub-tópico — ver docs/TOPICS.md para el
detalle de cada payload. Cada handler recibe el device_id ya parseado y el payload ya decodificado
(dict para JSON, str para 'status')."""
import json
import logging

from . import db

logger = logging.getLogger(__name__)


def _es_lectura_suelo(payload):
    # El manual distingue ambiente de suelo por los campos presentes, no por un 'tipo' explícito
    # en el payload (sección 06): ambiente trae temperatura/humedad, suelo trae humedad_suelo/
    # temperatura_suelo/conductividad.
    return 'humedad_suelo' in payload or 'temperatura_suelo' in payload or 'conductividad' in payload


def manejar_data(device_id, payload):
    if _es_lectura_suelo(payload):
        db.insertar_lectura_suelo(device_id, payload)
        logger.debug('lectura de suelo guardada: %s', device_id)
    else:
        db.insertar_lectura_ambiente(device_id, payload)
        logger.debug('lectura de ambiente guardada: %s', device_id)


def manejar_valvulas_state(device_id, payload):
    db.insertar_estado_valvula(device_id, payload)
    logger.info(
        'estado de válvulas %s: RO1=%s RO2=%s origen=%s',
        device_id, payload.get('RO1'), payload.get('RO2'), payload.get('origen'),
    )


def manejar_health(device_id, payload):
    db.insertar_healthcheck(device_id, payload)


def manejar_status(device_id, payload_texto):
    estado = payload_texto.strip().lower()
    db.insertar_estado_conexion(device_id, estado)
    if estado == 'offline':
        logger.warning('gateway %s reportado OFFLINE (LWT)', device_id)
    else:
        logger.info('gateway %s reportado %s', device_id, estado)


def despachar(topic_info, raw_payload):
    """topic_info: topics.TopicAgrohub ya parseado. raw_payload: bytes crudos del mensaje MQTT."""
    db.registrar_dispositivo_visto(topic_info.device_id, topic_info.base_topic)

    if topic_info.subtopico == 'status':
        manejar_status(topic_info.device_id, raw_payload.decode('utf-8', errors='replace'))
        return

    try:
        payload = json.loads(raw_payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.error('payload no es JSON válido en %s/%s: %r', topic_info.base_topic, topic_info.subtopico, raw_payload[:200])
        return

    if topic_info.subtopico == 'data':
        manejar_data(topic_info.device_id, payload)
    elif topic_info.subtopico == 'valvulas/state':
        manejar_valvulas_state(topic_info.device_id, payload)
    elif topic_info.subtopico == 'health':
        manejar_health(topic_info.device_id, payload)
    else:
        logger.warning('sub-tópico no reconocido: %s/%s', topic_info.base_topic, topic_info.subtopico)
