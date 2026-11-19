-- Migración reversible: cierres de ciclo de perfil/comisión (local / futuro deploy).
-- No altera ventas, premios, MI CAJA ni Banco General por sí sola.
-- Idempotente en PostgreSQL vía IF NOT EXISTS.

-- ===== APLICAR =====
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ciclo_perfil_cierre_id INTEGER;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ciclo_perfil_prueba_cierre_id INTEGER;

CREATE TABLE IF NOT EXISTS cierres_ciclo_cajera (
    id SERIAL PRIMARY KEY,
    operacion_id VARCHAR(40) NOT NULL UNIQUE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    sucursal_id INTEGER NOT NULL REFERENCES sucursales(id),
    cerrado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cerrado_por INTEGER NOT NULL REFERENCES usuarios(id),
    ventas_ciclo NUMERIC(14, 2) NOT NULL DEFAULT 0,
    premios_ciclo NUMERIC(14, 2) NOT NULL DEFAULT 0,
    comision_generada NUMERIC(14, 2) NOT NULL DEFAULT 0,
    comision_pagada_ciclo NUMERIC(14, 2) NOT NULL DEFAULT 0,
    comision_pagada_en_cierre NUMERIC(14, 2) NOT NULL DEFAULT 0,
    fondo_asignado NUMERIC(14, 2) NOT NULL DEFAULT 0,
    entregas_ciclo NUMERIC(14, 2) NOT NULL DEFAULT 0,
    recaudacion_ciclo NUMERIC(14, 2) NOT NULL DEFAULT 0,
    mi_caja_al_cerrar NUMERIC(14, 2) NOT NULL DEFAULT 0,
    tickets_vendidos INTEGER NOT NULL DEFAULT 0,
    tickets_anulados INTEGER NOT NULL DEFAULT 0,
    tickets_vigentes INTEGER NOT NULL DEFAULT 0,
    pago_comision_id INTEGER,
    marca_movimiento_id INTEGER,
    porcentaje_vigente NUMERIC(6, 2) NOT NULL DEFAULT 0,
    es_prueba BOOLEAN NOT NULL DEFAULT FALSE,
    detalle TEXT NOT NULL DEFAULT '',
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_cierres_ciclo_cajera_usuario_id ON cierres_ciclo_cajera (usuario_id);
CREATE INDEX IF NOT EXISTS ix_cierres_ciclo_cajera_sucursal_id ON cierres_ciclo_cajera (sucursal_id);
CREATE INDEX IF NOT EXISTS ix_cierres_ciclo_cajera_operacion_id ON cierres_ciclo_cajera (operacion_id);
CREATE INDEX IF NOT EXISTS ix_cierres_ciclo_cajera_cerrado_en ON cierres_ciclo_cajera (cerrado_en);

-- ===== REVERTIR (solo con autorización; no borra pagos_comision) =====
-- ALTER TABLE usuarios DROP COLUMN IF EXISTS ciclo_perfil_cierre_id;
-- ALTER TABLE usuarios DROP COLUMN IF EXISTS ciclo_perfil_prueba_cierre_id;
-- DROP TABLE IF EXISTS cierres_ciclo_cajera;
