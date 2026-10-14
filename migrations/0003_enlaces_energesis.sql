-- Enlace de cada dispositivo NUESTRO (device0001...) con su dispositivo en ThingsBoard/Energesis.
-- Una fila por dispositivo: "el device N de ellos es el device N de nosotros". El daemon lee esta
-- tabla para saber a qué token reenviar la telemetría de cada gateway (ver mqtt_agrohub/thingsboard.py)
-- y la API del backend (riego_iot) la administra. Idempotente: se puede correr más de una vez.
--
--   docker exec -i agrohub_mqtt_db psql -U agrohub_mqtt -d agrohub_mqtt < migrations/0003_enlaces_energesis.sql
CREATE TABLE IF NOT EXISTS enlaces_energesis (
    device_id          TEXT PRIMARY KEY REFERENCES dispositivos(device_id) ON DELETE CASCADE,
    -- Credencial de ThingsBoard (se usa como usuario MQTT). Texto plano porque el daemon tiene que
    -- presentarla tal cual; la API nunca la devuelve completa (solo enmascarada).
    thingsboard_token  TEXT NOT NULL,
    thingsboard_nombre TEXT,
    activo             BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Lo escribe el daemon para que desde la API se vea si el enlace de verdad está funcionando.
    ultimo_envio_en    TIMESTAMPTZ,
    ultimo_error       TEXT,
    ultimo_error_en    TIMESTAMPTZ
);
