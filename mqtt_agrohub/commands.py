"""Enviar comandos de válvula a un gateway — ver docs/TOPICS.md, tópico control/valvulas.
Reusable por quien necesite mandar comandos (un script, un endpoint de otro servicio, etc.) —
este repo es solo la capa MQTT, no decide CUÁNDO regar; eso lo decide quien llame a esta función."""
import json
import logging

from . import db
from .topics import topic_control_valvulas

logger = logging.getLogger(__name__)

VALVULAS_VALIDAS = {'RO1', 'RO2', '1', '2'}
ACCIONES_ABRIR = {'abrir', 'open', 'on', 'encender'}
ACCIONES_CERRAR = {'cerrar', 'close', 'off', 'apagar'}


def enviar_comando_valvula(mqtt_client, device_id, valvula, accion):
    if valvula not in VALVULAS_VALIDAS:
        raise ValueError(f"Válvula inválida: {valvula!r} (válidas: {sorted(VALVULAS_VALIDAS)})")
    accion_normalizada = accion.strip().lower()
    if accion_normalizada not in ACCIONES_ABRIR and accion_normalizada not in ACCIONES_CERRAR:
        raise ValueError(
            f"Acción inválida: {accion!r} "
            f"(abrir: {sorted(ACCIONES_ABRIR)} / cerrar: {sorted(ACCIONES_CERRAR)})"
        )

    payload = {'valvula': valvula, 'accion': accion}
    topic = topic_control_valvulas(device_id)
    resultado = mqtt_client.publish(topic, json.dumps(payload), qos=1, retain=False)
    if resultado.rc != 0:
        raise RuntimeError(f'No se pudo publicar el comando en {topic} (rc={resultado.rc})')

    db.registrar_comando_enviado(device_id, valvula, accion, payload)
    logger.info('comando enviado a %s: %s', device_id, payload)
    return resultado
