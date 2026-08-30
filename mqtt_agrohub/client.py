import logging
import ssl

import paho.mqtt.client as mqtt

from . import config
from .heartbeat import HiloLatido
from .topics import parsear

logger = logging.getLogger(__name__)


def _on_connect(client, userdata, flags, rc):
    if rc != 0:
        logger.error('conexión al broker rechazada (rc=%s)', rc)
        return
    logger.info('conectado al broker %s:%s', config.MQTT_HOST, config.MQTT_PORT)
    for topic in config.TOPICS_SUSCRIPCION:
        client.subscribe(topic, qos=1)
        logger.info('suscrito a %s', topic)


def _on_disconnect(client, userdata, rc):
    if rc != 0:
        logger.warning('desconectado del broker inesperadamente (rc=%s) — paho reintenta solo', rc)
    else:
        logger.info('desconectado del broker')


def _on_message(client, userdata, msg):
    topic_info = parsear(msg.topic)
    if topic_info is None:
        logger.debug('mensaje en tópico no reconocido, ignorado: %s', msg.topic)
        return
    try:
        from . import handlers
        handlers.despachar(topic_info, msg.payload)
    except Exception:
        # Un mensaje malformado o un error de base de datos no puede tumbar el loop de MQTT —
        # se registra y se sigue, igual que _llamar_llm en el proyecto Django hermano nunca deja
        # que un fallo puntual tumbe el resto del pipeline.
        logger.exception('error procesando mensaje de %s', msg.topic)


def construir_cliente():
    client = mqtt.Client(client_id=config.MQTT_CLIENT_ID, clean_session=True)
    if config.MQTT_USERNAME:
        client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
    if config.MQTT_USE_TLS:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def iniciar():
    client = construir_cliente()
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
    client.loop_start()

    latido = HiloLatido(client)
    latido.start()

    return client, latido
