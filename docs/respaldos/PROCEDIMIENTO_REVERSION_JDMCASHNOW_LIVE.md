# Reversión segura — JDMCASHNOW LIVE

1. Restaurar `COMPAT_GLOBAL_FORZADO=1` en Render + restart del servicio.
2. Si el login de JDMCASHNOW falla: no borrar datos; reset clave con script `--live --reset-clave` y secret.
3. Si el aislamiento deja ciego a un admin: confirmar `sucursal_id` (Alfredo=1 CASTILLO) antes de quitar el flag.
4. Rollback de código: redeploy del commit `b2ef3cc` si el paquete falla.
5. Restore de dump `banca_moderna_pre_jdmcashnow_*.dump` **solo** si hay corrupción (no esperado).
6. APK 0.3.34: no tocar en ningún escenario.
