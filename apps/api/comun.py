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


def modo_desarrollo() -> bool:
    """Indicador de pruebas. Encendido, la terminal ve y vende todos los
    sorteos configurados sin reescribir sus horarios. Apagado, vuelven
    las reglas de día y hora de cierre. No debe quedar encendido al
    operar con dinero real."""
    return os.environ.get("MODO_DESARROLLO", "").strip().lower() in {
        "1", "true", "si", "sí", "yes", "on",
    }


class ErrorServicio(Exception):
    """Error de negocio con código HTTP y mensaje claro en español."""

    def __init__(self, status: int, mensaje: str):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje
