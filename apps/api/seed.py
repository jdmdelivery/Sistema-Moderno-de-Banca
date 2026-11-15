"""Datos iniciales: consorcio, usuario admin, sorteos observados en los videos,
tipos de jugada QN/PL/SP y una tabla de pagos inicial (todo editable del panel).
"""
from datetime import datetime, time

from .comun import D, modo_desarrollo
from .models import Consorcio, Sorteo, TablaPagos, TipoJugada, Usuario
from .security import hash_clave

# (nombre, hora del sorteo, hora de cierre) — horas típicas del mercado,
# editables desde el panel. Orden = orden en la lista DISP de la terminal.
SORTEOS_SEMILLA = [
    ("La Primera 12", time(11, 55), time(11, 50)),
    ("La Suerte 12:30", time(12, 30), time(12, 25)),
    ("King 12PM", time(12, 30), time(12, 25)),
    ("Real Tarde", time(12, 55), time(12, 50)),
    ("Florida Día", time(13, 30), time(13, 25)),
    ("Anguilla 1PM", time(13, 0), time(12, 55)),
    ("NY Tarde", time(14, 30), time(14, 25)),
    ("Nacional Tarde", time(14, 55), time(14, 50)),
    ("LOTEDOM", time(15, 55), time(15, 50)),
    ("La Primera 8PM", time(19, 55), time(19, 50)),
    ("La Suerte 6PM", time(18, 0), time(17, 55)),
    ("Anguilla 6PM", time(18, 0), time(17, 55)),
    ("LOTEKA", time(19, 55), time(19, 50)),
    ("King 07PM", time(19, 30), time(19, 25)),
    ("Nacional Noche", time(20, 55), time(20, 50)),
    ("QP Noche", time(21, 0), time(20, 55)),
    ("Anguilla 9PM", time(21, 0), time(20, 55)),
    ("Florida Noche", time(21, 45), time(21, 40)),
    ("NY Noche", time(22, 30), time(22, 25)),
]

# Factores iniciales por cada $1 apostado (valores típicos del mercado
# dominicano; el consorcio los ajusta desde el panel con vigencia).
FACTORES_SEMILLA = {
    "QN": {"1ro": 60, "2do": 10, "3ro": 5},
    "PL": {"1-2": 1200, "1-3": 400, "2-3": 200},
    "SP": {"sp": 2500},
}


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
    for codigo, nombre, descripcion, dos in [
        ("QN", "Quiniela", "Un número contra el 1.º, 2.º o 3.º premio del sorteo.", False),
        ("PL", "Palé", "Una pareja de números entre los tres premios de un sorteo.", False),
        ("SP", "Súper Palé", "Una pareja que cruza el 1.º premio de dos loterías.", True),
    ]:
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
