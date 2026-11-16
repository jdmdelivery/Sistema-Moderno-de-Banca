-- Migración TR (Tripleta) — idempotente. No borra histórico.
-- Validada en base aislada; aplicar en LIVE solo con autorización.

BEGIN;

ALTER TABLE jugadas ADD COLUMN IF NOT EXISTS n3 INTEGER;

INSERT INTO tipos_jugada (codigo, nombre, descripcion, requiere_dos_sorteos, activo)
SELECT 'TR', 'Tripleta',
       'Tres números en cualquier orden contra los tres premios del sorteo.',
       FALSE, TRUE
WHERE NOT EXISTS (SELECT 1 FROM tipos_jugada WHERE codigo = 'TR');

UPDATE tipos_jugada SET activo = TRUE WHERE codigo = 'TR' AND activo IS DISTINCT FROM TRUE;

INSERT INTO tabla_pagos (tipo_jugada_id, clave, factor, vigente_desde, creado_en)
SELECT tj.id, 'tr', 500, TIMESTAMP '2020-01-01 00:00:00', NOW()
FROM tipos_jugada tj
WHERE tj.codigo = 'TR'
  AND NOT EXISTS (
        SELECT 1 FROM tabla_pagos tp
        WHERE tp.tipo_jugada_id = tj.id
          AND tp.clave = 'tr'
          AND tp.vigente_hasta IS NULL
  );

COMMIT;
