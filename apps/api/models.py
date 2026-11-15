"""Modelo de datos del sistema de lotería (ver ESPECIFICACION.md §5).

Reglas del modelo:
- El saldo de una sucursal solo cambia por movimientos (`movimientos_saldo`).
- El ticket es inmutable tras la venta: solo cambian su estado y los campos
  de pago/anulación, siempre auditados.
- El ID del ticket ES el número consecutivo global del consorcio.
"""
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .comun import ahora_local
from .db import Base

DINERO = Numeric(14, 2)


class Consorcio(Base):
    __tablename__ = "consorcio"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(120), nullable=False, default="Sistema de Banca Moderna")
    moneda = Column(String(8), nullable=False, default="DOP")
    siguiente_ticket = Column(Integer, nullable=False, default=1)
    plazo_vencimiento_dias = Column(Integer, nullable=False, default=90)
    monto_min_jugada = Column(DINERO, nullable=False, default=5)
    monto_max_jugada = Column(DINERO, nullable=False, default=5000)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(120), nullable=False)
    usuario = Column(String(60), nullable=False, unique=True)
    clave_hash = Column(String(255))  # acceso al panel (admin / supervisor)
    pin_hash = Column(String(255))  # acceso a la app de terminal (operador)
    rol = Column(String(20), nullable=False, default="operador")  # admin|supervisor|operador
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"))
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)

    sucursal = relationship("Sucursal")


class Sesion(Base):
    __tablename__ = "sesiones"
    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo = Column(String(20), nullable=False, default="panel")  # panel|terminal
    terminal_id = Column(Integer, ForeignKey("terminales.id"))
    creado_en = Column(DateTime, nullable=False, default=ahora_local)
    expira_en = Column(DateTime, nullable=False)

    usuario = relationship("Usuario")


class Sucursal(Base):
    __tablename__ = "sucursales"
    id = Column(Integer, primary_key=True)
    codigo = Column(String(20), nullable=False, unique=True)
    nombre = Column(String(120), nullable=False)
    direccion = Column(String(200))
    telefono = Column(String(40))
    comision_porcentaje = Column(Numeric(6, 2), nullable=False, default=10)
    saldo_actual = Column(DINERO, nullable=False, default=0)
    activa = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Terminal(Base):
    __tablename__ = "terminales"
    __table_args__ = (UniqueConstraint("sucursal_id", "numero_terminal"),)
    id = Column(Integer, primary_key=True)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False)
    numero_terminal = Column(Integer, nullable=False, default=1)
    serial_sunmi = Column(String(60), nullable=False, unique=True)
    token_hash = Column(String(64))
    activa = Column(Boolean, nullable=False, default=True)
    ultima_conexion_en = Column(DateTime)
    version_app = Column(String(30))
    creado_en = Column(DateTime, nullable=False, default=ahora_local)

    sucursal = relationship("Sucursal")


class Sorteo(Base):
    __tablename__ = "sorteos"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(80), nullable=False, unique=True)
    hora_sorteo = Column(Time, nullable=False)
    hora_cierre = Column(Time, nullable=False)
    dias_activos = Column(String(20), nullable=False, default="1,2,3,4,5,6,7")  # ISO: 1=lunes
    activo = Column(Boolean, nullable=False, default=True)
    orden = Column(Integer, nullable=False, default=100)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class TipoJugada(Base):
    __tablename__ = "tipos_jugada"
    id = Column(Integer, primary_key=True)
    codigo = Column(String(10), nullable=False, unique=True)  # QN|PL|SP
    nombre = Column(String(60), nullable=False)
    descripcion = Column(String(255))
    requiere_dos_sorteos = Column(Boolean, nullable=False, default=False)
    activo = Column(Boolean, nullable=False, default=True)


class TablaPagos(Base):
    """Factor por cada $1 apostado, por tipo de jugada y posición/combinación.

    Claves: QN -> '1ro'|'2do'|'3ro'; PL -> '1-2'|'1-3'|'2-3'; SP -> 'sp'.
    La vigencia manda: un ticket se liquida con la tabla vigente al vender.
    """

    __tablename__ = "tabla_pagos"
    id = Column(Integer, primary_key=True)
    tipo_jugada_id = Column(Integer, ForeignKey("tipos_jugada.id"), nullable=False)
    clave = Column(String(10), nullable=False)
    factor = Column(Numeric(12, 2), nullable=False)
    vigente_desde = Column(DateTime, nullable=False)
    vigente_hasta = Column(DateTime)
    creado_por = Column(Integer, ForeignKey("usuarios.id"))
    creado_en = Column(DateTime, nullable=False, default=ahora_local)

    tipo = relationship("TipoJugada")


class LimiteVenta(Base):
    __tablename__ = "limites_venta"
    __table_args__ = (UniqueConstraint("sorteo_id", "tipo_jugada_id", "clave_numero"),)
    id = Column(Integer, primary_key=True)
    sorteo_id = Column(Integer, ForeignKey("sorteos.id"), nullable=False)
    tipo_jugada_id = Column(Integer, ForeignKey("tipos_jugada.id"), nullable=False)
    clave_numero = Column(String(12), nullable=False)  # "26" o "26-58" (pareja ordenada)
    monto_max_acumulado = Column(DINERO, nullable=False)


class MovimientoSaldo(Base):
    __tablename__ = "movimientos_saldo"
    id = Column(Integer, primary_key=True)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False)  # recarga|venta|anulacion|pago_premio|recibir_efectivo|gasto|entrega_cuadre|ajuste
    monto = Column(DINERO, nullable=False)  # siempre positivo; el tipo dice la dirección
    referencia = Column(String(120))
    saldo_resultante = Column(DINERO, nullable=False)
    creado_por = Column(Integer, ForeignKey("usuarios.id"))
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, autoincrement=False)  # consecutivo global
    serial = Column(String(20), nullable=False, unique=True, index=True)
    sucursal_vendedora_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"))
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    vendido_en = Column(DateTime, nullable=False, default=ahora_local, index=True)
    operacion_id = Column(String(40), unique=True, index=True)  # idempotencia: la app lo genera por ticket
    fecha = Column(Date, nullable=False, index=True)  # fecha de los sorteos del ticket
    total = Column(DINERO, nullable=False)
    estado = Column(String(20), nullable=False, default="vendido", index=True)
    # vendido|ganador|no_ganador|pagado|anulado|vencido
    premio_total = Column(DINERO, nullable=False, default=0)
    pagado_en_sucursal_id = Column(Integer, ForeignKey("sucursales.id"))
    pagado_por_terminal_id = Column(Integer, ForeignKey("terminales.id"))
    pagado_por_usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    pagado_en = Column(DateTime)
    anulado_en = Column(DateTime)
    anulado_por = Column(Integer, ForeignKey("usuarios.id"))

    jugadas = relationship("Jugada", back_populates="ticket", cascade="all, delete-orphan")
    sucursal_vendedora = relationship("Sucursal", foreign_keys=[sucursal_vendedora_id])
    sucursal_pago = relationship("Sucursal", foreign_keys=[pagado_en_sucursal_id])
    terminal = relationship("Terminal", foreign_keys=[terminal_id])


class Jugada(Base):
    __tablename__ = "jugadas"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    tipo_jugada_id = Column(Integer, ForeignKey("tipos_jugada.id"), nullable=False)
    sorteo_id = Column(Integer, ForeignKey("sorteos.id"), nullable=False)
    sorteo2_id = Column(Integer, ForeignKey("sorteos.id"))  # solo Súper Palé
    fecha = Column(Date, nullable=False, index=True)
    numeros = Column(String(12), nullable=False)  # "26" o "26-58" (pareja ordenada)
    n1 = Column(Integer, nullable=False)
    n2 = Column(Integer)
    monto = Column(DINERO, nullable=False)
    factores_json = Column(Text, nullable=False, default="{}")  # foto de la tabla al vender
    evaluada = Column(Boolean, nullable=False, default=False)
    premio = Column(DINERO)
    detalle_eval = Column(String(20))  # '1ro'|'2do'|'3ro'|'1-2'|'1-3'|'2-3'|'sp'

    ticket = relationship("Ticket", back_populates="jugadas")
    tipo = relationship("TipoJugada")
    sorteo = relationship("Sorteo", foreign_keys=[sorteo_id])
    sorteo2 = relationship("Sorteo", foreign_keys=[sorteo2_id])


class Resultado(Base):
    __tablename__ = "resultados"
    __table_args__ = (UniqueConstraint("sorteo_id", "fecha"),)
    id = Column(Integer, primary_key=True)
    sorteo_id = Column(Integer, ForeignKey("sorteos.id"), nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    premio1 = Column(Integer, nullable=False)
    premio2 = Column(Integer, nullable=False)
    premio3 = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default="propuesto", index=True)
    # propuesto|confirmado|liquidado (confirmar liquida en la misma operación)
    fuente = Column(String(20), nullable=False, default="manual")  # manual|conectate
    propuesto_por = Column(Integer, ForeignKey("usuarios.id"))
    propuesto_en = Column(DateTime, nullable=False, default=ahora_local)
    confirmado_por = Column(Integer, ForeignKey("usuarios.id"))
    confirmado_en = Column(DateTime)
    liquidado_en = Column(DateTime)

    sorteo = relationship("Sorteo")


class Importacion(Base):
    """Cada intento del importador de resultados queda registrado, falle o no."""

    __tablename__ = "importaciones"
    id = Column(Integer, primary_key=True)
    fuente = Column(String(30), nullable=False, default="conectate")
    url = Column(String(255), nullable=False)
    fecha_objetivo = Column(Date, nullable=False)
    ok = Column(Boolean, nullable=False, default=False)
    estado_http = Column(Integer)
    encontrados = Column(Integer, nullable=False, default=0)
    detalle = Column(Text)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class TransaccionCaja(Base):
    __tablename__ = "transacciones_caja"
    id = Column(Integer, primary_key=True)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False, index=True)
    terminal_id = Column(Integer, ForeignKey("terminales.id"))
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    tipo = Column(String(30), nullable=False)  # recibir_efectivo|gasto|entrega_cuadre
    monto = Column(DINERO, nullable=False)
    concepto = Column(String(200))
    fecha = Column(Date, nullable=False, index=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Cuadre(Base):
    __tablename__ = "cuadres"
    id = Column(Integer, primary_key=True)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False)
    terminal_id = Column(Integer, ForeignKey("terminales.id"))
    fecha = Column(Date, nullable=False, index=True)
    ventas_total = Column(DINERO, nullable=False, default=0)
    premios_pagados_total = Column(DINERO, nullable=False, default=0)
    gastos_total = Column(DINERO, nullable=False, default=0)
    efectivo_recibido_total = Column(DINERO, nullable=False, default=0)
    total_a_entregar = Column(DINERO, nullable=False, default=0)
    efectivo_contado = Column(DINERO)
    diferencia = Column(DINERO)
    entregado_por = Column(Integer, ForeignKey("usuarios.id"))
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Auditoria(Base):
    __tablename__ = "auditoria"
    id = Column(Integer, primary_key=True)
    entidad = Column(String(40), nullable=False, index=True)
    entidad_id = Column(String(40), nullable=False)
    accion = Column(String(40), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    terminal_id = Column(Integer, ForeignKey("terminales.id"))
    detalle_json = Column(Text, nullable=False, default="{}")
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)
