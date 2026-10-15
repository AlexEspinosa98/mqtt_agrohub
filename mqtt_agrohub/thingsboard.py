"""Reenvío OPCIONAL de la telemetría a ThingsBoard (plataforma de Energesis) — apagado por defecto.

Nuestro Mosquitto sigue siendo la fuente de verdad: este módulo solo copia hacia ThingsBoard lo que
el daemon ya recibe de los gateways. Nunca recibe comandos de allá, y un fallo de ThingsBoard
(caído, token malo, red) no puede afectar el guardado en nuestra base: todo va por una cola y un
hilo aparte, y `reenviar()` jamás lanza ni bloquea.

Dos modos, según qué credenciales entregue Energesis (ver config.py):
  - por dispositivo (el normal): cada dispositivo NUESTRO se enlaza a uno de ThingsBoard con una fila
    de la tabla `enlaces_energesis` (device0001 nuestro = token del device 1 de ellos), que se
    administra desde la API del backend. Publica en v1/devices/me/telemetry {"ts":ms,"values":{...}}.
    La tabla se relee cada 30 s: un enlace nuevo, cambiado, desactivado o borrado aplica sin
    reiniciar. THINGSBOARD_TOKENS del .env sigue valiendo como respaldo (la base manda).
  - gateway: un solo token de dispositivo tipo "gateway" en el .env -> v1/gateway/telemetry con
    {"device0014":[{"ts":ms,"values":{...}}]} (ThingsBoard relaciona los dispositivos por nombre)

Los tokens salen de la base o del entorno, nunca del código ni del repo. El puerto 1884 de Energesis
no usa TLS (verificado), así que el token viaja sin cifrar mientras no habiliten un puerto seguro.
"""
import json
import logging
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request
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


REFRESCO_ENLACES_SEGUNDOS = 30


class ReenviadorThingsBoard:
    def __init__(self, host, port, usar_tls, tokens, token_gateway, maxsize=2000,
                 fuente_tokens=None, registrar_estado=None, refresco=REFRESCO_ENLACES_SEGUNDOS,
                 transporte='mqtt'):
        """`tokens`: respaldo estático {device_id: token} (el .env). `fuente_tokens`: callable que
        devuelve los enlaces vigentes {device_id: token} (la base); si da algo, pisa al respaldo.
        `registrar_estado(device_id, ultimo_envio_en=None, error=None)`: deja en la base lo que
        pasó con el envío. Ambos son opcionales para poder probar esto sin base de datos."""
        self._host = host
        self._port = port
        self._usar_tls = usar_tls
        self._respaldo = dict(tokens or {})
        self._tokens = dict(self._respaldo)
        self._token_gateway = token_gateway or None
        self._fuente_tokens = fuente_tokens
        self._registrar_estado = registrar_estado
        self._refresco = refresco
        self._http = transporte == 'http' and not token_gateway  # HTTP(S): solo modo por dispositivo
        self._cola = queue.Queue(maxsize=maxsize)
        self._clientes = {}  # token -> cliente paho (uno por conexión)
        self._ultimo_ok = {}      # device_id -> datetime del último PUBACK de ThingsBoard
        self._ultimo_error = {}   # device_id -> texto del último fallo de conexión
        self._pendientes_estado = set()
        self._detener = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, name='thingsboard', daemon=True)

    @property
    def modo(self):
        return 'gateway' if self._token_gateway else 'dispositivo'

    def iniciar(self):
        self._refrescar_enlaces()
        self._hilo.start()
        logger.info(
            'reenvío a ThingsBoard activo (%s:%s, modo %s, tls=%s, %d dispositivos enlazados)',
            self._host, self._port, 'http' if self._http else self.modo, self._usar_tls, len(self._tokens),
        )

    def detener(self):
        self._detener.set()
        self._hilo.join(timeout=5)
        self._volcar_estado()
        for cliente in list(self._clientes.values()):
            cliente.loop_stop()
            cliente.disconnect()

    def _refrescar_enlaces(self):
        """Relee los enlaces de la base y cierra las conexiones de los que cambiaron o se fueron."""
        if self._fuente_tokens is None or self._token_gateway:
            return
        try:
            desde_base = self._fuente_tokens()
        except Exception:
            logger.exception('no se pudieron leer los enlaces con ThingsBoard — se conservan los anteriores')
            return
        nuevos = {**self._respaldo, **desde_base}
        if nuevos == self._tokens:
            return
        en_uso = set(nuevos.values())
        for token in [t for t in self._clientes if t not in en_uso]:
            cliente = self._clientes.pop(token)
            cliente.loop_stop()
            cliente.disconnect()
        logger.info('enlaces con ThingsBoard actualizados: %d dispositivos', len(nuevos))
        self._tokens = nuevos

    def _volcar_estado(self):
        """Pasa a la base el último envío exitoso / error de cada dispositivo (para verlo en la API)."""
        if self._registrar_estado is None:
            return
        for device_id in list(self._pendientes_estado):
            self._pendientes_estado.discard(device_id)
            try:
                error = self._ultimo_error.get(device_id)
                if error:
                    self._registrar_estado(device_id, error=error)
                elif device_id in self._ultimo_ok:
                    self._registrar_estado(device_id, ultimo_envio_en=self._ultimo_ok[device_id])
            except Exception:
                logger.exception('no se pudo registrar el estado del envío de %s', device_id)

    def encolar(self, device_id, subtopico, payload):
        """Nunca bloquea ni lanza: con la cola llena descarta el mensaje y lo registra."""
        try:
            self._cola.put_nowait((device_id, subtopico, payload))
        except queue.Full:
            logger.warning('cola de ThingsBoard llena, se descarta un mensaje de %s/%s', device_id, subtopico)

    def _cliente(self, token, client_id, device_id=None):
        if token not in self._clientes:
            cliente = mqtt.Client(client_id=client_id, clean_session=True, userdata=device_id)
            cliente.username_pw_set(token)  # ThingsBoard: el token va como usuario, sin contraseña
            if self._usar_tls:
                cliente.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            cliente.max_queued_messages_set(1000)
            cliente.reconnect_delay_set(min_delay=1, max_delay=60)
            cliente.on_connect = self._on_connect
            cliente.on_disconnect = self._on_disconnect
            cliente.on_publish = self._on_publish
            cliente.connect_async(self._host, self._port, keepalive=30)
            cliente.loop_start()
            self._clientes[token] = cliente
        return self._clientes[token]

    def _marcar(self, device_id, ok=None, error=None):
        if device_id is None:
            return
        if ok is not None:
            self._ultimo_ok[device_id] = ok
            self._ultimo_error.pop(device_id, None)
        if error is not None:
            self._ultimo_error[device_id] = error
        self._pendientes_estado.add(device_id)

    def _on_connect(self, client, device_id, flags, rc):
        if rc == 0:
            logger.info('ThingsBoard conectado (%s)', device_id or 'gateway')
        else:
            logger.error('ThingsBoard rechazó la conexión de %s (rc=%s)', device_id or 'gateway', rc)
            self._marcar(device_id, error=f'ThingsBoard rechazó la conexión (rc={rc}): revisa el token')

    def _on_disconnect(self, client, device_id, rc):
        if rc != 0:
            self._marcar(device_id, error=f'conexión con ThingsBoard perdida (rc={rc})')

    def _on_publish(self, client, device_id, mid):
        self._marcar(device_id, ok=datetime.now(timezone.utc))

    def _publicar(self, device_id, subtopico, payload):
        ts, values = aplanar(subtopico, payload)
        if not values:
            return
        punto = {'ts': ts, 'values': values}
        if self._http:
            token = self._tokens.get(device_id)
            if token:
                self._publicar_http(device_id, token, punto)
            return
        if self._token_gateway:
            cliente = self._cliente(self._token_gateway, 'agrohub-thingsboard-gateway')
            topic, cuerpo = TOPIC_GATEWAY, {device_id: [punto]}
        else:
            token = self._tokens.get(device_id)
            if not token:
                logger.debug('sin token de ThingsBoard para %s, no se reenvía', device_id)
                return
            cliente = self._cliente(token, f'agrohub-thingsboard-{device_id}', device_id)
            topic, cuerpo = TOPIC_DISPOSITIVO, punto
        cliente.publish(topic, json.dumps(cuerpo, ensure_ascii=False), qos=1)

    def _publicar_http(self, device_id, token, punto):
        """POST https://host[:puerto]/api/v1/<token>/telemetry — la API HTTP de ThingsBoard, que en
        Energesis va por HTTPS (a diferencia de su MQTT en el 1884, sin cifrar)."""
        esquema = 'https' if self._usar_tls else 'http'
        url = f'{esquema}://{self._host}:{self._port}/api/v1/{token}/telemetry'
        req = urllib.request.Request(url, data=json.dumps(punto, ensure_ascii=False).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
            self._marcar(device_id, ok=datetime.now(timezone.utc))
        except urllib.error.HTTPError as exc:
            self._marcar(device_id, error=f'ThingsBoard respondió HTTP {exc.code}' + (' (token inválido)' if exc.code in (401, 404) else ''))
        except (urllib.error.URLError, OSError) as exc:
            self._marcar(device_id, error=f'no se pudo contactar a ThingsBoard: {exc}')

    def _bucle(self):
        proximo_refresco = time.monotonic() + self._refresco
        while not self._detener.is_set():
            if time.monotonic() >= proximo_refresco:
                self._refrescar_enlaces()
                self._volcar_estado()
                proximo_refresco = time.monotonic() + self._refresco
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
    """Arranca el reenvío si THINGSBOARD_ENABLED=true. Los enlaces por dispositivo salen de la tabla
    enlaces_energesis (administrada desde la API); puede arrancar sin ninguno y los toma cuando
    se creen. Con token de gateway en el .env usa ese modo en su lugar."""
    global _instancia
    if not config.THINGSBOARD_ENABLED:
        return None
    from . import db
    _instancia = ReenviadorThingsBoard(
        config.THINGSBOARD_HOST, config.THINGSBOARD_PORT, config.THINGSBOARD_USE_TLS,
        config.THINGSBOARD_TOKENS, config.THINGSBOARD_GATEWAY_TOKEN,
        transporte=config.THINGSBOARD_TRANSPORT,
        fuente_tokens=db.listar_enlaces_energesis_activos,
        registrar_estado=db.registrar_estado_envio_energesis,
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
