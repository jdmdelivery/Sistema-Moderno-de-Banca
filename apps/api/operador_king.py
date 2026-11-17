"""King Lottery: RDLotto verified + contraste con el operador oficial.

Fuentes:
- RDLotto `king-lottery-quiniela` con status `verified` (fecha, sesión, hora).
- Operador https://www.kinglotterysxm.com/ (Quiniela SXM día/noche).

Conéctate widget no publica King; no se inventan números del widget.

Regla:
- Si RDLotto trae verified de hoy con sesión/hora correctas, se acepta.
- Si el operador ya publicó hoy y los números difieren, se rechaza.
- Si el operador solo muestra ayer o aún no publica, no se usa esa fecha:
  manda el verified de hoy de RDLotto (origen `rdlotto`).
- Si solo hay operador sin RDLotto verified, queda pendiente.
- Pick 3, Pick 4, Loto Pool y Philipsburg no entran.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, timedelta

KING_URL = "https://www.kinglotterysxm.com/"
RDLOTTO_URL = "https://rdlotto.com/api/v1/results"
GAME = "king-lottery-quiniela"
NOMBRES = (
    "King Lottery 12:30 PM",
    "King Lottery 7:30 PM",
)
_POR_SESION = {
    "dia": ("King Lottery 12:30 PM", "12:30"),
    "noche": ("King Lottery 7:30 PM", "19:30"),
}
_POR_NOMBRE = {
    "King Lottery 12:30 PM": ("dia", "12:30"),
    "King Lottery 7:30 PM": ("noche", "19:30"),
}
_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_ARTICULO = re.compile(r"<article\b([^>]*)>(.*?)</article>", re.I | re.S)
_CLASE_DIA = re.compile(r"\bsorteos-quiniela-sxm\b(?!-noche)", re.I)
_CLASE_NOCHE = re.compile(r"\bsorteos-quiniela-sxm-noche\b", re.I)
_NUMERO = re.compile(
    r'class="elementor-widget-container">\s*(\d{1,2})\s*</div>',
    re.I,
)
_FECHA = re.compile(
    r"<time[^>]*>\s*([a-záéíóúñ]+)\s+(\d{1,2}),\s*(\d{4})\s*</time>",
    re.I,
)


def es_king(nombre):
    return nombre in _POR_NOMBRE


def _triple(valor):
    """Tres enteros 0–99. Se permiten repeticiones (p. ej. 53-09-09, 00-00-00)."""
    if not isinstance(valor, (list, tuple)) or len(valor) != 3:
        return None
    try:
        numeros = tuple(int(n) for n in valor)
    except (TypeError, ValueError):
        return None
    if any(n < 0 or n > 99 for n in numeros):
        return None
    return numeros


def _fecha_texto(texto):
    hallado = _FECHA.search(texto or "")
    if hallado is None:
        return None
    mes = _MESES.get(hallado.group(1).lower())
    if mes is None:
        return None
    try:
        return date(int(hallado.group(3)), mes, int(hallado.group(2)))
    except ValueError:
        return None


def _numeros_articulo(bloque):
    hallados = _NUMERO.findall(bloque or "")
    if len(hallados) < 3:
        return None
    return _triple(hallados[:3])


def _sesion_clases(attrs):
    if _CLASE_NOCHE.search(attrs or ""):
        return "noche"
    if _CLASE_DIA.search(attrs or ""):
        return "dia"
    return None


def leer_operador(html, hoy):
    """Quiniela SXM del sitio oficial. Ignora Pick 3/4, Loto Pool y Philipsburg."""
    if not html or not isinstance(hoy, date):
        return {}
    salida = {}
    vistos = set()
    for attrs, cuerpo in _ARTICULO.findall(html):
        sesion = _sesion_clases(attrs)
        if sesion is None:
            continue
        nombre, _hora = _POR_SESION[sesion]
        publicada = _fecha_texto(cuerpo)
        numeros = _numeros_articulo(cuerpo)
        if publicada is None or numeros is None:
            continue
        if publicada > hoy:
            continue
        if publicada not in (hoy, hoy - timedelta(days=1)):
            continue
        clave = (nombre, publicada)
        if clave in vistos:
            continue
        vistos.add(clave)
        salida[clave] = {"fecha": publicada, "numeros": numeros, "sesion": sesion}
    return salida


def leer_rdlotto(documento, hoy):
    """Solo king-lottery-quiniela verified, con hora y sesión exactas."""
    if not isinstance(hoy, date):
        return {}
    draws = documento.get("draws") if isinstance(documento, dict) else None
    if not isinstance(draws, list):
        return {}
    salida = {}
    for draw in draws:
        if not isinstance(draw, dict):
            continue
        if draw.get("game") != GAME:
            continue
        if draw.get("status") != "verified":
            continue
        sesion = draw.get("session")
        if sesion not in _POR_SESION:
            continue
        nombre, hora = _POR_SESION[sesion]
        if str(draw.get("time") or "") != hora:
            continue
        try:
            publicada = date.fromisoformat(str(draw.get("date"))[:10])
        except ValueError:
            continue
        if publicada > hoy or publicada not in (hoy, hoy - timedelta(days=1)):
            continue
        numeros = _triple(draw.get("numbers"))
        if numeros is None:
            continue
        salida[(nombre, publicada)] = {
            "fecha": publicada,
            "numeros": numeros,
            "sesion": sesion,
        }
    return salida


def cruzar(operador, rdlotto, hoy):
    """Acepta verified de hoy; no usa números de ayer para tickets de hoy.

    RDLotto verified de hoy con sesión/hora exactas es la base. El operador
    confirma cuando coincide. Si el sitio oficial aún muestra ayer o no ha
    publicado, no se bloquea el verified de hoy: se acepta con origen
    `rdlotto`. Si el operador ya publicó hoy con otros números, se rechaza.
    """
    if not isinstance(hoy, date):
        return {}, []
    aceptados = {}
    discrepancias = []
    for nombre, sesion_hora in _POR_NOMBRE.items():
        sesion, _hora = sesion_hora
        clave = (nombre, hoy)
        oficial = (operador or {}).get(clave)
        contraste = (rdlotto or {}).get(clave)
        if oficial is None and contraste is None:
            continue
        if contraste is not None and contraste.get("sesion") != sesion:
            contraste = None
        if oficial is not None and oficial.get("sesion") != sesion:
            oficial = None
        if contraste is None and oficial is not None:
            discrepancias.append({
                "sorteo": nombre,
                "fecha": hoy.isoformat(),
                "sesion": sesion,
                "causa": "operador_hoy_sin_rdlotto_verified",
                "operador": list(oficial["numeros"]),
            })
            continue
        if contraste is None:
            continue
        if oficial is not None:
            if oficial["numeros"] != contraste["numeros"]:
                discrepancias.append({
                    "sorteo": nombre,
                    "fecha": hoy.isoformat(),
                    "sesion": sesion,
                    "causa": "numeros_distintos",
                    "operador": list(oficial["numeros"]),
                    "rdlotto": list(contraste["numeros"]),
                })
                continue
            aceptados[nombre] = {
                "fecha": hoy,
                "numeros": oficial["numeros"],
                "titulo": nombre,
                "origen": "operador",
            }
            continue
        # RDLotto verified de hoy; operador ausente o solo con fecha vieja.
        ayer = (operador or {}).get((nombre, hoy - timedelta(days=1)))
        origen = "rdlotto"
        if ayer is not None:
            # Diagnóstico informativo: no bloquea el verified de hoy.
            discrepancias.append({
                "sorteo": nombre,
                "fecha": hoy.isoformat(),
                "sesion": sesion,
                "causa": "operador_atrasado_acepta_rdlotto",
                "rdlotto": list(contraste["numeros"]),
                "operador_fecha": (hoy - timedelta(days=1)).isoformat(),
                "operador": list(ayer["numeros"]),
            })
        aceptados[nombre] = {
            "fecha": hoy,
            "numeros": contraste["numeros"],
            "titulo": nombre,
            "origen": origen,
        }
    return aceptados, discrepancias


def _abrir(url, headers, timeout=20):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            return resp.read(), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "sin respuesta"


def descargar_operador():
    url = str(os.environ.get("KING_OPERADOR_URL") or KING_URL).strip()
    cuerpo, error = _abrir(url, {"User-Agent": _NAVEGADOR, "Accept": "text/html"})
    if error:
        return "", "operador king " + error
    return cuerpo.decode("utf-8", "replace"), None


def descargar_rdlotto(hoy):
    if not isinstance(hoy, date):
        return None, "rdlotto king sin fecha"
    url = f"{RDLOTTO_URL}?date={hoy.isoformat()}"
    cuerpo, error = _abrir(
        url,
        {"User-Agent": "banca-moderna", "Accept": "application/json"},
    )
    if error:
        return None, "rdlotto king " + error
    try:
        return json.loads(cuerpo.decode("utf-8")), None
    except (UnicodeError, json.JSONDecodeError, AttributeError):
        return None, "rdlotto king sin respuesta"


def confirmar(hoy, html=None, documento=None):
    """RDLotto verified (+ operador si coincide). html/documento = pruebas."""
    if not isinstance(hoy, date):
        return {}, "operador king no disponible", []
    aviso = None
    if html is None:
        html, err = descargar_operador()
        aviso = err
        # Sin HTML del operador aún se puede confirmar con RDLotto verified.
        html = html or ""
    if documento is None:
        documento, err_rd = descargar_rdlotto(hoy)
        aviso = aviso or err_rd
        if documento is None:
            return {}, aviso or "rdlotto king no disponible", []
    oficial = leer_operador(html or "", hoy)
    contraste = leer_rdlotto(documento, hoy)
    aceptados, discrepancias = cruzar(oficial, contraste, hoy)
    return aceptados, aviso, discrepancias


def confirmar_ventana(hoy):
    """Consulta en vivo. Una caída deja King pendiente sin frenar el reloj."""
    return confirmar(hoy)
