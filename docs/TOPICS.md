# Tópicos MQTT — referencia rápida

Extraído de `SL-ENT-2026-001 Manual de Usuario - Gateway Riego UG56 - AgroHub.pdf`, sección 06.
Ante cualquier duda, esa es la fuente autoritativa — esto es solo un resumen para no tener que
reabrir el PDF en cada cambio de código.

`baseTopic` = `ahub/<device_id>` (ej. `ahub/device0001`). Cada gateway AgroHub tiene el suyo,
fijado en su configuración local — **no lo inventamos nosotros**, ya viene definido por quien
instala el gateway.

## El gateway publica (nosotros nos suscribimos)

| Tópico | QoS | Retenido | Payload |
|---|---|---|---|
| `ahub/<id>/data` | 1 | no | Ambiente: `{device, devEUI, ts, temperatura, humedad, measured_by, measured_at}`. Suelo: `{device, devEUI, ts, humedad_suelo, temperatura_suelo, conductividad, measured_by, measured_at}`. Si viene de un reenvío tras corte de conexión, además trae `recuperado: true, guardado_en, reenviado_en`. |
| `ahub/<id>/valvulas/state` | 1 | **sí** | `{ts, RO1, RO2, origen, ultimo_comando}`. `origen` ∈ `auto` (lógica local) / `remoto` (comando cloud) / `manual` (botón en el editor) / `reportado` (estado físico real informado por el uplink del LT-22222-L — es la fuente de verdad). |
| `ahub/<id>/health` | 0 | no | `{mqtt_conectado, ultimo_uplink, valvulas, override_manual, modo_control, measured_by, measured_at}`. `modo_control` ∈ `nube` / `local`. Cada 60s. **No se respalda en microSD** — solo tiene valor en tiempo real, si se pierde no se reenvía. |
| `ahub/<id>/status` | — | **sí** | `online` / `offline`, vía Last Will and Testament del broker. Si el gateway se cae, el broker publica `offline` automáticamente en ~22s (1.5 × keepalive de 15s). |

`measured_at` (o `ts` cuando no viene `measured_at`) es **siempre** el momento real de la
medición — nunca el momento de llegada al broker. Con datos recuperados de la microSD esto
puede ser minutos u horas antes de `reenviado_en`. **Usar `measured_at` para ordenar/graficar
series de tiempo, nunca la hora de inserción en la base de datos.**

## Nosotros publicamos (el gateway se suscribe)

| Tópico | QoS | Retenido | Payload |
|---|---|---|---|
| `ahub/<id>/control/valvulas` | 1 | no | `{"valvula": "RO1", "accion": "abrir"}`. Válvulas: `RO1`/`RO2` (también `1`/`2`). Acciones abrir: `abrir`/`open`/`on`/`encender`. Acciones cerrar: `cerrar`/`close`/`off`/`apagar`. Si el gateway está desconectado, el broker lo retiene (sesión persistente + QoS 1) y se entrega al reconectar — **puede ejecutarse con retraso**, evaluar vigencia si eso importa. |
| `iotunimagdalena/cloud/health` | 0 | **NUNCA** | Nuestro latido, cada 60s. Mientras llegue (ventana de 3 min) y haya conexión, el gateway deja el control de riego en manos de la nube. Si deja de llegar, el gateway pasa a control local automáticamente. **Jamás publicar con `retain=True`** — un latido retenido engañaría al gateway tras una reconexión real. |

## Jerarquía de control (para entender qué implica cada acción)

1. **Nube** (nosotros, mientras el latido llegue) — mandamos comandos por `control/valvulas`.
2. **Local (failover)** — sin latido en 3 min: el gateway controla solo por humedad de suelo.
3. **Remoto/Manual (override)** — un comando fija la válvula y bloquea la lógica local por
   `overrideMin` minutos (30 por defecto).
4. Botones físicos en el editor Node-RED del gateway — no nos concierne desde el servidor.

## Identificadores y unicidad — cosas que rompen todo si se duplican

- **Client ID único por gateway** (ej. `ug56-agrohub1`, `ug56-agrohub2`). Dos gateways con el
  mismo Client ID se expulsan mutuamente del broker en ciclo — síntoma: conecta/desconecta
  todo el tiempo. Esto lo configura quien instala cada gateway; nosotros solo lo detectamos en
  los logs del broker (`already connected`).
- **`device_id` (`device00xx`) único por gateway** — define su `baseTopic` y viaja en
  `measured_by` de cada payload. Un `device_id` repetido mezcla datos de dos gateways distintos
  en la plataforma.
