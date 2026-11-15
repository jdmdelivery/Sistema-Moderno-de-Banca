"""Consulta el widget de Conéctate cada 4 minutos.

No abre una pantalla y no llama a RDLotto. El hilo es uno solo. Si otro
proceso ya tomó el candado, esta pasada se omite. Al reiniciar, las
lecturas siguen en la base: no vuelven a cero.

En el plan gratuito de Render el proceso duerme cuando no hay tráfico.
El ciclo corre cada vez que el proceso está despierto y retoma el conteo
desde PostgreSQL. No se crea un segundo trabajador.
"""
import os
import threading
import time
from datetime import timedelta

from . import conectate_widget, estabilizacion, servicios
from .comun import modo_desarrollo
from .db import nueva_sesion
from .models import CandadoConsulta, Importacion, Sorteo

INTERVALO_SEGUNDOS = 240
_hilo = None
_estado = {
    "activo": False,
    "corriendo": False,
    "ultimo_intento": None,
    "ultimo_ok": None,
    "ultimo_error": None,
    "fuente": "conectate",
}
_candado = threading.Lock()


def activo():
    return os.environ.get("RESULTADOS_AUTOMATICOS", "").strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def estado():
    with _candado:
        return dict(_estado)


def _tomar(db, momento):
    fila = db.get(CandadoConsulta, 1)
    if fila is None:
        db.add(CandadoConsulta(id=1, tomado_en=momento, pid=os.getpid()))
        db.commit()
        return True
    corte = momento - timedelta(minutes=3)
    if fila.tomado_en is not None and fila.tomado_en > corte and fila.pid not in (None, os.getpid()):
        return False
    fila.tomado_en = momento
    fila.pid = os.getpid()
    db.commit()
    return True


def _soltar(db):
    fila = db.get(CandadoConsulta, 1)
    if fila is not None:
        fila.tomado_en = None
        db.commit()


def ciclo(forzar=False, payload=None):
    """Una pasada. payload evita la red en las pruebas. No paga."""
    with _candado:
        if _estado["corriendo"]:
            return {"ok": True, "omitido": "ya hay una consulta en curso"}
        _estado["corriendo"] = True
    db = nueva_sesion()
    try:
        momento = servicios.ahora_local()
        with _candado:
            _estado["ultimo_intento"] = momento.isoformat(sep=" ")
        if not _tomar(db, momento):
            return {"ok": True, "omitido": "otro proceso ya está consultando"}
        datos = payload
        error = None
        if datos is None:
            datos, error = conectate_widget.descargar()
        if error:
            db.add(Importacion(
                fuente="conectate", url=conectate_widget.URL_WIDGET,
                fecha_objetivo=momento.date(), ok=False, detalle=error[:500],
            ))
            db.commit()
            with _candado:
                _estado["ultimo_error"] = error
            return {"ok": False, "motivo": error, "confirmados": 0, "rdlotto": False}
        encontrados, forma = conectate_widget.interpretar(datos, momento.date())
        if forma:
            db.add(Importacion(
                fuente="conectate", url=conectate_widget.URL_WIDGET,
                fecha_objetivo=momento.date(), ok=False, detalle=forma,
            ))
            db.commit()
            return {"ok": False, "motivo": forma, "confirmados": 0, "rdlotto": False}
        confirmados = 0
        for nombre, dato in encontrados.items():
            sorteo = db.query(Sorteo).filter_by(nombre=nombre, activo=True).first()
            if sorteo is None:
                continue
            marca = estabilizacion.observar(db, sorteo, dato["fecha"], dato["numeros"], momento)
            if marca == "confirmado":
                confirmados += 1
        premios = estabilizacion.procesar_cola(db)
        db.add(Importacion(
            fuente="conectate", url=conectate_widget.URL_WIDGET,
            fecha_objetivo=momento.date(), ok=True, estado_http=200,
            encontrados=len(encontrados),
            detalle=f"confirmados {confirmados}; premios {premios}",
        ))
        db.commit()
        with _candado:
            _estado["ultimo_ok"] = momento.isoformat(sep=" ")
            _estado["ultimo_error"] = None
        return {
            "ok": True,
            "encontrados": len(encontrados),
            "confirmados": confirmados,
            "premios": premios,
            "rdlotto": False,
        }
    except Exception as exc:
        db.rollback()
        with _candado:
            _estado["ultimo_error"] = str(exc)
        return {"ok": False, "motivo": str(exc), "confirmados": 0, "rdlotto": False}
    finally:
        try:
            _soltar(db)
        except Exception:
            pass
        db.close()
        with _candado:
            _estado["corriendo"] = False


def _bucle():
    time.sleep(20)
    while True:
        try:
            ciclo(forzar=False)
        except Exception:
            pass
        time.sleep(INTERVALO_SEGUNDOS)


def arrancar_si_esta_activado():
    global _hilo
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    encendido = activo() or modo_desarrollo()
    with _candado:
        _estado["activo"] = encendido
    if not encendido or (_hilo is not None and _hilo.is_alive()):
        return
    _hilo = threading.Thread(target=_bucle, name="resultados-conectate", daemon=True)
    _hilo.start()
