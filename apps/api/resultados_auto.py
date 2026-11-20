"""Consulta el widget de Conéctate con intervalo adaptativo.

Intervalo normal: 4 minutos. Cerca de un sorteo pendiente o con lectura
provisional: 60 segundos, sin martillar Conéctate el resto del día.
No abre una pantalla y no reactiva RDLotto para el catálogo completo.
King Lottery consulta RDLotto solo como contraste del operador oficial.
El hilo es uno solo. Si otro proceso ya tomó el candado, esta pasada se
omite. Al reiniciar, las lecturas siguen en la base: no vuelven a cero.

El estado que ve el administrador sale de PostgreSQL, no de que el
proceso acabe de arrancar. Una segunda pasada dentro del mismo intervalo
no crea otra lectura.
"""
import os
import threading
import time
from datetime import datetime, timedelta

from . import (
    conectate_firmado,
    conectate_widget,
    estabilizacion,
    operador_king,
    operador_oficial,
    servicios,
)
from .comun import modo_desarrollo
from .db import nueva_sesion
from .models import CandadoConsulta, Importacion, ObservacionResultado, Resultado, Sorteo

INTERVALO_SEGUNDOS = 240
INTERVALO_RAPIDO_SEGUNDOS = 60
# Ventana alrededor de la hora del sorteo (minutos) para acelerar.
_VENTANA_ANTES_MIN = 2
_VENTANA_DESPUES_MIN = 25
# Tope de consulta forzada desde terminal (no salta la validación).
_MINIMO_FORZADO_SEGUNDOS = 45
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
    "intervalo_actual": INTERVALO_SEGUNDOS,
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


def intervalo_actual(db, momento=None):
    """240 s en calma; 60 s cerca de sorteos pendientes o con provisional."""
    momento = momento or servicios.ahora_local()
    hoy = momento.date()
    for sorteo in db.query(Sorteo).filter_by(activo=True).all():
        if sorteo.hora_sorteo is None:
            continue
        inicio = datetime.combine(hoy, sorteo.hora_sorteo)
        delta_min = (momento - inicio).total_seconds() / 60.0
        if not (-_VENTANA_ANTES_MIN <= delta_min <= _VENTANA_DESPUES_MIN):
            continue
        fila = db.query(Resultado).filter_by(sorteo_id=sorteo.id, fecha=hoy).first()
        if fila is None or fila.estado not in ("confirmado", "liquidado"):
            return INTERVALO_RAPIDO_SEGUNDOS
    pendientes = (
        db.query(ObservacionResultado)
        .filter(
            ObservacionResultado.fecha == hoy,
            ObservacionResultado.bloqueado.is_(False),
            ObservacionResultado.primera_en.isnot(None),
        )
        .all()
    )
    for obs in pendientes:
        fila = db.query(Resultado).filter_by(sorteo_id=obs.sorteo_id, fecha=hoy).first()
        if fila is None or fila.estado not in ("confirmado", "liquidado"):
            return INTERVALO_RAPIDO_SEGUNDOS
    return INTERVALO_SEGUNDOS


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
    intervalo = intervalo_actual(db, momento)
    proxima = None
    if ultima is not None and ultima.creado_en is not None and marca != "DETENIDO":
        proxima = _sin_zona(ultima.creado_en) + timedelta(seconds=intervalo)
    return {
        "reloj": marca,
        "ultima_ejecucion": None if ultima is None or ultima.creado_en is None else _sin_zona(ultima.creado_en).isoformat(sep=" ", timespec="minutes"),
        "ultima_consulta_ok": None if ultima_ok is None or ultima_ok.creado_en is None else _sin_zona(ultima_ok.creado_en).isoformat(sep=" ", timespec="minutes"),
        "ultimo_detalle": None if ultima_ok is None else (ultima_ok.detalle or None),
        "proxima_estimada": None if proxima is None else proxima.isoformat(sep=" ", timespec="minutes"),
        "ultimo_error": None if not errores else (errores[0].detalle or "la consulta falló"),
        "errores_recientes": [fila.detalle for fila in errores if fila.detalle],
        "fuente": "conectate",
        "intervalo_segundos": intervalo,
        "intervalo_normal": INTERVALO_SEGUNDOS,
        "intervalo_rapido": INTERVALO_RAPIDO_SEGUNDOS,
    }


def _demasiado_pronto(db, momento, segundos=None):
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
    limite = segundos if segundos is not None else intervalo_actual(db, momento)
    return edad < timedelta(seconds=max(15, limite - 15))


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


def _especiales(payload, firmado, momento, operador):
    """La firma y el operador solo se abren en el reloj real.

    Las pruebas traen el documento. Sin la coincidencia del operador,
    La Anguila y Haití Bolet no entran, aunque el widget los traiga.
    """
    if firmado is not None:
        candidatos = conectate_firmado.propuestos(firmado, momento.date())
        aceptados, discrepancias = operador_oficial.cruzar(
            candidatos, operador or {}, momento.date(),
        )
        return aceptados, None, discrepancias
    if payload is not None or "PYTEST_CURRENT_TEST" in os.environ:
        return {}, None, []
    try:
        return operador_oficial.confirmar_ventana(momento.date())
    except Exception:
        return {}, "operador no disponible", []


def _king(payload, momento, king_html=None, king_rdlotto=None):
    """King Lottery: operador oficial cruzado con RDLotto verified.

    No reactiva RDLotto para el resto del catálogo. En pruebas hace falta
    inyectar html/documento; sin eso King no entra.
    """
    if king_html is not None or king_rdlotto is not None:
        args = {}
        if king_html is not None:
            args["html"] = king_html
        if king_rdlotto is not None:
            args["documento"] = king_rdlotto
        return operador_king.confirmar(momento.date(), **args)
    if payload is not None or "PYTEST_CURRENT_TEST" in os.environ:
        return {}, None, []
    try:
        return operador_king.confirmar_ventana(momento.date())
    except Exception:
        return {}, "operador king no disponible", []


def ciclo(forzar=False, payload=None, firmado=None, operador=None,
          king_html=None, king_rdlotto=None, minimo_segundos=None):
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
            _estado["intervalo_actual"] = intervalo_actual(db, momento)
        if not _tomar(db, momento):
            return {"ok": True, "omitido": "otro proceso ya está consultando", "rdlotto": False}
        if forzar and minimo_segundos is not None:
            if _demasiado_pronto(db, momento, segundos=minimo_segundos):
                return {
                    "ok": True,
                    "omitido": "consulta reciente; se muestran los datos ya guardados",
                    "rdlotto": False,
                    "confirmados": 0,
                }
        elif not forzar and _demasiado_pronto(db, momento):
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
        especiales, aviso_firma, discrepancias = _especiales(
            payload, firmado, momento, operador,
        )
        king_ok, aviso_king, difs_king = _king(
            payload, momento, king_html=king_html, king_rdlotto=king_rdlotto,
        )
        discrepancias = list(discrepancias) + list(difs_king)
        if datos is None:
            encontrados, forma = {}, None
        else:
            encontrados, forma = conectate_widget.interpretar(datos, momento.date())
            if forma:
                encontrados = {}
        encontrados = {
            nombre: dato
            for nombre, dato in encontrados.items()
            if not conectate_firmado.es_especial(nombre) and not operador_king.es_king(nombre)
        }
        for nombre, dato in especiales.items():
            if conectate_firmado.es_especial(nombre):
                encontrados[nombre] = dato
        for nombre, dato in king_ok.items():
            if operador_king.es_king(nombre):
                encontrados[nombre] = dato
        for item in discrepancias:
            sorteo = db.query(Sorteo).filter_by(nombre=item["sorteo"], activo=True).first()
            servicios.auditar(
                db, "resultado", sorteo.id if sorteo else 0,
                "discrepancia_operador", detalle=item,
            )
        aviso = aviso_firma or aviso_king
        if not encontrados and (error or forma or aviso):
            motivo = error or forma or aviso
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
        detalle = (
            f"confirmados {confirmados}; premios {premios}; "
            f"firmados {len(especiales)}; king {len(king_ok)}"
        )
        if discrepancias:
            detalle += f"; discrepancias {len(discrepancias)}"
        if aviso_firma:
            # Conservar el motivo real (p. ej. operador anguila sin respuesta /
            # certificado no reconocido). "firma pendiente" era demasiado genérico.
            detalle += "; " + str(aviso_firma)[:100]
        if aviso_king:
            detalle += "; king " + str(aviso_king)[:80]
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
            _estado["intervalo_actual"] = intervalo_actual(db, momento)
        return {
            "ok": True,
            "encontrados": len(encontrados),
            "confirmados": confirmados,
            "premios": premios,
            "rdlotto": False,
            "king": len(king_ok),
            "intervalo_segundos": _estado["intervalo_actual"],
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


def ciclo_desde_terminal():
    """Comprobación pedida por SUNMI: respeta tope anti-abuso y la validación."""
    return ciclo(forzar=True, minimo_segundos=_MINIMO_FORZADO_SEGUNDOS)


def _bucle():
    time.sleep(20)
    while True:
        try:
            ciclo(forzar=False)
        except Exception:
            pass
        db = nueva_sesion()
        try:
            espera = intervalo_actual(db)
        except Exception:
            espera = INTERVALO_SEGUNDOS
        finally:
            db.close()
        with _candado:
            _estado["intervalo_actual"] = espera
        time.sleep(espera)


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
