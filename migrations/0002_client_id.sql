-- No hay framework de migraciones en este repo (schema.sql solo se aplica una vez, al crear el
-- volumen de Postgres) — este archivo es para bases YA provisionadas, aplicar a mano:
--   docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < migrations/0002_client_id.sql
ALTER TABLE dispositivos ADD COLUMN IF NOT EXISTS client_id TEXT UNIQUE;
