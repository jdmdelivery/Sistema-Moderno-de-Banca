"""API del Sistema de Banca Moderna: panel del consorcio + API de terminales.

Arranque local:  uvicorn apps.api.main:app --port 8100
La BD se elige con DATABASE_URL (PostgreSQL en producción, SQLite en local).
"""
import json
from datetime import date, datetime, time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import conectate, conectate_widget, estabilizacion, permisos, resultados_auto, servicios
from .comun import D, ErrorServicio, MSG_USUARIO_BLOQUEADO, loterias_abiertas_desarrollo, modo_desarrollo
from .db import configurar, engine, init_db, nueva_sesion
from .models import (
    Auditoria,
    LimiteVenta,
    MovimientoSaldo,
    PermisoSucursal,
    Resultado,
    Sorteo,
    Sucursal,
    TablaPagos,
    Terminal,
    Ticket,
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
        if not permisos.tiene_rol(usuario, *roles):
            raise ErrorServicio(403, f"Su rol ({usuario.rol}) no puede hacer esta operación")
        return usuario

    return dep


def requiere_super_admin(usuario=Depends(panel_actual)):
    if not permisos.es_super_admin(usuario):
        raise ErrorServicio(403, "Solo el Super Admin puede hacer esta operación")
    return usuario


def requiere_gestion_consorcio(usuario=Depends(panel_actual), db=Depends(get_db)):
    """Terminales/sorteos/resultados/auditoría: solo Super Admin (o admin en compat)."""
    if permisos.es_super_admin(usuario):
        return usuario
    if usuario.rol == "admin" and permisos.compat_global_activo(db):
        return usuario
    raise ErrorServicio(403, "Solo el Super Admin puede hacer esta operación")


def requiere_gestion_sucursales(usuario=Depends(panel_actual), db=Depends(get_db)):
    """Crear/editar sucursales: Super Admin, o admin en modo compat global."""
    if permisos.es_super_admin(usuario):
        return usuario
    if usuario.rol == "admin" and permisos.compat_global_activo(db):
        return usuario
    raise ErrorServicio(403, "Solo el Super Admin puede crear o editar sucursales")


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
    eliminado = bool(getattr(u, "eliminado", False))
    aprob = permisos.estado_aprobacion_de(u)
    if eliminado:
        estado = "ELIMINADO"
    elif aprob == permisos.ESTADO_PENDIENTE:
        estado = "PENDIENTE"
    elif aprob == permisos.ESTADO_RECHAZADO:
        estado = "RECHAZADO"
    elif bool(getattr(u, "suspendido", False)):
        estado = "SUSPENDIDO"
    elif u.activo:
        estado = "ACTIVO"
    else:
        estado = "BLOQUEADO"
    datos = {
        "id": u.id, "nombre": u.nombre, "usuario": u.usuario, "rol": u.rol,
        "sucursal_id": u.sucursal_id, "activo": bool(u.activo) and not eliminado,
        "eliminado": eliminado,
        "suspendido": bool(getattr(u, "suspendido", False)),
        "estado_aprobacion": aprob,
        "estado": estado,
        "tiene_clave": bool(u.clave_hash), "tiene_pin": bool(u.pin_hash),
        "eliminado_en": u.eliminado_en.isoformat(sep=" ") if getattr(u, "eliminado_en", None) else None,
        "motivo_eliminacion": getattr(u, "motivo_eliminacion", None),
        "solicitado_en": u.solicitado_en.isoformat(sep=" ") if getattr(u, "solicitado_en", None) else None,
        "aprobado_en": u.aprobado_en.isoformat(sep=" ") if getattr(u, "aprobado_en", None) else None,
        "aprobado_por": getattr(u, "aprobado_por", None),
        "motivo_rechazo": getattr(u, "motivo_rechazo", None),
    }
    if con_cajas:
        datos["saldo_caja"] = str(D(u.saldo_caja or 0))
        datos["saldo_caja_prueba"] = str(D(u.saldo_caja_prueba or 0))
    return datos


def permiso_sucursal_dict(p):
    return {
        "sucursal_id": p.sucursal_id,
        "puede_crear_cajeros": bool(p.puede_crear_cajeros),
        "puede_asignar_fondos": bool(p.puede_asignar_fondos),
        "puede_registrar_entregas": bool(p.puede_registrar_entregas),
        "puede_ajustar_caja": bool(p.puede_ajustar_caja),
        "puede_configurar_limites": bool(p.puede_configurar_limites),
        "puede_anular_tickets": bool(p.puede_anular_tickets),
        "puede_ver_reportes": bool(p.puede_ver_reportes),
        "actualizado_en": p.actualizado_en.isoformat(sep=" ") if p.actualizado_en else None,
        "actualizado_por": p.actualizado_por,
    }


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
    sid2 = int(getattr(l, "sorteo2_id", 0) or 0)
    tipo = db.get(TipoJugada, l.tipo_jugada_id)
    return {
        "id": l.id, "sorteo_id": l.sorteo_id, "sorteo2_id": sid2,
        "sorteo": servicios._etiqueta_sorteos(db, l.sorteo_id, sid2),
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
    if (usuario is None or usuario.rol not in ("super_admin", "admin", "supervisor")
            or not usuario.clave_hash or not verificar_clave(datos.clave, usuario.clave_hash)):
        raise ErrorServicio(401, "Usuario o clave incorrectos")
    permisos.usuario_puede_iniciar_sesion(usuario)
    token = servicios.crear_sesion(db, usuario, tipo="panel")
    db.commit()
    datos_u = usuario_dict(usuario)
    datos_u["compat_global"] = permisos.compat_global_activo(db)
    return {"token": token, "usuario": datos_u}


@app.post("/auth/logout")
def logout(request: Request, db=Depends(get_db)):
    servicios.cerrar_sesion(db, _bearer(request))
    return {"ok": True}


@app.get("/auth/yo")
def yo(usuario=Depends(panel_actual), db=Depends(get_db)):
    datos = usuario_dict(usuario)
    datos["compat_global"] = permisos.compat_global_activo(db)
    return datos


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
    q = db.query(Sucursal).order_by(Sucursal.codigo)
    q = permisos.filtrar_query_sucursal(q, Sucursal.id, db, usuario)
    filas = []
    for s in q.all():
        datos = sucursal_dict(s)
        if permisos.es_admin_panel(usuario):
            datos["consolidado_cajas"] = servicios.consolidado_cajas(db, s.id)
        filas.append(datos)
    return filas


@app.post("/sucursales", status_code=201)
def crear_sucursal(datos: SucursalIn, db=Depends(get_db), usuario=Depends(requiere_gestion_sucursales)):
    if db.query(Sucursal).filter_by(codigo=datos.codigo.strip()).first():
        raise ErrorServicio(409, f"Ya existe una sucursal con el código {datos.codigo}")
    s = Sucursal(
        codigo=datos.codigo.strip(), nombre=datos.nombre.strip(), direccion=datos.direccion,
        telefono=datos.telefono, comision_porcentaje=D(datos.comision_porcentaje), activa=datos.activa,
    )
    db.add(s)
    db.flush()
    db.add(PermisoSucursal(sucursal_id=s.id))
    servicios.auditar(db, "sucursal", s.id, "creacion", usuario_id=usuario.id,
                      detalle={"codigo": s.codigo, "nombre": s.nombre})
    db.commit()
    db.refresh(s)
    return sucursal_dict(s)


@app.put("/sucursales/{sucursal_id}")
def editar_sucursal(sucursal_id: int, datos: SucursalIn, db=Depends(get_db),
                    usuario=Depends(requiere_gestion_sucursales)):
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
    permisos.assert_sucursal_permitida(db, usuario, sucursal_id)
    filas = (
        db.query(MovimientoSaldo)
        .filter_by(sucursal_id=sucursal_id)
        .order_by(MovimientoSaldo.id.desc())
        .limit(min(limite, 500))
        .all()
    )
    return [movimiento_dict(m) for m in filas]


# ---------------------------------------------------------- diseño ticket (panel)
class DisenoTicketIn(BaseModel):
    config: dict
    activo: bool = True


@app.get("/panel/diseno-ticket")
def panel_diseno_ticket_get(
    sucursal_id: int | None = None,
    db=Depends(get_db),
    usuario=Depends(requiere_rol("admin", "super_admin")),
):
    from . import impresion_servidor as imp

    sid = sucursal_id or usuario.sucursal_id
    if sid is None:
        raise ErrorServicio(400, "Indique sucursal_id")
    permisos.assert_sucursal_permitida(db, usuario, sid)
    try:
        return imp.diseno_a_dict(db, int(sid))
    except imp.ErrorImpresion as e:
        raise ErrorServicio(e.codigo, e.detalle)


@app.put("/panel/diseno-ticket")
def panel_diseno_ticket_put(
    datos: DisenoTicketIn,
    sucursal_id: int | None = None,
    db=Depends(get_db),
    usuario=Depends(requiere_rol("admin", "super_admin")),
):
    from . import impresion_servidor as imp

    sid = sucursal_id or usuario.sucursal_id
    if sid is None:
        raise ErrorServicio(400, "Indique sucursal_id")
    permisos.assert_sucursal_permitida(db, usuario, sid)
    try:
        return imp.guardar_diseno(db, int(sid), datos.config, usuario.id, activo=datos.activo)
    except imp.ErrorImpresion as e:
        raise ErrorServicio(e.codigo, e.detalle)


@app.post("/panel/diseno-ticket/preview")
def panel_diseno_ticket_preview(
    datos: DisenoTicketIn | None = None,
    sucursal_id: int | None = None,
    db=Depends(get_db),
    usuario=Depends(requiere_rol("admin", "super_admin")),
):
    from . import impresion_servidor as imp

    sid = sucursal_id or usuario.sucursal_id
    if sid is not None:
        permisos.assert_sucursal_permitida(db, usuario, sid)
    cfg = datos.config if datos else None
    try:
        png = imp.render_preview(db, int(sid) if sid else None, cfg)
    except Exception as e:
        raise ErrorServicio(500, f"No se pudo generar la vista previa: {e}")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- terminales
class TerminalIn(BaseModel):
    sucursal_id: int
    numero_terminal: int = 1
    serial_sunmi: str
    version_app: str | None = None
    activa: bool = True


@app.get("/terminales")
def listar_terminales(db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    """Listado de gestión de terminales: solo Super Admin (panel Consorcio).
    Las SUNMI usan /terminal/* y no dependen de este endpoint."""
    q = db.query(Terminal).order_by(Terminal.sucursal_id, Terminal.numero_terminal)
    q = permisos.filtrar_query_sucursal(q, Terminal.sucursal_id, db, usuario)
    return [terminal_dict(t) for t in q.all()]


@app.post("/terminales", status_code=201)
def crear_terminal(datos: TerminalIn, db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    permisos.assert_sucursal_permitida(db, usuario, datos.sucursal_id)
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
                    usuario=Depends(requiere_gestion_consorcio)):
    t = db.get(Terminal, terminal_id)
    if t is None:
        raise ErrorServicio(404, "La terminal no existe")
    permisos.assert_sucursal_permitida(db, usuario, t.sucursal_id)
    permisos.assert_sucursal_permitida(db, usuario, datos.sucursal_id)
    t.numero_terminal = datos.numero_terminal
    t.serial_sunmi = datos.serial_sunmi.strip()
    t.version_app = datos.version_app
    t.activa = datos.activa
    servicios.auditar(db, "terminal", t.id, "edicion", usuario_id=usuario.id, detalle={})
    db.commit()
    db.refresh(t)
    return terminal_dict(t)


@app.post("/terminales/{terminal_id}/revocar")
def revocar_terminal(terminal_id: int, db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    t = db.get(Terminal, terminal_id)
    if t is None:
        raise ErrorServicio(404, "La terminal no existe")
    permisos.assert_sucursal_permitida(db, usuario, t.sucursal_id)
    t.token_hash = None
    t.activa = False
    servicios.auditar(db, "terminal", t.id, "revocacion", usuario_id=usuario.id,
                      detalle={"serial_sunmi": t.serial_sunmi})
    db.commit()
    db.refresh(t)
    return terminal_dict(t)


@app.post("/terminales/{terminal_id}/reactivar")
def reactivar_terminal(terminal_id: int, db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    t = db.get(Terminal, terminal_id)
    if t is None:
        raise ErrorServicio(404, "La terminal no existe")
    permisos.assert_sucursal_permitida(db, usuario, t.sucursal_id)
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
def listar_usuarios(estado: str | None = None, db=Depends(get_db),
                    usuario=Depends(requiere_rol("admin", "supervisor"))):
    q = db.query(Usuario).order_by(Usuario.nombre)
    q = permisos.filtrar_query_sucursal(q, Usuario.sucursal_id, db, usuario)
    # Supervisor/admin de sucursal nunca listan Super Admin.
    if not permisos.es_super_admin(usuario):
        q = q.filter(Usuario.rol != "super_admin")
    clave = (estado or "").strip().lower()
    if clave in ("activos", "activo"):
        q = q.filter(Usuario.activo.is_(True), Usuario.eliminado.is_(False))
    elif clave in ("bloqueados", "bloqueado"):
        q = q.filter(Usuario.activo.is_(False), Usuario.eliminado.is_(False))
    elif clave in ("eliminados", "eliminado"):
        q = q.filter(Usuario.eliminado.is_(True))
    elif clave in ("pendientes", "pendiente"):
        q = q.filter(
            Usuario.eliminado.is_(False),
            Usuario.estado_aprobacion == permisos.ESTADO_PENDIENTE,
        )
    elif clave in ("todos", "all"):
        pass
    else:
        # Default / operativos: sin eliminados.
        q = q.filter(Usuario.eliminado.is_(False))
    return [
        usuario_dict(u, con_cajas=permisos.es_admin_panel(usuario))
        for u in q.all()
    ]


@app.post("/usuarios", status_code=201)
def crear_usuario(datos: UsuarioIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    if datos.rol == "super_admin" and not permisos.es_super_admin(usuario):
        raise ErrorServicio(403, "Solo el Super Admin puede crear otro Super Admin")
    if datos.rol in ("admin", "super_admin") and not (
        permisos.es_super_admin(usuario) or permisos.compat_global_activo(db)
    ):
        raise ErrorServicio(403, "Solo el Super Admin puede crear administradores")
    roles_ok = ("admin", "supervisor", "operador")
    if permisos.es_super_admin(usuario):
        roles_ok = ("super_admin", "admin", "supervisor", "operador")
    if datos.rol not in roles_ok:
        raise ErrorServicio(400, f"Rol no válido: {', '.join(roles_ok)}")
    if db.query(Usuario).filter_by(usuario=datos.usuario.strip()).first():
        raise ErrorServicio(409, f"Ya existe el usuario {datos.usuario}")
    if datos.rol in ("super_admin", "admin", "supervisor") and not datos.clave:
        raise ErrorServicio(400, "Un admin/supervisor necesita una clave para el panel")
    if datos.rol == "operador" and not datos.clave:
        raise ErrorServicio(400, "Un operador necesita una contraseña para entrar en la terminal")

    sucursal_id = datos.sucursal_id
    if usuario.rol == "admin" and not permisos.compat_global_activo(db):
        if usuario.sucursal_id is None:
            raise ErrorServicio(403, "Su cuenta no tiene sucursal asignada")
        sucursal_id = usuario.sucursal_id
        if datos.rol != "operador":
            raise ErrorServicio(403, "Un administrador de sucursal solo puede crear cajeros")
    if datos.rol in ("admin", "supervisor", "operador") and sucursal_id is None and datos.rol != "super_admin":
        if datos.rol == "operador":
            raise ErrorServicio(400, "El cajero necesita una sucursal asignada")
    if sucursal_id is not None:
        permisos.assert_sucursal_permitida(db, usuario, sucursal_id)
    if datos.rol == "operador" and sucursal_id is not None and not permisos.es_super_admin(usuario):
        permisos.assert_permiso_sucursal(db, usuario, sucursal_id, "puede_crear_cajeros")

    u = Usuario(
        nombre=datos.nombre.strip(), usuario=datos.usuario.strip(), rol=datos.rol,
        sucursal_id=sucursal_id, activo=datos.activo,
        clave_hash=hash_clave(datos.clave) if datos.clave else None,
        estado_aprobacion=permisos.ESTADO_APROBADO,
    )
    # Con Super Admin activo: cajeros creados por admin de sucursal quedan PENDIENTES.
    # Compat global (sin Super Admin): nacen aprobados (comportamiento histórico / tests).
    if (
        datos.rol == "operador"
        and not permisos.es_super_admin(usuario)
        and permisos.hay_super_admin(db)
    ):
        permisos.marcar_operador_pendiente(u, usuario.id)
        u.activo = True  # ficha activa; login bloqueado por pendiente
    db.add(u)
    db.flush()
    servicios.auditar(
        db, "usuario", u.id, "creacion", usuario_id=usuario.id,
        detalle={
            "rol": u.rol,
            "estado_aprobacion": u.estado_aprobacion,
            "sucursal_id": u.sucursal_id,
        },
    )
    db.commit()
    db.refresh(u)
    return usuario_dict(u, con_cajas=True)


@app.put("/usuarios/{usuario_id}")
def editar_usuario(usuario_id: int, datos: UsuarioIn, db=Depends(get_db),
                   usuario=Depends(requiere_rol("admin"))):
    u = db.get(Usuario, usuario_id)
    if u is None:
        raise ErrorServicio(404, "El usuario no existe")
    if getattr(u, "eliminado", False):
        raise ErrorServicio(409, "Un usuario eliminado no se puede editar")
    permisos.assert_usuario_en_alcance(db, usuario, u)
    if datos.rol == "super_admin" and not permisos.es_super_admin(usuario):
        raise ErrorServicio(403, "No puede asignar el rol Super Admin")
    if u.rol == "super_admin" and not permisos.es_super_admin(usuario):
        raise ErrorServicio(403, "No puede editar una cuenta Super Admin")
    # El estado ACTIVO/BLOQUEADO se cambia solo con /bloquear y /desbloquear
    # para exigir confirmación, auditoría e invalidación de sesiones.
    nuevo_sucursal = datos.sucursal_id
    if usuario.rol == "admin" and not permisos.compat_global_activo(db):
        nuevo_sucursal = usuario.sucursal_id
        if datos.rol != u.rol and datos.rol != "operador":
            raise ErrorServicio(403, "Un administrador de sucursal no puede cambiar roles de panel")
    if nuevo_sucursal is not None:
        permisos.assert_sucursal_permitida(db, usuario, nuevo_sucursal)
    u.nombre = datos.nombre.strip()
    if permisos.es_super_admin(usuario) or permisos.compat_global_activo(db):
        u.rol = datos.rol
        u.sucursal_id = nuevo_sucursal
    else:
        u.sucursal_id = nuevo_sucursal
    if datos.clave:
        u.clave_hash = hash_clave(datos.clave)
    servicios.auditar(db, "usuario", u.id, "edicion", usuario_id=usuario.id, detalle={})
    db.commit()
    db.refresh(u)
    return usuario_dict(u, con_cajas=True)


@app.post("/usuarios/{usuario_id}/bloquear")
def bloquear_usuario(usuario_id: int, db=Depends(get_db),
                     usuario=Depends(requiere_rol("admin"))):
    """Bloqueo en tiempo real: activo=False + invalida sesiones SUNMI/panel."""
    return usuario_dict(
        servicios.bloquear_usuario(db, usuario, usuario_id),
        con_cajas=True,
    )


@app.post("/usuarios/{usuario_id}/desbloquear")
def desbloquear_usuario(usuario_id: int, db=Depends(get_db),
                        usuario=Depends(requiere_rol("admin"))):
    return usuario_dict(
        servicios.desbloquear_usuario(db, usuario, usuario_id),
        con_cajas=True,
    )


class EliminarUsuarioIn(BaseModel):
    motivo: str | None = None
    confirmar: bool = False


@app.post("/usuarios/{usuario_id}/eliminar")
def eliminar_usuario(usuario_id: int, datos: EliminarUsuarioIn, db=Depends(get_db),
                     usuario=Depends(requiere_rol("admin"))):
    """Eliminación física sin historial o lógica si hay movimientos financieros."""
    if not datos.confirmar:
        raise ErrorServicio(400, "Debe confirmar la eliminación del usuario")
    resultado = servicios.eliminar_usuario(db, usuario, usuario_id, datos.motivo)
    if resultado["modo"] == "fisica":
        return {"ok": True, "modo": "fisica", "id": resultado["id"], "detalle": resultado["detalle"]}
    return {
        "ok": True,
        "modo": "logica",
        "usuario": usuario_dict(resultado["usuario"], con_cajas=True),
    }


class RechazoCajeroIn(BaseModel):
    motivo: str | None = None


@app.get("/super/cajeros-pendientes")
def listar_cajeros_pendientes(db=Depends(get_db), usuario=Depends(requiere_super_admin)):
    filas = (
        db.query(Usuario)
        .filter(
            Usuario.rol == "operador",
            Usuario.eliminado.is_(False),
            Usuario.estado_aprobacion == permisos.ESTADO_PENDIENTE,
        )
        .order_by(Usuario.id.desc())
        .all()
    )
    return [usuario_dict(u, con_cajas=True) for u in filas]


@app.get("/super/resumen")
def super_resumen(db=Depends(get_db), usuario=Depends(requiere_super_admin)):
    """Vista consorcio: sucursales, admins, cajeros y cola de aprobación."""
    pendientes = (
        db.query(Usuario)
        .filter(
            Usuario.rol == "operador",
            Usuario.eliminado.is_(False),
            Usuario.estado_aprobacion == permisos.ESTADO_PENDIENTE,
        )
        .count()
    )
    filas = []
    for s in db.query(Sucursal).order_by(Sucursal.codigo).all():
        admins = (
            db.query(Usuario)
            .filter(
                Usuario.sucursal_id == s.id,
                Usuario.rol == "admin",
                Usuario.eliminado.is_(False),
            )
            .all()
        )
        ops = (
            db.query(Usuario)
            .filter(
                Usuario.sucursal_id == s.id,
                Usuario.rol == "operador",
                Usuario.eliminado.is_(False),
            )
            .all()
        )
        ops_pend = sum(
            1 for u in ops
            if permisos.estado_aprobacion_de(u) == permisos.ESTADO_PENDIENTE
        )
        ops_ok = sum(
            1 for u in ops
            if permisos.estado_aprobacion_de(u) == permisos.ESTADO_APROBADO and u.activo
        )
        filas.append({
            "id": s.id,
            "codigo": s.codigo,
            "nombre": s.nombre,
            "activa": bool(s.activa),
            "saldo_actual": float(s.saldo_actual or 0),
            "admins": [
                {"id": a.id, "nombre": a.nombre, "usuario": a.usuario, "activo": bool(a.activo)}
                for a in admins
            ],
            "cajeros_activos": ops_ok,
            "cajeros_pendientes": ops_pend,
            "cajeros_total": len(ops),
            "permisos": permiso_sucursal_dict(permisos.permisos_de_sucursal(db, s.id)),
        })
    return {
        "compat_global": permisos.compat_global_activo(db),
        "compat_global_forzado": permisos.compat_global_forzado(),
        "cajeros_pendientes_total": pendientes,
        "sucursales": filas,
    }


@app.post("/super/cajeros/{usuario_id}/aprobar")
def aprobar_cajero(usuario_id: int, db=Depends(get_db), usuario=Depends(requiere_super_admin)):
    objetivo = db.get(Usuario, usuario_id)
    permisos.aprobar_operador(db, usuario, objetivo)
    servicios.auditar(
        db, "usuario", objetivo.id, "aprobacion_cajero", usuario_id=usuario.id,
        detalle={"usuario": objetivo.usuario, "sucursal_id": objetivo.sucursal_id},
    )
    db.commit()
    db.refresh(objetivo)
    return usuario_dict(objetivo, con_cajas=True)


@app.post("/super/cajeros/{usuario_id}/rechazar")
def rechazar_cajero(usuario_id: int, datos: RechazoCajeroIn | None = None,
                    db=Depends(get_db), usuario=Depends(requiere_super_admin)):
    objetivo = db.get(Usuario, usuario_id)
    motivo = datos.motivo if datos else None
    permisos.rechazar_operador(db, usuario, objetivo, motivo)
    servicios.invalidar_sesiones_usuario(db, objetivo.id)
    servicios.auditar(
        db, "usuario", objetivo.id, "rechazo_cajero", usuario_id=usuario.id,
        detalle={"usuario": objetivo.usuario, "motivo": motivo},
    )
    db.commit()
    db.refresh(objetivo)
    return usuario_dict(objetivo, con_cajas=True)


@app.get("/super/permisos-sucursal/{sucursal_id}")
def ver_permisos_sucursal(sucursal_id: int, db=Depends(get_db),
                          usuario=Depends(requiere_super_admin)):
    if db.get(Sucursal, sucursal_id) is None:
        raise ErrorServicio(404, "La sucursal no existe")
    return permiso_sucursal_dict(permisos.permisos_de_sucursal(db, sucursal_id))


class PermisosSucursalIn(BaseModel):
    puede_crear_cajeros: bool = True
    puede_asignar_fondos: bool = True
    puede_registrar_entregas: bool = True
    puede_ajustar_caja: bool = True
    puede_configurar_limites: bool = True
    puede_anular_tickets: bool = True
    puede_ver_reportes: bool = True


@app.put("/super/permisos-sucursal/{sucursal_id}")
def editar_permisos_sucursal(sucursal_id: int, datos: PermisosSucursalIn,
                             db=Depends(get_db), usuario=Depends(requiere_super_admin)):
    if db.get(Sucursal, sucursal_id) is None:
        raise ErrorServicio(404, "La sucursal no existe")
    fila = permisos.permisos_de_sucursal(db, sucursal_id)
    for campo, valor in datos.model_dump().items():
        setattr(fila, campo, valor)
    from .comun import ahora_local
    fila.actualizado_en = ahora_local()
    fila.actualizado_por = usuario.id
    servicios.auditar(
        db, "permisos_sucursal", sucursal_id, "edicion", usuario_id=usuario.id,
        detalle=datos.model_dump(),
    )
    db.commit()
    db.refresh(fila)
    return permiso_sucursal_dict(fila)


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
def crear_sorteo(datos: SorteoIn, db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
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
                  usuario=Depends(requiere_gestion_consorcio)):
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
    sorteo2_id: int | None = None
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
    n1, n2, n3 = servicios._parse_numeros(tipo.codigo, datos.numeros)
    clave = servicios.clave_numero(n1, n2, n3)
    sid2 = int(getattr(datos, "sorteo2_id", 0) or 0)
    if tipo.codigo == "SP":
        if not sid2 or sid2 == datos.sorteo_id:
            raise ErrorServicio(400, "El Súper Palé requiere dos loterías diferentes")
        if db.get(Sorteo, sid2) is None:
            raise ErrorServicio(404, "Sorteo o tipo de jugada no válido")
        sid, sid2 = servicios._par_sorteos_limite(datos.sorteo_id, sid2)
    else:
        sid, sid2 = datos.sorteo_id, 0
    existente = db.query(LimiteVenta).filter_by(
        sorteo_id=sid, sorteo2_id=sid2, tipo_jugada_id=tipo.id, clave_numero=clave,
    ).first()
    if existente is not None:
        existente.monto_max_acumulado = D(datos.monto_max_acumulado)
        db.commit()
        db.refresh(existente)
        return limite_dict(existente, db)
    lim = LimiteVenta(
        sorteo_id=sid, sorteo2_id=sid2, tipo_jugada_id=tipo.id, clave_numero=clave,
        monto_max_acumulado=D(datos.monto_max_acumulado),
    )
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
    sorteo2_id: int | None = None
    tipo: str
    numeros: str | None = None
    monto_max_acumulado: float
    id: int | None = None


@app.get("/limites-cajera")
def listar_limites_cajera(usuario_id: int | None = None, sucursal_id: int | None = None,
                          db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.listar_limites_cajera(db, usuario_id, sid)


@app.post("/limites-cajera", status_code=201)
def guardar_limite_cajera(datos: LimiteCajeraIn, db=Depends(get_db),
                          usuario=Depends(requiere_rol("admin"))):
    return servicios.guardar_limite_cajera(
        db, usuario, datos.usuario_id, datos.sorteo_id, datos.tipo, datos.numeros,
        datos.monto_max_acumulado, datos.id, datos.sorteo2_id,
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
                      db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    q = db.query(Resultado)
    if fecha:
        q = q.filter(Resultado.fecha == _fecha(fecha))
    if sorteo_id:
        q = q.filter(Resultado.sorteo_id == sorteo_id)
    return [servicios.resultado_a_dict(r) for r in q.order_by(Resultado.fecha.desc(), Resultado.sorteo_id).all()]


@app.post("/resultados", status_code=201)
def guardar_resultado(datos: ResultadoIn, db=Depends(get_db),
                      usuario=Depends(requiere_gestion_consorcio)):
    r = servicios.guardar_resultado(
        db, datos.sorteo_id, _fecha(datos.fecha),
        datos.premio1, datos.premio2, datos.premio3, usuario, simulado=datos.simulado,
    )
    salida = servicios.resultado_a_dict(r)
    salida["tickets_prueba"] = int(getattr(r, "_tickets_prueba", 0) or 0)
    return salida


@app.post("/resultados/{resultado_id}/confirmar")
def confirmar_resultado(resultado_id: int, db=Depends(get_db),
                        usuario=Depends(requiere_gestion_consorcio)):
    r, afectados = servicios.confirmar_resultado(db, resultado_id, usuario)
    salida = servicios.resultado_a_dict(r)
    salida["tickets_afectados"] = afectados
    return salida


@app.post("/resultados/{resultado_id}/revertir")
def revertir_resultado(resultado_id: int, db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    r, afectados = servicios.revertir_resultado(db, resultado_id, usuario)
    salida = servicios.resultado_a_dict(r)
    salida["tickets_afectados"] = afectados
    return salida


class ImportarIn(BaseModel):
    fecha: str | None = None


@app.post("/resultados/importar")
def importar_resultados(datos: ImportarIn, db=Depends(get_db),
                        usuario=Depends(requiere_gestion_consorcio)):
    fecha = _fecha(datos.fecha) if datos.fecha else servicios.ahora_local().date()
    return conectate.importar_resultados(db, fecha, usuario)


@app.get("/resultados/tablero")
def tablero_resultados(db=Depends(get_db), usuario=Depends(panel_actual)):
    return servicios.tablero_resultados(db, servicios.ahora_local().date())


@app.get("/movil/admin")
def movil_admin(seccion: str = "inicio", desde: str | None = None, hasta: str | None = None,
                sucursal_id: int | None = None, usuario_id: int | None = None, q: str = "",
                db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    # Resultados automáticos / consorcio: solo Super Admin (o compat global).
    if (seccion or "").strip().lower() == "resultados":
        if not permisos.es_super_admin(usuario) and not (
            usuario.rol == "admin" and permisos.compat_global_activo(db)
        ):
            raise ErrorServicio(403, "Solo el Super Admin puede ver resultados del consorcio")
    hoy = servicios.ahora_local().date()
    inicio = _fecha(desde) if desde else hoy
    fin = _fecha(hasta) if hasta else hoy
    return servicios.panel_movil(db, usuario, seccion, inicio, fin, sucursal_id, usuario_id, q)


@app.get("/fuente-resultados")
def cobertura_resultados(db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    trabajador = resultados_auto.estado_reloj(db)
    return {
        "fuente": "conectate",
        "nombre_fuente": "Conéctate.com",
        "url": conectate_widget.URL_WIDGET,
        "aviso": "Fuente: Conéctate.com. Tres lecturas iguales y 4 minutos "
                 "estables antes de confirmar. Intervalo adaptativo cerca del sorteo. "
                 "No paga solo. No inventa números si la fuente falla.",
        "intervalo_segundos": resultados_auto.INTERVALO_SEGUNDOS,
        "intervalo_rapido_segundos": resultados_auto.INTERVALO_RAPIDO_SEGUNDOS,
        "minutos_estables": estabilizacion.MINUTOS_ESTABLES,
        "lecturas_minimas": estabilizacion.LECTURAS_MINIMAS,
        "trabajador": trabajador,
        "ultimo_resultado": trabajador.get("ultimo_detalle"),
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
def probar_widget(usuario=Depends(requiere_gestion_consorcio)):
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
def sincronizar_resultados(db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
    return resultados_auto.ciclo(forzar=True)


@app.get("/ganadores")
def ganadores(fecha: str | None = None, sorteo_id: int | None = None, sucursal_id: int | None = None,
              usuario_id: int | None = None, estado: str | None = None,
              db=Depends(get_db), usuario=Depends(panel_actual)):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.listar_ganadores(
        db,
        fecha=_fecha(fecha) if fecha else None,
        sorteo_id=sorteo_id,
        sucursal_id=sid,
        usuario_id=usuario_id,
        estado=estado,
    )


@app.get("/ganadores/{ticket_id}")
def ganador_detalle(ticket_id: int, db=Depends(get_db), usuario=Depends(panel_actual)):
    """Solo lectura: jugadas ganadoras del ticket, sin pagar desde el panel."""
    ticket = db.get(Ticket, ticket_id)
    permisos.assert_ticket_en_alcance(db, usuario, ticket)
    return servicios.detalle_ticket_ganador(db, ticket_id)


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


@app.get("/panel/tickets")
def panel_listar_tickets(
    desde: date | None = None,
    hasta: date | None = None,
    sucursal_id: int | None = None,
    usuario_id: int | None = None,
    estado: str | None = None,
    ticket_id: int | None = None,
    pagina: int = 1,
    por_pagina: int = 50,
    db=Depends(get_db),
    usuario=Depends(requiere_rol("admin", "supervisor")),
):
    """Lista filtrada de tickets. Solo lectura; filtrada por alcance."""
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.listar_tickets_panel(
        db,
        desde=desde,
        hasta=hasta,
        sucursal_id=sid,
        usuario_id=usuario_id,
        estado=estado,
        ticket_id=ticket_id,
        pagina=pagina,
        por_pagina=por_pagina,
    )


@app.get("/panel/tickets/{ticket_id}")
def panel_detalle_ticket(ticket_id: int, db=Depends(get_db),
                         usuario=Depends(requiere_rol("admin", "supervisor"))):
    ticket = db.get(Ticket, ticket_id)
    permisos.assert_ticket_en_alcance(db, usuario, ticket)
    return servicios.ticket_a_dict(db, ticket)


@app.get("/panel/tickets/{ticket_id}/anulacion")
def panel_info_anulacion(ticket_id: int, db=Depends(get_db),
                         usuario=Depends(requiere_rol("admin"))):
    """Vista previa de anulación administrativa (no modifica datos)."""
    ticket = db.get(Ticket, ticket_id)
    permisos.assert_ticket_en_alcance(db, usuario, ticket)
    return servicios.info_anulacion_admin(db, ticket)


@app.post("/panel/tickets/consultar")
def panel_consultar(datos: LlaveIn, db=Depends(get_db), usuario=Depends(panel_actual)):
    ticket = db.get(Ticket, datos.id)
    permisos.assert_ticket_en_alcance(db, usuario, ticket)
    return servicios.consultar_ticket(db, datos.id, datos.serial)


@app.post("/panel/tickets/pagar")
def panel_pagar(datos: PanelPagoIn, db=Depends(get_db),
                usuario=Depends(requiere_rol("admin", "supervisor"))):
    permisos.assert_sucursal_permitida(db, usuario, datos.sucursal_id)
    ticket = db.get(Ticket, datos.id)
    permisos.assert_ticket_en_alcance(db, usuario, ticket)
    return servicios.pagar_ticket(db, datos.id, datos.serial, datos.sucursal_id, None, usuario.id)


@app.post("/panel/tickets/anular")
def panel_anular(datos: AnularIn, db=Depends(get_db),
                 usuario=Depends(requiere_rol("admin"))):
    """Solo el administrador del Panel. No aplica el límite de 5 minutos."""
    ticket = db.get(Ticket, datos.id)
    permisos.assert_ticket_en_alcance(db, usuario, ticket)
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
    permisos.assert_sucursal_permitida(db, usuario, datos.sucursal_id)
    permisos.assert_permiso_sucursal(db, usuario, datos.sucursal_id, "puede_ajustar_caja")
    tx = servicios.registrar_caja(db, "recibir_efectivo", datos.monto, datos.concepto,
                                  datos.sucursal_id, datos.terminal_id, usuario.id)
    return caja_dict(tx)


@app.post("/panel/caja/gasto", status_code=201)
def panel_gasto(datos: CajaIn, db=Depends(get_db), usuario=Depends(requiere_rol("admin", "supervisor"))):
    permisos.assert_sucursal_permitida(db, usuario, datos.sucursal_id)
    permisos.assert_permiso_sucursal(db, usuario, datos.sucursal_id, "puede_ajustar_caja")
    tx = servicios.registrar_caja(db, "gasto", datos.monto, datos.concepto,
                                  datos.sucursal_id, datos.terminal_id, usuario.id)
    return caja_dict(tx)


@app.get("/caja/transacciones")
def listar_caja(sucursal_id: int | None = None, terminal_id: int | None = None,
                fecha: str | None = None, limite: int = 200,
                db=Depends(get_db), usuario=Depends(panel_actual)):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    q = db.query(TransaccionCaja)
    if sid is not None:
        q = q.filter(TransaccionCaja.sucursal_id == sid)
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
    permisos.assert_sucursal_permitida(db, usuario, datos.sucursal_id)
    c = servicios.entregar_cuadre(
        db, datos.sucursal_id, datos.terminal_id, usuario.id,
        fecha=_fecha(datos.fecha) if datos.fecha else None,
        efectivo_contado=datos.efectivo_contado,
    )
    return servicios.cuadre_a_dict(c)


@app.get("/cuadres")
def listar_cuadres(sucursal_id: int | None = None, fecha: str | None = None,
                   db=Depends(get_db), usuario=Depends(panel_actual)):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    q = db.query(Cuadre)
    if sid is not None:
        q = q.filter(Cuadre.sucursal_id == sid)
    if fecha:
        q = q.filter(Cuadre.fecha == _fecha(fecha))
    return [servicios.cuadre_a_dict(c) for c in q.order_by(Cuadre.id.desc()).limit(100).all()]


# ------------------------------------------------------------------ reportes
@app.get("/reportes/inicio")
def reporte_inicio(desde: str | None = None, hasta: str | None = None,
                   db=Depends(get_db), usuario=Depends(panel_actual)):
    hoy = servicios.ahora_local().date()
    sid = permisos.resolver_filtro_sucursal(db, usuario, None)
    return servicios.resumen_inicio(
        db, _fecha(desde) if desde else hoy, _fecha(hasta) if hasta else hoy, sid,
    )


@app.get("/reportes/resumen")
def reporte_resumen(desde: str, hasta: str, vista: str = "final", sucursal_id: int | None = None,
                    db=Depends(get_db), usuario=Depends(panel_actual)):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.reporte_resumen(db, _fecha(desde), _fecha(hasta), vista, sid)


@app.get("/reportes/ventas")
def reporte_ventas(desde: str, hasta: str, usuario_id: int | None = None,
                   sucursal_id: int | None = None, limite: int = 500,
                   db=Depends(get_db), usuario=Depends(panel_actual)):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.reporte_ventas(db, _fecha(desde), _fecha(hasta), usuario_id, sid, limite)

@app.get("/reportes/ventas-cajeros")
def reporte_ventas_cajeros(desde: str | None = None, hasta: str | None = None,
                           usuario_id: int | None = None, sucursal_id: int | None = None,
                           db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    hoy = servicios.ahora_local().date()
    return servicios.resumen_ventas_cajeros(
        db, usuario,
        _fecha(desde) if desde else hoy,
        _fecha(hasta) if hasta else hoy,
        sucursal_id, usuario_id,
    )


@app.get("/reportes/ventas-cajeros/{usuario_id}")
def detalle_ventas_cajero(usuario_id: int, desde: str | None = None, hasta: str | None = None,
                          db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    hoy = servicios.ahora_local().date()
    return servicios.detalle_ventas_cajero(
        db, usuario, usuario_id,
        _fecha(desde) if desde else hoy,
        _fecha(hasta) if hasta else hoy,
    )


@app.get("/reportes/pendientes")
def reporte_pendientes(desde: str, hasta: str, sucursal_id: int, formato: str = "json",
                       db=Depends(get_db), usuario=Depends(panel_actual)):
    permisos.assert_sucursal_permitida(db, usuario, sucursal_id)
    if formato == "texto":
        texto = servicios.pendientes_texto(db, _fecha(desde), _fecha(hasta), sucursal_id)
        return PlainTextResponse(texto)
    return servicios.reporte_pendientes(db, _fecha(desde), _fecha(hasta), sucursal_id)


# ------------------------------------------------------------------ auditoría
@app.get("/auditoria")
def listar_auditoria(entidad: str | None = None, accion: str | None = None, limite: int = 100,
                     db=Depends(get_db), usuario=Depends(requiere_gestion_consorcio)):
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
        or not usuario.clave_hash
        or not verificar_clave(datos.clave, usuario.clave_hash)
    ):
        raise ErrorServicio(401, "Usuario o contraseña incorrectos")
    permisos.usuario_puede_iniciar_sesion(usuario)
    if usuario.rol in ("admin", "super_admin"):
        token = servicios.crear_sesion(db, usuario, tipo="panel")
        servicios.auditar(
            db, "usuario", usuario.id, "login_admin_movil", usuario_id=usuario.id,
            detalle={"dispositivo": datos.dispositivo_id or "", "version": datos.version_app or ""},
        )
        db.commit()
        return {
            "token": token,
            "rol": usuario.rol,
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
        usuario_id=usuario.id,
    )
    if terminal is None:
        raise ErrorServicio(
            403,
            "Este dispositivo está revocado: el consorcio debe reactivarlo en el panel.",
        )
    # Aparato físico: una sola sesión activa. Sin serial (login legado/tests)
    # varias sesiones pueden compartir la terminal APP- de la sucursal.
    if datos.dispositivo_id and str(datos.dispositivo_id).strip():
        servicios.invalidar_sesiones_terminal(db, terminal.id)
    token = servicios.crear_sesion(db, usuario, tipo="terminal", terminal_id=terminal.id)
    servicios.auditar(
        db, "usuario", usuario.id, "login_terminal", usuario_id=usuario.id,
        terminal_id=terminal.id,
        detalle={
            "dispositivo": datos.dispositivo_id or "",
            "sucursal_id": sucursal.id,
            "sucursal": sucursal.nombre,
            "version": datos.version_app or "",
        },
    )
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
    tablero = servicios.tablero_resultados(db, servicios.ahora_local().date())
    tablero["actualizado_en"] = servicios.ahora_local().isoformat(sep=" ", timespec="seconds")
    return tablero


@app.post("/terminal/resultados/actualizar")
def terminal_actualizar_resultados(db=Depends(get_db), terminal=Depends(terminal_actual),
                                   operador=Depends(operador_actual)):
    """Pide una comprobación segura a Conéctate sin saltarse la validación.

    No paga premios. Respeta el tope anti-abuso del reloj. La SUNMI solo
    refresca lo ya confirmado o deja PENDIENTE.
    """
    sync = resultados_auto.ciclo_desde_terminal()
    momento = servicios.ahora_local()
    tablero = servicios.tablero_resultados(db, momento.date())
    tablero["actualizado_en"] = momento.isoformat(sep=" ", timespec="seconds")
    tablero["sincronizacion"] = {
        "ok": bool(sync.get("ok")),
        "omitido": sync.get("omitido"),
        "confirmados": sync.get("confirmados", 0),
        "premios": sync.get("premios", 0),
        "motivo": sync.get("motivo"),
    }
    return tablero


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


@app.get("/terminal/entregas/{entrega_id}/imagen")
def terminal_entrega_imagen(
    entrega_id: int,
    db=Depends(get_db),
    terminal=Depends(terminal_actual),
    operador=Depends(operador_actual),
):
    """PNG 384 px de entrega. Reimpresión: no mueve dinero."""
    from . import impresion_servidor as imp

    try:
        png = imp.render_entrega_id(db, entrega_id, operador)
    except ErrorServicio:
        raise
    except imp.ErrorImpresion as e:
        raise ErrorServicio(e.codigo, e.detalle)
    except Exception as e:
        raise ErrorServicio(500, f"No se pudo generar la imagen de la entrega: {e}")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Ticket-Ancho": "384"},
    )


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
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.listar_fondos(db, sid, usuario_id)


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
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.listar_comisiones(db, sid, usuario_id)


@app.post("/comisiones", status_code=201)
def panel_guardar_comision(datos: ComisionIn, db=Depends(get_db),
                           usuario=Depends(requiere_rol("admin"))):
    return servicios.guardar_comision(db, usuario, datos.usuario_id, datos.porcentaje)


@app.get("/comisiones/resumen")
def panel_resumen_comisiones(desde: str, hasta: str, sucursal_id: int | None = None,
                             usuario_id: int | None = None, db=Depends(get_db),
                             usuario=Depends(requiere_rol("admin"))):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.resumen_comisiones(db, _fecha(desde), _fecha(hasta), sid, usuario_id)


@app.get("/comisiones/liquidaciones")
def panel_liquidaciones(sucursal_id: int | None = None, usuario_id: int | None = None,
                        db=Depends(get_db), usuario=Depends(requiere_rol("admin"))):
    sid = permisos.resolver_filtro_sucursal(db, usuario, sucursal_id)
    return servicios.listar_liquidaciones(db, sid, usuario_id)


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
    # Solo tickets vendidos por la cajera de la sesión (no confiar en IDs de la APK).
    return servicios.consultar_ticket(
        db, datos.id, datos.serial, exigir_vendedor_id=operador.id,
    )


@app.post("/terminal/tickets/pagar")
def terminal_pagar(datos: LlaveIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                   operador=Depends(operador_actual)):
    return servicios.pagar_ticket(
        db, datos.id, datos.serial, terminal.sucursal_id,
        terminal.id, operador.id, operacion_id=datos.operacion_id,
        exigir_vendedor_id=operador.id,
    )


@app.post("/terminal/tickets/reimprimir")
def terminal_reimprimir(datos: LlaveIn, db=Depends(get_db), terminal=Depends(terminal_actual),
                        operador=Depends(operador_actual)):
    return servicios.reimprimir_ticket(db, datos.id, datos.serial, operador.id, terminal_id=terminal.id)


@app.get("/terminal/tickets/{ticket_id}/imagen")
def terminal_ticket_imagen(
    ticket_id: int,
    serial: str = Query(..., min_length=4),
    db=Depends(get_db),
    terminal=Depends(terminal_actual),
    operador=Depends(operador_actual),
):
    """PNG 384 px del ticket. Aislado por sucursal. No altera venta ni premios."""
    from . import impresion_servidor as imp

    try:
        ticket = servicios.buscar_ticket(db, ticket_id, serial.strip().upper())
        imp.autorizar_imagen_terminal(db, ticket, terminal, operador)
        png, ticket = imp.render_ticket_id(db, ticket_id, serial.strip().upper())
    except ErrorServicio as e:
        raise
    except imp.ErrorImpresion as e:
        raise ErrorServicio(e.codigo, e.detalle)
    except Exception as e:
        raise ErrorServicio(500, f"No se pudo generar la imagen del ticket: {e}")
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Ticket-QR": f"LOT:{ticket_id}:{serial.strip().upper()}",
            "X-Ticket-Ancho": "384",
        },
    )


@app.get("/terminal/tickets/{ticket_id}/pago/imagen")
def terminal_pago_imagen(
    ticket_id: int,
    serial: str = Query(..., min_length=4),
    operacion: str | None = Query(None),
    reimpresion: bool = Query(False),
    db=Depends(get_db),
    terminal=Depends(terminal_actual),
    operador=Depends(operador_actual),
):
    """PNG del comprobante de pago. No cobra; reimpresión conserva el pago original."""
    from . import impresion_servidor as imp

    try:
        ticket = servicios.buscar_ticket(db, ticket_id, serial.strip().upper())
        imp.autorizar_imagen_terminal(db, ticket, terminal, operador)
        png = imp.render_pago_ticket(
            db, ticket_id, serial.strip().upper(), operacion, reimpresion=reimpresion,
        )
    except ErrorServicio:
        raise
    except imp.ErrorImpresion as e:
        raise ErrorServicio(e.codigo, e.detalle)
    except Exception as e:
        raise ErrorServicio(500, f"No se pudo generar la imagen del pago: {e}")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Ticket-Ancho": "384"},
    )


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
    # No reescribir alcance en silencio: servicios.resumen_dia responde 403
    # si un operador pide alcance=sucursal (no se elevan privilegios).
    sucursal = db.get(Sucursal, terminal.sucursal_id)
    return servicios.resumen_dia(db, inicio, fin, operador, sucursal, terminal, alcance)


@app.get("/terminal/reportes/dia/imagen")
def terminal_resumen_dia_imagen(
    desde: str | None = None,
    hasta: str | None = None,
    alcance: str = "cajero",
    db=Depends(get_db),
    terminal=Depends(terminal_actual),
    operador=Depends(operador_actual),
):
    """PNG 384 px del resumen de caja. Solo lectura; no mueve saldos."""
    from . import impresion_servidor as imp

    hoy = servicios.ahora_local().date()
    inicio = _fecha(desde) if desde else hoy
    fin = _fecha(hasta) if hasta else hoy
    if fin < inicio:
        raise ErrorServicio(400, "La fecha hasta no puede ser anterior a la fecha desde")
    sucursal = db.get(Sucursal, terminal.sucursal_id)
    datos = servicios.resumen_dia(db, inicio, fin, operador, sucursal, terminal, alcance)
    try:
        png = imp.render_resumen_datos(datos)
    except Exception as e:
        raise ErrorServicio(500, f"No se pudo generar la imagen del resumen: {e}")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Ticket-Ancho": "384"},
    )


@app.get("/terminal/reportes/mes")
def terminal_resumen_mes(anio: int, mes: int, alcance: str = "cajero",
                         db=Depends(get_db), terminal=Depends(terminal_actual),
                         operador=Depends(operador_actual)):
    # Misma regla que resumen_dia: 403 si un operador pide alcance=sucursal.
    sucursal = db.get(Sucursal, terminal.sucursal_id)
    return servicios.resumen_mes(db, anio, mes, operador, sucursal, terminal, alcance)


@app.get("/terminal/reportes/resumen")
def terminal_reporte_resumen(desde: str, hasta: str, vista: str = "final",
                             db=Depends(get_db), terminal=Depends(terminal_actual),
                             operador=Depends(operador_actual)):
    # Información personal siempre del autenticado; admin/supervisor ven resumen de sucursal.
    propio = operador.id if operador.rol == "operador" else None
    return servicios.reporte_resumen(
        db, _fecha(desde), _fecha(hasta), vista, terminal.sucursal_id, propio,
    )


@app.get("/terminal/reportes/pendientes")
def terminal_reporte_pendientes(desde: str, hasta: str, formato: str = "json",
                                db=Depends(get_db), terminal=Depends(terminal_actual),
                                operador=Depends(operador_actual)):
    # Siempre la cajera autenticada: nunca listar tickets de otra.
    # Ámbito real/prueba alineado con MODO_DESARROLLO (misma caja que ve la APK).
    propio = operador.id
    ambito_prueba = servicios.modo_desarrollo()
    if formato == "texto":
        return PlainTextResponse(
            servicios.pendientes_texto(
                db, _fecha(desde), _fecha(hasta), terminal.sucursal_id, terminal, propio,
                es_prueba=ambito_prueba,
            )
        )
    return servicios.reporte_pendientes(
        db, _fecha(desde), _fecha(hasta), terminal.sucursal_id, propio,
        detalle_premios=True, es_prueba=ambito_prueba,
    )


# ------------------------------------------------------------------ lab (solo MODO_DESARROLLO)
@app.get("/lab/recibos/{clave}/imagen")
def lab_recibo_imagen(
    clave: str,
    db=Depends(get_db),
    terminal=Depends(terminal_actual),
    operador=Depends(operador_actual),
):
    """PNG ficticios de los 6 diseños aprobados. No vende, no paga, no mueve caja."""
    if not modo_desarrollo():
        raise ErrorServicio(404, "No disponible fuera de laboratorio")
    from .recibos_imagen import lab_preview_png

    try:
        png = lab_preview_png(clave)
    except ValueError as e:
        raise ErrorServicio(404, str(e))
    except Exception as e:
        raise ErrorServicio(500, f"No se pudo generar la imagen LAB: {e}")
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Ticket-Ancho": "384",
            "X-Lab-Recibo": clave,
        },
    )


# ------------------------------------------------------------------ panel web
@app.get("/")
def raiz():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/manifest.webmanifest")
def manifest_pwa():
    return FileResponse(
        WEB_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
def service_worker():
    return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
