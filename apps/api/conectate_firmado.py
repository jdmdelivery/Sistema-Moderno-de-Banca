"""La Anguila y Haití Bolet por la sesión firmada de Conéctate.

El portal abre un websocket, recibe ws.session y lo manda en
Accept-Language al leer site-companies. Sin esa firma la API responde
un señuelo. Un horario entra solo si su triple firmado es de esa fecha,
tiene exactamente tres números y no coincide con el señuelo de esa
misma hora. No se usa lastSession ni el listado público de sesiones.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .conectate_widget import PORTAL, _ANGUILA_NOMBRES, _HAITI_NOMBRES, normalizar

API = "https://api.conectate.com.do/conectate"
WS = "wss://client-ws.kiskooloterias.com/?site=conectate"
ANGUILA_ID = "69fd98475e76585b60269648"
HAITI_ID = "6a550314ab686d300c930834"

_HORAS = {
    "anguila": tuple(nombre[len("La Anguila "):] for nombre in _ANGUILA_NOMBRES),
    "haiti": tuple(nombre[len("Haiti Bolet "):] for nombre in _HAITI_NOMBRES),
}
_PREFIJO = {"anguila": "La Anguila ", "haiti": "Haiti Bolet "}
_EMPRESAS = (
    ("anguila", "senuelo_anguila", "ANGUILA_SITE_COMPANY_ID", ANGUILA_ID, "/anguilla/"),
    ("haiti", "senuelo_haiti", "HAITI_BOLET_SITE_COMPANY_ID", HAITI_ID, "/haiti-bolet/"),
)


def es_especial(nombre):
    return nombre in _ANGUILA_NOMBRES or nombre in _HAITI_NOMBRES


def _empresa(env, default):
    valor = str(os.environ.get(env) or "").strip()
    return valor or default


def _norm_sig(raw):
    texto = re.sub(r"[^a-zA-Z0-9]", "", str(raw or "")).lower()
    return texto if len(texto) >= 16 else ""


def _idioma(sig):
    """El mismo Accept-Language del portal: idiomas del navegador y el token x-."""
    firma = _norm_sig(sig)
    if not firma:
        return "en-US,en;q=0.9"
    trozos = [firma[i:i + 8] for i in range(0, len(firma), 8) if firma[i:i + 8]]
    token = "x-" + "-".join(trozos) + ";q=0.1"
    base = ["en-US", "en;q=0.9"]
    while len(",".join(base)) + 1 + len(token) > 128 and len(base) > 1:
        base.pop()
    return ",".join(base + [token])


def _ap(texto):
    limpio = texto.upper().replace(".", "").replace(" ", "")
    if limpio.startswith("A"):
        return "AM"
    if limpio.startswith("P"):
        return "PM"
    return None


def _hora(titulo, familia):
    nt = re.sub(r"\s+", " ", normalizar(titulo))
    if "cuarteta" in nt:
        return None
    catalogo = _HORAS[familia]
    if familia == "haiti":
        if "haiti" not in nt or "bolet" not in nt:
            return None
        compacto = nt.replace(" ", "")
        for hora in catalogo:
            if hora.lower() in nt or hora.lower().replace(" ", "") in compacto:
                return hora
        return None
    if "anguila" not in nt and "anguilla" not in nt:
        return None
    hallado = re.search(
        r"(?:la\s+)?(?:anguila|anguilla)\s+(\d{1,2})\s*:\s*(\d{2})\s*(a\.?\s*m\.?|p\.?\s*m\.?)",
        nt,
    )
    if hallado:
        ap = _ap(hallado.group(3))
        hora = f"{int(hallado.group(1))}:{hallado.group(2)} {ap}"
        return hora if ap and hora in catalogo else None
    corto = re.search(
        r"(?:la\s+)?(?:anguila|anguilla)\s+(\d{1,2})\s*(a\.?\s*m\.?|p\.?\s*m\.?)",
        nt,
    )
    if corto:
        ap = _ap(corto.group(2))
        hora = f"{int(corto.group(1))}:00 {ap}"
        return hora if ap and hora in catalogo else None
    return None


def _tres(score):
    fila = score
    if isinstance(score, list) and score and isinstance(score[0], list):
        fila = score[0]
    if not isinstance(fila, (list, tuple)) or len(fila) != 3:
        return None
    numeros = []
    for valor in fila:
        texto = str(valor or "").strip()
        if not re.fullmatch(r"\d{1,2}", texto):
            return None
        numero = int(texto)
        if numero > 99:
            return None
        numeros.append(numero)
    return tuple(numeros)


def _fecha_sesion(valor):
    texto = str(valor or "").strip()
    if len(texto) >= 10 and texto[4:5] == "-" and texto[7:8] == "-":
        return texto[:10]
    return None


def _vigencia(sesion):
    for campo in ("updatedAt", "createdAt", "date"):
        crudo = str(sesion.get(campo) or "").strip()
        if not crudo:
            continue
        if crudo.endswith("Z"):
            crudo = crudo[:-1] + "+00:00"
        try:
            marca = datetime.fromisoformat(crudo)
        except ValueError:
            continue
        if marca.tzinfo is None:
            marca = marca.replace(tzinfo=timezone.utc)
        return marca.timestamp()
    return 0.0


def extraer(payload, fecha, familia):
    """{hora: (n1, n2, n3)} de esa fecha. Un horario con dos triples distintos se descarta."""
    if not isinstance(payload, dict):
        return {}
    ref = fecha.isoformat()
    salida = {}
    conflicto = set()
    for juego in payload.get("siteGames") or []:
        if not isinstance(juego, dict):
            continue
        hora = _hora(juego.get("title"), familia)
        if hora is None:
            continue
        game = juego.get("game") if isinstance(juego.get("game"), dict) else {}
        gid = str(juego.get("game_id") or game.get("_id") or "").strip()
        if not gid:
            continue
        sesiones = list(game.get("sessions") or juego.get("sessions") or [])
        elegido = None
        for sesion in sesiones:
            if not isinstance(sesion, dict):
                continue
            if _fecha_sesion(sesion.get("date")) != ref:
                continue
            numeros = _tres(sesion.get("score"))
            if numeros is None:
                continue
            marca = _vigencia(sesion)
            if elegido is None or marca >= elegido[0]:
                elegido = (marca, numeros)
        if elegido is None:
            continue
        if hora in salida and salida[hora] != elegido[1]:
            conflicto.add(hora)
        salida[hora] = elegido[1]
    for hora in conflicto:
        salida.pop(hora, None)
    return salida


def aceptados(firmado, senuelo, fecha, familia):
    """Acepta la hora solo cuando el señuelo de esa hora existe y es distinto."""
    if not isinstance(firmado, dict) or not firmado.get("siteGames"):
        return {}
    if not isinstance(senuelo, dict) or not senuelo.get("siteGames"):
        return {}
    reales = extraer(firmado, fecha, familia)
    falsos = extraer(senuelo, fecha, familia)
    return {
        hora: numeros
        for hora, numeros in reales.items()
        if hora in falsos and falsos[hora] != numeros
    }


def leer(documento, fecha):
    """Traduce la prueba o la descarga a nombres del catálogo. Sin firma, no entra nadie."""
    if not isinstance(documento, dict) or not documento.get("firma"):
        return {}
    salida = {}
    for familia, senuelo, _env, _default, _referer in _EMPRESAS:
        horas = aceptados(documento.get(familia), documento.get(senuelo), fecha, familia)
        for hora, numeros in horas.items():
            nombre = _PREFIJO[familia] + hora
            if not es_especial(nombre):
                continue
            salida[nombre] = {
                "fecha": fecha,
                "numeros": numeros,
                "titulo": nombre,
                "origen": "firmado",
            }
    return salida


def _consulta(fecha):
    return fecha.isoformat() + "T04:00:00.000Z"


def _firma():
    try:
        import websocket
    except ImportError:
        return None, "firma no disponible"
    endpoint = str(os.environ.get("HAITI_BOLET_WS_ENDPOINT") or WS).strip()
    if not endpoint:
        return None, "firma no disponible"
    timeout = 8
    try:
        conexion = websocket.create_connection(
            endpoint,
            timeout=timeout,
            header=[
                "Origin: https://loterias.conectate.com.do",
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            ],
        )
    except Exception:
        return None, "firma no disponible"
    try:
        conexion.settimeout(timeout)
        limite = time.time() + timeout
        while time.time() < limite:
            try:
                crudo = conexion.recv()
            except Exception:
                return None, "firma no disponible"
            try:
                mensaje = json.loads(crudo)
            except Exception:
                continue
            if not isinstance(mensaje, dict):
                continue
            if str(mensaje.get("subject") or "").strip().lower() != "ws.session":
                continue
            data = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else {}
            firma = _norm_sig(data.get("id"))
            if firma:
                return firma, None
        return None, "firma no disponible"
    finally:
        try:
            conexion.close()
        except Exception:
            pass


def _bajar(company_id, fecha, sig, referer):
    url = API + "/site-companies/" + company_id + "?" + urllib.parse.urlencode({"date": _consulta(fecha)})
    idioma = _idioma(sig)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://loterias.conectate.com.do",
        "Referer": PORTAL.rstrip("/") + referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept-Language": idioma,
        "accept-language": idioma,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            datos = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None, "firma no disponible"
    if not isinstance(datos, dict) or not datos.get("siteGames"):
        return None, "firma no disponible"
    return datos, None


def descargar_ventana(hoy):
    """Ayer y hoy, con una sola firma. Si la firma falla, no devuelve sorteos."""
    firma, error = _firma()
    if not firma:
        return {}, error or "firma no disponible"
    unidos = {}
    fallo = None
    for fecha in (hoy - timedelta(days=1), hoy):
        documento = {"firma": True}
        for familia, senuelo, env, default, referer in _EMPRESAS:
            company = _empresa(env, default)
            documento[familia], err1 = _bajar(company, fecha, firma, referer)
            documento[senuelo], err2 = _bajar(company, fecha, None, referer)
            fallo = fallo or err1 or err2
        unidos.update(leer(documento, fecha))
    if not unidos and fallo:
        return {}, fallo
    return unidos, None
