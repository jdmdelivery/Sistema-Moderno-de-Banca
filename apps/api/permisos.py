"""Permisos y alcance por rol (Super Admin / admin sucursal / supervisor).

Compat global: mientras no exista ningún super_admin activo, los `admin`
conservan alcance de consorcio (comportamiento histórico). Con al menos un
super_admin, cada `admin` queda limitado a su sucursal_id — salvo que
`COMPAT_GLOBAL_FORZADO=1` mantenga el modo histórico hasta verificar el
login de JDMCASHNOW (aislamiento diferido).
Los `supervisor` siempre se limitan a su sucursal.
"""
from __future__ import annotations

import os

from .comun import ErrorServicio, ahora_local
from .models import PermisoSucursal, Usuario

ROLES_PANEL = ("super_admin", "admin", "supervisor")
ROLES_TERMINAL = ("operador", "supervisor")
ESTADO_APROBADO = "aprobado"
ESTADO_PENDIENTE = "pendiente"
ESTADO_RECHAZADO = "rechazado"
MSG_PENDIENTE_APROBACION = (
    "Usuario pendiente de aprobación del Super Admin. No puede iniciar sesión todavía."
)
MSG_RECHAZADO = "Usuario rechazado por el Super Admin. Contacte al consorcio."
MSG_SUSPENDIDO = "Usuario suspendido. Contacte al administrador."


def es_super_admin(usuario) -> bool:
    return bool(usuario) and usuario.rol == "super_admin"


def es_admin_panel(usuario) -> bool:
    """Admin de sucursal o Super Admin (pueden administrar usuarios/panel)."""
    return bool(usuario) and usuario.rol in ("super_admin", "admin")


def hay_super_admin(db) -> bool:
    return (
        db.query(Usuario.id)
        .filter(
            Usuario.rol == "super_admin",
            Usuario.eliminado.is_(False),
            Usuario.activo.is_(True),
        )
        .first()
        is not None
    )


def compat_global_forzado() -> bool:
    """Puerta de seguridad: mantiene alcance global aunque ya exista Super Admin."""
    return os.environ.get("COMPAT_GLOBAL_FORZADO", "").strip().lower() in (
        "1", "true", "yes", "si", "sí",
    )


def compat_global_activo(db) -> bool:
    """True = los admin siguen con alcance de consorcio.

    Se desactiva al existir un super_admin activo, excepto si
    COMPAT_GLOBAL_FORZADO=1 (transición segura post-creación de JDMCASHNOW).
    """
    if compat_global_forzado():
        return True
    return not hay_super_admin(db)


def tiene_rol(usuario, *roles) -> bool:
    if usuario is None:
        return False
    if usuario.rol in roles:
        return True
    # Super Admin hereda capacidades de admin en endpoints que piden admin.
    if usuario.rol == "super_admin" and "admin" in roles:
        return True
    return False


def estado_aprobacion_de(usuario) -> str:
    valor = getattr(usuario, "estado_aprobacion", None) or ESTADO_APROBADO
    return str(valor).strip().lower() or ESTADO_APROBADO


def usuario_puede_iniciar_sesion(usuario) -> None:
    """Lanza ErrorServicio si el usuario no puede autenticarse."""
    if usuario is None:
        raise ErrorServicio(401, "Usuario o clave incorrectos")
    if getattr(usuario, "eliminado", False) or not usuario.activo:
        from .comun import MSG_USUARIO_BLOQUEADO

        raise ErrorServicio(401, MSG_USUARIO_BLOQUEADO)
    if bool(getattr(usuario, "suspendido", False)):
        raise ErrorServicio(401, MSG_SUSPENDIDO)
    estado = estado_aprobacion_de(usuario)
    if estado == ESTADO_PENDIENTE:
        raise ErrorServicio(401, MSG_PENDIENTE_APROBACION)
    if estado == ESTADO_RECHAZADO:
        raise ErrorServicio(401, MSG_RECHAZADO)


def alcance_sucursal_ids(db, usuario) -> set[int] | None:
    """None = todas las sucursales. set() = ninguna. set({id}) = solo esas."""
    if usuario is None:
        return set()
    if es_super_admin(usuario):
        return None
    if usuario.rol == "admin":
        if compat_global_activo(db):
            return None
        if usuario.sucursal_id is None:
            return set()
        return {int(usuario.sucursal_id)}
    if usuario.rol == "supervisor":
        if usuario.sucursal_id is None:
            return set()
        return {int(usuario.sucursal_id)}
    return set()


def puede_ver_sucursal(db, usuario, sucursal_id) -> bool:
    if sucursal_id is None:
        return es_super_admin(usuario) or (
            usuario.rol == "admin" and compat_global_activo(db)
        )
    alcance = alcance_sucursal_ids(db, usuario)
    if alcance is None:
        return True
    return int(sucursal_id) in alcance


def assert_sucursal_permitida(db, usuario, sucursal_id, mensaje=None):
    if puede_ver_sucursal(db, usuario, sucursal_id):
        return
    raise ErrorServicio(
        403,
        mensaje or "No tiene permiso para operar en esa sucursal",
    )


def resolver_filtro_sucursal(db, usuario, sucursal_id=None) -> int | None:
    """Normaliza el filtro de sucursal según el alcance del actor.

    - Super Admin / compat global: None = todas; id ajeno permitido.
    - Admin/supervisor aislado: siempre su sucursal; 403 si pide otra.
    """
    if sucursal_id is not None:
        assert_sucursal_permitida(db, usuario, int(sucursal_id))
        return int(sucursal_id)
    alcance = alcance_sucursal_ids(db, usuario)
    if alcance is None:
        return None
    if not alcance:
        raise ErrorServicio(403, "Su cuenta no tiene sucursal asignada")
    return int(next(iter(alcance)))


def assert_ticket_en_alcance(db, usuario, ticket):
    if ticket is None:
        raise ErrorServicio(404, "Ticket no encontrado")
    sid = getattr(ticket, "sucursal_vendedora_id", None)
    assert_sucursal_permitida(db, usuario, sid, "No puede consultar tickets de otra sucursal")


def assert_usuario_en_alcance(db, actor, objetivo):
    """El actor solo gestiona usuarios de su alcance."""
    if objetivo is None:
        raise ErrorServicio(404, "El usuario no existe")
    if es_super_admin(actor):
        return
    if es_super_admin(objetivo):
        raise ErrorServicio(403, "No puede modificar una cuenta Super Admin")
    alcance = alcance_sucursal_ids(db, actor)
    if alcance is None:
        return
    if objetivo.sucursal_id is None or int(objetivo.sucursal_id) not in alcance:
        raise ErrorServicio(403, "No puede gestionar usuarios de otra sucursal")


def assert_puede_consultar_clave(db, actor, objetivo):
    """Más estricto que el alcance general: COMPAT_GLOBAL no abre otras bancas.

    - Solo admin/super_admin consultan.
    - Solo objetivos con rol operador.
    - Admin de sucursal: únicamente su propia sucursal_id (aunque compat_global
      le permita listar el consorcio en otras pantallas).
    - Super Admin: cualquier operador.
    """
    if objetivo is None:
        raise ErrorServicio(404, "El usuario no existe")
    if actor is None or not es_admin_panel(actor):
        raise ErrorServicio(403, "Solo un administrador puede consultar contraseñas")
    if getattr(objetivo, "eliminado", False):
        raise ErrorServicio(404, "El usuario no existe")
    if objetivo.rol != "operador":
        raise ErrorServicio(403, "Solo se pueden consultar contraseñas de operadores")
    if es_super_admin(actor):
        return
    if actor.sucursal_id is None:
        raise ErrorServicio(403, "Su cuenta no tiene sucursal asignada")
    if objetivo.sucursal_id is None or int(objetivo.sucursal_id) != int(actor.sucursal_id):
        raise ErrorServicio(403, "No puede consultar contraseñas de otra banca")


def filtrar_query_sucursal(q, columna, db, usuario):
    alcance = alcance_sucursal_ids(db, usuario)
    if alcance is None:
        return q
    if not alcance:
        return q.filter(False)
    return q.filter(columna.in_(list(alcance)))


def permisos_de_sucursal(db, sucursal_id) -> PermisoSucursal | None:
    if sucursal_id is None:
        return None
    fila = db.get(PermisoSucursal, int(sucursal_id))
    if fila is not None:
        return fila
    # Lazy create defaults (aditivo, no borra nada)
    fila = PermisoSucursal(sucursal_id=int(sucursal_id))
    db.add(fila)
    db.flush()
    return fila


def assert_permiso_sucursal(db, usuario, sucursal_id, atributo: str):
    assert_sucursal_permitida(db, usuario, sucursal_id)
    if es_super_admin(usuario):
        return
    fila = permisos_de_sucursal(db, sucursal_id)
    if fila is None or not bool(getattr(fila, atributo, False)):
        raise ErrorServicio(403, "Esta sucursal no tiene habilitada esa operación")


def marcar_operador_pendiente(operador, solicitado_por_id):
    operador.estado_aprobacion = ESTADO_PENDIENTE
    operador.solicitado_por = solicitado_por_id
    operador.solicitado_en = ahora_local()
    operador.aprobado_por = None
    operador.aprobado_en = None
    operador.rechazado_por = None
    operador.rechazado_en = None
    operador.motivo_rechazo = None


def aprobar_operador(db, super_u, operador):
    if not es_super_admin(super_u):
        raise ErrorServicio(403, "Solo el Super Admin puede aprobar cajeros")
    if operador is None or operador.rol != "operador":
        raise ErrorServicio(400, "Solo se aprueban cuentas de cajero (operador)")
    if getattr(operador, "eliminado", False):
        raise ErrorServicio(409, "Un usuario eliminado no se puede aprobar")
    if estado_aprobacion_de(operador) == ESTADO_APROBADO and operador.activo:
        raise ErrorServicio(409, "Ese cajero ya está aprobado")
    operador.estado_aprobacion = ESTADO_APROBADO
    operador.aprobado_por = super_u.id
    operador.aprobado_en = ahora_local()
    operador.rechazado_por = None
    operador.rechazado_en = None
    operador.motivo_rechazo = None
    operador.activo = True
    return operador


def rechazar_operador(db, super_u, operador, motivo=None):
    if not es_super_admin(super_u):
        raise ErrorServicio(403, "Solo el Super Admin puede rechazar cajeros")
    if operador is None or operador.rol != "operador":
        raise ErrorServicio(400, "Solo se rechazan cuentas de cajero (operador)")
    if getattr(operador, "eliminado", False):
        raise ErrorServicio(409, "Un usuario eliminado no se puede rechazar")
    operador.estado_aprobacion = ESTADO_RECHAZADO
    operador.rechazado_por = super_u.id
    operador.rechazado_en = ahora_local()
    operador.motivo_rechazo = (motivo or "").strip()[:200] or None
    operador.activo = False
    return operador
