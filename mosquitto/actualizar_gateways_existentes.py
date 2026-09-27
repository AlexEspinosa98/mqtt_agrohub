#!/usr/bin/env python3
"""Parcha los bloques ACL de los gateways YA DADOS DE ALTA (agregar_gateway.sh solo aplica a
los nuevos) para que coincidan con la plantilla actualizada 2026-09-27:

  - agrega  `topic write ahub/<device_id>/config/state`      (tópico nuevo, faltaba)
  - agrega  `topic read  ahub/<device_id>/config/state`      (mismo patrón "leer lo propio" que
                                                                ya tienen data/valvulas/health/status)
  - agrega  `topic read  ahub/+/control/valvulas`             (ahora comodín, no por dispositivo)
  - agrega  `topic read  ahub/+/config/set`                   (tópico nuevo)
  - agrega  `topic read  ahub/+/cloud/health`                 (tópico nuevo, coexiste con
                                                                 iotunimagdalena/cloud/health)
  - dentro de un bloque de gateway (`# --- ug56-agrohubN (deviceXXXX) ---`), NUNCA toca las
    líneas de iotunimagdalena-persister ni de otros usuarios.

Idempotente: si una línea ya está, no la duplica -- se puede correr más de una vez sin riesgo.
Nunca borra nada, solo agrega lo que falte.

Uso: sudo python3 actualizar_gateways_existentes.py [--dry-run]
  --dry-run: solo imprime qué cambiaría, no toca el archivo ni recarga el broker.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ACL_FILE = Path("/etc/mosquitto/acl.conf")

BLOQUE_RE = re.compile(
    r"^# --- (ug56-agrohub\d+) \((device\d+)\) ---$"
)

LINEAS_NUEVAS_TEMPLATE = [
    "topic write ahub/{device_id}/config/state",
    "topic read  ahub/{device_id}/config/state",
    "topic read  ahub/+/control/valvulas",
    "topic read  ahub/+/config/set",
    "topic read  ahub/+/cloud/health",
]


def parchear(contenido: str) -> tuple[str, list[str]]:
    lineas = contenido.splitlines()
    salida: list[str] = []
    resumen: list[str] = []

    i = 0
    while i < len(lineas):
        linea = lineas[i]
        salida.append(linea)
        m = BLOQUE_RE.match(linea.strip())
        if not m:
            i += 1
            continue

        client_id, device_id = m.group(1), m.group(2)

        # Recolectar el resto del bloque (hasta la próxima línea en blanco o el próximo
        # "# ---", lo que llegue primero) para saber qué líneas ya tiene.
        j = i + 1
        bloque_existente = []
        while j < len(lineas) and lineas[j].strip() != "" and not lineas[j].strip().startswith("# ---"):
            bloque_existente.append(lineas[j])
            salida.append(lineas[j])
            j += 1

        faltantes = [
            linea_nueva.format(device_id=device_id)
            for linea_nueva in LINEAS_NUEVAS_TEMPLATE
            if linea_nueva.format(device_id=device_id) not in bloque_existente
        ]
        if faltantes:
            salida.extend(faltantes)
            resumen.append(f"{client_id} ({device_id}): +{len(faltantes)} línea(s) -> {faltantes}")

        i = j

    return "\n".join(salida) + ("\n" if contenido.endswith("\n") else ""), resumen


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    if not ACL_FILE.exists():
        print(f"No existe {ACL_FILE}", file=sys.stderr)
        sys.exit(1)

    original = ACL_FILE.read_text()
    actualizado, resumen = parchear(original)

    if not resumen:
        print("Nada que hacer -- todos los gateways ya tienen los tópicos nuevos.")
        return

    print(f"Gateways a actualizar ({len(resumen)}):")
    for linea in resumen:
        print(f"  - {linea}")

    if dry_run:
        print("\n(--dry-run: no se modificó nada ni se recargó el broker)")
        return

    backup = ACL_FILE.with_suffix(f".conf.bak-{datetime.now():%Y%m%d%H%M%S}")
    backup.write_text(original)
    print(f"\nRespaldo del archivo original: {backup}")

    ACL_FILE.write_text(actualizado)
    print(f"Actualizado: {ACL_FILE}")

    subprocess.run(["sudo", "systemctl", "reload", "mosquitto"], check=True)
    print("Broker recargado (systemctl reload mosquitto).")


if __name__ == "__main__":
    main()
