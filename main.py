import logging
import signal
import time

from mqtt_agrohub import config
from mqtt_agrohub.client import iniciar

logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger('mqtt_agrohub')


def main():
    client, latido = iniciar()

    detener = {'flag': False}

    def _manejar_senal(signum, frame):
        logger.info('señal %s recibida, cerrando...', signum)
        detener['flag'] = True

    signal.signal(signal.SIGTERM, _manejar_senal)
    signal.signal(signal.SIGINT, _manejar_senal)

    try:
        while not detener['flag']:
            time.sleep(1)
    finally:
        latido.detener()
        client.loop_stop()
        client.disconnect()
        logger.info('detenido limpiamente')


if __name__ == '__main__':
    main()
