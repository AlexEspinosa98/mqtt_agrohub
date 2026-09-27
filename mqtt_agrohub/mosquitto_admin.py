"""Administra credenciales y ACLs de Mosquitto — la versión "por API" de
mosquitto/agregar_gateway.sh, con la misma forma de bloque de ACL (ver docs/TOPICS.md: cada
gateway solo puede tocar su propio namespace, nunca uno genérico).

Requiere que el proceso que corre la API pueda:
  1. Escribir en MOSQUITTO_PASSWD_FILE y MOSQUITTO_ACL_FILE (permisos de grupo, ver README —
     sección "API de administración").
  2. Ejecutar `sudo systemctl reload mosquitto` sin contraseña — una regla de sudoers acotada a
     ESE comando exacto, nada más (ver README). Sin esto, los cambios quedan escritos en disco
     pero Mosquitto no los toma hasta el próximo reinicio manual.
"""
import logging
import re
import subprocess

from . import config

logger = logging.getLogger(__name__)


class MosquittoAdminError(Exception):
    pass


def _bloque_acl(client_id, device_id):
    return (
        f"\n# --- {client_id} ({device_id}) ---\n"
        f"user {client_id}\n"
        f"topic write ahub/{device_id}/data\n"
        f"topic read  ahub/{device_id}/data\n"
        f"topic write ahub/{device_id}/valvulas/state\n"
        f"topic read  ahub/{device_id}/valvulas/state\n"
        f"topic write ahub/{device_id}/health\n"
        f"topic read  ahub/{device_id}/health\n"
        f"topic write ahub/{device_id}/status\n"
        f"topic read  ahub/{device_id}/status\n"
        f"topic read  ahub/{device_id}/control/valvulas\n"
        f"topic read  iotunimagdalena/cloud/health\n"
    )


def _recargar_mosquitto():
    resultado = subprocess.run(
        ['sudo', '-n', 'systemctl', 'reload', 'mosquitto'],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        raise MosquittoAdminError(
            f'No se pudo recargar Mosquitto (código {resultado.returncode}): '
            f'{resultado.stderr.strip()}. Verifica la regla de sudoers — ver README.'
        )


def _existe_en_acl(client_id):
    try:
        with open(config.MOSQUITTO_ACL_FILE) as f:
            contenido = f.read()
    except FileNotFoundError:
        return False
    return re.search(rf'^user {re.escape(client_id)}$', contenido, re.MULTILINE) is not None


def crear_credencial(client_id, device_id, password):
    """Crea (o sobrescribe) el usuario en el passwd file y agrega su bloque de ACL. No recarga
    Mosquitto — llamar a _recargar_mosquitto() (o dejar que el caller agrupe varios cambios)."""
    if _existe_en_acl(client_id):
        raise MosquittoAdminError(f"Ya existe una credencial para '{client_id}'.")

    resultado = subprocess.run(
        ['mosquitto_passwd', '-b', config.MOSQUITTO_PASSWD_FILE, client_id, password],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        raise MosquittoAdminError(f'mosquitto_passwd falló: {resultado.stderr.strip()}')

    with open(config.MOSQUITTO_ACL_FILE, 'a') as f:
        f.write(_bloque_acl(client_id, device_id))

    _recargar_mosquitto()
    logger.info('credencial creada: client_id=%s device_id=%s', client_id, device_id)


def eliminar_credencial(client_id):
    """Elimina el usuario del passwd file y su bloque de ACL — corta el acceso al gateway de
    inmediato tras la recarga. No borra los datos históricos en Postgres (eso lo decide la API,
    marcando el dispositivo inactivo, no borrando sus lecturas)."""
    resultado = subprocess.run(
        ['mosquitto_passwd', '-D', config.MOSQUITTO_PASSWD_FILE, client_id],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        raise MosquittoAdminError(f'mosquitto_passwd -D falló: {resultado.stderr.strip()}')

    with open(config.MOSQUITTO_ACL_FILE) as f:
        contenido = f.read()
    nuevo_contenido = re.sub(
        rf'\n# --- {re.escape(client_id)} \([^)]*\) ---\nuser {re.escape(client_id)}\n'
        rf'(?:topic .+\n)+',
        '',
        contenido,
    )
    with open(config.MOSQUITTO_ACL_FILE, 'w') as f:
        f.write(nuevo_contenido)

    _recargar_mosquitto()
    logger.info('credencial eliminada: client_id=%s', client_id)


def rotar_password(client_id, password_nuevo):
    resultado = subprocess.run(
        ['mosquitto_passwd', '-b', config.MOSQUITTO_PASSWD_FILE, client_id, password_nuevo],
        capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        raise MosquittoAdminError(f'mosquitto_passwd falló: {resultado.stderr.strip()}')
    _recargar_mosquitto()
    logger.info('password rotado: client_id=%s', client_id)
