"""Latido de nube — ver README ("Por qué el latido de nube es la parte más delicada") y
docs/TOPICS.md. Mientras este latido llegue cada <=3 min, los gateways dejan el control de riego
en manos de la nube; si se detiene, cada gateway pasa a control local automáticamente. Por eso
corre en su propio hilo, independiente del procesamiento de mensajes entrantes, y por eso NUNCA
se publica con retain=True — un latido retenido engañaría a un gateway que reconecta creyendo
que la nube sigue viva."""
import json
import logging
import threading
from datetime import datetime, timezone

from . import config

logger = logging.getLogger(__name__)


class HiloLatido(threading.Thread):
    def __init__(self, mqtt_client):
        super().__init__(name='latido-nube', daemon=True)
        self._client = mqtt_client
        self._detener = threading.Event()

    def run(self):
        logger.info(
            'latido de nube iniciado: tópico=%s intervalo=%ss',
            config.CLOUD_HEALTH_TOPIC, config.CLOUD_HEALTH_INTERVAL_SECONDS,
        )
        while not self._detener.is_set():
            payload = json.dumps({
                'ts': datetime.now(timezone.utc).isoformat(),
                'estado': 'activo',
            })
            resultado = self._client.publish(
                config.CLOUD_HEALTH_TOPIC, payload, qos=0, retain=False,
            )
            if resultado.rc != 0:
                logger.warning('no se pudo publicar el latido de nube (rc=%s)', resultado.rc)
            else:
                logger.debug('latido de nube publicado')
            self._detener.wait(config.CLOUD_HEALTH_INTERVAL_SECONDS)

    def detener(self):
        self._detener.set()
