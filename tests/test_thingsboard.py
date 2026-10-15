"""Pruebas del reenvío a ThingsBoard. Las de integración levantan un Mosquitto LOCAL que imita a
ThingsBoard (nunca se conectan a Energesis ni usan tokens reales) y se saltan si no hay `mosquitto`."""
import json
import os
import shutil
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'postgresql://x:x@localhost/x')  # config.py exige la variable

import paho.mqtt.client as mqtt  # noqa: E402

# mqtt_agrohub.db abre un pool de Postgres al importarse; estas pruebas no necesitan base de datos.
sys.modules.setdefault('mqtt_agrohub.db', mock.MagicMock())

from mqtt_agrohub import handlers, thingsboard  # noqa: E402
from mqtt_agrohub.topics import parsear  # noqa: E402

PUERTO = 18884


class TestAplanar(unittest.TestCase):
    def test_suelo_prefija_zona_y_aplana_radio(self):
        ts, v = thingsboard.aplanar('data', {
            'ts': '2026-10-04T16:02:38.218Z', 'tipo': 'suelo', 'zona': 'z3', 'devEUI': 'a840', 'equipo': 'SE01-03',
            'humedad_suelo': 34.46, 'sonda_ok': True, 'bateria_v': 3.1, 'radio': {'rssi': -76, 'snr': 13.5},
        })
        self.assertEqual(ts, 1791129758218)
        self.assertEqual(v, {'z3_humedad_suelo': 34.46, 'z3_sonda_ok': True, 'z3_bateria_v': 3.1,
                             'z3_radio_rssi': -76, 'z3_radio_snr': 13.5})

    def test_ambiente_sin_zona_no_lleva_prefijo(self):
        _, v = thingsboard.aplanar('data', {'ts': '2026-10-04T16:00:00Z', 'temperatura': 28.1, 'humedad': 70})
        self.assertEqual(v, {'temperatura': 28.1, 'humedad': 70})

    def test_valvulas_con_zona(self):
        _, v = thingsboard.aplanar('valvulas/state', {'ts': '2026-10-04T14:32:39.561Z', 'zona': 'z3',
                                                      'RO1': 'desconocido', 'RO2': 'abierta', 'confirmada': False})
        self.assertEqual(v, {'z3_RO1': 'desconocido', 'z3_RO2': 'abierta', 'z3_confirmada': False})

    def test_health_anidado_y_listas_se_serializan(self):
        _, v = thingsboard.aplanar('health', {'modo_control': 'local', 'zonas_auto': {'z1': True},
                                              'valvulas_sin_confirmar': ['RO1'], 'config_rev': 8})
        self.assertEqual(v['modo_control'], 'local')
        self.assertEqual(v['zonas_auto_z1'], True)
        self.assertEqual(v['valvulas_sin_confirmar'], '["RO1"]')
        self.assertEqual(v['config_rev'], 8)

    def test_status_texto(self):
        _, v = thingsboard.aplanar('status', 'ONLINE\n')
        self.assertEqual(v, {'estado_conexion': 'online'})

    def test_ts_con_offset_y_sin_fecha(self):
        a, _ = thingsboard.aplanar('data', {'ts': '2026-10-04T11:02:38.218-05:00', 'temperatura': 1})
        self.assertEqual(a, 1791129758218)
        ahora = int(time.time() * 1000)
        b, _ = thingsboard.aplanar('data', {'temperatura': 1})
        self.assertLess(abs(b - ahora), 5000)


class TestTransporteHttp(unittest.TestCase):
    def test_http_publica_en_api_v1_token_telemetry_y_registra_estado(self):
        import http.server
        recibido = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                recibido.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200 if 'BUENO' in self.path else 401)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(('127.0.0.1', 18885), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = thingsboard.ReenviadorThingsBoard('127.0.0.1', 18885, False, {'d1': 'TOKEN_BUENO', 'd2': 'TOKEN_MALO'}, None,
                                                  transporte='http')
            r._publicar('d1', 'data', {'ts': '2026-10-04T16:02:38.218Z', 'zona': 'z3', 'humedad_suelo': 34.46})
            r._publicar('d2', 'data', {'temperatura': 5})
            self.assertEqual(recibido[0], ('/api/v1/TOKEN_BUENO/telemetry',
                                           {'ts': 1791129758218, 'values': {'z3_humedad_suelo': 34.46}}))
            self.assertIn('d1', r._ultimo_ok)
            self.assertIn('401', r._ultimo_error['d2'])
        finally:
            srv.shutdown()


class TestApagado(unittest.TestCase):
    def test_reenviar_apagado_es_noop(self):
        thingsboard._instancia = None
        thingsboard.reenviar('device0014', 'data', {'temperatura': 1})  # no debe lanzar

    def test_cola_llena_no_lanza_ni_bloquea(self):
        r = thingsboard.ReenviadorThingsBoard('localhost', 1, False, {'d': 't'}, None, maxsize=2)
        for _ in range(5):
            r.encolar('d', 'data', {'temperatura': 1})
        self.assertEqual(r._cola.qsize(), 2)


@unittest.skipUnless(shutil.which('mosquitto'), 'requiere mosquitto local')
class TestIntegracionBrokerFalso(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        conf = os.path.join(cls.tmp, 'm.conf')
        open(conf, 'w').write(f'listener {PUERTO} 127.0.0.1\nallow_anonymous true\n')
        cls.broker = subprocess.Popen(['mosquitto', '-c', conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        cls.recibidos = []
        cls.espia = mqtt.Client(client_id='espia')
        cls.espia.on_message = lambda c, u, m: cls.recibidos.append((m.topic, json.loads(m.payload)))
        cls.espia.connect('127.0.0.1', PUERTO)
        cls.espia.subscribe('v1/#', qos=1)
        cls.espia.loop_start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.espia.loop_stop()
        cls.broker.terminate()
        cls.broker.wait(timeout=5)

    def _esperar(self, n, timeout=8):
        fin = time.time() + timeout
        while time.time() < fin and len(self.recibidos) < n:
            time.sleep(0.1)

    def test_modo_dispositivo_publica_con_token_como_usuario(self):
        self.recibidos.clear()
        r = thingsboard.ReenviadorThingsBoard('127.0.0.1', PUERTO, False, {'device0014': 'TOKEN_FALSO_14'}, None)
        r.iniciar()
        try:
            r.encolar('device0014', 'data', {'ts': '2026-10-04T16:02:38.218Z', 'zona': 'z3', 'humedad_suelo': 34.46})
            r.encolar('device0099', 'data', {'temperatura': 5})  # sin token -> no se reenvía
            self._esperar(1)
            self.assertEqual(len(self.recibidos), 1)
            topic, cuerpo = self.recibidos[0]
            self.assertEqual(topic, 'v1/devices/me/telemetry')
            self.assertEqual(cuerpo, {'ts': 1791129758218, 'values': {'z3_humedad_suelo': 34.46}})
            self.assertEqual(r._clientes['TOKEN_FALSO_14']._username, b'TOKEN_FALSO_14')
        finally:
            r.detener()

    def test_modo_gateway_agrupa_por_nombre_de_dispositivo(self):
        self.recibidos.clear()
        r = thingsboard.ReenviadorThingsBoard('127.0.0.1', PUERTO, False, {}, 'TOKEN_GATEWAY_FALSO')
        r.iniciar()
        try:
            r.encolar('device0014', 'status', 'online')
            r.encolar('device0002', 'valvulas/state', {'ts': '2026-10-04T14:32:39.561Z', 'zona': 'z1', 'RO1': 'abierta'})
            self._esperar(2)
            por_topic = {}
            for topic, cuerpo in self.recibidos:
                por_topic.setdefault(topic, []).append(cuerpo)
            self.assertEqual(set(por_topic), {'v1/gateway/telemetry'})
            nombres = sorted(k for cuerpo in por_topic['v1/gateway/telemetry'] for k in cuerpo)
            self.assertEqual(nombres, ['device0002', 'device0014'])
            self.assertEqual(r._clientes['TOKEN_GATEWAY_FALSO']._username, b'TOKEN_GATEWAY_FALSO')
        finally:
            r.detener()

    def test_enlaces_de_la_base_se_aplican_y_registran_estado(self):
        self.recibidos.clear()
        enlaces = {'device0001': 'TOKEN_FALSO_1'}
        estados = []
        r = thingsboard.ReenviadorThingsBoard(
            '127.0.0.1', PUERTO, False, {}, None,
            fuente_tokens=lambda: dict(enlaces),
            registrar_estado=lambda d, ultimo_envio_en=None, error=None: estados.append((d, ultimo_envio_en, error)),
            refresco=1,
        )
        r.iniciar()
        try:
            r.encolar('device0001', 'data', {'ts': '2026-10-04T16:02:38.218Z', 'temperatura': 20})
            r.encolar('device0002', 'data', {'temperatura': 21})  # aún sin enlace
            self._esperar(1)
            self.assertEqual(len(self.recibidos), 1)
            # se crea el enlace de device0002 y se cambia el token de device0001, sin reiniciar
            enlaces['device0002'] = 'TOKEN_FALSO_2'
            enlaces['device0001'] = 'TOKEN_FALSO_1B'
            time.sleep(1.6)
            self.recibidos.clear()
            r.encolar('device0001', 'data', {'temperatura': 22})
            r.encolar('device0002', 'data', {'temperatura': 23})
            self._esperar(2)
            self.assertEqual(len(self.recibidos), 2)
            self.assertNotIn('TOKEN_FALSO_1', r._clientes)
            self.assertIn('TOKEN_FALSO_1B', r._clientes)
            time.sleep(1.6)
            self.assertTrue(any(d == 'device0001' and ok is not None for d, ok, _ in estados))
            self.assertTrue(any(d == 'device0002' and ok is not None for d, ok, _ in estados))
        finally:
            r.detener()

    def test_enlace_desactivado_deja_de_reenviar(self):
        self.recibidos.clear()
        enlaces = {'device0001': 'TOKEN_FALSO_1'}
        r = thingsboard.ReenviadorThingsBoard('127.0.0.1', PUERTO, False, {}, None,
                                              fuente_tokens=lambda: dict(enlaces), refresco=1)
        r.iniciar()
        try:
            enlaces.clear()
            time.sleep(1.6)
            r.encolar('device0001', 'data', {'temperatura': 20})
            time.sleep(1.0)
            self.assertEqual(self.recibidos, [])
        finally:
            r.detener()

    def test_fallo_al_leer_la_base_conserva_enlaces(self):
        def rota():
            raise RuntimeError('base caída')
        r = thingsboard.ReenviadorThingsBoard('localhost', 1, False, {'d': 't'}, None, fuente_tokens=rota)
        r._refrescar_enlaces()
        self.assertEqual(r._tokens, {'d': 't'})

    def test_thingsboard_caido_no_bloquea_ni_lanza(self):
        r = thingsboard.ReenviadorThingsBoard('127.0.0.1', 1, False, {'device0014': 'T'}, None)  # puerto sin servicio
        r.iniciar()
        try:
            t0 = time.time()
            for _ in range(50):
                r.encolar('device0014', 'data', {'temperatura': 1})
            self.assertLess(time.time() - t0, 1.0)
        finally:
            r.detener()


class TestEnganceEnHandlers(unittest.TestCase):
    """handlers.despachar guarda en la base y DESPUÉS copia a ThingsBoard; un fallo de la copia
    nunca debe impedir ni deshacer el guardado."""

    def tearDown(self):
        thingsboard._instancia = None

    def test_guarda_en_base_y_reenvia_cada_subtopico(self):
        falso = mock.Mock()
        thingsboard._instancia = falso
        with mock.patch.object(handlers, 'db') as db:
            handlers.despachar(parsear('ahub/device0014/data'), json.dumps({'zona': 'z1', 'humedad_suelo': 12.3}).encode())
            handlers.despachar(parsear('ahub/device0014/status'), b'online')
            handlers.despachar(parsear('ahub/device0014/valvulas/state'), json.dumps({'zona': 'z1', 'RO1': 'abierta'}).encode())
            handlers.despachar(parsear('ahub/device0014/health'), json.dumps({'config_rev': 8}).encode())
        db.insertar_lectura_suelo.assert_called_once()
        db.insertar_estado_conexion.assert_called_once()
        db.insertar_estado_valvula.assert_called_once()
        db.insertar_healthcheck.assert_called_once()
        self.assertEqual([c.args[1] for c in falso.encolar.call_args_list],
                         ['data', 'status', 'valvulas/state', 'health'])

    def test_fallo_del_reenvio_no_rompe_el_guardado(self):
        falso = mock.Mock()
        falso.encolar.side_effect = RuntimeError('thingsboard roto')
        thingsboard._instancia = falso
        with mock.patch.object(handlers, 'db') as db:
            handlers.despachar(parsear('ahub/device0014/data'), json.dumps({'humedad_suelo': 5}).encode())
        db.insertar_lectura_suelo.assert_called_once()  # se guardó igual y no se propagó el error

    def test_json_invalido_no_se_reenvia(self):
        falso = mock.Mock()
        thingsboard._instancia = falso
        with mock.patch.object(handlers, 'db'):
            handlers.despachar(parsear('ahub/device0014/data'), b'no es json')
        falso.encolar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
