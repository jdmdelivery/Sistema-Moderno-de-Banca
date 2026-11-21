"""PDF A4 horizontal del reporte de tickets. No usa la impresora de Windows."""
from io import BytesIO

from reportlab.pdfbase import pdfmetrics
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.colors import HexColor, white

from .pdf_ventas_resumido import _fuentes, formato_monto

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 28
FUENTE_PT = 7
ALTO = 15
ALTO_TICKET = 26
PAD = 2
ANCHOS = (148, 78, 46, 68, 68, 108, 78, 108, 78)
CAB = (
    "Banca", "Fecha y hora", "N.º", "Total apostado", "Total ganado",
    "Usuario que pagó", "Fecha de pago", "Usuario que anuló", "Fecha de anulación",
)
DINERO = {3, 4}

NEGRO = HexColor("#000000")
GRIS = HexColor("#d3d3d3")
AZUL = HexColor("#003399")
LINEA = HexColor("#a0a0a0")


def _fecha(iso: str) -> str:
    partes = str(iso or "").split("-")
    if len(partes) == 3 and all(partes):
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return str(iso or "")


def _cuando(iso: str) -> str:
    texto = str(iso or "").strip()
    if not texto:
        return ""
    fecha, _, hora = texto.partition(" ")
    return f"{_fecha(fecha)} {hora[:5]}".strip()


def _estado(valor: str) -> str:
    return str(valor or "").replace("_", " ").upper()


def _xs():
    xs = [MARGIN]
    for ancho in ANCHOS:
        xs.append(xs[-1] + ancho)
    return xs


def _recortar(texto, fuente, tam, ancho):
    valor = str(texto or "")
    if pdfmetrics.stringWidth(valor, fuente, tam) <= ancho - PAD * 2:
        return valor
    while valor and pdfmetrics.stringWidth(valor + "…", fuente, tam) > ancho - PAD * 2:
        valor = valor[:-1]
    return (valor + "…") if valor else ""


def _texto(c, texto, x, y, ancho, alto, fuente, tam, color, align="left"):
    visible = _recortar(texto, fuente, tam, ancho)
    c.setFillColor(color)
    c.setFont(fuente, tam)
    ancho_txt = pdfmetrics.stringWidth(visible, fuente, tam)
    if align == "right":
        tx = x + ancho - PAD - ancho_txt
    elif align == "center":
        tx = x + (ancho - ancho_txt) / 2
    else:
        tx = x + PAD
    c.drawString(tx, y + (alto - tam) / 2, visible)


def _cabecera_doc(c, datos, fuentes, y):
    regular, negrita = fuentes
    filtros = datos.get("filtros") or {}
    c.setFillColor(NEGRO)
    c.setFont(negrita, 14)
    c.drawString(MARGIN, y, datos.get("empresa") or "BANCA MODERNA")
    c.setFont(regular, 9)
    c.drawRightString(PAGE_W - MARGIN, y, f"Fecha/Hora {datos.get('impreso') or ''}")
    y -= 18
    c.setFillColor(AZUL)
    c.setFont(negrita, 12)
    c.drawCentredString(PAGE_W / 2, y, "Resumen de Tickets")
    y -= 14
    c.setFillColor(NEGRO)
    c.setFont(negrita, 9)
    c.drawCentredString(
        PAGE_W / 2, y,
        f"Desde {_fecha(datos.get('desde'))} {filtros.get('hora_desde') or '00:00'}"
        f" al {_fecha(datos.get('hasta'))} {filtros.get('hora_hasta') or '23:59'}",
    )
    y -= 12
    c.setFont(regular, 7.5)
    numero = filtros.get("ticket_id")
    extra = f" · N.º {numero}" if numero else ""
    c.drawCentredString(
        PAGE_W / 2, y,
        f"Grupo: {filtros.get('grupo') or 'TODOS LOS GRUPOS'} · "
        f"Banca: {filtros.get('banca') or 'TODAS LAS BANCAS'} · "
        f"Lotería: {filtros.get('loteria') or 'TODAS LAS LOTERÍAS'} · "
        f"Estado: {_estado(filtros.get('estado') or 'todos')}",
    )
    y -= 11
    c.drawCentredString(
        PAGE_W / 2, y,
        f"Ruta: {filtros.get('ruta') or 'TODAS LAS RUTAS'} · "
        f"Cajero: {filtros.get('cajero') or 'TODOS LOS CAJEROS'} · "
        f"Orden: {filtros.get('orden') or 'numero'}{extra}",
    )
    return y - 10


def _cabecera_tabla(c, y, fuentes):
    negrita = fuentes[1]
    xs = _xs()
    y1 = y - ALTO
    c.setFillColor(GRIS)
    c.rect(xs[0], y1, xs[-1] - xs[0], ALTO, stroke=0, fill=1)
    c.setStrokeColor(LINEA)
    c.setLineWidth(0.4)
    c.rect(xs[0], y1, xs[-1] - xs[0], ALTO, stroke=1, fill=0)
    for x in xs[1:-1]:
        c.line(x, y1, x, y)
    for i, titulo in enumerate(CAB):
        align = "right" if i in DINERO else "left"
        _texto(c, titulo, xs[i], y1, ANCHOS[i], ALTO, negrita, 6.5, NEGRO, align)
    return y1


def _fila(c, y, valores, fuentes, fondo=white, negrita=False, sub=None):
    fuente = fuentes[1] if negrita else fuentes[0]
    alto = ALTO_TICKET if sub else ALTO
    xs = _xs()
    y1 = y - alto
    if fondo != white:
        c.setFillColor(fondo)
        c.rect(xs[0], y1, xs[-1] - xs[0], alto, stroke=0, fill=1)
    c.setStrokeColor(LINEA)
    c.setLineWidth(0.3)
    c.rect(xs[0], y1, xs[-1] - xs[0], alto, stroke=1, fill=0)
    for x in xs[1:-1]:
        c.line(x, y1, x, y)
    if sub:
        banca = _recortar(valores[0], fuente, FUENTE_PT, ANCHOS[0])
        cajero = _recortar(sub, fuentes[0], 6.5, ANCHOS[0])
        c.setFillColor(NEGRO)
        c.setFont(fuente, FUENTE_PT)
        c.drawString(xs[0] + PAD, y1 + 13, banca)
        c.setFont(fuentes[0], 6.5)
        c.drawString(xs[0] + PAD, y1 + 3, cajero)
    for i, valor in enumerate(valores):
        if sub and i == 0:
            continue
        align = "right" if i in DINERO else "left"
        _texto(c, valor, xs[i], y1, ANCHOS[i], alto, fuente, FUENTE_PT, NEGRO, align)
    return y1


def _grupo(c, y, texto, fuentes):
    negrita = fuentes[1]
    xs = _xs()
    y1 = y - ALTO
    c.setFillColor(HexColor("#e8e8e8"))
    c.rect(xs[0], y1, xs[-1] - xs[0], ALTO, stroke=0, fill=1)
    c.setStrokeColor(LINEA)
    c.setLineWidth(0.3)
    c.rect(xs[0], y1, xs[-1] - xs[0], ALTO, stroke=1, fill=0)
    _texto(c, texto, xs[0], y1, xs[-1] - xs[0], ALTO, negrita, 8, NEGRO, "left")
    return y1


def _cajero(t):
    nombre = str(t.get("cajera") or "").strip()
    return nombre or "Cajero sin registrar"


def _valores(t):
    banca = f"{t.get('sucursal_codigo') or ''} {t.get('sucursal') or ''}".strip()
    premio = t.get("premio_total")
    ganado = formato_monto(premio) if premio not in (None, "", "0", "0.00", "0.0") else ""
    try:
        if float(premio or 0) <= 0:
            ganado = ""
    except (TypeError, ValueError):
        ganado = ""
    return (
        banca,
        _cuando(t.get("vendido_en")),
        str(t.get("id")),
        formato_monto(t.get("total")),
        ganado,
        t.get("usuario_pago") or "",
        _cuando(t.get("fecha_pago")),
        t.get("usuario_anulo") or "",
        _cuando(t.get("fecha_anulacion")),
    )


def construir(datos) -> bytes:
    from reportlab.pdfgen import canvas

    fuentes = _fuentes()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle("Reporte de Tickets")
    y = _cabecera_doc(c, datos, fuentes, PAGE_H - MARGIN)
    y = _cabecera_tabla(c, y, fuentes)
    pagina = 1
    agrupar = bool(datos.get("agrupar_estado"))
    conteos = {
        g.get("estado"): int(g.get("cantidad") or 0)
        for g in (datos.get("grupos") or [])
    }
    previo = None

    def pie():
        c.setFillColor(NEGRO)
        c.setFont(fuentes[0], 8)
        c.drawRightString(PAGE_W - MARGIN, 16, f"Página {pagina}")

    def nueva():
        nonlocal y, pagina
        pie()
        c.showPage()
        pagina += 1
        y = PAGE_H - MARGIN
        y = _cabecera_tabla(c, y, fuentes)

    for t in datos.get("tickets") or []:
        if agrupar and t.get("estado") != previo:
            if y - ALTO * 2 < MARGIN + 28:
                nueva()
            etiqueta = t.get("etiqueta_estado") or t.get("estado") or ""
            n = conteos.get(t.get("estado"), 0)
            y = _grupo(c, y, f"{etiqueta} · {n} ticket{'s' if n != 1 else ''}", fuentes)
            previo = t.get("estado")
        if y - ALTO_TICKET < MARGIN + 28:
            nueva()
            if agrupar and previo:
                etiqueta = t.get("etiqueta_estado") or previo
                n = conteos.get(previo, 0)
                y = _grupo(c, y, f"{etiqueta} · {n} ticket{'s' if n != 1 else ''}", fuentes)
        y = _fila(c, y, _valores(t), fuentes, sub=_cajero(t))
    if y - ALTO < MARGIN + 28:
        nueva()
    premio = datos.get("suma_premio")
    try:
        ganado = formato_monto(premio) if float(premio or 0) > 0 else ""
    except (TypeError, ValueError):
        ganado = ""
    y = _fila(c, y, (
        "Total",
        "",
        f"{datos.get('mostrados', 0)} ticket(s)",
        formato_monto(datos.get("suma") or 0),
        ganado,
        "",
        "",
        "",
        "",
    ), fuentes, GRIS, negrita=True)
    pie()
    c.save()
    return buf.getvalue()


def _titulo_grupo(sorteos) -> str:
    partes = []
    for sorteo in sorteos or []:
        nombre = str(sorteo.get("nombre") or "").strip()
        horario = str(sorteo.get("horario") or "").strip()
        if horario and horario.lower() not in nombre.lower():
            nombre = f"{nombre} · {horario}".strip(" ·")
        if nombre:
            partes.append(nombre)
    return " + ".join(partes) or "Sin lotería"


def construir_recibo(png: bytes) -> bytes:
    """PDF vertical con el mismo recibo que se ve al abrir el ticket."""
    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    im = Image.open(BytesIO(png))
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    ancho, alto = A4
    max_w, max_h = 300, alto - 72
    escala = min(max_w / im.width, max_h / im.height)
    dw, dh = im.width * escala, im.height * escala
    c.drawImage(ImageReader(im), (ancho - dw) / 2, alto - 36 - dh, dw, dh, mask="auto")
    c.save()
    return buf.getvalue()


def construir_detalle(datos) -> bytes:
    """PDF del ticket abierto en el visor. No es el recibo de venta."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    fuentes = _fuentes()
    regular, negrita = fuentes
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Ticket {datos.get('id')}")
    ancho, alto = A4
    margen = 36
    y = alto - margen
    pagina = 1

    def pie():
        c.setFillColor(NEGRO)
        c.setFont(regular, 8)
        c.drawRightString(ancho - margen, 18, f"Página {pagina}")

    def salto():
        nonlocal y, pagina
        pie()
        c.showPage()
        pagina += 1
        y = alto - margen

    def linea(texto, fuente, tam, color=NEGRO, centrado=False, salto_antes=14):
        nonlocal y
        if y - salto_antes < margen + 24:
            salto()
        y -= salto_antes
        c.setFillColor(color)
        c.setFont(fuente, tam)
        if centrado:
            c.drawCentredString(ancho / 2, y, str(texto))
        else:
            c.drawString(margen, y, str(texto))

    linea(datos.get("empresa") or "BANCA MODERNA", negrita, 16, salto_antes=0)
    linea(datos.get("banca") or "", negrita, 12)
    linea(f"Ticket #{datos.get('id')}", negrita, 12, AZUL)
    linea(f"Fecha y hora  {_cuando(datos.get('fecha_hora'))}", regular, 10)
    linea(f"Estado  {datos.get('etiqueta_estado') or _estado(datos.get('estado'))}", regular, 10)
    if datos.get("fecha_pago") or datos.get("usuario_pago"):
        quienes = []
        if datos.get("pagos"):
            for pago in datos["pagos"]:
                quienes.append(
                    f"{pago.get('usuario') or ''} el {_cuando(pago.get('fecha'))}".strip()
                )
        else:
            quienes.append(
                f"{datos.get('usuario_pago') or ''} el {_cuando(datos.get('fecha_pago'))}".strip()
            )
        linea("Pagado por  " + " · ".join(q for q in quienes if q), regular, 9)
    if datos.get("fecha_anulacion") or datos.get("usuario_anulo"):
        linea(
            f"Anulado por  {datos.get('usuario_anulo') or ''} el {_cuando(datos.get('fecha_anulacion'))}",
            regular, 9,
        )
    y -= 8
    columnas = (320, 90, 90)
    cab = ("Tipo y número", "Apostado", "Ganado")

    def fila_tabla(valores, fondo=white, fuente=regular, alto_fila=16):
        nonlocal y
        if y - alto_fila < margen + 24:
            salto()
        y -= alto_fila
        x = margen
        if fondo != white:
            c.setFillColor(fondo)
            c.rect(margen, y, sum(columnas), alto_fila, stroke=0, fill=1)
        c.setStrokeColor(LINEA)
        c.setLineWidth(0.3)
        c.rect(margen, y, sum(columnas), alto_fila, stroke=1, fill=0)
        for i, valor in enumerate(valores):
            align = "right" if i else "left"
            _texto(c, valor, x, y, columnas[i], alto_fila, fuente, 8, NEGRO, align)
            x += columnas[i]
            if i < len(valores) - 1:
                c.setStrokeColor(LINEA)
                c.line(x, y, x, y + alto_fila)

    fila_tabla(cab, GRIS, negrita)
    for grupo in datos.get("grupos") or []:
        fila_tabla((_titulo_grupo(grupo.get("sorteos")), "", ""), HexColor("#e8e8e8"), negrita)
        for jugada in grupo.get("jugadas") or []:
            premio = jugada.get("premio")
            ganado = ""
            if premio not in (None, ""):
                ganado = formato_monto(premio)
            fila_tabla((
                f"{jugada.get('tipo_nombre') or ''} {jugada.get('numeros') or ''}".strip(),
                formato_monto(jugada.get("monto")),
                ganado,
            ))
    cierre = (
        ("Total apostado", datos.get("total")),
        ("Premio ganado", datos.get("premio_ganado")),
        ("Monto pagado", datos.get("importe_pagado")),
        ("Saldo pendiente", datos.get("importe_pendiente")),
    )
    ancho_cierre = sum(columnas)
    alto_fila = 16
    for etiqueta, monto in cierre:
        if y - alto_fila < margen + 24:
            salto()
        y -= alto_fila
        c.setFillColor(GRIS)
        c.rect(margen, y, ancho_cierre, alto_fila, stroke=0, fill=1)
        c.setStrokeColor(LINEA)
        c.setLineWidth(0.3)
        c.rect(margen, y, ancho_cierre, alto_fila, stroke=1, fill=0)
        c.line(margen + 360, y, margen + 360, y + alto_fila)
        _texto(c, etiqueta, margen, y, 360, alto_fila, negrita, 8, NEGRO, "left")
        _texto(c, formato_monto(monto), margen + 360, y, ancho_cierre - 360, alto_fila, negrita, 8, NEGRO, "right")
    linea("Historial de pagos", negrita, 10, salto_antes=18)
    pagos = datos.get("pagos") or []
    if not pagos:
        linea("Sin pagos", regular, 9, salto_antes=12)
    for pago in pagos:
        linea(
            f"{pago.get('usuario') or ''}   {_cuando(pago.get('fecha'))}   {formato_monto(pago.get('monto'))}",
            regular, 9, salto_antes=12,
        )
    pie()
    c.save()
    return buf.getvalue()
