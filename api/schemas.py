import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

DEVICE_ID_RE = re.compile(r'^[a-z0-9_-]{3,40}$')
CLIENT_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{3,60}$')


class DispositivoCrear(BaseModel):
    device_id: str
    client_id: str
    nombre: Optional[str] = None

    @field_validator('device_id')
    @classmethod
    def _validar_device_id(cls, v):
        if not DEVICE_ID_RE.match(v):
            raise ValueError(
                "device_id inválido — solo minúsculas, números, '-' y '_', 3 a 40 caracteres "
                "(convención del manual: 'device0001', 'device0002', ...)."
            )
        return v

    @field_validator('client_id')
    @classmethod
    def _validar_client_id(cls, v):
        if not CLIENT_ID_RE.match(v):
            raise ValueError("client_id inválido — 3 a 60 caracteres alfanuméricos, '-' o '_'.")
        return v


class DispositivoCreado(BaseModel):
    device_id: str
    client_id: str
    base_topic: str
    password: str
    nota: str = (
        'Guarda esta contraseña ahora — no se puede volver a consultar. Configurar en el '
        'gateway: host back.alunaia.co, puerto 8883, TLS, usuario y Client ID = client_id, '
        'keepalive 15s, clean session desactivado (ver manual UG56, sección 03).'
    )


class Dispositivo(BaseModel):
    device_id: str
    base_topic: Optional[str] = None
    client_id: Optional[str] = None
    nombre: Optional[str] = None
    activo: bool
    primera_vez_visto: Optional[datetime] = None
    ultima_vez_visto: Optional[datetime] = None


class PasswordRotado(BaseModel):
    client_id: str
    password: str
    nota: str = 'Guarda esta contraseña ahora y actualízala en el gateway — la anterior deja de funcionar de inmediato.'
