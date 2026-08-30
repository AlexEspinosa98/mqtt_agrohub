"""API de administración de mqtt_agrohub — dar de alta/baja gateways, rotar sus credenciales, y
consultar el dashboard de telemetría. Servicio HTTP separado del daemon de ingesta (main.py):
uno atiende mensajes MQTT sin parar, este atiende requests bajo demanda — mismo patrón que
CienaNet (FastAPI) en este servidor, ver systemd/mqtt-agrohub-api.service.

Arrancar en desarrollo: uvicorn api.main:app --reload --port 8005
"""
import logging

from fastapi import FastAPI

from mqtt_agrohub import config

from .routers import dashboard, dispositivos

logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)

app = FastAPI(
    title='mqtt_agrohub — API de administración',
    description=(
        'Alta/baja/rotación de credenciales de gateways AgroHub y dashboard de telemetría. '
        'Ver docs/TOPICS.md y el manual del UG56 para el origen de los datos.'
    ),
)

app.include_router(dispositivos.router)
app.include_router(dashboard.router)


@app.get('/salud')
def salud():
    return {'estado': 'ok'}
