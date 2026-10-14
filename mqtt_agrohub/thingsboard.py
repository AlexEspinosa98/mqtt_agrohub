"""Reenvío OPCIONAL de la telemetría a ThingsBoard (plataforma de Energesis) — apagado por defecto.

Nuestro Mosquitto sigue siendo la fuente de verdad: este módulo solo copia hacia ThingsBoard lo que
el daemon ya recibe de los gateways. Nunca recibe comandos de allá, y un fallo de ThingsBoard
(caído, token malo, red) no puede afectar el guardado en nuestra base: todo va por una cola y un
hilo aparte, y `reenviar()` jamás lanza ni bloquea.

Dos modos, según qué credenciales entregue Energesis (ver config.py):
  - por dispositivo: un token por gateway -> v1/devices/me/telemetry con {"ts":ms,"values":{...}}
  - gateway: un solo token de dispositivo tipo "gateway" -> v1/gateway/telemetry con
    {"device0014":[{"ts":ms,"values":{...}}]} (ThingsBoard crea/relaciona los dispositivos por nombre)

Los tokens salen solo del entorno (.env), nunca del código ni del repo. El puerto 1884 de Energesis
no usa TLS (verificado), así que el token viaja sin cifrar mientras no habiliten un puerto seguro.
"""
import json
import logging
import queue
import ssl
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from . import config

logger = logging.getLogger(__name__)

TOPIC_DISPOSITIVO = 'v1/devices/me/telemetry'
TOPIC_GATEWAY = 'v1/gateway/telemetry'

# Metadatos que no son telemetría (identifican el mensaje, no miden nada).
_EXCLUIDAS = {
    'ts', 'device', 'devEUI', 'measured_by', 'measured_at', 'zona', 'tipo', 'equipo', 'modelo',
    'guardado_en', 'reenviado_en',
}
# Sub-tópicos cuyas claves se repiten por zona (z1, z2, z3...) y por eso se prefijan con ella.
_CON_ZONA = {'data', 'valvulas/state'}


def _es_escalar(valor):
    return isinstance(valor, (bool, int, float, str)) and valor is not None


def _a_epoch_ms(payload):
    """ISO 8601 (con 'Z' u offset) -> milisegundos. Sin fecha utilizable, la hora actual."""
    crudo = payload.get('measured_at') or payload.get('ts')
    if isinstance(crudo, str):
        try:
            dt = datetime.fromisoformat(crudo.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def aplanar(subtopico, payload):
    """Payload de un gateway -> (ts_ms, values) con claves planas, el formato que ThingsBoard
    espera. Un nivel de anidamiento se aplana con '_' (radio.rssi -> radio_rssi); lo más profundo o
    las listas se serializan como texto. En data y valvulas/state las claves llevan el prefijo de la
    zona (z1_humedad_suelo), porque un gateway tiene varias zonas y se pisarían entre sí."""
    if not isinstance(payload, dict):
        return _a_epoch_ms({}), {'estado_conexion': str(payload).strip().lower()}

    prefijo = ''
    if subtopico in _CON_ZONA and payload.get('zona'):
        prefijo = f"{payload['zona']}_"

    values = {}
    for clave, valor in payload.items():
        if clave in _EXCLUIDAS:
            continue
        if _es_escalar(valor):
            values[f'{prefijo}{clave}'] = valor
        elif isinstance(valor, dict):
            for sub_clave, sub_valor in valor.items():
                values[f'{prefijo}{clave}_{sub_clave}'] = (
                    sub_valor if _es_escalar(sub_valor) else json.dumps(sub_valor, ensure_ascii=False)
                )
        elif isinstance(valor, list):
            values[f'{prefijo}{clave}'] = json.dumps(valor, ensure_ascii=False)
    return _a_epoch_ms(payload), values


class ReenviadorThingsBoard:
    def __init__(self, host, port, usar_tls, tokens, token_gateway, maxsize=2000):
        self._host = host
        self._port = port
        self._usar_tls = usar_tls
        self._tokens = dict(tokens or {})
        self._token_gateway = token_gateway or None
        self._cola = queue.Queue(maxsize=maxsize)
        self._clientes = {}  # token -> cliente paho (uno por conexión)
        self._detener = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, name='thingsboard', daemon=True)

    @property
    def modo(self):
        return 'gateway' if self._token_gateway else 'dispositivo'

    def iniciar(self):
        self._hilo.start()
        logger.info(
            'reenvío a ThingsBoard activo (%s:%s, modo %s, tls=%s)',
            self._host, self._port, self.modo, self._usar_tls,
        )

    def detener(self):
        self._detener.set()
        self._hilo.join(timeout=5)
        for cliente in self._clientes.values():
            cliente.loop_stop()
            cliente.disconnect()

    def encolar(self, device_id, subtopico, payload):
        """Nunca bloquea ni lanza: con la cola llena descarta el mensaje y lo registra."""
        try:
            self._cola.put_nowait((device_id, subtopico, payload))
        except queue.Full:
            logger.warning('cola de ThingsBoard llena, se descarta un mensaje de %s/%s', device_id, subtopico)

    def _cliente(self, token, client_id):
        if token not in self._clientes:
            cliente = mqtt.Client(client_id=client_id, clean_session=True)
            cliente.username_pw_set(token)  # ThingsBoard: el token va como usuario, sin contraseña
            if self._usar_tls:
                cliente.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            cliente.max_queued_messages_set(1000)
            cliente.reconnect_delay_set(min_delay=1, max_delay=60)
            cliente.on_connect = lambda c, u, f, rc: (
                logger.info('ThingsBoard conectado (%s)', client_id) if rc == 0
                else logger.error('ThingsBoard rechazó la conexión de %s (rc=%s)', client_id, rc)
            )
            cliente.connect_async(self._host, self._port, keepalive=30)
            cliente.loop_start()
            self._clientes[token] = cliente
        return self._clientes[token]

    def _publicar(self, device_id, subtopico, payload):
        ts, values = aplanar(subtopico, payload)
        if not values:
            return
        punto = {'ts': ts, 'values': values}
        if self._token_gateway:
            cliente = self._cliente(self._token_gateway, 'agrohub-thingsboard-gateway')
            topic, cuerpo = TOPIC_GATEWAY, {device_id: [punto]}
        else:
            token = self._tokens.get(device_id)
            if not token:
                logger.debug('sin token de ThingsBoard para %s, no se reenvía', device_id)
                return
            cliente = self._cliente(token, f'agrohub-thingsboard-{device_id}')
            topic, cuerpo = TOPIC_DISPOSITIVO, punto
        cliente.publish(topic, json.dumps(cuerpo, ensure_ascii=False), qos=1)

    def _bucle(self):
        while not self._detener.is_set():
            try:
                device_id, subtopico, payload = self._cola.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._publicar(device_id, subtopico, payload)
            except Exception:
                logger.exception('error reenviando a ThingsBoard (%s/%s)', device_id, subtopico)


_instancia = None


def iniciar():
    """Arranca el reenvío si THINGSBOARD_ENABLED=true y hay credenciales; si no, no hace nada."""
    global _instancia
    if not config.THINGSBOARD_ENABLED:
        return None
    if not config.THINGSBOARD_GATEWAY_TOKEN and not config.THINGSBOARD_TOKENS:
        logger.error('THINGSBOARD_ENABLED=true pero faltan THINGSBOARD_GATEWAY_TOKEN o THINGSBOARD_TOKENS — reenvío desactivado')
        return None
    _instancia = ReenviadorThingsBoard(
        config.THINGSBOARD_HOST, config.THINGSBOARD_PORT, config.THINGSBOARD_USE_TLS,
        config.THINGSBOARD_TOKENS, config.THINGSBOARD_GATEWAY_TOKEN,
    )
    _instancia.iniciar()
    return _instancia


def detener():
    if _instancia:
        _instancia.detener()


def reenviar(device_id, subtopico, payload):
    """Punto de enganche para handlers.despachar. No-op si el reenvío está apagado; jamás lanza."""
    if _instancia is None:
        return
    try:
        _instancia.encolar(device_id, subtopico, payload)
    except Exception:
        logger.exception('no se pudo encolar para ThingsBoard')
