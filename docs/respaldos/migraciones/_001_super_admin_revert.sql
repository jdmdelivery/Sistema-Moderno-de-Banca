-- REVERSIÓN de _001_super_admin_aditiva.sql
-- Solo elimina objetos NUEVOS. No toca tickets, saldos, claves ni roles existentes.

BEGIN;

DROP INDEX IF EXISTS ix_usuarios_estado_aprobacion;
DROP TABLE IF EXISTS permisos_sucursal;

ALTER TABLE usuarios DROP COLUMN IF EXISTS motivo_rechazo;
ALTER TABLE usuarios DROP COLUMN IF EXISTS rechazado_en;
ALTER TABLE usuarios DROP COLUMN IF EXISTS rechazado_por;
ALTER TABLE usuarios DROP COLUMN IF EXISTS aprobado_en;
ALTER TABLE usuarios DROP COLUMN IF EXISTS aprobado_por;
ALTER TABLE usuarios DROP COLUMN IF EXISTS solicitado_en;
ALTER TABLE usuarios DROP COLUMN IF EXISTS solicitado_por;
ALTER TABLE usuarios DROP COLUMN IF EXISTS estado_aprobacion;
ALTER TABLE usuarios DROP COLUMN IF EXISTS suspendido;

COMMIT;
