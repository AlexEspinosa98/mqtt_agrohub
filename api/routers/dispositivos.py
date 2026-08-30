import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from mqtt_agrohub import db
from mqtt_agrohub.mosquitto_admin import MosquittoAdminError, crear_credencial, eliminar_credencial, rotar_password

from ..auth import requiere_api_key
from ..schemas import Dispositivo, DispositivoCrear, DispositivoCreado, PasswordRotado

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/dispositivos', tags=['dispositivos'], dependencies=[Depends(requiere_api_key)])


def _generar_password():
    return secrets.token_hex(16)


@router.get('', response_model=list[Dispositivo])
def listar(solo_activos: bool = False):
    return db.listar_dispositivos(solo_activos=solo_activos)


@router.get('/{device_id}', response_model=Dispositivo)
def obtener(device_id: str):
    dispositivo = db.obtener_dispositivo(device_id)
    if not dispositivo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el dispositivo '{device_id}'.")
    return dispositivo


@router.post('', response_model=DispositivoCreado, status_code=status.HTTP_201_CREATED)
def crear(payload: DispositivoCrear):
    existente = db.obtener_dispositivo(payload.device_id)
    if existente and existente['activo']:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Ya existe un dispositivo activo con device_id '{payload.device_id}'. "
            f"Elimínalo primero o usa otro device_id.",
        )

    base_topic = f'ahub/{payload.device_id}'
    password = _generar_password()

    try:
        crear_credencial(payload.client_id, payload.device_id, password)
    except MosquittoAdminError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    db.crear_dispositivo(payload.device_id, base_topic, payload.client_id, payload.nombre)

    return DispositivoCreado(
        device_id=payload.device_id,
        client_id=payload.client_id,
        base_topic=base_topic,
        password=password,
    )


@router.delete('/{device_id}', status_code=status.HTTP_204_NO_CONTENT)
def eliminar(device_id: str):
    dispositivo = db.obtener_dispositivo(device_id)
    if not dispositivo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el dispositivo '{device_id}'.")
    if not dispositivo['client_id']:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{device_id}' no tiene client_id registrado (fue creado antes de esta API, o solo "
            f"se detectó por telemetría) — elimina su credencial a mano en Mosquitto primero.",
        )

    try:
        eliminar_credencial(dispositivo['client_id'])
    except MosquittoAdminError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    db.marcar_dispositivo_inactivo(device_id)
    # Las lecturas históricas NO se borran — solo se corta el acceso y se marca inactivo.


@router.post('/{device_id}/rotar-password', response_model=PasswordRotado)
def rotar(device_id: str):
    dispositivo = db.obtener_dispositivo(device_id)
    if not dispositivo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el dispositivo '{device_id}'.")
    if not dispositivo['client_id']:
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{device_id}' no tiene client_id registrado.")

    password = _generar_password()
    try:
        rotar_password(dispositivo['client_id'], password)
    except MosquittoAdminError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    return PasswordRotado(client_id=dispositivo['client_id'], password=password)
