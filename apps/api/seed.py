"""Datos iniciales: consorcio, usuario admin, los 40 sorteos, tipos QN/PL/SP/TR
y una tabla de pagos inicial (todo editable del panel).
"""
from datetime import datetime, time, timedelta

from .comun import D, modo_desarrollo
from .models import Consorcio, Sorteo, TablaPagos, TipoJugada, Usuario
from .security import hash_clave


def cierre_cinco_minutos(hora):
    """El cierre es exactamente cinco minutos antes de la hora del sorteo."""
    base = datetime(2026, 1, 1, hora.hour, hora.minute, hora.second)
    return (base - timedelta(minutes=5)).time()


# Nombre y hora del sorteo, en el orden del catálogo. El cierre se calcula.
HORAS_CATALOGO = [
    ("Florida 2:30 PM", time(14, 30)),
    ("Florida 10:45 PM", time(22, 45)),
    ("Haiti Bolet 9:30 AM", time(9, 30)),
    ("Haiti Bolet 10:30 AM", time(10, 30)),
    ("Haiti Bolet 11:30 AM", time(11, 30)),
    ("Haiti Bolet 5:30 PM", time(17, 30)),
    ("Haiti Bolet 6:30 PM", time(18, 30)),
    ("Haiti Bolet 7:30 PM", time(19, 30)),
    ("King Lottery 12:30 PM", time(12, 30)),
    ("King Lottery 7:30 PM", time(19, 30)),
    ("La Anguila 8:00 AM", time(8, 0)),
    ("La Anguila 9:00 AM", time(9, 0)),
    ("La Anguila 10:00 AM", time(10, 0)),
    ("La Anguila 11:00 AM", time(11, 0)),
    ("La Anguila 12:00 PM", time(12, 0)),
    ("La Anguila 1:00 PM", time(13, 0)),
    ("La Anguila 2:00 PM", time(14, 0)),
    ("La Anguila 3:00 PM", time(15, 0)),
    ("La Anguila 4:00 PM", time(16, 0)),
    ("La Anguila 5:00 PM", time(17, 0)),
    ("La Anguila 6:00 PM", time(18, 0)),
    ("La Anguila 7:00 PM", time(19, 0)),
    ("La Anguila 8:00 PM", time(20, 0)),
    ("La Anguila 9:00 PM", time(21, 0)),
    ("La Anguila 10:00 PM", time(22, 0)),
    ("La Primera 12:00 PM", time(12, 0)),
    ("La Primera 7:00 PM", time(19, 0)),
    ("La Suerte Dominicana 12:30 PM", time(12, 30)),
    ("La Suerte Dominicana 6:00 PM", time(18, 0)),
    ("Leidsa 3:55 PM", time(15, 55)),
    ("Leidsa 8:55 PM", time(20, 55)),
    ("Lotedom 12:00 PM", time(12, 0)),
    ("Loteka 7:55 PM", time(19, 55)),
    ("Lotería Nacional 2:30 PM", time(14, 30)),
    ("Lotería Nacional 6:00 PM", time(18, 0)),
    ("Lotería Nacional 9:00 PM", time(21, 0)),
    ("Lotería Real Noche 8:00 PM", time(20, 0)),
    ("New York 3:30 PM", time(15, 30)),
    ("New York 11:30 PM", time(23, 30)),
    ("Quiniela Real 12:55 PM", time(12, 55)),
]

SORTEOS_SEMILLA = [
    (nombre, hora, cierre_cinco_minutos(hora)) for nombre, hora in HORAS_CATALOGO
]

# Factores iniciales por cada $1 apostado (valores típicos del mercado
# dominicano; el consorcio los ajusta desde el panel con vigencia).
FACTORES_SEMILLA = {
    "QN": {"1ro": 60, "2do": 10, "3ro": 5},
    "PL": {"1-2": 1200, "1-3": 400, "2-3": 200},
    "SP": {"sp": 2500},
    "TR": {"tr": 500},
}

TIPOS_SEMILLA = [
    ("QN", "Quiniela", "Un número contra el 1.º, 2.º o 3.º premio del sorteo.", False),
    ("PL", "Palé", "Una pareja de números entre los tres premios de un sorteo.", False),
    ("SP", "Súper Palé", "Una pareja que cruza el 1.º premio de dos loterías.", True),
    ("TR", "Tripleta", "Tres números en cualquier orden contra los tres premios del sorteo.", False),
]


def sembrar_si_vacio(db):
    if db.query(Consorcio).first() is not None:
        return
    db.add(
        Consorcio(
            nombre="Sistema de Banca Moderna",
            moneda="DOP",
            siguiente_ticket=1,
            plazo_vencimiento_dias=90,
            monto_min_jugada=D(5),
            monto_max_jugada=D(5000),
        )
    )
    db.add(
        Usuario(
            nombre="Administrador",
            usuario="admin",
            clave_hash=hash_clave("admin123"),
            rol="admin",
            activo=True,
        )
    )
    for i, (nombre, hora_sorteo, hora_cierre) in enumerate(SORTEOS_SEMILLA, start=1):
        db.add(
            Sorteo(
                nombre=nombre,
                hora_sorteo=hora_sorteo,
                hora_cierre=hora_cierre,
                dias_activos="1,2,3,4,5,6,7",
                activo=True,
                orden=i * 10,
            )
        )
    tipos = {}
    for codigo, nombre, descripcion, dos in TIPOS_SEMILLA:
        tipo = TipoJugada(codigo=codigo, nombre=nombre, descripcion=descripcion,
                          requiere_dos_sorteos=dos, activo=True)
        db.add(tipo)
        tipos[codigo] = tipo
    db.flush()
    desde = datetime(2020, 1, 1, 0, 0, 0)
    for codigo, claves in FACTORES_SEMILLA.items():
        for clave, factor in claves.items():
            db.add(
                TablaPagos(
                    tipo_jugada_id=tipos[codigo].id,
                    clave=clave,
                    factor=D(factor),
                    vigente_desde=desde,
                )
            )
    db.commit()


def asegurar_tripleta(db):
    """Inserta TR y su factor ×500 si la base ya existía sin Tripleta.

    Idempotente: no toca QN/PL/SP ni altera factores históricos. Solo agrega
    el tipo y la fila de tabla de pagos inicial cuando faltan.
    """
    tipo = db.query(TipoJugada).filter_by(codigo="TR").first()
    if tipo is None:
        meta = next(t for t in TIPOS_SEMILLA if t[0] == "TR")
        tipo = TipoJugada(
            codigo=meta[0], nombre=meta[1], descripcion=meta[2],
            requiere_dos_sorteos=meta[3], activo=True,
        )
        db.add(tipo)
        db.flush()
    elif not tipo.activo:
        tipo.activo = True
    vigente = (
        db.query(TablaPagos)
        .filter_by(tipo_jugada_id=tipo.id, clave="tr")
        .filter(TablaPagos.vigente_hasta.is_(None))
        .first()
    )
    if vigente is None:
        db.add(
            TablaPagos(
                tipo_jugada_id=tipo.id,
                clave="tr",
                factor=D(FACTORES_SEMILLA["TR"]["tr"]),
                vigente_desde=datetime(2020, 1, 1, 0, 0, 0),
            )
        )
    db.commit()


def aplicar_catalogo_sorteos(db):
    """Deja exactamente los 40 sorteos activos, sin borrar filas ni tickets.

    Si el nombre ya existe, actualiza su horario. Si un sorteo anterior no
    está en el catálogo, se archiva (activo = false) y sus tickets siguen
    apuntando a esa fila. Llamarla dos veces no crea duplicados.
    """
    nombres = set()
    for orden, (nombre, hora_sorteo, hora_cierre) in enumerate(SORTEOS_SEMILLA, start=1):
        nombres.add(nombre)
        fila = db.query(Sorteo).filter_by(nombre=nombre).first()
        if fila is None:
            db.add(
                Sorteo(
                    nombre=nombre,
                    hora_sorteo=hora_sorteo,
                    hora_cierre=hora_cierre,
                    dias_activos="1,2,3,4,5,6,7",
                    activo=True,
                    orden=orden * 10,
                )
            )
        else:
            fila.hora_sorteo = hora_sorteo
            fila.hora_cierre = hora_cierre
            fila.dias_activos = "1,2,3,4,5,6,7"
            fila.activo = True
            fila.orden = orden * 10
    db.flush()
    for fila in db.query(Sorteo).all():
        if fila.nombre not in nombres and fila.activo:
            fila.activo = False
    db.commit()


def sembrar_sucursal_prueba(db):
    """Si el modo desarrollo arranca sin bancas, deja una sucursal de prueba.

    El nombre, el movimiento y la clave dejan claro que no es dinero real.
    No toca una base que ya tenga sucursales. Fuera de modo desarrollo no hace nada.
    """
    from .models import MovimientoSaldo, Sucursal, Terminal, Usuario

    if not modo_desarrollo():
        return
    if db.query(Sucursal).first() is not None:
        return
    admin = db.query(Usuario).filter_by(usuario="admin").first()
    sucursal = Sucursal(
        codigo="1301",
        nombre="BANCA CASTILLO (PRUEBA)",
        direccion="DATOS DE PRUEBA — no es dinero real",
        comision_porcentaje=D(10),
        saldo_actual=D("5764.00"),
        activa=True,
    )
    db.add(sucursal)
    db.flush()
    db.add(
        MovimientoSaldo(
            sucursal_id=sucursal.id,
            tipo="recarga",
            monto=D("5764.00"),
            referencia="SALDO DE PRUEBA — no es dinero real",
            saldo_resultante=D("5764.00"),
            creado_por=admin.id if admin is not None else None,
        )
    )
    db.add(
        Usuario(
            nombre="JOSE (PRUEBA)",
            usuario="jose",
            clave_hash=hash_clave("prueba123"),
            rol="operador",
            sucursal_id=sucursal.id,
            activo=True,
        )
    )
    db.add(
        Terminal(
            sucursal_id=sucursal.id,
            numero_terminal=1,
            serial_sunmi="APP-1301",
            activa=True,
        )
    )
    db.commit()
