"""Importador de resultados desde Conectate (https://www.conectate.com.do/loterias/).

Realidad comprobada (2026-11-14): el sitio está detrás de Cloudflare y
responde **HTTP 403** a los accesos automáticos desde servidor. Por eso el
importador está diseñado para FALLAR CON GRACIA:

- Cada intento queda registrado en la tabla `importaciones` (hora, estado
  HTTP y motivo), falle o no.
- NUNCA inventa números: si no puede leer la página, no propone nada.
- Lo que sí logra leer queda como resultado PROPUESTO: un operador debe
  revisarlo y CONFIRMARLO en el panel antes de que se liquide nada.

El parseo trabaja sobre el texto visible de la página y usa alias por
sorteo (con índice de ocurrencia para loterías con dos tandas). Es una
propuesta para revisión humana, no una fuente de verdad.
"""
import re
import urllib.error
import urllib.request
from datetime import timedelta

from .comun import ahora_local
from .models import Importacion, Resultado, Sorteo
from .servicios import auditar, guardar_resultado

URL_CONECTATE = "https://www.conectate.com.do/loterias/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Nombre del sorteo en NUESTRO catálogo -> [(alias en la página, ocurrencia)]
# La ocurrencia 0 es la primera aparición del alias (tanda del mediodía) y la
# 1 la segunda (tanda de la noche) cuando la página no distingue con nombre.
ALIAS_CONECTATE = {
    "La Primera 12:00 PM": [("La Primera Día", 0), ("La Primera", 0)],
    "La Primera 7:00 PM": [("La Primera Noche", 0), ("La Primera", 1)],
    "La Suerte Dominicana 12:30 PM": [("La Suerte", 0)],
    "La Suerte Dominicana 6:00 PM": [("La Suerte", 1), ("La Suerte Tarde", 0)],
    "Quiniela Real 12:55 PM": [("Lotería Real", 0), ("Real", 0)],
    "Lotería Nacional 2:30 PM": [("Nacional Tarde", 0), ("Lotería Nacional", 0)],
    "Lotería Nacional 9:00 PM": [("Nacional Noche", 0), ("Lotería Nacional", 1)],
    "Loteka 7:55 PM": [("Loteka", 0)],
    "Lotedom 12:00 PM": [("Lotedom", 0), ("Loto Dom", 0)],
    "King Lottery 12:30 PM": [("King Lottery", 0), ("King", 0)],
    "King Lottery 7:30 PM": [("King Lottery", 1), ("King", 1)],
    "La Anguila 1:00 PM": [("Anguilla 1", 0), ("Anguilla", 0)],
    "La Anguila 6:00 PM": [("Anguilla 6", 0), ("Anguilla", 1)],
    "La Anguila 9:00 PM": [("Anguilla 9", 0), ("Anguilla", 2)],
    "New York 3:30 PM": [("New York Tarde", 0), ("New York", 0), ("NY", 0)],
    "New York 11:30 PM": [("New York Noche", 0), ("New York", 1), ("NY", 1)],
    "Florida 2:30 PM": [("Florida Día", 0), ("Florida", 0)],
    "Florida 10:45 PM": [("Florida Noche", 0), ("Florida", 1)],
}


def _texto_visible(html: str) -> str:
    """Extrae el texto visible conservando saltos de línea entre bloques."""
    texto = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    texto = re.sub(r"(?i)<br\s*/?>", "\n", texto)
    texto = re.sub(r"(?i)</(div|p|li|tr|h\d|section|article)>", "\n", texto)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = (
        texto.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#039;", "'")
        .replace("&quot;", '"')
    )
    lineas = [re.sub(r"[ \t]+", " ", ln).strip() for ln in texto.splitlines()]
    return "\n".join(ln for ln in lineas if ln)


def _numeros_tras(texto: str, inicio: int):
    """Busca los primeros 3 números de 2 cifras tras la posición `inicio`.

    Acepta números solos en su línea ("05") o tríos en una línea
    ("05 - 23 - 87"). Ignora fechas (14/11/2026) y horas (7:55) porque no
    calzan con el patrón de número aislado de 2 cifras.
    """
    encontrados = []
    fin = min(len(texto), inicio + 600)
    segmento = texto[inicio:fin]
    for ln in segmento.splitlines():
        trio = re.findall(r"(?<!\d)(\d{2})(?!\d)", ln)
        # Una línea con 3+ números de 2 cifras se toma como el trío del sorteo
        # solo si no parece una fecha u hora larga.
        if len(trio) >= 3 and "/" not in ln and ":" not in ln:
            return [int(x) for x in trio[:3]]
        if re.fullmatch(r"\d{2}", ln):
            encontrados.append(int(ln))
            if len(encontrados) == 3:
                return encontrados
    return None


def parsear_resultados(html: str, nombres_sorteos=None):
    """Devuelve {nombre_sorteo: (p1, p2, p3)} con lo encontrado en la página."""
    texto = _texto_visible(html)
    texto_norm = texto
    resultado = {}
    # Alias más largos primero: que "La Primera Noche" no la robe "La Primera".
    orden = sorted(
        ALIAS_CONECTATE.items(),
        key=lambda kv: -max(len(a) for a, _ in kv[1]),
    )
    for nombre, alias_lista in orden:
        if nombres_sorteos is not None and nombre not in nombres_sorteos:
            continue
        for alias, ocurrencia in alias_lista:
            patron = re.compile(re.escape(alias), re.IGNORECASE)
            coincidencias = list(patron.finditer(texto_norm))
            if len(coincidencias) <= ocurrencia:
                continue
            m = coincidencias[ocurrencia]
            numeros = _numeros_tras(texto_norm, m.end())
            if numeros:
                resultado[nombre] = tuple(numeros)
                break
    return resultado


def descargar_pagina(url=URL_CONECTATE, timeout=20):
    """Descarga la página. Devuelve (html, estado_http) o (None, estado/motivo)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "es"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:  # red caída, DNS, TLS, timeout...
        return None, f"Error de red: {e}"


def importar_resultados(db, fecha, usuario, url=URL_CONECTATE, html=None):
    """Intenta importar los resultados de `fecha` y los deja PROPUESTOS.

    `html` se puede inyectar (tests con fixture, sin red real).
    Devuelve un resumen; registra el intento SIEMPRE.
    """
    if html is None:
        html, estado = descargar_pagina(url)
        if html is None:
            motivo = (
                f"HTTP {estado}: el sitio bloqueó el acceso automático del servidor "
                "(protección Cloudflare). Registre los resultados a mano o "
                "inténtelo más tarde."
                if isinstance(estado, int)
                else str(estado)
            )
            db.add(
                Importacion(
                    fuente="conectate", url=url, fecha_objetivo=fecha, ok=False,
                    estado_http=estado if isinstance(estado, int) else None,
                    encontrados=0, detalle=motivo,
                )
            )
            db.commit()
            return {"ok": False, "motivo": motivo, "propuestos": 0, "detalle": []}
        estado_http = estado
    else:
        estado_http = 200

    sorteos = {s.nombre: s for s in db.query(Sorteo).all()}
    encontrados = parsear_resultados(html, nombres_sorteos=set(sorteos.keys()))
    detalle = []
    propuestos = 0
    for nombre, numeros in sorted(encontrados.items()):
        sorteo = sorteos[nombre]
        existente = db.query(Resultado).filter_by(sorteo_id=sorteo.id, fecha=fecha).first()
        if existente is not None and existente.estado in ("confirmado", "liquidado"):
            detalle.append(f"{nombre}: ya confirmado/liquidado, no se tocó")
            continue
        if existente is not None and (existente.premio1, existente.premio2, existente.premio3) == tuple(numeros):
            detalle.append(f"{nombre}: resultado repetido, no se duplicó")
            continue
        if existente is not None:
            detalle.append(f"{nombre}: resultado contradictorio, no se reemplazó")
            continue
        guardar_resultado(db, sorteo.id, fecha, *numeros, usuario, fuente="conectate")
        propuestos += 1
        detalle.append(f"{nombre}: propuesto {'-'.join(f'{n:02d}' for n in numeros)}")
    db.add(
        Importacion(
            fuente="conectate", url=url, fecha_objetivo=fecha, ok=True,
            estado_http=estado_http, encontrados=propuestos,
            detalle="; ".join(detalle) or "La página se leyó pero no se reconoció ningún sorteo",
        )
    )
    auditar(db, "resultado", f"importacion-{fecha}", "importacion_conectate",
            usuario_id=usuario.id,
            detalle={"fecha": str(fecha), "propuestos": propuestos})
    db.commit()
    return {
        "ok": True,
        "motivo": f"{propuestos} resultado(s) quedaron PROPUESTOS para revisión del operador",
        "propuestos": propuestos,
        "detalle": detalle,
    }


def fecha_de_hoy():
    return ahora_local().date()
