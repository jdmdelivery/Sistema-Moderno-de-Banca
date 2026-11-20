"""Cruce de La Anguila y Haití Bolet con el operador.

La Anguila se lee en anguillalottery.ai. Haití Bolet se lee en
api-prod.haitibolet.net. Un horario entra solo si esa publicación trae
la misma fecha, la misma hora y los mismos tres números que Conéctate.
Si el operador no responde, el sorteo sigue pendiente. Si los números
difieren, no se guarda y queda una auditoría.

anguillalottery.ai publica un certificado TLS autofirmado. El cliente
primero intenta la verificación normal; si falla, reintenta solo si el
SHA-256 del certificado coincide con el pin conocido (o ANGUILA_CERT_SHA256).
No se acepta un certificado distinto ni se desactiva SSL de forma global.
"""
import hashlib
import http.client
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from urllib.parse import urlparse

from . import conectate_firmado

ANGUILA_URL = "https://anguillalottery.ai/"
# Pin del certificado autofirmado actual (CN=anguillalottery.ai, emitido 2026-11-14).
# El dominio tiene historial Let's Encrypt en crt.sh; desde 2026-11-14 el leaf
# servido es autofirmado. Al renovar: si vuelve CA pública, gana _abrir_anguila_ca;
# si cambia el autofirmado, hay que actualizar ANGUILA_CERT_SHA256 (rechazo seguro).
ANGUILA_CERT_SHA256 = "9857ff64fd6d20a8b0acea2a8a745868747dd48effc10863a0e2a1d5934f0525"
_ANGUILA_HOSTS = frozenset({"anguillalottery.ai", "www.anguillalottery.ai"})
HAITI_API = "https://api-prod.haitibolet.net"
_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_SLUGS = {
    "9:30 AM": "haiti_bolet_9_30_haiti_api",
    "10:30 AM": "haiti_bolet_10_30_haiti_api",
    "11:30 AM": "haiti_bolet_11_35_haiti_api",
    "5:30 PM": "haiti_bolet_17_30_haiti_api",
    "6:30 PM": "haiti_bolet_18_35_haiti_api",
    "7:30 PM": "haiti_bolet_19_30_haiti_api",
}
_NOMBRES = {
    "9:30 AM": "HAITI BOLET 9:30",
    "10:30 AM": "HAITI BOLET 10:30",
    "11:30 AM": "HAITI BOLET 11:30",
    "5:30 PM": "HAITI BOLET 17:30",
    "6:30 PM": "HAITI BOLET 18:30",
    "7:30 PM": "HAITI BOLET 19:30",
}
_HORA_HTML = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.I)
_FECHA_HTML = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _triple(valor):
    if not isinstance(valor, (list, tuple)) or len(valor) != 3:
        return None
    try:
        numeros = tuple(int(n) for n in valor)
    except (TypeError, ValueError):
        return None
    if any(n < 0 or n > 99 for n in numeros):
        return None
    return numeros


def _fecha_iso(valor):
    texto = str(valor or "")
    if len(texto) < 10:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None


def _numeros_html(bloque):
    numeros = []
    cursor = 0
    marca = 'class="numero"'
    while True:
        puesto = bloque.lower().find(marca, cursor)
        if puesto < 0:
            break
        abre = bloque.find(">", puesto)
        if abre < 0:
            break
        contenido = _span(bloque, abre + 1)
        if contenido is None:
            break
        texto = re.sub(r"<[^>]+>", "", contenido)
        hallado = re.search(r"(\d{1,2})\s*$", texto.strip())
        if hallado is None:
            return None
        numero = int(hallado.group(1))
        if numero > 99:
            return None
        numeros.append(numero)
        cursor = abre + 1 + len(contenido)
    return _triple(numeros)


def _span(html, inicio):
    profundidad = 1
    i = inicio
    while i < len(html) and profundidad:
        if html.lower().startswith("<span", i):
            cierre = html.find(">", i)
            if cierre < 0:
                return None
            profundidad += 1
            i = cierre + 1
            continue
        if html.lower().startswith("</span>", i):
            profundidad -= 1
            if profundidad == 0:
                return html[inicio:i]
            i += 7
            continue
        i += 1
    return None


def leer_anguila(html, hoy):
    """Quinielas del operador. Ignora cuarteta, rapidita y fechas futuras."""
    if not html or not isinstance(hoy, date):
        return {}
    salida = {}
    rechazados = set()
    for bloque in re.split(r'class="result-sorteo', html, flags=re.I)[1:]:
        bajo = bloque.lower()
        if "cuarteta" in bajo or "rapidita" in bajo:
            continue
        horas = _HORA_HTML.findall(bloque)
        fechas = _FECHA_HTML.findall(bloque)
        numeros = _numeros_html(bloque)
        if len(horas) != 1 or len(fechas) != 1 or numeros is None:
            continue
        hora = f"{int(horas[0][0])}:{int(horas[0][1]):02d} {horas[0][2].upper()}"
        try:
            publicada = date(int(fechas[0][2]), int(fechas[0][1]), int(fechas[0][0]))
        except ValueError:
            continue
        nombre = "La Anguila " + hora
        if publicada > hoy or not conectate_firmado.es_especial(nombre):
            continue
        clave = (nombre, publicada)
        if clave in rechazados:
            continue
        previo = salida.get(clave)
        if previo is not None and previo["numeros"] != numeros:
            salida.pop(clave, None)
            rechazados.add(clave)
            continue
        salida[clave] = {"fecha": publicada, "numeros": numeros}
    return salida


def interpretar_haiti(cuerpo, hora, fecha, hoy):
    """Una respuesta del operador. La fecha es el día civil, sin correr la zona."""
    if hora not in _NOMBRES or not isinstance(fecha, date) or not isinstance(hoy, date):
        return None
    if fecha > hoy:
        return None
    data = cuerpo.get("data") if isinstance(cuerpo, dict) else None
    if not isinstance(data, dict):
        return None
    if str(data.get("name_sorteo") or "").strip() != _NOMBRES[hora]:
        return None
    if _fecha_iso(data.get("date")) != fecha:
        return None
    numeros = _triple((data.get("numeros_ganadores") or {}).get("tradicional"))
    if numeros is None:
        return None
    nombre = "Haiti Bolet " + hora
    if not conectate_firmado.es_especial(nombre):
        return None
    return {"nombre": nombre, "fecha": fecha, "numeros": numeros}


def _indice(operador):
    indice = {}
    for clave, dato in (operador or {}).items():
        if not isinstance(dato, dict):
            continue
        numeros = _triple(dato.get("numeros"))
        publicada = dato.get("fecha")
        if isinstance(clave, tuple) and len(clave) == 2:
            nombre, publicada = clave
        else:
            nombre = clave
        if numeros is None or not isinstance(publicada, date):
            continue
        indice[(nombre, publicada)] = {"fecha": publicada, "numeros": numeros}
    return indice


def cruzar(candidatos, operador, hoy):
    """Acepta solo la coincidencia exacta. Devuelve aceptados y discrepancias."""
    if not isinstance(hoy, date):
        return {}, []
    indice = _indice(operador)
    aceptados = {}
    discrepancias = []
    for nombre, dato in (candidatos or {}).items():
        if not conectate_firmado.es_especial(nombre) or not isinstance(dato, dict):
            continue
        fecha = dato.get("fecha")
        numeros = _triple(dato.get("numeros"))
        if not isinstance(fecha, date) or fecha > hoy or numeros is None:
            continue
        oficial = indice.get((nombre, fecha))
        if oficial is None:
            continue
        if oficial["numeros"] != numeros:
            discrepancias.append({
                "sorteo": nombre,
                "fecha": fecha.isoformat(),
                "conectate": list(numeros),
                "operador": list(oficial["numeros"]),
            })
            continue
        aceptados[nombre] = {
            "fecha": fecha,
            "numeros": numeros,
            "titulo": nombre,
            "origen": "operador",
        }
    return aceptados, discrepancias


def _abrir(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            return resp.read(), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError):
        return None, "sin respuesta"


def _pin_anguila() -> str:
    return str(os.environ.get("ANGUILA_CERT_SHA256") or ANGUILA_CERT_SHA256).strip().lower()


def _url_anguila_permitida(url: str):
    """Solo HTTPS hacia anguillalottery.ai / www. Sin otros hosts."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _ANGUILA_HOSTS:
        return None, "dominio no autorizado"
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = path + "?" + parsed.query
    return (host, port, path), None


def _https_get_anguila(host, port, path, headers, timeout, ctx, pin=None):
    """GET sin seguir redirecciones. Opcionalmente exige pin SHA-256 del leaf."""
    try:
        conn = http.client.HTTPSConnection(host, port=port, context=ctx, timeout=timeout)
        try:
            conn.connect()
            sock = conn.sock
            if sock is None:
                return None, "sin respuesta"
            if pin is not None:
                der = sock.getpeercert(binary_form=True)
                if not der or hashlib.sha256(der).hexdigest().lower() != pin:
                    return None, "certificado no reconocido"
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            cuerpo = resp.read()
            if resp.status in (301, 302, 303, 307, 308):
                return None, "redireccion no permitida"
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            return cuerpo, None
        finally:
            conn.close()
    except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError):
        return None, "sin respuesta"


def _abrir_anguila_ca(url, headers, timeout=15):
    """Intento con verificación CA pública (hostname + cadena)."""
    destino, error = _url_anguila_permitida(url)
    if error:
        return None, error
    host, port, path = destino
    ctx = ssl.create_default_context()
    return _https_get_anguila(host, port, path, headers, timeout, ctx, pin=None)


def _abrir_anguila_pin(url, headers, timeout=15):
    """GET HTTPS al operador validando el pin SHA-256 del certificado."""
    destino, error = _url_anguila_permitida(url)
    if error:
        return None, error
    host, port, path = destino
    pin = _pin_anguila()
    if len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin):
        return None, "certificado no reconocido"
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return _https_get_anguila(host, port, path, headers, timeout, ctx, pin=pin)


def descargar_anguila():
    url = str(os.environ.get("ANGUILA_OPERADOR_URL") or ANGUILA_URL).strip()
    headers = {"User-Agent": _NAVEGADOR, "Accept": "text/html"}
    # 1) CA pública (cuando el operador restaure Let's Encrypt).
    cuerpo, error = _abrir_anguila_ca(url, headers)
    if error is None:
        return cuerpo.decode("utf-8", "replace"), None
    # 2) Autofirmado: solo host allowlist + pin SHA-256 exacto.
    cuerpo, error_pin = _abrir_anguila_pin(url, headers)
    if error_pin is None:
        return cuerpo.decode("utf-8", "replace"), None
    return "", "operador anguila " + (error_pin or error)


def _pedir_haiti(slug, fecha):
    base = str(os.environ.get("HAITI_OPERADOR_API") or HAITI_API).strip().rstrip("/")
    consulta = urllib.parse.urlencode({"name": slug, "fecha": fecha.isoformat()})
    cuerpo, error = _abrir(
        base + "/haiti-bolet/find?" + consulta,
        {
            "User-Agent": _NAVEGADOR,
            "Accept": "application/json",
            "Origin": "https://haitibolet.net",
        },
    )
    if error == "HTTP 404":
        return None, "ausente"
    if error:
        return None, error
    try:
        return json.loads(cuerpo.decode("utf-8")), None
    except (UnicodeError, json.JSONDecodeError):
        return None, "sin respuesta"


def descargar_haiti(hoy):
    """Los seis horarios de ayer y de hoy. Un 404 deja ese sorteo pendiente."""
    if not isinstance(hoy, date):
        return {}, "operador haiti sin respuesta"
    mapa = {}
    errores = 0
    intentos = 0
    for publicada in (hoy - timedelta(days=1), hoy):
        for hora, slug in _SLUGS.items():
            intentos += 1
            cuerpo, error = _pedir_haiti(slug, publicada)
            if error == "ausente":
                continue
            if error:
                errores += 1
                continue
            fila = interpretar_haiti(cuerpo, hora, publicada, hoy)
            if fila is None:
                continue
            mapa[(fila["nombre"], fila["fecha"])] = {
                "fecha": fila["fecha"],
                "numeros": fila["numeros"],
            }
    if intentos and errores == intentos:
        return {}, "operador haiti sin respuesta"
    return mapa, None


def confirmar_ventana(hoy):
    """Firma de Conéctate y operadores. Una caída no confirma esos sorteos."""
    if not isinstance(hoy, date):
        return {}, "operador no disponible", []
    firma, error = conectate_firmado._firma()
    if not firma:
        return {}, error or "firma no disponible", []
    html, err_html = descargar_anguila()
    oficial = leer_anguila(html or "", hoy)
    haiti, err_haiti = descargar_haiti(hoy)
    oficial.update(haiti)
    aceptados = {}
    discrepancias = []
    aviso = err_html or err_haiti
    for publicada in (hoy - timedelta(days=1), hoy):
        documento = {"firma": True}
        fallo = None
        for familia, _senuelo, env, default, referer in conectate_firmado._EMPRESAS:
            company = conectate_firmado._empresa(env, default)
            documento[familia], err = conectate_firmado._bajar(company, publicada, firma, referer)
            fallo = fallo or err
        candidatos = conectate_firmado.propuestos(documento, publicada)
        ok, difs = cruzar(candidatos, oficial, hoy)
        aceptados.update(ok)
        discrepancias.extend(difs)
        if not candidatos and fallo:
            aviso = aviso or fallo
    return aceptados, aviso, discrepancias
