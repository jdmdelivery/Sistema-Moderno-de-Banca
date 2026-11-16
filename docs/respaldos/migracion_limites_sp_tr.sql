-- Migración LOCAL / aislada: límites SP (par de loterías) y TR (clave de 3).
-- NO ejecutar en PostgreSQL LIVE sin autorización explícita.
-- Idempotente en lo posible.

BEGIN;

ALTER TABLE limites_cajera
  ADD COLUMN IF NOT EXISTS sorteo2_id INTEGER NOT NULL DEFAULT 0;

ALTER TABLE limites_venta
  ADD COLUMN IF NOT EXISTS sorteo2_id INTEGER NOT NULL DEFAULT 0;

-- Ampliar clave para tripletas "00-00-00" (ya cabe en 12; se deja 20 por margen).
ALTER TABLE limites_cajera
  ALTER COLUMN clave_numero TYPE VARCHAR(20);
ALTER TABLE limites_venta
  ALTER COLUMN clave_numero TYPE VARCHAR(20);

-- Recrear unicidad incluyendo sorteo2_id (SP).
ALTER TABLE limites_cajera DROP CONSTRAINT IF EXISTS uq_limite_cajera;
ALTER TABLE limites_cajera
  ADD CONSTRAINT uq_limite_cajera
  UNIQUE (usuario_id, sorteo_id, sorteo2_id, tipo_jugada_id, clave_numero);

ALTER TABLE limites_venta DROP CONSTRAINT IF EXISTS uq_limite_venta;
-- Nombre histórico posible de create_all / UniqueConstraint sin name:
DO $$
DECLARE
  cname text;
BEGIN
  SELECT conname INTO cname
  FROM pg_constraint
  WHERE conrelid = 'limites_venta'::regclass
    AND contype = 'u'
    AND conname <> 'uq_limite_venta'
  LIMIT 1;
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE limites_venta DROP CONSTRAINT %I', cname);
  END IF;
END $$;

ALTER TABLE limites_venta
  ADD CONSTRAINT uq_limite_venta
  UNIQUE (sorteo_id, sorteo2_id, tipo_jugada_id, clave_numero);

COMMIT;
