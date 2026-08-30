-- Esquema de mqtt_agrohub. Ver docs/TOPICS.md para el origen de cada campo.
-- payload_crudo (JSONB) siempre guarda el mensaje tal cual llegó, para poder reprocesar sin
-- volver a esperar datos del gateway si en el futuro cambia cómo interpretamos algún campo.

CREATE TABLE IF NOT EXISTS dispositivos (
    device_id           TEXT PRIMARY KEY,          -- ej. 'device0001'
    base_topic          TEXT NOT NULL,              -- ej. 'ahub/device0001'
    nombre               TEXT,
    activo               BOOLEAN NOT NULL DEFAULT TRUE,
    primera_vez_visto    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_vez_visto     TIMESTAMPTZ,
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lecturas_ambiente (
    id                BIGSERIAL PRIMARY KEY,
    device_id         TEXT NOT NULL REFERENCES dispositivos(device_id),
    dev_eui           TEXT,
    medido_en         TIMESTAMPTZ NOT NULL,   -- measured_at / ts — nunca la hora de llegada
    temperatura       DOUBLE PRECISION,
    humedad           DOUBLE PRECISION,
    recuperado        BOOLEAN NOT NULL DEFAULT FALSE,
    guardado_en       TIMESTAMPTZ,
    reenviado_en      TIMESTAMPTZ,
    recibido_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_crudo     JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lecturas_ambiente_device_medido
    ON lecturas_ambiente (device_id, medido_en DESC);

CREATE TABLE IF NOT EXISTS lecturas_suelo (
    id                  BIGSERIAL PRIMARY KEY,
    device_id           TEXT NOT NULL REFERENCES dispositivos(device_id),
    dev_eui             TEXT,
    medido_en           TIMESTAMPTZ NOT NULL,
    humedad_suelo       DOUBLE PRECISION,
    temperatura_suelo   DOUBLE PRECISION,
    conductividad       DOUBLE PRECISION,
    recuperado          BOOLEAN NOT NULL DEFAULT FALSE,
    guardado_en         TIMESTAMPTZ,
    reenviado_en        TIMESTAMPTZ,
    recibido_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_crudo       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lecturas_suelo_device_medido
    ON lecturas_suelo (device_id, medido_en DESC);

CREATE TABLE IF NOT EXISTS estados_valvula (
    id                BIGSERIAL PRIMARY KEY,
    device_id         TEXT NOT NULL REFERENCES dispositivos(device_id),
    medido_en         TIMESTAMPTZ NOT NULL,
    ro1               TEXT,
    ro2               TEXT,
    origen            TEXT NOT NULL,   -- auto | remoto | manual | reportado
    ultimo_comando    TEXT,
    recibido_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_crudo     JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_estados_valvula_device_medido
    ON estados_valvula (device_id, medido_en DESC);

CREATE TABLE IF NOT EXISTS healthchecks (
    id                BIGSERIAL PRIMARY KEY,
    device_id         TEXT NOT NULL REFERENCES dispositivos(device_id),
    medido_en         TIMESTAMPTZ NOT NULL,
    mqtt_conectado    BOOLEAN,
    ultimo_uplink     TIMESTAMPTZ,
    modo_control      TEXT,   -- nube | local
    override_manual   BOOLEAN,
    valvulas          JSONB,
    recibido_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_crudo     JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_healthchecks_device_medido
    ON healthchecks (device_id, medido_en DESC);

CREATE TABLE IF NOT EXISTS estados_conexion (
    id             BIGSERIAL PRIMARY KEY,
    device_id      TEXT NOT NULL REFERENCES dispositivos(device_id),
    estado         TEXT NOT NULL,   -- online | offline
    recibido_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_estados_conexion_device_recibido
    ON estados_conexion (device_id, recibido_en DESC);

-- Auditoría de lo que nosotros mandamos hacia los gateways.
CREATE TABLE IF NOT EXISTS comandos_enviados (
    id                BIGSERIAL PRIMARY KEY,
    device_id         TEXT NOT NULL REFERENCES dispositivos(device_id),
    valvula           TEXT NOT NULL,
    accion            TEXT NOT NULL,
    enviado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_crudo     JSONB NOT NULL
);
