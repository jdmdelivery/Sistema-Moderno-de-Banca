"""Utilidades comunes: dinero exacto, hora local y errores de servicio."""
import os
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Santo_Domingo")
CENTAVOS = Decimal("0.01")
# La cajera solo anula en este plazo. A los 5 minutos exactos ya no puede.
MINUTOS_ANULACION_CAJERA = 5
MSG_ANULACION_VENCIDA = (
    "El tiempo de anulación de la cajera venció (5 minutos). "
    "Solo el administrador puede anularlo desde el Panel del Consorcio."
)
MSG_USUARIO_BLOQUEADO = "USUARIO BLOQUEADO. CONTACTE AL ADMINISTRADOR."


def D(valor) -> Decimal:
    """Convierte cualquier valor monetario a Decimal con 2 decimales exactos."""
    return Decimal(str(valor)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def ahora_local() -> datetime:
    """Hora actual en República Dominicana, sin zona (naive) para guardar en BD."""
    return datetime.now(ZONA).replace(tzinfo=None)


def ahora_oficial(db, forzar=None) -> datetime:
    """Hora oficial del servidor de base de datos en America/Santo_Domingo.

    En PostgreSQL usa CURRENT_TIMESTAMP de la BD. En SQLite (pruebas) usa
    ahora_local, que los tests pueden fijar. `forzar` permite inyectar la hora.
    """
    if forzar is not None:
        return forzar
    try:
        motor = db.get_bind()
    except Exception:
        motor = None
    dialect = getattr(getattr(motor, "dialect", None), "name", "") if motor is not None else ""
    if dialect == "postgresql":
        from sqlalchemy import text

        marca = db.execute(
            text(
                "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')"
                "::timestamp WITHOUT TIME ZONE"
            )
        ).scalar()
        if isinstance(marca, datetime):
            return marca.replace(tzinfo=None) if marca.tzinfo else marca
    return ahora_local()


def ventana_anulacion_cajera(vendido_en, ahora):
    """True solo si aún no se cumplieron los 5 minutos exactos."""
    if vendido_en is None or ahora is None:
        return False
    return (ahora - vendido_en) < timedelta(minutes=MINUTOS_ANULACION_CAJERA)


def segundos_para_anular_cajera(vendido_en, ahora):
    if vendido_en is None or ahora is None:
        return 0
    limite = vendido_en + timedelta(minutes=MINUTOS_ANULACION_CAJERA)
    queda = int((limite - ahora).total_seconds())
    return max(0, queda)


def _indicador(nombre: str) -> bool:
    return os.environ.get(nombre, "").strip().lower() in {
        "1", "true", "si", "sí", "yes", "on",
    }


def modo_desarrollo() -> bool:
    """Indicador de pruebas. Encendido, las ventas quedan marcadas como
    prueba: no mueven la caja real ni entran en los reportes reales.
    No cambia los horarios guardados. No debe quedar encendido al operar
    con dinero real."""
    return _indicador("MODO_DESARROLLO")


def loterias_abiertas_desarrollo() -> bool:
    """La excepción de ventas 24 horas quedó retirada.

    El horario guardado de cada sorteo manda, también en modo de prueba.
    La variable de entorno ya no abre sorteos cerrados.
    """
    return False


class ErrorServicio(Exception):
    """Error de negocio con código HTTP y mensaje claro en español."""

    def __init__(self, status: int, mensaje: str):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje
