"""Consulta el widget de Conéctate cada 4 minutos.

No abre una pantalla y no llama a RDLotto. El hilo es uno solo. Si otro
proceso ya tomó el candado, esta pasada se omite. Al reiniciar, las
lecturas siguen en la base: no vuelven a cero.

El estado que ve el administrador sale de PostgreSQL, no de que el
proceso acabe de arrancar. Una segunda pasada dentro del mismo intervalo
no crea otra lectura.
"""
import os
import threading
import time
from datetime import timedelta

from . import conectate_firmado, conectate_widget, estabilizacion, servicios
from .comun import modo_desarrollo
from .db import nueva_sesion
from .models import CandadoConsulta, Importacion, Sorteo

INTERVALO_SEGUNDOS = 240
# Una ejecución cuenta como reciente si llegó dentro del intervalo más un margen.
_VENTANA_ACTIVO = timedelta(minutes=6)
# Pasado este tiempo sin filas nuevas, el reloj está detenido, no solo retrasado.
_VENTANA_RETRASO = timedelta(minutes=20)
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
    """Estado en memoria de este proceso. No sirve para decir si el reloj vive."""
    with _candado:
        return dict(_estado)


def _sin_zona(marca):
    if marca is not None and getattr(marca, "tzinfo", None) is not None:
        return marca.replace(tzinfo=None)
    return marca


def _edad(momento, fila):
    if fila is None or fila.creado_en is None:
        return None
    return momento - _sin_zona(fila.creado_en)


def estado_reloj(db, momento=None):
    """ACTIVO, RETRASADO, ERROR o DETENIDO según las filas guardadas.

    Sobrevive a un reinicio: no mira si el hilo acaba de arrancar.
    """
    momento = momento or servicios.ahora_local()
    consulta = db.query(Importacion).filter(Importacion.fuente == "conectate")
    ultima = consulta.order_by(Importacion.id.desc()).first()
    ultima_ok = (
        consulta.filter(Importacion.ok.is_(True)).order_by(Importacion.id.desc()).first()
    )
    errores = (
        consulta.filter(Importacion.ok.is_(False))
        .order_by(Importacion.id.desc())
        .limit(3)
        .all()
    )
    edad = _edad(momento, ultima)
    if ultima is None or edad is None or edad > _VENTANA_RETRASO:
        marca = "DETENIDO"
    elif not ultima.ok:
        marca = "ERROR"
    elif edad <= _VENTANA_ACTIVO:
        marca = "ACTIVO"
    else:
        marca = "RETRASADO"
    proxima = None
    if ultima is not None and ultima.creado_en is not None and marca != "DETENIDO":
        proxima = _sin_zona(ultima.creado_en) + timedelta(seconds=INTERVALO_SEGUNDOS)
    return {
        "reloj": marca,
        "ultima_ejecucion": None if ultima is None or ultima.creado_en is None else _sin_zona(ultima.creado_en).isoformat(sep=" ", timespec="minutes"),
        "ultima_consulta_ok": None if ultima_ok is None or ultima_ok.creado_en is None else _sin_zona(ultima_ok.creado_en).isoformat(sep=" ", timespec="minutes"),
        "proxima_estimada": None if proxima is None else proxima.isoformat(sep=" ", timespec="minutes"),
        "ultimo_error": None if not errores else (errores[0].detalle or "la consulta falló"),
        "errores_recientes": [fila.detalle for fila in errores if fila.detalle],
        "fuente": "conectate",
    }


def _demasiado_pronto(db, momento):
    """Otra pasada de este intervalo ya quedó registrada. Evita un segundo reloj."""
    ultima = (
        db.query(Importacion)
        .filter(Importacion.fuente == "conectate")
        .order_by(Importacion.id.desc())
        .first()
    )
    edad = _edad(momento, ultima)
    if edad is None:
        return False
    return edad < timedelta(seconds=INTERVALO_SEGUNDOS - 30)


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


def _especiales(payload, firmado, momento):
    """La firma solo se abre en el reloj real. Las pruebas traen el documento."""
    if firmado is not None:
        return conectate_firmado.leer(firmado, momento.date()), None
    if payload is not None or "PYTEST_CURRENT_TEST" in os.environ:
        return {}, None
    return conectate_firmado.descargar_ventana(momento.date())


def ciclo(forzar=False, payload=None, firmado=None):
    """Una pasada. payload y firmado evitan la red en las pruebas. No paga."""
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
            return {"ok": True, "omitido": "otro proceso ya está consultando", "rdlotto": False}
        if not forzar and _demasiado_pronto(db, momento):
            return {
                "ok": True,
                "omitido": "otra consulta ya corrió en este intervalo",
                "rdlotto": False,
                "confirmados": 0,
            }
        datos = payload
        error = None
        if datos is None:
            datos, error = conectate_widget.descargar()
        especiales, aviso_firma = _especiales(payload, firmado, momento)
        if datos is None:
            encontrados, forma = {}, None
        else:
            encontrados, forma = conectate_widget.interpretar(datos, momento.date())
            if forma:
                encontrados = {}
        for nombre, dato in especiales.items():
            if conectate_firmado.es_especial(nombre):
                encontrados[nombre] = dato
        if not encontrados and (error or forma or aviso_firma):
            motivo = error or forma or aviso_firma
            db.add(Importacion(
                fuente="conectate", url=conectate_widget.URL_WIDGET,
                fecha_objetivo=momento.date(), ok=False, detalle=str(motivo)[:500],
                creado_en=momento,
            ))
            db.commit()
            with _candado:
                _estado["ultimo_error"] = str(motivo)
            return {"ok": False, "motivo": motivo, "confirmados": 0, "rdlotto": False}
        confirmados = 0
        for nombre, dato in encontrados.items():
            sorteo = db.query(Sorteo).filter_by(nombre=nombre, activo=True).first()
            if sorteo is None:
                continue
            marca = estabilizacion.observar(
                db, sorteo, dato["fecha"], dato["numeros"], momento,
                dato.get("origen", "widget"),
            )
            if marca == "confirmado":
                confirmados += 1
        premios = estabilizacion.procesar_cola(db)
        detalle = f"confirmados {confirmados}; premios {premios}; firmados {len(especiales)}"
        if aviso_firma:
            detalle += "; firma pendiente"
        if error:
            detalle += "; widget " + str(error)[:120]
        db.add(Importacion(
            fuente="conectate", url=conectate_widget.URL_WIDGET,
            fecha_objetivo=momento.date(), ok=True, estado_http=200,
            encontrados=len(encontrados),
            detalle=detalle[:500],
            creado_en=momento,
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
        try:
            db.add(Importacion(
                fuente="conectate", url=conectate_widget.URL_WIDGET,
                fecha_objetivo=servicios.ahora_local().date(), ok=False,
                detalle=str(exc)[:500], creado_en=servicios.ahora_local(),
            ))
            db.commit()
        except Exception:
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
