"""Utilidades comunes: dinero exacto, hora local y errores de servicio."""
import os
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Santo_Domingo")
CENTAVOS = Decimal("0.01")


def D(valor) -> Decimal:
    """Convierte cualquier valor monetario a Decimal con 2 decimales exactos."""
    return Decimal(str(valor)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def ahora_local() -> datetime:
    """Hora actual en República Dominicana, sin zona (naive) para guardar en BD."""
    return datetime.now(ZONA).replace(tzinfo=None)


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
