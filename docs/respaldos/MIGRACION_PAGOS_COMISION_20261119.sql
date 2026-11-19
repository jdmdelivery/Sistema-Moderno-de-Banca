-- Migración reversible: historial de pagos de comisión (local / futuro deploy).
-- No altera ventas, premios, MI CAJA ni Banco General.
-- Idempotente en PostgreSQL vía IF NOT EXISTS.

-- ===== APLICAR =====
CREATE TABLE IF NOT EXISTS pagos_comision (
    id SERIAL PRIMARY KEY,
    operacion_id VARCHAR(40) NOT NULL UNIQUE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    sucursal_id INTEGER NOT NULL REFERENCES sucursales(id),
    monto NUMERIC(14, 2) NOT NULL,
    comision_acumulada NUMERIC(14, 2) NOT NULL,
    comision_pagada_antes NUMERIC(14, 2) NOT NULL,
    saldo_pendiente_antes NUMERIC(14, 2) NOT NULL,
    saldo_pendiente_despues NUMERIC(14, 2) NOT NULL,
    es_prueba BOOLEAN NOT NULL DEFAULT FALSE,
    pagado_por INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_pagos_comision_usuario_id ON pagos_comision (usuario_id);
CREATE INDEX IF NOT EXISTS ix_pagos_comision_sucursal_id ON pagos_comision (sucursal_id);
CREATE INDEX IF NOT EXISTS ix_pagos_comision_operacion_id ON pagos_comision (operacion_id);
CREATE INDEX IF NOT EXISTS ix_pagos_comision_creado_en ON pagos_comision (creado_en);

-- ===== REVERTIR (solo si se autoriza y no hay dependencia operativa) =====
-- DROP TABLE IF EXISTS pagos_comision;
