"""Seguridad: hash de claves, tokens de sesión y de terminal, seriales."""
import hashlib
import hmac
import secrets

_ITERACIONES = 260_000
_ALFABETO_SERIAL = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # legado (tickets antiguos)
_LARGO_SERIAL_NUMERICO = 12


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    resumen = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, _ITERACIONES)
    return f"pbkdf2${_ITERACIONES}${sal.hex()}${resumen.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, iteraciones, sal_hex, resumen_hex = guardado.split("$")
        calculado = hashlib.pbkdf2_hmac(
            "sha256", clave.encode("utf-8"), bytes.fromhex(sal_hex), int(iteraciones)
        )
        return hmac.compare_digest(calculado.hex(), resumen_hex)
    except Exception:
        return False


def hash_token(token: str) -> str:
    """Los tokens (sesión y terminal) se guardan solo como hash SHA-256."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)


def generar_serial(largo: int = _LARGO_SERIAL_NUMERICO) -> str:
    """S/N de ticket: solo dígitos, con ceros a la izquierda.

    No es el ID interno ni secuencial predecible: se elige al azar y la
    unicidad se garantiza al insertar (reintento si choca con UNIQUE).
    Los tickets antiguos pueden conservar S/N alfanumérico.
    """
    if largo < 6:
        largo = _LARGO_SERIAL_NUMERICO
    n = secrets.randbelow(10 ** largo)
    return f"{n:0{largo}d}"


def es_serial_numerico(serial: str | None) -> bool:
    s = str(serial or "").strip()
    return len(s) > 0 and s.isdigit()
