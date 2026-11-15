"""Trabajador de resultados. No arranca solo: hace falta RESULTADOS_AUTOMATICOS.

Aunque esté activo, no confirma ni liquida. Un resultado de RDLotto queda en
verificación hasta que una persona del consorcio lo confirme en el panel.
Si Render reinicia el proceso, el arranque vuelve a lanzar el mismo ciclo.
"""
import os
import threading
import time

from .comun import ahora_local, modo_desarrollo
from .db import nueva_sesion
from . import rdlotto

_hilo = None
_estado = {
    "activo": False,
    "corriendo": False,
    "ultimo_intento": None,
    "ultimo_ok": None,
    "ultimo_error": None,
}
_candado = threading.Lock()


def activo():
    return os.environ.get("RESULTADOS_AUTOMATICOS", "").strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def estado():
    with _candado:
        return dict(_estado)


def ciclo(forzar=False):
    """Una pasada. Fuera de la ventana de publicación no llama a la fuente."""
    with _candado:
        if _estado["corriendo"]:
            return {"ok": True, "omitido": "ya hay una consulta en curso"}
        _estado["corriendo"] = True
    db = nueva_sesion()
    try:
        momento = ahora_local()
        with _candado:
            _estado["ultimo_intento"] = momento.isoformat(sep=" ")
        if not forzar and not rdlotto.hay_sorteo_en_ventana(db, momento):
            return {"ok": True, "omitido": "ningún sorteo conectado está en su ventana"}
        resumen = rdlotto.sincronizar(db, momento.date())
        with _candado:
            if resumen.get("ok"):
                _estado["ultimo_ok"] = momento.isoformat(sep=" ")
                _estado["ultimo_error"] = None
            else:
                _estado["ultimo_error"] = resumen.get("motivo")
        return resumen
    except Exception as e:
        with _candado:
            _estado["ultimo_error"] = str(e)
        return {"ok": False, "motivo": str(e), "guardados": 0, "alertas": [str(e)]}
    finally:
        db.close()
        with _candado:
            _estado["corriendo"] = False


def _bucle():
    while True:
        try:
            ciclo(forzar=False)
        except Exception:
            pass
        time.sleep(rdlotto.INTERVALO_SEGUNDOS)


def arrancar_si_esta_activado():
    global _hilo
    encendido = activo() or modo_desarrollo()
    with _candado:
        _estado["activo"] = encendido
    if not encendido or (_hilo is not None and _hilo.is_alive()):
        return
    _hilo = threading.Thread(target=_bucle, name="resultados-rdlotto", daemon=True)
    _hilo.start()
