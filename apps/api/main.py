"""API del Sistema de Banca Moderna: panel del consorcio + API de terminales.

Arranque local:  uvicorn apps.api.main:app --port 8100
La BD se elige con DATABASE_URL (PostgreSQL en producción, SQLite en local).
"""
import json
from datetime import date, datetime, time
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import conectate, conectate_widget, resultados_auto, servicios
from .comun import D, ErrorServicio, loterias_abiertas_desarrollo, modo_desarrollo
from .db import configurar, engine, init_db, nueva_sesion
from .models import (
    Auditoria,
    LimiteVenta,
    MovimientoSaldo,
    Resultado,
    Sorteo,
    Sucursal,
    TablaPagos,
    Terminal,
    TipoJugada,
    TransaccionCaja,
    Usuario,
    Cuadre,
    Importacion,
)
from .security import hash_clave, hash_token, nuevo_token, verificar_clave

configurar()

app = FastAPI(title="Sistema de Banca Moderna", version="1.0-etapa2")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.on_event("startup")
def _al_arrancar():
    init_db()
    resultados_auto.arrancar_si_esta_activado()


@app.exception_handler(ErrorServicio)
def _error_servicio(request: Request, exc: ErrorServicio):
    return JSONResponse(status_code=exc.status, content={"detail": exc.mensaje})


def get_db():
    db = nueva_sesion()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------- auth
def _bearer(request: Request):
    cab = request.headers.get("authorization", "")
    return cab[7:] if cab.lower().startswith("bearer ") else None


def panel_actual(request: Request, db=Depends(get_db)):
    _, usuario = servicios.sesion_y_usuario(db, _bearer(request), tipo="panel")
    return usuario


def requiere_rol(*roles):
    def dep(usuario=Depends(panel_actual)):
        if usuario.rol not in roles:
            raise ErrorServicio(403, f"Su rol ({usuario.rol}) no puede hacer esta operación")
        return usuario

    return dep


def terminal_actual(request: Request, db=Depends(get_db)):
    """La terminal sale de la SESIÓN del operador (sin serial ni token de
    activación desde 2026-11-14: se entra con usuario y contraseña)."""
    sesion, _ = servicios.sesion_y_usuario(db, _bearer(request), tipo="terminal")
    terminal = db.get(Terminal, sesion.terminal_id) if sesion.terminal_id else None
    if terminal is None or not terminal.activa:
        raise ErrorServicio(401, "La terminal de esta sesión está revocada o no existe")
    return terminal


def operador_actual(request: Request, db=Depends(get_db)):
    _, usuario = servicios.sesion_y_usuario(db, _bearer(request), tipo="terminal")
    return usuario


# -------------------------------------------------------------- serialización
def sucursal_dict(s, con_saldo=True):
    datos = {
        "id": s.id, "codigo": s.codigo, "nombre": s.nombre, "direccion": s.direccion,
        "telefono": s.telefono, "comision_porcentaje": str(D(s.comision_porcentaje)),
        "activa": bool(s.activa),
    }
    if con_saldo:
        datos["saldo_actual"] = str(D(s.saldo_actual))
    return datos


def terminal_dict(t):
    return {
        "id": t.id, "sucursal_id": t.sucursal_id,
        "sucursal": t.sucursal.nombre if t.sucursal else "?",
        "numero_terminal": t.numero_terminal, "serial_sunmi": t.serial_sunmi,
        "activa": bool(t.activa), "tiene_token": bool(t.token_hash),
        "ultima_conexion_en": t.ultima_conexion_en.isoformat(sep=" ") if t.ultima_conexion_en else None,
        "version_app": t.version_app,
    }


def usuario_dict(u, con_cajas=False):
    datos = {
        "id": u.id, "nombre": u.nombre, "usuario": u.usuario, "rol": u.rol,
        "sucursal_id": u.sucursal_id, "activo": bool(u.activo),
        "tiene_clave": bool(u.clave_hash), "tiene_pin": bool(u.pin_hash),
    }
    if con_cajas:
        datos["saldo_caja"] = str(D(u.saldo_caja or 0))
        datos["saldo_caja_prueba"] = str(D(u.saldo_caja_prueba or 0))
    return datos


def sorteo_dict(s):
    return {
        "id": s.id, "nombre": s.nombre,
        "hora_sorteo": s.hora_sorteo.strftime("%H:%M"),
        "hora_cierre": s.hora_cierre.strftime("%H:%M"),
        "dias_activos": [int(d) for d in s.dias_activos.split(",") if d.strip()],
        "activo": bool(s.activo), "orden": s.orden,
    }


def tipo_dict(t):
    return {
        "id": t.id, "codigo": t.codigo, "nombre": t.nombre, "descripcion": t.descripcion,
        "requiere_dos_sorteos": bool(t.requiere_dos_sorteos), "activo": bool(t.activo),
    }


def tabla_dict(f):
    return {
        "id": f.id, "tipo": f.tipo.codigo if f.tipo else "?", "tipo_jugada_id": f.tipo_jugada_id,
        "clave": f.clave, "factor": str(D(f.factor)),
        "vigente_desde": f.vigente_desde.isoformat(sep=" "),
        "vigente_hasta": f.vigente_hasta.isoformat(sep=" ") if f.vigente_hasta else None,
    }


def limite_dict(l, db):
    sorteo = db.get(Sorteo, l.sorteo_id)
    tipo = db.get(TipoJugada, l.tipo_jugada_id)
    return {
        "id": l.id, "sorteo_id": l.sorteo_id, "sorteo": sorteo.nombre if sorteo else "?",
        "tipo": tipo.codigo if tipo else "?", "clave_numero": l.clave_numero,
        "monto_max_acumulado": str(D(l.monto_max_acumulado)),
    }


def movimiento_dict(m):
    return {
        "id": m.id, "sucursal_id": m.sucursal_id, "tipo": m.tipo, "monto": str(D(m.monto)),
        "referencia": m.referencia, "saldo_resultante": str(D(m.saldo_resultante)),
        "creado_en": m.creado_en.isoformat(sep=" ") if m.creado_en else None,
    }


def caja_dict(t):
    return {
        "id": t.id, "sucursal_id": t.sucursal_id, "terminal_id": t.terminal_id,
        "tipo": t.tipo, "monto": str(D(t.monto)), "concepto": t.concepto,
        "fecha": t.fecha.isoformat(), "creado_en": t.creado_en.isoformat(sep=" ") if t.creado_en else None,
    }


def importacion_dict(i):
    return {
        "id": i.id, "fuente": i.fuente, "url": i.url, "fecha_objetivo": i.fecha_objetivo.isoformat(),
        "ok": bool(i.ok), "estado_http": i.estado_http, "encontrados": i.encontrados,
        "detalle": i.detalle, "creado_en": i.creado_en.isoformat(sep=" ") if i.creado_en else None,
    }


def _entorno_publico():
    abiertas = loterias_abiertas_desarrollo()
    return {
        "modo_desarrollo": modo_desarrollo(),
        "loterias_abiertas_desarrollo": abiertas,
        "leyenda": "MODO DESARROLLO — DATOS DE PRUEBA" if modo_desarrollo() else "",
        "leyenda_loterias": "MODO DESARROLLO — LOTERÍAS ABIERTAS 24 HORAS" if abiertas else "",
    }


def _hora(texto):
    try:
        return datetime.strptime(texto, "%H:%M").time()
    except Exception:
        raise ErrorServicio(400, f"Hora inválida: «{texto}» (use HH:MM)")


def _fecha(texto):
    try:
        return date.fromisoformat(texto)
    except Exception:
        raise ErrorServicio(400, f"Fecha inválida: «{texto}» (use AAAA-MM-DD)")


# ------------------------------------------------------------------- salud
@app.get("/health")
def salud():
    desarrollo = modo_desarrollo()
    return {
        "ok": True,
        "servicio": "sistema-de-banca-moderna",
        "hora": servicios.ahora_local().isoformat(),
        "datos": "prueba" if desarrollo else "produccion",
        "base": engine().dialect.name,
        **_entorno_publico(),
    }


# ------------------------------------------------------------- autenticación
class LoginIn(BaseModel):
    usuario: str
    clave: str


@app.post("/auth/login")
def login(datos: LoginIn, db=Depends(get_db)):
    usuario = db.query(Usuario).filter_by(usuario=datos.usuario.strip()).first()
    if (usuario is None or not usuario.activo or usuario.rol not in ("admin", "supervisor")
            or not usuario.clave_hash or not verificar_clave(datos.clave, usuario.clave_hash)):
        raise ErrorServicio(401, "Usuario o clave incorrectos")
    token = servicios.crear_sesion(db, usuario, tipo="panel")
    db.commit()
    return {"token": token, "usuario": usuario_dict(usuario)}


@app.post("/auth/logout")
def logout(request: Request, db=Depends(get_db)):
    servicios.cerrar_sesion(db, _bearer(request))
    return {"ok": True}


@app.get("/auth/yo")
def yo(usuario=Depends(panel_actual)):
    return usuario_dict(usuario)


# ---------------------------------------------------------------- sucursales
class SucursalIn(BaseModel):
    codigo: str
    nombre: str
    direccion: str | None = None
    telefono: str | None = None
    comision_porcentaje: float = 10
    activa: bool = True


@app.get("/sucursales")
def listar_sucursales(db=Depends(get_db), usuario=Depends(panel_actual)):
    filas = []
    for s in db.query(Sucursal).order_by(Sucursal.codigo).all():
        datos = sucursal_dict(s)
        if usuario.rol == "admin":
            datos["consolidado_cajas"] = servicios.consolidado_cajas(db, s.id)
        filas.append(datos)
    return filas


@app.post("/sucursales", status_code=201)
def crear_sucursal(datos: SucursalIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    if db.query(Sucursal).filter_by(codigo=datos.codigo.strip()).first():
        raise ErrorServicio(409, f"Ya existe una sucursal con el código {datos.codigo}")
    s = Sucursal(
        codigo=datos.codigo.strip(), nombre=datos.nombre.strip(), direccion=datos.direccion,
        telefono=datos.telefono, comision_porcentaje=D(datos.comision_porcentaje), activa=datos.activa,
    )
    db.add(s)
    db.flush()
    servicios.auditar(db, "sucursal", s.id, "creacion", usuario_id=usuario.id,
                      detalle={"codigo": s.codigo, "nombre": s.nombre})
    db.commit()
    db.refresh(s)
    return sucursal_dict(s)


@app.put("/sucursales/{sucursal_id}")
def editar_sucursal(sucursal_id: int, datos: SucursalIn, db=Depends(get_db),
                    usuario=Depends(requiere_rol("admin"))):
    s = db.get(Sucursal, sucursal_id)
    if s is None:
        raise ErrorServicio(404, "La sucursal no existe")
    otra = db.query(Sucursal).filter_by(codigo=datos.codigo.strip()).first()
    if otra is not None and otra.id != s.id:
        raise ErrorServicio(409, f"Ya existe una sucursal con el código {datos.codigo}")
    s.codigo, s.nombre = datos.codigo.strip(), datos.nombre.strip()
    s.direccion, s.telefono = datos.direccion, datos.telefono
    s.comision_porcentaje, s.activa = D(datos.comision_porcentaje), datos.activa
    servicios.auditar(db, "sucursal", s.id, "edicion", usuario_id=usuario.id, detalle={"codigo": s.codigo})
    db.commit()
    db.refresh(s)
    return sucursal_dict(s)


class RecargaIn(BaseModel):
    monto: float
    referencia: str | None = None


@app.post("/sucursales/{sucursal_id}/recargar")
def recargar(sucursal_id: int, datos: RecargaIn, db=Depends(get_db),
             usuario=Depends(requiere_rol("admin", "supervisor"))):
    mov = servicios.recargar_saldo(db, sucursal_id, datos.monto, datos.referencia, usuario)
    return movimiento_dict(mov)


@app.get("/sucursales/{sucursal_id}/movimientos")
def movimientos(sucursal_id: int, limite: int = 100, db=Depends(get_db), usuario=Depends(panel_actual)):
    filas = (
        db.query(MovimientoSaldo)
        .filter_by(sucursal_id=sucursal_id)
        .order_by(MovimientoSaldo.id.desc())
        .limit(min(limite, 500))
        .all()
    )
    return [movimiento_dict(m) for m in filas]


# ---------------------------------------------------------------- terminales
class TerminalIn(BaseModel):
    sucursal_id: int
    numero_terminal: int = 1
    serial_sunmi: str
    version_app: str | None = None
    activa: bool = True


@app.get("/terminales")
def listar_terminales(db=Depends(get_db), usuario=Depends(panel_actual)):
    return [terminal_dict(t) for t in db.query(Terminal).order_by(Terminal.sucursal_id, Terminal.numero_terminal).all()]


@app.post("/terminales", status_code=201)
def crear_terminal(datos: TerminalIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    if db.get(Sucursal, datos.sucursal_id) is None:
        raise ErrorServicio(404, "La sucursal no existe")
    if db.query(Terminal).filter_by(serial_sunmi=datos.serial_sunmi.strip()).first():
        raise ErrorServicio(409, "Ya hay una terminal con ese serial SUNMI")
    if db.query(Terminal).filter_by(sucursal_id=datos.sucursal_id, numero_terminal=datos.numero_terminal).first():
        raise ErrorServicio(409, "Esa sucursal ya tiene una terminal con ese número")
    t = Terminal(
        sucursal_id=datos.sucursal_id, numero_terminal=datos.numero_terminal,
        serial_sunmi=datos.serial_sunmi.strip(),
        activa=datos.activa, version_app=datos.version_app,
    )
    db.add(t)
    db.flush()
    servicios.auditar(db, "terminal", t.id, "creacion", usuario_id=usuario.id,
                      detalle={"serial_sunmi": t.serial_sunmi})
    db.commit()
    db.refresh(t)
    return terminal_dict(t)


@app.put("/terminales/{terminal_id}")
def editar_terminal(terminal_id: int, datos: TerminalIn, db=Depends(get_db),
                    usuario=Depends(requiere_rol("admin"))):
    t = db.get(Terminal, terminal_id)
    if t is None:
        raise ErrorServicio(404, "La terminal no existe")
    t.numero_terminal = datos.numero_terminal
    t.serial_sunmi = datos.serial_sunmi.strip()
    t.version_app = datos.version_app
    t.activa = datos.activa
    servicios.auditar(db, "terminal", t.id, "edicion", usuario_id=usuario.id, detalle={})
    db.commit()
    db.refresh(t)
    return terminal_dict(t)


@app.post("/terminales/{terminal_id}/revocar")
def revocar_terminal(terminal_id: int, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    t = db.get(Terminal, terminal_id)
    if t is None:
        raise ErrorServicio(404, "La terminal no existe")
    t.token_hash = None
    t.activa = False
    servicios.auditar(db, "terminal", t.id, "revocacion", usuario_id=usuario.id,
                      detalle={"serial_sunmi": t.serial_sunmi})
    db.commit()
    db.refresh(t)
    return terminal_dict(t)


@app.post("/terminales/{terminal_id}/reactivar")
def reactivar_terminal(terminal_id: int, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    t = db.get(Terminal, terminal_id)
    if t is None:
        raise ErrorServicio(404, "La terminal no existe")
    t.token_hash = None
    t.activa = True
    servicios.auditar(db, "terminal", t.id, "reactivacion", usuario_id=usuario.id, detalle={})
    db.commit()
    db.refresh(t)
    return terminal_dict(t)


# ------------------------------------------------------------------ usuarios
class UsuarioIn(BaseModel):
    nombre: str
    usuario: str
    rol: str = "operador"
    sucursal_id: int | None = None
    clave: str | None = None
    activo: bool = True


@app.get("/usuarios")
def listar_usuarios(db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    return [usuario_dict(u, con_cajas=usuario.rol == "admin") for u in db.query(Usuario).order_by(Usuario.nombre).all()]


@app.post("/usuarios", status_code=201)
def crear_usuario(datos: UsuarioIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    if datos.rol not in ("admin", "supervisor", "operador"):
        raise ErrorServicio(400, "Rol no válido: admin, supervisor u operador")
    if db.query(Usuario).filter_by(usuario=datos.usuario.strip()).first():
        raise ErrorServicio(409, f"Ya existe el usuario {datos.usuario}")
    if datos.rol in ("admin", "supervisor") and not datos.clave:
        raise ErrorServicio(400, "Un admin/supervisor necesita una clave para el panel")
    if datos.rol == "operador" and not datos.clave:
        raise ErrorServicio(400, "Un operador necesita una contraseña para entrar en la terminal")
    u = Usuario(
        nombre=datos.nombre.strip(), usuario=datos.usuario.strip(), rol=datos.rol,
        sucursal_id=datos.sucursal_id, activo=datos.activo,
        clave_hash=hash_clave(datos.clave) if datos.clave else None,
    )
    db.add(u)
    db.flush()
    servicios.auditar(db, "usuario", u.id, "creacion", usuario_id=usuario.id, detalle={"rol": u.rol})
    db.commit()
    db.refresh(u)
    return usuario_dict(u)


@app.put("/usuarios/{usuario_id}")
def editar_usuario(usuario_id: int, datos: UsuarioIn, db=Depends(get_db),
                   usuario=Depends(requiere_rol("admin"))):
    u = db.get(Usuario, usuario_id)
    if u is None:
        raise ErrorServicio(404, "El usuario no existe")
    u.nombre, u.rol, u.sucursal_id, u.activo = datos.nombre.strip(), datos.rol, datos.sucursal_id, datos.activo
    if datos.clave:
        u.clave_hash = hash_clave(datos.clave)
    servicios.auditar(db, "usuario", u.id, "edicion", usuario_id=usuario.id, detalle={})
    db.commit()
    db.refresh(u)
    return usuario_dict(u)


# ------------------------------------------------------------------ sorteos
class SorteoIn(BaseModel):
    nombre: str
    hora_sorteo: str
    hora_cierre: str
    dias_activos: list[int] = [1, 2, 3, 4, 5, 6, 7]
    activo: bool = True
    orden: int = 100


@app.get("/sorteos")
def listar_sorteos(db=Depends(get_db), usuario=Depends(panel_actual)):
    return [sorteo_dict(s) for s in db.query(Sorteo).order_by(Sorteo.orden, Sorteo.nombre).all()]


@app.post("/sorteos", status_code=201)
def crear_sorteo(datos: SorteoIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    if db.query(Sorteo).filter_by(nombre=datos.nombre.strip()).first():
        raise ErrorServicio(409, f"Ya existe el sorteo {datos.nombre}")
    s = Sorteo(
        nombre=datos.nombre.strip(), hora_sorteo=_hora(datos.hora_sorteo),
        hora_cierre=_hora(datos.hora_cierre),
        dias_activos=",".join(str(d) for d in datos.dias_activos),
        activo=datos.activo, orden=datos.orden,
    )
    db.add(s)
    db.flush()
    servicios.auditar(db, "sorteo", s.id, "creacion", usuario_id=usuario.id, detalle={"nombre": s.nombre})
    db.commit()
    db.refresh(s)
    return sorteo_dict(s)


@app.put("/sorteos/{sorteo_id}")
def editar_sorteo(sorteo_id: int, datos: SorteoIn, db=Depends(get_db),
                  usuario=Depends(requiere_rol("admin"))):
    s = db.get(Sorteo, sorteo_id)
    if s is None:
        raise ErrorServicio(404, "El sorteo no existe")
    s.nombre = datos.nombre.strip()
    s.hora_sorteo, s.hora_cierre = _hora(datos.hora_sorteo), _hora(datos.hora_cierre)
    s.dias_activos = ",".join(str(d) for d in datos.dias_activos)
    s.activo, s.orden = datos.activo, datos.orden
    servicios.auditar(db, "sorteo", s.id, "edicion", usuario_id=usuario.id, detalle={"nombre": s.nombre})
    db.commit()
    db.refresh(s)
    return sorteo_dict(s)


# -------------------------------------------------------------- tipos y tabla
@app.get("/tipos-jugada")
def listar_tipos(db=Depends(get_db), usuario=Depends(panel_actual)):
    return [tipo_dict(t) for t in db.query(TipoJugada).order_by(TipoJugada.codigo).all()]


@app.get("/tabla-pagos")
def listar_tabla(db=Depends(get_db), usuario=Depends(panel_actual)):
    filas = db.query(TablaPagos).order_by(TablaPagos.tipo_jugada_id, TablaPagos.clave, TablaPagos.vigente_desde.desc()).all()
    return [tabla_dict(f) for f in filas]


class TablaIn(BaseModel):
    tipo: str
    clave: str
    factor: float
    vigente_desde: str  # AAAA-MM-DD o AAAA-MM-DD HH:MM


@app.post("/tabla-pagos", status_code=201)
def crear_factor(datos: TablaIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    tipo = db.query(TipoJugada).filter_by(codigo=datos.tipo.upper()).first()
    if tipo is None:
        raise ErrorServicio(404, f"El tipo de jugada {datos.tipo} no existe")
    if datos.clave not in servicios.CLAVES_REQUERIDAS.get(tipo.codigo, []):
        raise ErrorServicio(400, f"Clave no válida para {tipo.codigo}: {datos.clave}")
    if D(datos.factor) <= 0:
        raise ErrorServicio(400, "El factor debe ser mayor que cero")
    try:
        desde = datetime.fromisoformat(datos.vigente_desde)
    except Exception:
        raise ErrorServicio(400, "vigente_desde inválido (use AAAA-MM-DD o AAAA-MM-DD HH:MM)")
    anteriores = (
        db.query(TablaPagos)
        .filter(
            TablaPagos.tipo_jugada_id == tipo.id,
            TablaPagos.clave == datos.clave,
            TablaPagos.vigente_desde < desde,
            (TablaPagos.vigente_hasta.is_(None)) | (TablaPagos.vigente_hasta > desde),
        )
        .all()
    )
    anterior_txt = None
    for f in anteriores:
        anterior_txt = str(D(f.factor))
        f.vigente_hasta = desde
    nueva = TablaPagos(tipo_jugada_id=tipo.id, clave=datos.clave, factor=D(datos.factor),
                       vigente_desde=desde, creado_por=usuario.id)
    db.add(nueva)
    db.flush()
    servicios.auditar(db, "tabla_pagos", nueva.id, "cambio_tabla", usuario_id=usuario.id,
                      detalle={"tipo": tipo.codigo, "clave": datos.clave,
                               "factor_anterior": anterior_txt, "factor_nuevo": str(D(datos.factor)),
                               "vigente_desde": str(desde)})
    db.commit()
    db.refresh(nueva)
    return tabla_dict(nueva)


# ------------------------------------------------------------------ límites
class LimiteIn(BaseModel):
    sorteo_id: int
    tipo: str
    numeros: str
    monto_max_acumulado: float


@app.get("/limites")
def listar_limites(db=Depends(get_db), usuario=Depends(panel_actual)):
    return [limite_dict(l, db) for l in db.query(LimiteVenta).order_by(LimiteVenta.id).all()]


@app.post("/limites", status_code=201)
def crear_limite(datos: LimiteIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    tipo = db.query(TipoJugada).filter_by(codigo=datos.tipo.upper()).first()
    if tipo is None or db.get(Sorteo, datos.sorteo_id) is None:
        raise ErrorServicio(404, "Sorteo o tipo de jugada no válido")
    n1, n2 = servicios._parse_numeros(tipo.codigo, datos.numeros)
    clave = servicios.clave_numero(n1, n2)
    existente = db.query(LimiteVenta).filter_by(
        sorteo_id=datos.sorteo_id, tipo_jugada_id=tipo.id, clave_numero=clave).first()
    if existente is not None:
        existente.monto_max_acumulado = D(datos.monto_max_acumulado)
        db.commit()
        db.refresh(existente)
        return limite_dict(existente, db)
    lim = LimiteVenta(sorteo_id=datos.sorteo_id, tipo_jugada_id=tipo.id, clave_numero=clave,
                      monto_max_acumulado=D(datos.monto_max_acumulado))
    db.add(lim)
    db.flush()
    servicios.auditar(db, "limite", lim.id, "creacion", usuario_id=usuario.id, detalle={"clave": clave})
    db.commit()
    db.refresh(lim)
    return limite_dict(lim, db)


class AplicarTodasIn(BaseModel):
    tipo: str
    numeros: str
    monto_max_acumulado: float
    reemplazar: bool = False
    aplicar: bool = False


@app.post("/limites/aplicar-todas")
def aplicar_limite_todas(datos: AplicarTodasIn, db=Depends(get_db),
                         usuario=Depends(requiere_rol("admin", "supervisor"))):
    return servicios.aplicar_limite_todas(
        db, datos.tipo, datos.numeros, datos.monto_max_acumulado, usuario.id,
        reemplazar=datos.reemplazar, aplicar=datos.aplicar)


@app.delete("/limites/{limite_id}")
def borrar_limite(limite_id: int, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    lim = db.get(LimiteVenta, limite_id)
    if lim is None:
        raise ErrorServicio(404, "El límite no existe")
    db.delete(lim)
    servicios.auditar(db, "limite", limite_id, "eliminacion", usuario_id=usuario.id, detalle={})
    db.commit()
    return {"ok": True}


class LimiteCajeraIn(BaseModel):
    usuario_id: int
    sorteo_id: int | None = None
    tipo: str
    numeros: str | None = None
    monto_max_acumulado: float
    id: int | None = None


@app.get("/limites-cajera")
def listar_limites_cajera(usuario_id: int | None = None, sucursal_id: int | None = None,
                          db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    return servicios.listar_limites_cajera(db, usuario_id, sucursal_id)


@app.post("/limites-cajera", status_code=201)
def guardar_limite_cajera(datos: LimiteCajeraIn, db=Depends(get_db),
                          usuario=Depends(requiere_rol("admin"))):
    return servicios.guardar_limite_cajera(
        db, usuario, datos.usuario_id, datos.sorteo_id, datos.tipo, datos.numeros,
        datos.monto_max_acumulado, datos.id,
    )


@app.delete("/limites-cajera/{limite_id}")
def borrar_limite_cajera(limite_id: int, db=Depends(get_db),
                         usuario=Depends(requiere_rol("admin"))):
    return servicios.borrar_limite_cajera(db, usuario, limite_id)


# ---------------------------------------------------------------- resultados
class ResultadoIn(BaseModel):
    sorteo_id: int
    fecha: str
    premio1: int
    premio2: int
    premio3: int
    simulado: bool = False


@app.get("/resultados")
def listar_resultados(fecha: str | None = None, sorteo_id: int | None = None,
                      db=Depends(get_db), usuario=Depends(panel_actual)):
    q = db.query(Resultado)
    if fecha:
        q = q.filter(Resultado.fecha == _fecha(fecha))
    if sorteo_id:
        q = q.filter(Resultado.sorteo_id == sorteo_id)
    return [servicios.resultado_a_dict(r) for r in q.order_by(Resultado.fecha.desc(), Resultado.sorteo_id).all()]


@app.post("/resultados", status_code=201)
def guardar_resultado(datos: ResultadoIn, db=Depends(get_db),
                      usuario=Depends(requiere_rol("admin", "supervisor"))):
    r = servicios.guardar_resultado(
        db, datos.sorteo_id, _fecha(datos.fecha),
        datos.premio1, datos.premio2, datos.premio3, usuario, simulado=datos.simulado,
    )
    salida = servicios.resultado_a_dict(r)
    salida["tickets_prueba"] = int(getattr(r, "_tickets_prueba", 0) or 0)
    return salida


@app.post("/resultados/{resultado_id}/confirmar")
def confirmar_resultado(resultado_id: int, db=Depends(get_db),
                        usuario=Depends(requiere_rol("admin", "supervisor"))):
    r, afectados = servicios.confirmar_resultado(db, resultado_id, usuario)
    salida = servicios.resultado_a_dict(r)
    salida["tickets_afectados"] = afectados
    return salida


@app.post("/resultados/{resultado_id}/revertir")
def revertir_resultado(resultado_id: int, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    r, afectados = servicios.revertir_resultado(db, resultado_id, usuario)
    salida = servicios.resultado_a_dict(r)
    salida["tickets_afectados"] = afectados
    return salida


class ImportarIn(BaseModel):
    fecha: str | None = None


@app.post("/resultados/importar")
def importar_resultados(datos: ImportarIn, db=Depends(get_db),
                        usuario=Depends(requiere_rol("admin", "supervisor"))):
    fecha = _fecha(datos.fecha) if datos.fecha else servicios.ahora_local().date()
    return conectate.importar_resultados(db, fecha, usuario)


@app.get("/resultados/tablero")
def tablero_resultados(db=Depends(get_db), usuario=Depends(panel_actual)):
    return servicios.tablero_resultados(db, servicios.ahora_local().date())


@app.get("/movil/admin")
def movil_admin(seccion: str = "inicio", desde: str | None = None, hasta: str | None = None,
                sucursal_id: int | None = None, usuario_id: int | None = None, q: str = "",
                db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    hoy = servicios.ahora_local().date()
    inicio = _fecha(desde) if desde else hoy
    fin = _fecha(hasta) if hasta else hoy
    return servicios.panel_movil(db, usuario, seccion, inicio, fin, sucursal_id, usuario_id, q)


@app.get("/fuente-resultados")
def cobertura_resultados(db=Depends(get_db), usuario=Depends(panel_actual)):
    return {
        "fuente": "conectate",
        "url": conectate_widget.URL_WIDGET,
        "aviso": "Solo el widget público de Conéctate. Tres lecturas iguales y 10 minutos "
                 "antes de confirmar. No paga solo. RDLotto no se consulta.",
        "intervalo_segundos": resultados_auto.INTERVALO_SEGUNDOS,
        "trabajador": resultados_auto.estado_reloj(db),
        "sorteos": [
            {
                "sorteo": s.nombre,
                "hora": s.hora_sorteo.strftime("%H:%M"),
                "conectada": s.nombre in conectate_widget.RECONOCIDOS,
                "motivo": None if s.nombre in conectate_widget.RECONOCIDOS else conectate_widget.motivo_sin_fuente(s.nombre),
            }
            for s in db.query(Sorteo).filter_by(activo=True).order_by(Sorteo.hora_sorteo, Sorteo.nombre)
        ],
    }


@app.get("/fuente-resultados/probar")
def probar_widget(usuario=Depends(requiere_rol("admin", "supervisor"))):
    """Consulta el widget desde este proceso. No guarda ni confirma."""
    datos, error = conectate_widget.descargar()
    if error:
        return {"ok": False, "motivo": error, "cantidad": 0, "titulos": []}
    titulos = []
    if isinstance(datos, list):
        for item in datos:
            if isinstance(item, dict):
                titulos.append(str(item.get("game_title") or item.get("title") or ""))
    return {"ok": True, "motivo": None, "cantidad": len(titulos), "titulos": titulos}


@app.post("/fuente-resultados/sincronizar")
def sincronizar_resultados(db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    return resultados_auto.ciclo(forzar=True)


@app.get("/ganadores")
def ganadores(fecha: str | None = None, sorteo_id: int | None = None, sucursal_id: int | None = None,
              usuario_id: int | None = None, estado: str | None = None,
              db=Depends(get_db), usuario=Depends(panel_actual)):
    return servicios.listar_ganadores(
        db,
        fecha=_fecha(fecha) if fecha else None,
        sorteo_id=sorteo_id,
        sucursal_id=sucursal_id,
        usuario_id=usuario_id,
        estado=estado,
    )


@app.get("/importaciones")
def listar_importaciones(limite: int = 20, db=Depends(get_db), usuario=Depends(panel_actual)):
    filas = db.query(Importacion).order_by(Importacion.id.desc()).limit(min(limite, 100)).all()
    return [importacion_dict(i) for i in filas]


# ------------------------------------------------------- tickets desde el panel
class LlaveIn(BaseModel):
    id: int
    serial: str
    operacion_id: str | None = None


class PanelPagoIn(LlaveIn):
    sucursal_id: int


class AnularIn(BaseModel):
    id: int
    serial: str
    motivo: str | None = None


@app.post("/panel/tickets/consultar")
def panel_consultar(datos: LlaveIn, db=Depends(get_db), usuario=Depends(panel_actual)):
    return servicios.consultar_ticket(db, datos.id, datos.serial)


@app.post("/panel/tickets/pagar")
def panel_pagar(datos: PanelPagoIn, db=Depends(get_db),
                usuario=Depends(requiere_rol("admin", "supervisor"))):
    return servicios.pagar_ticket(db, datos.id, datos.serial, datos.sucursal_id, None, usuario.id)


@app.post("/panel/tickets/anular")
def panel_anular(datos: AnularIn, db=Depends(get_db),
                 usuario=Depends(requiere_rol("admin"))):
    """Solo el administrador del Panel. No aplica el límite de 5 minutos."""
    return servicios.anular_ticket(
        db, datos.id, datos.serial, usuario.id, terminal_id=None,
        motivo=datos.motivo, ventana_cajera=False,
    )


# ------------------------------------------------------------------ caja panel
class CajaIn(BaseModel):
    sucursal_id: int
    terminal_id: int | None = None
    monto: float
    concepto: str | None = None


@app.post("/panel/caja/recibir", status_code=201)
def panel_recibir(datos: CajaIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    tx = servicios.registrar_caja(db, "recibir_efectivo", datos.monto, datos.concepto,
                                  datos.sucursal_id, datos.terminal_id, usuario.id)
    return caja_dict(tx)


@app.post("/panel/caja/gasto", status_code=201)
def panel_gasto(datos: CajaIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    tx = servicios.registrar_caja(db, "gasto", datos.monto, datos.concepto,
                                  datos.sucursal_id, datos.terminal_id, usuario.id)
    return caja_dict(tx)


@app.get("/caja/transacciones")
def listar_caja(sucursal_id: int | None = None, terminal_id: int | None = None,
                fecha: str | None = None, limite: int = 200,
                db=Depends(get_db), usuario=Depends(panel_actual)):
    q = db.query(TransaccionCaja)
    if sucursal_id:
        q = q.filter(TransaccionCaja.sucursal_id == sucursal_id)
    if terminal_id:
        q = q.filter(TransaccionCaja.terminal_id == terminal_id)
    if fecha:
        q = q.filter(TransaccionCaja.fecha == _fecha(fecha))
    filas = q.order_by(TransaccionCaja.id.desc()).limit(min(limite, 500)).all()
    return [caja_dict(t) for t in filas]


class CuadreIn(BaseModel):
    sucursal_id: int
    terminal_id: int | None = None
    fecha: str | None = None
    efectivo_contado: float | None = None


@app.post("/panel/caja/cuadre", status_code=201)
def panel_cuadre(datos: CuadreIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    c = servicios.entregar_cuadre(
        db, datos.sucursal_id, datos.terminal_id, usuario.id,
        fecha=_fecha(datos.fecha) if datos.fecha else None,
        efectivo_contado=datos.efectivo_contado,
    )
    return servicios.cuadre_a_dict(c)


@app.get("/cuadres")
def listar_cuadres(sucursal_id: int | None = None, fecha: str | None = None,
                   db=Depends(get_db), usuario=Depends(panel_actual)):
    q = db.query(Cuadre)
    if sucursal_id:
        q = q.filter(Cuadre.sucursal_id == sucursal_id)
    if fecha:
        q = q.filter(Cuadre.fecha == _fecha(fecha))
    return [servicios.cuadre_a_dict(c) for c in q.order_by(Cuadre.id.desc()).limit(100).all()]


# ------------------------------------------------------------------ reportes
@app.get("/reportes/inicio")
def reporte_inicio(desde: str | None = None, hasta: str | None = None,
                   db=Depends(get_db), usuario=Depends(panel_actual)):
    hoy = servicios.ahora_local().date()
    return servicios.resumen_inicio(
        db, _fecha(desde) if desde else hoy, _fecha(hasta) if hasta else hoy,
    )


@app.get("/reportes/resumen")
def reporte_resumen(desde: str, hasta: str, vista: str = "final", sucursal_id: int | None = None,
                    db=Depends(get_db), usuario=Depends(panel_actual)):
    return servicios.reporte_resumen(db, _fecha(desde), _fecha(hasta), vista, sucursal_id)


@app.get("/reportes/ventas")
def reporte_ventas(desde: str, hasta: str, usuario_id: int | None = None,
                   sucursal_id: int | None = None, limite: int = 500,
                   db=Depends(get_db), usuario=Depends(panel_actual)):
    return servicios.reporte_ventas(db, _fecha(desde), _fecha(hasta), usuario_id, sucursal_id, limite)


@app.get("/reportes/pendientes")
def reporte_pendientes(desde: str, hasta: str, sucursal_id: int, formato: str = "json",
                       db=Depends(get_db), usuario=Depends(panel_actual)):
    if formato == "texto":
        texto = servicios.pendientes_texto(db, _fecha(desde), _fecha(hasta), sucursal_id)
        return PlainTextResponse(texto)
    return servicios.reporte_pendientes(db, _fecha(desde), _fecha(hasta), sucursal_id)


# ------------------------------------------------------------------ auditoría
@app.get("/auditoria")
def listar_auditoria(entidad: str | None = None, accion: str | None = None, limite: int = 100,
                     db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    q = db.query(Auditoria)
    if entidad:
        q = q.filter(Auditoria.entidad == entidad)
    if accion:
        q = q.filter(Auditoria.accion == accion)
    filas = q.order_by(Auditoria.id.desc()).limit(min(limite, 500)).all()
    return [
        {
            "id": a.id, "entidad": a.entidad, "entidad_id": a.entidad_id, "accion": a.accion,
            "usuario_id": a.usuario_id, "terminal_id": a.terminal_id,
            "detalle": json.loads(a.detalle_json or "{}"),
            "creado_en": a.creado_en.isoformat(sep=" ") if a.creado_en else None,
        }
        for a in filas
    ]


# ============================================================ API DE TERMINAL
class TerminalLoginIn(BaseModel):
    usuario: str
    clave: str
    dispositivo_id: str | None = None
    modelo: str | None = None
    android: str | None = None
    version_app: str | None = None


@app.post("/terminal/login")
def terminal_login(datos: TerminalLoginIn, db=Depends(get_db)):
    """Entrada de la terminal: SOLO usuario y contraseña (sin serial ni
    token de activación). La sucursal y la terminal salen del usuario."""
    usuario = db.query(Usuario).filter_by(usuario=datos.usuario.strip()).first()
    if (
        usuario is None
        or not usuario.activo
        or not usuario.clave_hash
        or not verificar_clave(datos.clave, usuario.clave_hash)
    ):
        raise ErrorServicio(401, "Usuario o contraseña incorrectos")
    if usuario.rol == "admin":
        token = servicios.crear_sesion(db, usuario, tipo="panel")
        servicios.auditar(
            db, "usuario", usuario.id, "login_admin_movil", usuario_id=usuario.id,
            detalle={"dispositivo": datos.dispositivo_id or "", "version": datos.version_app or ""},
        )
        db.commit()
        return {
            "token": token,
            "rol": "admin",
            "operador": usuario_dict(usuario),
            "sucursal": None,
            "mi_caja": "0.00",
            **_entorno_publico(),
        }
    if usuario.rol not in ("operador", "supervisor"):
        raise ErrorServicio(403, "Su rol no puede entrar a la terminal")
    if usuario.sucursal_id is None:
        raise ErrorServicio(
            403,
            "Este usuario no tiene sucursal asignada: el consorcio debe asignarla en el panel (Usuarios).",
        )
    sucursal = db.get(Sucursal, usuario.sucursal_id)
    if sucursal is None or not sucursal.activa:
        raise ErrorServicio(403, "La sucursal de este usuario está inactiva")
    terminal = servicios.terminal_para_dispositivo(
        db, sucursal, datos.dispositivo_id, datos.modelo, datos.android, datos.version_app,
    )
    if terminal is None:
        raise ErrorServicio(
            403,
            "La terminal de esta sucursal está revocada: el consorcio debe reactivarla en el panel.",
        )
    token = servicios.crear_sesion(db, usuario, tipo="terminal", terminal_id=terminal.id)
    db.commit()
    return {
        "token": token,
        "rol": usuario.rol,
        "operador": usuario_dict(usuario),
        "sucursal": sucursal_dict(sucursal, con_saldo=False),
        "mi_caja": str(servicios.mi_caja_de(usuario)),
        **_entorno_publico(),
        "terminal": {
            "id": terminal.id,
            "numero": terminal.numero_terminal,
            "serial": terminal.serial_sunmi,
            "modelo": terminal.modelo,
            "android": terminal.android_api,
            "version_app": terminal.version_app,
        },
    }


@app.get("/terminal/resultados")
def terminal_resultados(db=Depends(get_db), terminal=Depends(terminal_actual),
                        operador=Depends(operador_actual)):
    return servicios.tablero_resultados(db, servicios.ahora_local().date())


@app.get("/terminal/sorteos")
def terminal_sorteos(db=Depends(get_db), terminal=Depends(terminal_actual),
                     operador=Depends(operador_actual)):
    ahora = servicios.ahora_local()
    salida = []
    for s in db.query(Sorteo).filter_by(activo=True).order_by(Sorteo.orden).all():
        info = servicios.estado_sorteo(s, ahora)
        d = sorteo_dict(s)
        d["abierto"] = info["abierto"]
        d["estado"] = info["estado"]
        d["motivo_cierre"] = info["motivo"]
        d["segundos_para_cierre"] = info["segundos_para_cierre"]
        salida.append(d)
    datos = {
        "sorteos": salida,
        **_entorno_publico(),
    }
    datos.update(servicios.indicadores_caja(db, operador))
    return datos


class EntregaIn(BaseModel):
    monto: float
    operacion_id: str


@app.get("/terminal/entregas/estado")
def terminal_estado_entrega(db=Depends(get_db), terminal=Depends(terminal_actual),
                            operador=Depends(operador_actual)):
    sucursal = db.get(Sucursal, terminal.sucursal_id)
    return servicios.estado_entrega(db, operador, sucursal, terminal)


@app.post("/terminal/entregas", status_code=201)
def terminal_entregar(datos: EntregaIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                      operador=Depends(operador_actual)):
    sucursal = db.get(Sucursal, terminal.sucursal_id)
    return servicios.entregar_efectivo(db, operador, sucursal, terminal, datos.monto, datos.operacion_id)


@app.get("/terminal/entregas/operacion/{operacion_id}")
def terminal_entrega_operacion(operacion_id: str, db=Depends(get_db), terminal=Depends(terminal_actual),
                               operador=Depends(operador_actual)):
    return servicios.entrega_por_operacion(db, operador.id, operacion_id)


@app.get("/terminal/entregas/{entrega_id}")
def terminal_reimprimir_entrega(entrega_id: int, db=Depends(get_db), terminal=Depends(terminal_actual),
                                operador=Depends(operador_actual)):
    return servicios.entrega_para_reimprimir(db, operador.id, entrega_id)


@app.get("/entregas")
def panel_entregas(sucursal_id: int | None = None, db=Depends(get_db),
                   usuario=Depends(requiere_rol("admin", "supervisor"))):
    return servicios.listar_entregas(db, usuario, sucursal_id)


@app.post("/entregas/{entrega_id}/recibir")
def panel_recibir_entrega(entrega_id: int, db=Depends(get_db),
                          usuario=Depends(requiere_rol("admin", "supervisor"))):
    return servicios.recibir_entrega(db, entrega_id, usuario)


class FondoIn(BaseModel):
    sucursal_id: int
    usuario_id: int
    monto: float
    tipo: str
    operacion_id: str
    motivo: str | None = None


@app.get("/fondos")
def panel_fondos(sucursal_id: int | None = None, usuario_id: int | None = None,
                 db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    return servicios.listar_fondos(db, sucursal_id, usuario_id)


@app.post("/fondos", status_code=201)
def panel_asignar_fondo(datos: FondoIn, db=Depends(get_db),
                        usuario=Depends(requiere_rol("admin"))):
    return servicios.asignar_fondo(
        db, usuario, datos.usuario_id, datos.sucursal_id, datos.monto, datos.tipo,
        datos.operacion_id, datos.motivo,
    )


class ComisionIn(BaseModel):
    usuario_id: int
    porcentaje: float


class LiquidacionIn(BaseModel):
    usuario_id: int
    desde: str
    hasta: str
    operacion_id: str


@app.get("/comisiones")
def panel_comisiones(sucursal_id: int | None = None, usuario_id: int | None = None,
                     db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    return servicios.listar_comisiones(db, sucursal_id, usuario_id)


@app.post("/comisiones", status_code=201)
def panel_guardar_comision(datos: ComisionIn, db=Depends(get_db),
                           usuario=Depends(requiere_rol("admin"))):
    return servicios.guardar_comision(db, usuario, datos.usuario_id, datos.porcentaje)


@app.get("/comisiones/resumen")
def panel_resumen_comisiones(desde: str, hasta: str, sucursal_id: int | None = None,
                             usuario_id: int | None = None, db=Depends(get_db),
                             usuario=Depends(requiere_rol("admin"))):
    return servicios.resumen_comisiones(db, _fecha(desde), _fecha(hasta), sucursal_id, usuario_id)


@app.get("/comisiones/liquidaciones")
def panel_liquidaciones(sucursal_id: int | None = None, usuario_id: int | None = None,
                        db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    return servicios.listar_liquidaciones(db, sucursal_id, usuario_id)


@app.post("/comisiones/liquidaciones", status_code=201)
def panel_registrar_liquidacion(datos: LiquidacionIn, db=Depends(get_db),
                                usuario=Depends(requiere_rol("admin"))):
    return servicios.registrar_liquidacion(
        db, usuario, datos.usuario_id, _fecha(datos.desde), _fecha(datos.hasta), datos.operacion_id,
    )


@app.post("/comisiones/liquidaciones/{liquidacion_id}/pagar")
def panel_pagar_liquidacion(liquidacion_id: int, db=Depends(get_db),
                            usuario=Depends(requiere_rol("admin"))):
    return servicios.pagar_liquidacion(db, usuario, liquidacion_id)


class JugadaIn(BaseModel):
    tipo: str
    sorteos: list[int]
    numeros: str
    monto: float


class VentaIn(BaseModel):
    jugadas: list[JugadaIn]
    operacion_id: str | None = None


@app.post("/terminal/venta", status_code=201)
def terminal_venta(datos: VentaIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                   operador=Depends(operador_actual)):
    jugadas = [j.model_dump() for j in datos.jugadas]
    return servicios.vender(db, terminal, operador, jugadas, operacion_id=datos.operacion_id)


@app.post("/terminal/tickets/consultar")
def terminal_consultar(datos: LlaveIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                       operador=Depends(operador_actual)):
    return servicios.consultar_ticket(db, datos.id, datos.serial)


@app.post("/terminal/tickets/pagar")
def terminal_pagar(datos: LlaveIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                   operador=Depends(operador_actual)):
    return servicios.pagar_ticket(db, datos.id, datos.serial, terminal.sucursal_id,
                                  terminal.id, operador.id, operacion_id=datos.operacion_id)


@app.post("/terminal/tickets/reimprimir")
def terminal_reimprimir(datos: LlaveIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                        operador=Depends(operador_actual)):
    return servicios.reimprimir_ticket(db, datos.id, datos.serial, operador.id, terminal_id=terminal.id)


@app.post("/terminal/tickets/anular")
def terminal_anular(datos: AnularIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                    operador=Depends(operador_actual)):
    """Cajera: solo sus tickets y solo durante los primeros 5 minutos."""
    return servicios.anular_ticket(
        db, datos.id, datos.serial, operador.id, terminal_id=terminal.id,
        motivo=datos.motivo, ventana_cajera=True,
    )


class CajaTerminalIn(BaseModel):
    monto: float
    concepto: str | None = None


@app.post("/terminal/caja/recibir", status_code=201)
def terminal_recibir(datos: CajaTerminalIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                     operador=Depends(operador_actual)):
    tx = servicios.registrar_caja(db, "recibir_efectivo", datos.monto, datos.concepto,
                                  terminal.sucursal_id, terminal.id, operador.id)
    return caja_dict(tx)


@app.post("/terminal/caja/gasto", status_code=201)
def terminal_gasto(datos: CajaTerminalIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                   operador=Depends(operador_actual)):
    tx = servicios.registrar_caja(db, "gasto", datos.monto, datos.concepto,
                                  terminal.sucursal_id, terminal.id, operador.id)
    return caja_dict(tx)


@app.get("/terminal/caja/transacciones")
def terminal_caja(fecha: str | None = None, db=Depends(get_db), terminal=Depends(terminal_actual),
                  operador=Depends(operador_actual)):
    q = db.query(TransaccionCaja).filter(TransaccionCaja.usuario_id == operador.id)
    q = q.filter(TransaccionCaja.fecha == (_fecha(fecha) if fecha else servicios.ahora_local().date()))
    return [caja_dict(t) for t in q.order_by(TransaccionCaja.id.desc()).all()]


class CuadreTerminalIn(BaseModel):
    efectivo_contado: float | None = None


@app.post("/terminal/caja/cuadre", status_code=201)
def terminal_cuadre(datos: CuadreTerminalIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                    operador=Depends(operador_actual)):
    c = servicios.entregar_cuadre(
        db, terminal.sucursal_id, terminal.id, operador.id,
        efectivo_contado=datos.efectivo_contado,
        limitar_a_usuario=operador.id if operador.rol == "operador" else None,
    )
    return servicios.cuadre_a_dict(c)


@app.get("/terminal/reportes/dia")
def terminal_resumen_dia(desde: str | None = None, hasta: str | None = None, alcance: str = "cajero",
                         db=Depends(get_db), terminal=Depends(terminal_actual),
                         operador=Depends(operador_actual)):
    hoy = servicios.ahora_local().date()
    inicio = _fecha(desde) if desde else hoy
    fin = _fecha(hasta) if hasta else hoy
    if fin < inicio:
        raise ErrorServicio(400, "La fecha hasta no puede ser anterior a la fecha desde")
    sucursal = db.get(Sucursal, terminal.sucursal_id)
    return servicios.resumen_dia(db, inicio, fin, operador, sucursal, terminal, alcance)


@app.get("/terminal/reportes/resumen")
def terminal_reporte_resumen(desde: str, hasta: str, vista: str = "final",
                             db=Depends(get_db), terminal=Depends(terminal_actual),
                             operador=Depends(operador_actual)):
    propio = operador.id if operador.rol == "operador" else None
    return servicios.reporte_resumen(
        db, _fecha(desde), _fecha(hasta), vista, terminal.sucursal_id, propio,
    )


@app.get("/terminal/reportes/pendientes")
def terminal_reporte_pendientes(desde: str, hasta: str, formato: str = "json",
                                db=Depends(get_db), terminal=Depends(terminal_actual),
                                operador=Depends(operador_actual)):
    propio = operador.id if operador.rol == "operador" else None
    if formato == "texto":
        return PlainTextResponse(
            servicios.pendientes_texto(
                db, _fecha(desde), _fecha(hasta), terminal.sucursal_id, terminal, propio,
            )
        )
    return servicios.reporte_pendientes(
        db, _fecha(desde), _fecha(hasta), terminal.sucursal_id, propio,
    )


# ------------------------------------------------------------------ panel web
@app.get("/")
def raiz():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
