"""Widget público de Conéctate para las loterías que publican título y hora.

GET https://api.conectate.com.do/conectate/api/widget
La Anguila y Haití Bolet no salen completos aquí. Esos 21 sorteos se leen
en conectate_firmado, con la sesión firmada. Sin esa firma el feed entrega
números señuelo y no se usa.

Un título solo entra si el nombre y la tanda coinciden con un sorteo del
catálogo. Una hora distinta no hereda los números de otra.
"""
import json
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timedelta

URL_WIDGET = "https://api.conectate.com.do/conectate/api/widget"
PORTAL = "https://loterias.conectate.com.do/"

# Título normalizado → nombre interno. La hora va en el nombre.
_EXACTOS = {
    "quiniela real": "Quiniela Real 12:55 PM",
    "quiniela loteka": "Loteka 7:55 PM",
    "quiniela loteka noche": "Loteka 7:55 PM",
    "new york tarde": "New York 3:30 PM",
    "new york noche": "New York 11:30 PM",
    "florida dia": "Florida 2:30 PM",
    "florida noche": "Florida 10:45 PM",
    "la primera dia": "La Primera 12:00 PM",
    "primera dia": "La Primera 12:00 PM",
    "la primera noche": "La Primera 7:00 PM",
    "primera noche": "La Primera 7:00 PM",
    "la suerte dia": "La Suerte Dominicana 12:30 PM",
    "la suerte tarde": "La Suerte Dominicana 6:00 PM",
    "lotedom": "Lotedom 12:00 PM",
    "lotedom dia": "Lotedom 12:00 PM",
    "loteria real noche": "Lotería Real Noche 8:00 PM",
    "gana mas": "Lotería Nacional 2:30 PM",
    "king lottery dia": "King Lottery 12:30 PM",
    "king lottery 12:30": "King Lottery 12:30 PM",
    "king lottery 12:30 pm": "King Lottery 12:30 PM",
    "king lottery noche": "King Lottery 7:30 PM",
    "king lottery 7:30": "King Lottery 7:30 PM",
    "king lottery 7:30 pm": "King Lottery 7:30 PM",
}
_LOTEKA_DIA = {"quiniela loteka dia", "quiniela loteka day"}
_ANGUILA = {
    "la anguila 8:00 am", "la anguila 9:00 am", "la anguila 10:00 am", "la anguila 11:00 am",
    "la anguila 12:00 pm", "la anguila 1:00 pm", "la anguila 2:00 pm", "la anguila 3:00 pm",
    "la anguila 4:00 pm", "la anguila 5:00 pm", "la anguila 6:00 pm", "la anguila 7:00 pm",
    "la anguila 8:00 pm", "la anguila 9:00 pm", "la anguila 10:00 pm",
}
_HAITI = {
    "haiti bolet 9:30 am", "haiti bolet 10:30 am", "haiti bolet 11:30 am",
    "haiti bolet 5:30 pm", "haiti bolet 6:30 pm", "haiti bolet 7:30 pm",
}
# Alias de tanda solo cuando el título no trae hora.
_HAITI_NOMBRES = (
    "Haiti Bolet 9:30 AM", "Haiti Bolet 10:30 AM", "Haiti Bolet 11:30 AM",
    "Haiti Bolet 5:30 PM", "Haiti Bolet 6:30 PM", "Haiti Bolet 7:30 PM",
)
_ANGUILA_NOMBRES = (
    "La Anguila 8:00 AM", "La Anguila 9:00 AM", "La Anguila 10:00 AM", "La Anguila 11:00 AM",
    "La Anguila 12:00 PM", "La Anguila 1:00 PM", "La Anguila 2:00 PM", "La Anguila 3:00 PM",
    "La Anguila 4:00 PM", "La Anguila 5:00 PM", "La Anguila 6:00 PM", "La Anguila 7:00 PM",
    "La Anguila 8:00 PM", "La Anguila 9:00 PM", "La Anguila 10:00 PM",
)
RECONOCIDOS = set(_EXACTOS.values()) | set(_ANGUILA_NOMBRES) | set(_HAITI_NOMBRES) | {
    "Leidsa 3:55 PM", "Leidsa 8:55 PM",
    "Lotería Nacional 6:00 PM", "Lotería Nacional 9:00 PM",
}
MOTIVO_SIN_WIDGET = (
    "Este sorteo se confirma cuando el operador y Conéctate coinciden "
    "en la fecha, la hora y los tres números. El widget no lo sustituye."
)


def motivo_sin_fuente(nombre):
    if nombre in _HAITI_NOMBRES or nombre.startswith("La Anguila"):
        return MOTIVO_SIN_WIDGET
    return "El widget público no tiene un título con este nombre y esta hora."


_ANGUILA_SIN_HORA = {
    "anguila manana": "La Anguila 10:00 AM",
    "anguila medio dia": "La Anguila 1:00 PM",
    "anguila tarde": "La Anguila 6:00 PM",
    "anguila noche": "La Anguila 9:00 PM",
}


def normalizar(texto):
    base = unicodedata.normalize("NFKD", str(texto or ""))
    sin = "".join(ch for ch in base if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sin).strip().lower()


def mapear_titulo(titulo, fecha):
    """Devuelve el nombre interno o None. No adivina por parecido."""
    nt = normalizar(titulo)
    if not nt or nt in _LOTEKA_DIA:
        return None
    if nt in _EXACTOS:
        return _EXACTOS[nt]
    if nt.startswith("anguila ") or nt.startswith("la anguila "):
        hora = _hora_en_titulo(nt)
        if hora:
            nombre = f"La Anguila {hora}"
            return nombre if normalizar(nombre) in _ANGUILA else None
        return _ANGUILA_SIN_HORA.get(nt)
    if "haiti" in nt and "bolet" in nt:
        hora = _hora_en_titulo(nt)
        if not hora:
            return None
        nombre = f"Haiti Bolet {hora}"
        return nombre if normalizar(nombre) in _HAITI else None
    if nt == "quiniela leidsa":
        return "Leidsa 3:55 PM" if fecha.weekday() == 6 else "Leidsa 8:55 PM"
    if nt == "pega 3":
        return None if fecha.weekday() == 6 else "Leidsa 3:55 PM"
    if nt in ("loteria nacional", "nacional noche", "loteria nacional noche"):
        if "2:30" in nt or "14:30" in nt:
            return "Lotería Nacional 2:30 PM"
        if "6:00" in nt or "18:00" in nt:
            return "Lotería Nacional 6:00 PM"
        if "9:00" in nt or "21:00" in nt:
            return "Lotería Nacional 9:00 PM"
        return "Lotería Nacional 6:00 PM" if fecha.weekday() == 6 else "Lotería Nacional 9:00 PM"
    return None


def _hora_en_titulo(texto):
    hallado = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", texto)
    if not hallado:
        return None
    hora = int(hallado.group(1))
    minuto = hallado.group(2)
    turno = hallado.group(3).upper()
    if hora < 1 or hora > 12:
        return None
    return f"{hora}:{minuto} {turno}"


def fecha_widget(texto, hoy):
    """DD-MM del widget → fecha. Solo hoy o ayer en el año de referencia."""
    hallado = re.match(r"^(\d{1,2})-(\d{1,2})$", str(texto or "").strip())
    if not hallado:
        return None
    dia, mes = int(hallado.group(1)), int(hallado.group(2))
    for anio in (hoy.year, hoy.year - 1):
        try:
            candidato = date(anio, mes, dia)
        except ValueError:
            continue
        if candidato in (hoy, hoy - timedelta(days=1)):
            return candidato
    return None


def _numeros(score):
    if not isinstance(score, (list, tuple)) or len(score) < 3:
        return None
    try:
        numeros = tuple(int(score[i]) for i in range(3))
    except (TypeError, ValueError):
        return None
    if any(n < 0 or n > 99 for n in numeros) or len(set(numeros)) != 3:
        return None
    return numeros


def interpretar(payload, hoy):
    """Lista del widget → {nombre: {fecha, numeros, titulo}}. Ignora lo no mapeado."""
    if not isinstance(payload, list):
        return {}, "La respuesta no es una lista"
    salida = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        fecha = fecha_widget(item.get("date"), hoy)
        if fecha is None:
            continue
        titulo = item.get("game_title") or item.get("title") or ""
        nombre = mapear_titulo(titulo, fecha)
        numeros = _numeros(item.get("score"))
        if nombre is None or numeros is None:
            continue
        salida[nombre] = {"fecha": fecha, "numeros": numeros, "titulo": str(titulo)}
    return salida, None


def descargar(timeout=20):
    """Devuelve (lista|None, error|None). Un 403 no se disfraza."""
    req = urllib.request.Request(
        URL_WIDGET,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": PORTAL,
            "Origin": "https://loterias.conectate.com.do",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, f"Error de red: {exc}"
