-- ============================================================================
-- Banca Moderna — REINICIO CONTROLADO (NO EJECUTAR sin confirmación explícita)
-- ============================================================================
-- Conserva: consorcio, sucursales, usuarios, terminales, sorteos, tipos_jugada,
--           tabla_pagos, limites_*, comisiones_cajera (config %), candado_consulta
-- NO reinicia consorcio.siguiente_ticket (evita reutilizar IDs de tickets).
-- Pone saldos operativos en 0.00.
-- Auditoría: borra acciones operativas; conserva acciones de seguridad/admin.
-- ============================================================================

BEGIN;

-- 1) Operativo dependiente (hijos primero)
DELETE FROM jugadas;
DELETE FROM tickets;
DELETE FROM movimientos_cajera;
DELETE FROM movimientos_saldo;
DELETE FROM entregas;
DELETE FROM fondos_asignados;
DELETE FROM transacciones_caja;
DELETE FROM cuadres;
DELETE FROM liquidaciones_comision;
DELETE FROM cola_premios;
DELETE FROM correcciones_pendientes;
DELETE FROM resultado_versiones;
DELETE FROM observaciones_resultado;
DELETE FROM resultados;
DELETE FROM importaciones;
DELETE FROM sesiones;

-- 2) Auditoría operativa (conserva seguridad)
DELETE FROM auditoria
 WHERE accion IN (
   'venta','anulacion','pago','pago_prueba','pago_premio','fondo_asignado',
   'entrega_cajera','registro_resultado','confirmacion_automatica',
   'importacion_conectate','limite_cajera'
 );

-- 3) Saldos a cero (sin borrar entidades)
UPDATE usuarios
   SET saldo_caja = 0,
       saldo_caja_prueba = 0,
       ciclo_caja_movimiento_id = NULL,
       ciclo_caja_prueba_movimiento_id = NULL;

UPDATE sucursales
   SET saldo_actual = 0;

-- NO tocar: siguiente_ticket, multiplicadores, horarios, terminales, usuarios.

COMMIT;
