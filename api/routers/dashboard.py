from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mqtt_agrohub import db

from ..auth import requiere_api_key

router = APIRouter(prefix='/dashboard', tags=['dashboard'], dependencies=[Depends(requiere_api_key)])

# Ventana usada para decidir "conectado ahora" cuando no hay un status/LWT reciente que lo diga
# explícitamente — coincide con la ventana de 3 minutos del manual (sección 08) para el failover
# de nube->local, mismo criterio con el que el propio gateway decide "perdí la nube".
VENTANA_CONEXION = timedelta(minutes=3)


def _resumen_dispositivo(device_id):
    health = db.ultimo_health(device_id)
    conexion = db.ultimo_estado_conexion(device_id)
    ambiente = db.ultima_lectura_ambiente(device_id)
    suelo = db.ultima_lectura_suelo(device_id)
    valvulas = db.ultimo_estado_valvula(device_id)

    ultimo_visto = None
    for fila, campo in ((health, 'medido_en'), (ambiente, 'medido_en'), (suelo, 'medido_en')):
        if fila and fila.get(campo):
            ultimo_visto = max(ultimo_visto, fila[campo]) if ultimo_visto else fila[campo]

    en_linea = bool(
        conexion and conexion['estado'] == 'online'
        and ultimo_visto and (datetime.now(timezone.utc) - ultimo_visto) <= VENTANA_CONEXION
    )

    return {
        'device_id': device_id,
        'en_linea': en_linea,
        'ultimo_visto': ultimo_visto,
        'modo_control': health['modo_control'] if health else None,
        'ambiente': ambiente,
        'suelo': suelo,
        'valvulas': valvulas,
        'health': health,
    }


@router.get('/resumen')
def resumen():
    """Vista general: todos los dispositivos activos con su último dato de cada tipo — la
    variables que se están enviando ahora mismo, de un vistazo."""
    dispositivos = db.listar_dispositivos(solo_activos=True)
    return [_resumen_dispositivo(d['device_id']) for d in dispositivos]


@router.get('/{device_id}')
def detalle(device_id: str):
    dispositivo = db.obtener_dispositivo(device_id)
    if not dispositivo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el dispositivo '{device_id}'.")
    return _resumen_dispositivo(device_id)


@router.get('/{device_id}/lecturas/ambiente')
def lecturas_ambiente(
    device_id: str,
    desde: datetime = Query(default=None),
    hasta: datetime = Query(default=None),
    limite: int = Query(default=500, le=5000),
):
    hasta = hasta or datetime.now(timezone.utc)
    desde = desde or (hasta - timedelta(days=7))
    return db.lecturas_ambiente_rango(device_id, desde, hasta, limite)


@router.get('/{device_id}/lecturas/suelo')
def lecturas_suelo(
    device_id: str,
    desde: datetime = Query(default=None),
    hasta: datetime = Query(default=None),
    limite: int = Query(default=500, le=5000),
):
    hasta = hasta or datetime.now(timezone.utc)
    desde = desde or (hasta - timedelta(days=7))
    return db.lecturas_suelo_rango(device_id, desde, hasta, limite)
