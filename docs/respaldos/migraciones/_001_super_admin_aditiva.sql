-- Migración ADITIVA / IDEMPOTENTE / REVERSIBLE (script aparte _001_revert.sql)
-- Super Admin multisucursal — NO borra datos, NO cambia saldos, NO toca contraseñas.
-- Aplicar SOLO tras autorización explícita. Probar primero en BD aislada.

BEGIN;

-- 1) Aprobación de cajeros (usuarios existentes = aprobados)
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS estado_aprobacion VARCHAR(20) NOT NULL DEFAULT 'aprobado';
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS solicitado_por INTEGER;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS solicitado_en TIMESTAMP;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS aprobado_por INTEGER;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS aprobado_en TIMESTAMP;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS rechazado_por INTEGER;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS rechazado_en TIMESTAMP;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS motivo_rechazo VARCHAR(200);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS suspendido BOOLEAN NOT NULL DEFAULT FALSE;

-- Garantiza que NINGÚN usuario previo quede pendiente/rechazado por esta migración
UPDATE usuarios
SET estado_aprobacion = 'aprobado'
WHERE estado_aprobacion IS NULL
   OR estado_aprobacion NOT IN ('aprobado', 'pendiente', 'rechazado');

-- 2) Permisos configurables por sucursal (defaults permisivos = comportamiento actual)
CREATE TABLE IF NOT EXISTS permisos_sucursal (
    sucursal_id INTEGER PRIMARY KEY REFERENCES sucursales(id),
    puede_crear_cajeros BOOLEAN NOT NULL DEFAULT TRUE,
    puede_asignar_fondos BOOLEAN NOT NULL DEFAULT TRUE,
    puede_registrar_entregas BOOLEAN NOT NULL DEFAULT TRUE,
    puede_ajustar_caja BOOLEAN NOT NULL DEFAULT TRUE,
    puede_configurar_limites BOOLEAN NOT NULL DEFAULT TRUE,
    puede_anular_tickets BOOLEAN NOT NULL DEFAULT TRUE,
    puede_ver_reportes BOOLEAN NOT NULL DEFAULT TRUE,
    actualizado_en TIMESTAMP,
    actualizado_por INTEGER
);

INSERT INTO permisos_sucursal (sucursal_id)
SELECT id FROM sucursales s
WHERE NOT EXISTS (
    SELECT 1 FROM permisos_sucursal p WHERE p.sucursal_id = s.id
);

-- 3) Índice de cola de aprobación (solo lectura/operativa; no altera filas)
CREATE INDEX IF NOT EXISTS ix_usuarios_estado_aprobacion
    ON usuarios (estado_aprobacion)
    WHERE eliminado IS NOT TRUE;

COMMIT;

-- NOTA: el rol 'super_admin' se introduce en código.
-- NO se convierte automáticamente ningún usuario.admin existente.
-- La promoción a super_admin requiere autorización explícita post-deploy.
