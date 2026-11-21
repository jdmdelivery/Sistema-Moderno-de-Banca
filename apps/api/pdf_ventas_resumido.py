"""PDF real del reporte de ventas resumido.

El archivo se arma en el servidor, en A4 horizontal, con el tamaño de
página escrito en el documento. No consulta la impresora de Windows:
aunque la predeterminada sea una térmica de 58 mm, el PDF no se encoge.
"""
import os
from io import BytesIO

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.colors import HexColor, white

from .comun import D

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 28
# 9 pt en A4: legible. No se reduce para meter más filas en una sola hoja.
FUENTE_PT = 9
FUENTE_CAB_PT = 8
ALTO_FILA = 16
ALTO_CAB_TABLA = 15
PAD_X = 3
# Anchos fijos que cubren encabezados y montos de hasta 7 cifras, sin recortar.
ANCHOS = (193, 66, 62, 66, 66, 70, 62, 62, 62, 76)
COLS_NUM = (
    ("loteria", "venta"),
    ("loteria", "comision"),
    ("loteria", "neto"),
    ("loteria", "premios"),
    ("loteria", "resultado"),
    ("recargas", "venta"),
    ("recargas", "comision"),
    ("recargas", "neto"),
    ("_total", "resultado_total"),
)
CAB_NUM = (
    "Venta", "Comisión", "Neto", "Premios", "Resultado",
    "Venta", "Comisión", "Neto",
)

NEGRO = HexColor("#000000")
ROJO = HexColor("#ff0000")
GRIS = HexColor("#d3d3d3")
GRIS_LOTERIA = HexColor("#c0c0c0")
AZUL_RECARGAS = HexColor("#6495ed")
AZUL_TITULO = HexColor("#003399")
LINEA = HexColor("#a0a0a0")
VACIO_REC = {"venta": "0.00", "comision": "0.00", "neto": "0.00"}

_FUENTES = None


def _fuentes():
    global _FUENTES
    if _FUENTES:
        return _FUENTES
    pares = (
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    )
    for regular, negrita in pares:
        if os.path.isfile(regular) and os.path.isfile(negrita):
            pdfmetrics.registerFont(TTFont("RvrSans", regular))
            pdfmetrics.registerFont(TTFont("RvrSans-Bold", negrita))
            _FUENTES = ("RvrSans", "RvrSans-Bold")
            return _FUENTES
    _FUENTES = ("Helvetica", "Helvetica-Bold")
    return _FUENTES


def formato_monto(valor) -> str:
    """Mismo signo que el panel: $1,234.56 y $-591.00."""
    n = D(valor)
    return f"${n:,.2f}"


def _fecha(iso: str) -> str:
    partes = str(iso or "").split("-")
    if len(partes) == 3 and all(partes):
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return str(iso or "")


def _xs():
    xs = [MARGIN]
    for ancho in ANCHOS:
        xs.append(xs[-1] + ancho)
    return xs


def _cabe_en_celda(texto, fuente, tam, ancho) -> bool:
    return pdfmetrics.stringWidth(texto, fuente, tam) <= (ancho - 2 * PAD_X)


def _partir(texto, fuente, tam, ancho):
    limite = ancho - 2 * PAD_X
    palabras = str(texto or "").split()
    if not palabras:
        return [""]
    lineas = []
    actual = palabras[0]
    for palabra in palabras[1:]:
        prueba = f"{actual} {palabra}"
        if pdfmetrics.stringWidth(prueba, fuente, tam) <= limite:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    lineas.append(actual)
    return lineas


def _filas(datos, fuente, negrita):
    """Filas del documento, con el alto que ocupan. Ninguna se parte entre páginas."""
    filas = []
    for grupo in datos.get("grupos") or []:
        n = len(grupo.get("bancas") or [])
        if grupo.get("subtotal"):
            n = grupo["subtotal"].get("bancas", n)
        filas.append({
            "tipo": "grupo",
            "texto": f"Grupo: {grupo.get('grupo_nombre', '')}    Total de Bancas: ({n})",
            "alto": ALTO_FILA,
        })
        for banca in grupo.get("bancas") or []:
            nombre = f"{banca.get('codigo', '')} {banca.get('banca', '')}".strip()
            lineas = _partir(nombre, fuente, FUENTE_PT, ANCHOS[0])
            alto = max(ALTO_FILA, len(lineas) * 11 + 5)
            filas.append({
                "tipo": "banca",
                "lineas": lineas,
                "banca": banca,
                "alto": alto,
            })
            if datos.get("desglose_cajeros"):
                for cajero in banca.get("cajeros") or []:
                    etiqueta = f"Cajero: {cajero.get('nombre', '')}"
                    lineas_c = _partir(etiqueta, fuente, FUENTE_PT, ANCHOS[0] - 10)
                    valores = [
                        cajero.get("venta", 0), cajero.get("comision", 0),
                        cajero.get("neto", 0), cajero.get("premios", 0),
                        cajero.get("resultado", 0),
                    ]
                    filas.append({
                        "tipo": "cajero",
                        "lineas": lineas_c,
                        "valores": valores,
                        "alto": max(ALTO_FILA, len(lineas_c) * 11 + 5),
                    })
                if banca.get("cajeros"):
                    filas.append({
                        "tipo": "comision_cajeras",
                        "texto": "Total comisión de cajeras",
                        "monto": banca.get("total_comision_cajeras") or 0,
                        "alto": ALTO_FILA,
                    })
        if grupo.get("subtotal"):
            filas.append({
                "tipo": "subtotal",
                "texto": "Sub-Total",
                "bloque": grupo["subtotal"],
                "alto": ALTO_FILA,
            })
    total = datos.get("total") or {}
    filas.append({"tipo": "total", "texto": "Total", "bloque": total, "alto": ALTO_FILA})
    filas.append({
        "tipo": "span",
        "texto": f"Total de Bancas: ({total.get('bancas', 0)})",
        "alto": ALTO_FILA,
    })
    filas.append({
        "tipo": "span",
        "texto": f"Promedio de Ventas por Banca: ({formato_monto(total.get('promedio_venta', 0))})",
        "alto": ALTO_FILA,
    })
    for fila in filas:
        if fila["tipo"] == "banca":
            _exigir_montos(fila["banca"], fuente)
        elif fila["tipo"] == "cajero":
            _exigir_valores(fila["valores"], ANCHOS[1:6], fuente)
        elif fila["tipo"] == "comision_cajeras":
            _exigir_valores([fila["monto"]], [ANCHOS[2]], fuente)
        elif fila["tipo"] in ("subtotal", "total"):
            _exigir_montos(fila["bloque"], negrita)
    return filas


def _montos(bloque):
    rec = (bloque or {}).get("recargas") or VACIO_REC
    lot = (bloque or {}).get("loteria") or {}
    total = (bloque or {}).get("resultado_total", 0)
    valores = []
    for seccion, campo in COLS_NUM:
        origen = lot if seccion == "loteria" else rec
        if seccion == "_total":
            valores.append(D(total))
        else:
            valores.append(D(origen.get(campo, 0)))
    return valores


def _exigir_valores(valores, anchos, fuente):
    for ancho, valor in zip(anchos, valores):
        texto = formato_monto(valor)
        if not _cabe_en_celda(texto, fuente, FUENTE_PT, ancho):
            raise RuntimeError(f"El importe {texto} no cabe en la columna ({ancho} pt)")


def _dibujar_valores(c, valores, y, alto, fuente, inicio=1):
    xs = _xs()
    for i, valor in enumerate(valores, start=inicio):
        texto = formato_monto(valor)
        color = ROJO if D(valor) < 0 else NEGRO
        _texto(c, texto, xs[i], y, ANCHOS[i], alto, fuente, FUENTE_PT, color, "right")


def _exigir_montos(bloque, fuente):
    """El monto se dibuja completo. Si no cabe, se rechaza el ancho, no se recorta."""
    for ancho, valor in zip(ANCHOS[1:], _montos(bloque)):
        texto = formato_monto(valor)
        if not _cabe_en_celda(texto, fuente, FUENTE_PT, ancho):
            raise RuntimeError(f"El importe {texto} no cabe en la columna ({ancho} pt)")


def _top_tabla():
    """Borde superior de la tabla. Tiene que coincidir con _dibujar_cabecera_doc."""
    return PAGE_H - MARGIN - 54


def _alto_util():
    return _top_tabla() - (ALTO_CAB_TABLA * 2) - 24


def _empaquetar(filas):
    disponible = _alto_util()
    paginas = []
    actual = []
    usado = 0
    i = 0
    while i < len(filas):
        fila = filas[i]
        bloque = 1
        extra = 0
        if fila["tipo"] == "total":
            bloque = min(3, len(filas) - i)
            extra = sum(filas[i + k]["alto"] for k in range(bloque))
        alto = extra or fila["alto"]
        if actual and usado + alto > disponible:
            paginas.append(actual)
            actual = []
            usado = 0
            continue
        for k in range(bloque):
            actual.append(filas[i + k])
            usado += filas[i + k]["alto"]
        i += bloque
    if actual or not paginas:
        paginas.append(actual)
    return paginas


def _texto(c, texto, x, y, ancho, alto, fuente, tam, color, align):
    c.setFillColor(color)
    c.setFont(fuente, tam)
    tw = pdfmetrics.stringWidth(texto, fuente, tam)
    if align == "right":
        tx = x + ancho - PAD_X - tw
    elif align == "center":
        tx = x + (ancho - tw) / 2
    else:
        tx = x + PAD_X
    c.drawString(tx, y + (alto - tam) / 2 + 1, texto)


def _rect(c, x, y, w, h, color):
    c.setFillColor(color)
    c.rect(x, y, w, h, fill=1, stroke=0)


def _linea(c, x1, y1, x2, y2):
    c.setStrokeColor(LINEA)
    c.setLineWidth(0.4)
    c.line(x1, y1, x2, y2)


def _dibujar_cabecera_doc(c, datos, fuentes):
    regular, negrita = fuentes
    y = PAGE_H - MARGIN
    c.setFillColor(NEGRO)
    c.setFont(negrita, 14)
    c.drawString(MARGIN, y - 14, str(datos.get("empresa") or "BANCA MODERNA"))
    c.setFont(regular, 9)
    c.drawRightString(PAGE_W - MARGIN, y - 12, f"Fecha/Hora {datos.get('impreso', '')}")
    y -= 20
    c.setFillColor(AZUL_TITULO)
    c.setFont(negrita, 13)
    c.drawCentredString(PAGE_W / 2, y - 13, "Resumen de Ventas")
    y -= 16
    c.setFillColor(NEGRO)
    c.setFont(negrita, 9)
    meta = f"Desde {_fecha(datos.get('desde', ''))} al {_fecha(datos.get('hasta', ''))}"
    c.drawCentredString(PAGE_W / 2, y - 10, meta)
    return _top_tabla()


def _dibujar_cabecera_tabla(c, top, fuentes):
    """Dos filas de encabezado. `top` es el borde superior; devuelve el borde inferior."""
    _, negrita = fuentes
    xs = _xs()
    alto = ALTO_CAB_TABLA
    y1 = top - alto
    y0 = y1 - alto
    _rect(c, xs[0], y0, ANCHOS[0], alto * 2, GRIS)
    _rect(c, xs[9], y0, ANCHOS[9], alto * 2, GRIS)
    _rect(c, xs[1], y1, sum(ANCHOS[1:6]), alto, GRIS_LOTERIA)
    _rect(c, xs[6], y1, sum(ANCHOS[6:9]), alto, AZUL_RECARGAS)
    for i in range(1, 9):
        _rect(c, xs[i], y0, ANCHOS[i], alto, GRIS)
    _linea(c, xs[0], y0, xs[-1], y0)
    _linea(c, xs[0], top, xs[-1], top)
    _linea(c, xs[1], y1, xs[9], y1)
    for x in (xs[0], xs[1], xs[9], xs[-1]):
        _linea(c, x, y0, x, top)
    for x in xs[2:9]:
        _linea(c, x, y0, x, y1)
    _texto(c, "Banca", xs[0], y0, ANCHOS[0], alto * 2, negrita, FUENTE_CAB_PT, NEGRO, "center")
    # La celda ya ocupa dos filas. En DejaVu (Render) las dos palabras no
    # caben en una sola línea; cada una sí.
    _texto(c, "Resultado", xs[9], y0 + alto, ANCHOS[9], alto, negrita, FUENTE_CAB_PT, NEGRO, "center")
    _texto(c, "Total", xs[9], y0, ANCHOS[9], alto, negrita, FUENTE_CAB_PT, NEGRO, "center")
    _texto(c, "LOTERÍA", xs[1], y1, sum(ANCHOS[1:6]), alto, negrita, FUENTE_CAB_PT, NEGRO, "center")
    _texto(c, "RECARGAS", xs[6], y1, sum(ANCHOS[6:9]), alto, negrita, FUENTE_CAB_PT, white, "center")
    for i, titulo in enumerate(CAB_NUM, start=1):
        _texto(c, titulo, xs[i], y0, ANCHOS[i], alto, negrita, FUENTE_CAB_PT, NEGRO, "center")
    return y0


def _dibujar_montos(c, bloque, y, alto, fuente, negrita=False):
    xs = _xs()
    fnt = negrita or fuente
    for i, valor in enumerate(_montos(bloque), start=1):
        texto = formato_monto(valor)
        color = ROJO if valor < 0 else NEGRO
        _texto(c, texto, xs[i], y, ANCHOS[i], alto, fnt, FUENTE_PT, color, "right")


def _dibujar_fila(c, fila, top, fuentes):
    regular, negrita = fuentes
    xs = _xs()
    alto = fila["alto"]
    y = top - alto
    ancho_total = sum(ANCHOS)
    gris = fila["tipo"] in ("subtotal", "total", "span")
    _rect(c, xs[0], y, ancho_total, alto, GRIS if gris else white)
    c.setStrokeColor(LINEA)
    c.setLineWidth(0.4)
    c.line(xs[0], y, xs[-1], y)
    c.line(xs[0], top, xs[-1], top)
    c.line(xs[0], y, xs[0], top)
    c.line(xs[-1], y, xs[-1], top)
    if fila["tipo"] not in ("grupo", "span"):
        for x in xs[1:-1]:
            c.line(x, y, x, top)
    if fila["tipo"] == "grupo":
        _texto(c, fila["texto"], xs[0], y, ancho_total, alto, negrita, FUENTE_PT, NEGRO, "left")
    elif fila["tipo"] == "banca":
        lineas = fila["lineas"]
        bloque_h = len(lineas) * 11
        y_txt = y + (alto - bloque_h) / 2
        c.setFillColor(NEGRO)
        c.setFont(regular, FUENTE_PT)
        for i, linea in enumerate(lineas):
            c.drawString(xs[0] + PAD_X, y_txt + (len(lineas) - 1 - i) * 11 + 1, linea)
        _dibujar_montos(c, fila["banca"], y, alto, regular)
    elif fila["tipo"] == "cajero":
        lineas = fila["lineas"]
        bloque_h = len(lineas) * 11
        y_txt = y + (alto - bloque_h) / 2
        c.setFillColor(NEGRO)
        c.setFont(regular, FUENTE_PT)
        for i, linea in enumerate(lineas):
            c.drawString(xs[0] + PAD_X + 8, y_txt + (len(lineas) - 1 - i) * 11 + 1, linea)
        _dibujar_valores(c, fila["valores"], y, alto, regular)
    elif fila["tipo"] == "comision_cajeras":
        _texto(c, fila["texto"], xs[0], y, ANCHOS[0], alto, negrita, FUENTE_PT, NEGRO, "left")
        _dibujar_valores(c, [fila["monto"]], y, alto, negrita, inicio=2)
    elif fila["tipo"] in ("subtotal", "total"):
        _texto(c, fila["texto"], xs[0], y, ANCHOS[0], alto, negrita, FUENTE_PT, NEGRO, "left")
        _dibujar_montos(c, fila["bloque"], y, alto, negrita, negrita=negrita)
    else:
        _texto(c, fila["texto"], xs[0], y, ancho_total, alto, negrita, FUENTE_PT, NEGRO, "left")
    return y


def _dibujar_pagina(c, datos, filas, numero, total, fuentes):
    c.setFillColor(white)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    cursor = _dibujar_cabecera_doc(c, datos, fuentes)
    cursor = _dibujar_cabecera_tabla(c, cursor, fuentes)
    for fila in filas:
        cursor = _dibujar_fila(c, fila, cursor, fuentes)
    c.setFillColor(HexColor("#444444"))
    c.setFont(fuentes[0], 8)
    c.drawRightString(PAGE_W - MARGIN, 12, f"Página {numero} de {total}")
    c.showPage()


def construir(datos: dict) -> bytes:
    """Devuelve el PDF (bytes) en A4 horizontal, una o más páginas."""
    regular, negrita = _fuentes()
    for titulo, ancho in zip(("Banca",) + CAB_NUM, ANCHOS[:-1]):
        if not _cabe_en_celda(titulo, negrita, FUENTE_CAB_PT, ancho):
            raise RuntimeError(f"El encabezado {titulo} no cabe en su columna")
    for linea in ("Resultado", "Total"):
        if not _cabe_en_celda(linea, negrita, FUENTE_CAB_PT, ANCHOS[9]):
            raise RuntimeError(f"El encabezado {linea} no cabe en su columna")
    if not _cabe_en_celda("LOTERÍA", negrita, FUENTE_CAB_PT, sum(ANCHOS[1:6])):
        raise RuntimeError("El encabezado LOTERÍA no cabe")
    if not _cabe_en_celda("RECARGAS", negrita, FUENTE_CAB_PT, sum(ANCHOS[6:9])):
        raise RuntimeError("El encabezado RECARGAS no cabe")

    filas = _filas(datos, regular, negrita)
    paginas = _empaquetar(filas)
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), pageCompression=0)
    c.setTitle("BANCA MODERNA — Resumen de Ventas")
    c.setAuthor(str(datos.get("empresa") or "BANCA MODERNA"))
    total = len(paginas)
    for n, filas_pagina in enumerate(paginas, start=1):
        _dibujar_pagina(c, datos, filas_pagina, n, total, (regular, negrita))
    c.save()
    return buf.getvalue()
