"""Recibos térmicos 384 px (resumen, entrega, pago de premios).

Solo dibuja. No vende, no paga, no mueve caja ni cambia cálculos.
Compatible con texto de respaldo para APK antiguas.
"""
from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ANCHO_DEFAULT = 384
MARGEN_X = 10


def _fuente(tamano: int, negrita: bool = False):
    candidatos = [
        "C:/Windows/Fonts/arialbd.ttf" if negrita else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if negrita else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if negrita else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for ruta in candidatos:
        try:
            return ImageFont.truetype(ruta, max(8, int(tamano)))
        except OSError:
            continue
    return ImageFont.load_default()


def _medir(draw: ImageDraw.ImageDraw, texto: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), texto, font=font)
    return box[2] - box[0], box[3] - box[1]


def _alto(font) -> int:
    try:
        a, d = font.getmetrics()
        return int(a + d)
    except Exception:
        return int(getattr(font, "size", 16) + 4)


def _centrar_x(ancho: int, w: int) -> int:
    return max(0, (ancho - w) // 2)


def _D(valor) -> Decimal:
    try:
        return Decimal(str(valor))
    except Exception:
        return Decimal("0")


def _rd(valor) -> str:
    return f"RD${_D(valor):.2f}"


def _recortar(draw, texto: str, font, util: int) -> str:
    if _medir(draw, texto, font)[0] <= util:
        return texto
    recorte = texto
    while len(recorte) > 1 and _medir(draw, recorte + "…", font)[0] > util:
        recorte = recorte[:-1]
    return recorte + "…"


def _nombre_ajustado(draw, texto: str, util: int, max_t: int = 28, min_t: int = 16):
    for tam in range(max_t, min_t - 1, -1):
        font = _fuente(tam, negrita=True)
        if _medir(draw, texto, font)[0] <= util - 4:
            return font
    return _fuente(min_t, negrita=True)


class _Lienzo:
    def __init__(self, ancho: int = ANCHO_DEFAULT):
        self.ancho = ancho
        self.util = ancho - MARGEN_X * 2
        self.gap = 3
        self.alto_tmp = 3200
        self.img = Image.new("L", (ancho, self.alto_tmp), 255)
        self.draw = ImageDraw.Draw(self.img)
        self.y = 8

    def texto(self, s: str, font, *, centrado: bool = False, extra: int | None = None, envolver: bool = False):
        s = str(s or "")
        lineas = [s]
        if envolver and _medir(self.draw, s, font)[0] > self.util:
            palabras = s.split()
            lineas = []
            actual = ""
            for p in palabras:
                prueba = f"{actual} {p}".strip()
                if actual and _medir(self.draw, prueba, font)[0] > self.util:
                    lineas.append(actual)
                    actual = p
                else:
                    actual = prueba
            if actual:
                lineas.append(actual)
            if not lineas:
                lineas = [_recortar(self.draw, s, font, self.util)]
        for i, ln in enumerate(lineas):
            ln = _recortar(self.draw, ln, font, self.util)
            w, _ = _medir(self.draw, ln, font)
            h = max(_medir(self.draw, ln, font)[1], _alto(font))
            x = _centrar_x(self.ancho, w) if centrado else MARGEN_X
            self.draw.text((x, self.y), ln, fill=0, font=font)
            if i < len(lineas) - 1:
                self.y += h + 1
            else:
                self.y += h + (self.gap if extra is None else extra)

    def _partir(self, texto: str, font, ancho: int) -> list[str]:
        texto = str(texto or "").strip()
        if not texto:
            return [""]
        palabras = texto.split()
        lineas: list[str] = []
        actual = ""
        for palabra in palabras:
            prueba = f"{actual} {palabra}".strip()
            if actual and _medir(self.draw, prueba, font)[0] > ancho:
                lineas.append(actual)
                actual = palabra
            else:
                actual = prueba
        if actual:
            lineas.append(actual)
        return lineas or [""]

    def texto_completo(self, s: str, font, *, centrado: bool = False, extra: int | None = None):
        """Escribe el texto entero. Encoge o parte líneas; no lo corta con puntos."""
        s = str(s or "")
        tam = int(getattr(font, "size", 16) or 16)
        fuente = font
        if " " not in s.strip() and _medir(self.draw, s, fuente)[0] > self.util:
            while tam > 11 and _medir(self.draw, s, fuente)[0] > self.util:
                tam -= 1
                fuente = _fuente(tam, negrita=True)
            self._linea_entera(s, fuente, centrado, extra)
            return
        lineas = self._partir(s, fuente, self.util)
        for i, ln in enumerate(lineas):
            fuente_linea = fuente
            t = tam
            while t > 11 and _medir(self.draw, ln, fuente_linea)[0] > self.util:
                t -= 1
                fuente_linea = _fuente(t, negrita=True)
            self._linea_entera(ln, fuente_linea, centrado, 1 if i < len(lineas) - 1 else extra)

    def _linea_entera(self, ln: str, font, centrado: bool, extra: int | None):
        w, h_med = _medir(self.draw, ln, font)
        h = max(h_med, _alto(font))
        x = _centrar_x(self.ancho, w) if centrado else MARGEN_X
        if x < MARGEN_X:
            x = MARGEN_X
        self.draw.text((x, self.y), ln, fill=0, font=font)
        self.y += h + (self.gap if extra is None else extra)

    def fila_completa(self, izq: str, der: str, font_izq, font_der=None, *, extra: int | None = None):
        """Etiqueta a la izquierda y monto completo a la derecha, sin recortes."""
        font_der = font_der or font_izq
        der = str(der or "")
        tam = int(getattr(font_der, "size", 18) or 18)
        fuente_monto = font_der
        while tam > 10 and _medir(self.draw, der, fuente_monto)[0] > self.util:
            tam -= 1
            fuente_monto = _fuente(tam, negrita=True)
        der_w = _medir(self.draw, der, fuente_monto)[0]
        lineas = self._partir(str(izq or ""), font_izq, self.util)
        ultima = lineas[-1] if lineas else ""
        ultima_w = _medir(self.draw, ultima, font_izq)[0]
        cabe = ultima_w + 8 + der_w <= self.util
        previas = lineas[:-1] if cabe and lineas else lineas
        for ln in previas:
            self._linea_entera(ln, font_izq, False, 1)
        h = max(
            _medir(self.draw, ultima if cabe else " ", font_izq)[1],
            _medir(self.draw, der, fuente_monto)[1],
            _alto(font_izq),
            _alto(fuente_monto),
        )
        if cabe:
            self.draw.text((MARGEN_X, self.y), ultima, fill=0, font=font_izq)
        self.draw.text((self.ancho - MARGEN_X - der_w, self.y), der, fill=0, font=fuente_monto)
        self.y += h + (self.gap if extra is None else extra)

    def fila(self, izq: str, der: str, font_izq, font_der=None, *, extra: int | None = None):
        font_der = font_der or font_izq
        izq = _recortar(self.draw, str(izq), font_izq, self.util // 2)
        der = _recortar(self.draw, str(der), font_der, self.util // 2)
        h = max(
            _medir(self.draw, izq, font_izq)[1],
            _medir(self.draw, der, font_der)[1],
            _alto(font_izq),
            _alto(font_der),
        )
        der_w, _ = _medir(self.draw, der, font_der)
        self.draw.text((MARGEN_X, self.y), izq, fill=0, font=font_izq)
        self.draw.text((self.ancho - MARGEN_X - der_w, self.y), der, fill=0, font=font_der)
        self.y += h + (self.gap if extra is None else extra)

    def sep(self):
        self.y += 2
        self.draw.line((MARGEN_X, self.y, self.ancho - MARGEN_X, self.y), fill=0, width=1)
        self.y += 4

    def png(self) -> bytes:
        self.y += 10
        recorte = self.img.crop((0, 0, self.ancho, min(self.y, self.alto_tmp)))
        bw = recorte.point(lambda p: 0 if p < 180 else 255, mode="1")
        buf = io.BytesIO()
        bw.convert("L").save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def _cabecera(c: _Lienzo, banca: str, titulo: str):
    banca = (banca or "BANCA").strip().upper() or "BANCA"
    f_nom = _nombre_ajustado(c.draw, banca, c.util, 28, 16)
    c.texto(banca, f_nom, centrado=True, extra=4)
    c.texto(titulo, _fuente(22, negrita=True), centrado=True, extra=4)
    c.sep()


def _importe_de_bloque(bloque: dict | None) -> Decimal:
    """Suma absoluta de los importes. Cero significa bloque vacío."""
    if not bloque:
        return Decimal("0")
    total = Decimal("0")
    for clave in ("ventas", "premios_pagados", "comision", "balance", "recargas", "total"):
        if clave not in bloque:
            continue
        try:
            total += abs(Decimal(str(bloque.get(clave) or "0")))
        except Exception:
            continue
    if total != 0:
        return total
    for fila in bloque.get("lineas") or []:
        texto = str((fila or {}).get("monto") or "")
        negativo = texto.strip().startswith("-")
        limpio = texto.replace("RD$", "").replace(",", "").replace("-", "").strip()
        try:
            n = Decimal(limpio or "0")
        except Exception:
            n = Decimal("0")
        total += abs(n if not negativo else n)
    return total


AVISO_RECIBO_DOS_GRUPOS = (
    "NO SE IMPRIMIÓ EL TOTAL. Este período tiene movimientos oficiales "
    "y de prueba. La consulta no indica cuál imprimir. No se elige uno ni se suman."
)


def concepto_papel(concepto: str) -> str:
    """Etiqueta del papel. La pantalla conserva la suya."""
    if concepto == "Premios":
        return "Premios pagados"
    return concepto


def seleccion_recibo(oficial: dict | None, prueba: dict | None) -> dict | None:
    """Un grupo para el papel. None avisa y no imprime montos.

    El grupo en cero se omite. Si los dos tienen movimiento, la consulta
    no identifica cuál se pidió: no se elige uno ni se suman.
    """
    if _importe_de_bloque(oficial) != 0 and _importe_de_bloque(prueba) != 0:
        return None
    if _importe_de_bloque(prueba) != 0:
        return prueba or {}
    if oficial is not None:
        return oficial
    return prueba or {}


def render_resumen_png(datos: dict[str, Any]) -> bytes:
    """PNG 384 px del resumen de caja. Un solo bloque, sin rótulo de prueba."""
    c = _Lienzo()
    f_c = _fuente(16, negrita=True)
    f_m = _fuente(18, negrita=True)
    f_tot = _fuente(22, negrita=True)
    inf = datos.get("informe") or {}
    banca = str(inf.get("banca") or datos.get("banca") or datos.get("sucursal") or "BANCA").strip().upper() or "BANCA"
    f_nom = _nombre_ajustado(c.draw, banca, c.util, 28, 14)
    c.texto_completo(banca, f_nom, centrado=True, extra=4)
    c.texto_completo("RESUMEN DE CAJA", _fuente(22, negrita=True), centrado=True, extra=4)
    c.sep()
    c.texto_completo(f"Código: {inf.get('codigo', '')}", f_c)
    c.texto_completo(f"Cajera: {inf.get('cajera') or datos.get('cajero', '')}", f_c)
    c.texto_completo(f"Terminal: {inf.get('terminal') or datos.get('terminal', '')}", f_c)
    periodo = inf.get("periodo")
    if not periodo and datos.get("desde"):
        periodo = datos.get("desde") if datos.get("desde") == datos.get("hasta") else (
            f"{datos.get('desde', '')} al {datos.get('hasta', '')}"
        )
    c.texto_completo(f"Período: {periodo or ''}", f_c)
    if datos.get("impreso"):
        c.texto_completo(f"Impreso: {datos['impreso']}", f_c)
    c.sep()

    bloque = seleccion_recibo(inf.get("oficial"), inf.get("prueba"))
    if bloque is None:
        c.texto_completo(AVISO_RECIBO_DOS_GRUPOS, f_c, centrado=True, extra=4)
        return c.png()
    for fila in bloque.get("lineas") or []:
        destacar = bool(fila.get("destacar"))
        if destacar:
            c.sep()
        c.fila_completa(
            concepto_papel(str(fila.get("concepto") or "")),
            str(fila.get("monto") or ""),
            f_tot if destacar else f_c,
            f_tot if destacar else f_m,
        )
    return c.png()


def render_entrega_png(datos: dict[str, Any]) -> bytes:
    """PNG de entrega de dinero. No altera montos ni operaciones."""
    c = _Lienzo()
    f_c = _fuente(16, negrita=True)
    f_m = _fuente(18, negrita=True)
    f_monto = _fuente(26, negrita=True)
    _cabecera(c, str(datos.get("banca") or datos.get("sucursal") or "BANCA"), "ENTREGA DE DINERO")
    if datos.get("es_prueba") or datos.get("leyenda"):
        c.texto("PRUEBA — NO OFICIAL", f_c, centrado=True)
    if datos.get("fecha_hora"):
        c.texto(str(datos["fecha_hora"]), f_c, centrado=True)
    c.sep()
    c.texto(f"Cajero: {datos.get('cajera') or datos.get('cajero') or ''}", f_c)
    receptor = str(datos.get("recibida_por_nombre") or datos.get("receptor") or "").strip()
    if receptor:
        c.texto(f"Recibe: {receptor}", f_c)
    if datos.get("sucursal"):
        c.texto(f"Sucursal: {datos['sucursal']}", f_c)
    if datos.get("numero") or datos.get("id"):
        c.texto(f"Nº entrega: {datos.get('numero') or datos.get('id')}", f_c)
    if datos.get("operacion_id"):
        c.texto(f"Operación: {datos['operacion_id']}", f_c)
    c.sep()
    c.texto("MONTO ENTREGADO", f_m, centrado=True, extra=2)
    c.texto(_rd(datos.get("monto")), f_monto, centrado=True, extra=6)
    c.fila("Saldo anterior", _rd(datos.get("saldo_anterior")), f_c, f_m)
    c.fila("Saldo restante", _rd(datos.get("saldo_restante")), f_c, f_m)
    c.sep()
    c.texto(f"Estado: {datos.get('estado') or 'CONFIRMADA'}", f_c, centrado=True)
    if datos.get("recepcion"):
        c.texto(f"Recepción: {datos['recepcion']}", f_c, centrado=True)
    return c.png()


def render_pago_png(datos: dict[str, Any]) -> bytes:
    """PNG de pago de premios de una operación. Reimpresión = mismos datos."""
    c = _Lienzo()
    f_c = _fuente(16, negrita=True)
    f_m = _fuente(18, negrita=True)
    f_lot = _fuente(18, negrita=True)
    f_tot = _fuente(24, negrita=True)
    _cabecera(c, str(datos.get("banca") or "BANCA"), "PAGO DE PREMIOS")
    if datos.get("es_prueba"):
        c.texto("PRUEBA — NO OFICIAL", f_c, centrado=True)
    if datos.get("reimpresion"):
        c.texto("COPIA — REIMPRESIÓN", f_c, centrado=True)
    if datos.get("fecha_hora"):
        c.texto(str(datos["fecha_hora"]), f_c, centrado=True)
    c.sep()
    c.texto(f"Ticket: {datos.get('ticket_id', '')}", f_c)
    if datos.get("serial"):
        c.texto(f"S/N: {datos['serial']}", f_c)
    if datos.get("cajero"):
        c.texto(f"Cajero: {datos['cajero']}", f_c)
    if datos.get("operacion_id"):
        c.texto(f"Operación: {datos['operacion_id']}", f_c)
    c.sep()

    # Agrupar jugadas ganadoras pagadas por lotería (solo las de esta operación).
    por_lot: dict[str, list[dict]] = {}
    orden: list[str] = []
    for j in datos.get("jugadas") or []:
        lots = [str(x).strip() for x in (j.get("loterias") or []) if str(x).strip()]
        clave = " · ".join(lots) if lots else "LOTERÍA"
        if clave not in por_lot:
            por_lot[clave] = []
            orden.append(clave)
        por_lot[clave].append(j)

    for clave in orden:
        c.texto(clave, f_lot, centrado=True, extra=2)
        for j in por_lot[clave]:
            tipo = str(j.get("tipo") or "").upper()
            nums = str(j.get("numeros") or "")
            etiqueta = f"{tipo}  {nums}".strip() if tipo else nums
            c.fila(etiqueta, _rd(j.get("premio")), f_c, f_m)
        c.sep()

    if datos.get("parcial"):
        c.texto(
            str(datos.get("nota_parcial") or "PAGO PARCIAL"),
            f_c,
            centrado=True,
            envolver=True,
        )
        c.sep()

    c.texto("TOTAL PAGADO", f_m, centrado=True, extra=2)
    c.texto(_rd(datos.get("total")), f_tot, centrado=True, extra=4)
    c.texto("ESTADO: PAGADO", f_c, centrado=True)
    c.texto("GRACIAS POR SU VISITA", f_c, centrado=True)
    return c.png()


def lab_preview_png(clave: str) -> bytes:
    """PNG ficticios de laboratorio (mismos diseños aprobados). No toca BD."""
    clave = (clave or "").strip().lower()
    if clave == "ticket":
        from .ticket_imagen import diseno_por_defecto, render_ticket_png, suma_montos_jugadas

        jugadas = [
            {"tipo": "QN", "numeros": "05", "monto": "50.00", "loterias": ["Real Tarde"]},
            {"tipo": "QN", "numeros": "08", "monto": "50.00", "loterias": ["Real Tarde"]},
            {"tipo": "PL", "numeros": "05-50", "monto": "25.00", "loterias": ["Real Tarde"]},
            {"tipo": "SP", "numeros": "26-58", "monto": "5.00", "loterias": ["Real Tarde", "La Primera 12"]},
            {"tipo": "TR", "numeros": "12-25-38", "monto": "50.00", "loterias": ["Real Tarde"]},
        ]
        total = suma_montos_jugadas(jugadas)
        return render_ticket_png(
            {
                "id": 900001,
                "serial": "000000900001",
                "qr": "LOT:900001:000000900001",
                "banca": "BANCA CASTILLO",
                "banca_codigo": "1301",
                "fecha_hora": "2026-11-18 20:30:00",
                "total": f"{total:.2f}",
                "jugadas": jugadas,
            },
            diseno_por_defecto(),
            tr_habilitado=True,
        )
    if clave == "resumen":
        return render_resumen_png({
            "banca": "BANCA CASTILLO",
            "sucursal": "BANCA CASTILLO",
            "cajero": "María Pérez",
            "desde": "18-11-2026",
            "hasta": "18-11-2026",
            "impreso": "18-11-2026 08:45 PM",
            "real": {
                "ventas": "1250.00",
                "anulados_monto": "50.00",
                "premios_pagados": "400.00",
                "premios_pendientes": "100.00",
                "pagado_en_otra": "0.00",
                "neto": "850.00",
                "quedo": "850.00",
            },
        })
    if clave == "entrega":
        return render_entrega_png({
            "banca": "BANCA CASTILLO",
            "sucursal": "BANCA CASTILLO",
            "cajera": "María Pérez",
            "recibida_por_nombre": "Admin Castillo",
            "fecha_hora": "18-11-2026 08:50 PM",
            "numero": 42,
            "id": 42,
            "operacion_id": "ENT-LAB-9001",
            "monto": "500.00",
            "saldo_anterior": "850.00",
            "saldo_restante": "350.00",
            "estado": "CONFIRMADA",
            "recepcion": "RECIBIDA",
        })
    if clave == "pago":
        return render_pago_png({
            "banca": "BANCA CASTILLO",
            "ticket_id": 900010,
            "serial": "000000900010",
            "cajero": "María Pérez",
            "operacion_id": "PAGO-LAB-1001",
            "fecha_hora": "18-11-2026 09:05 PM",
            "jugadas": [
                {"tipo": "QN", "numeros": "25", "premio": "300.00", "loterias": ["King Lottery 7:30 PM"]},
                {"tipo": "PL", "numeros": "12-34", "premio": "500.00", "loterias": ["King Lottery 7:30 PM"]},
            ],
            "total": "800.00",
        })
    if clave == "pago_parcial":
        return render_pago_png({
            "banca": "BANCA CASTILLO",
            "ticket_id": 900020,
            "serial": "000000900020",
            "cajero": "María Pérez",
            "operacion_id": "PAGO-LAB-PARCIAL-1",
            "fecha_hora": "18-11-2026 09:10 PM",
            "jugadas": [
                {"tipo": "QN", "numeros": "07", "premio": "200.00", "loterias": ["Florida 10:45 PM"]},
                {"tipo": "QN", "numeros": "15", "premio": "200.00", "loterias": ["La Anguila 8:00 PM"]},
                {
                    "tipo": "SP",
                    "numeros": "07-15",
                    "premio": "150.00",
                    "loterias": ["Florida 10:45 PM", "La Anguila 8:00 PM"],
                },
            ],
            "total": "550.00",
            "parcial": True,
            "nota_parcial": "PAGO PARCIAL — QUEDAN SORTEOS PENDIENTES",
        })
    if clave == "pago_reimpresion":
        return render_pago_png({
            "banca": "BANCA CASTILLO",
            "ticket_id": 900010,
            "serial": "000000900010",
            "cajero": "María Pérez",
            "operacion_id": "PAGO-LAB-1001",
            "fecha_hora": "18-11-2026 09:05 PM",
            "jugadas": [
                {"tipo": "QN", "numeros": "25", "premio": "300.00", "loterias": ["King Lottery 7:30 PM"]},
                {"tipo": "PL", "numeros": "12-34", "premio": "500.00", "loterias": ["King Lottery 7:30 PM"]},
            ],
            "total": "800.00",
            "reimpresion": True,
        })
    raise ValueError(f"Clave de recibo LAB desconocida: {clave}")


def datos_pago_desde_ticket(
    ticket: dict[str, Any],
    jugadas: list[dict[str, Any]],
    *,
    operacion_id: str | None,
    cajero: str,
    total,
    fecha_hora: str,
    parcial: bool = False,
    nota_parcial: str = "",
    reimpresion: bool = False,
) -> dict[str, Any]:
    """Estructura neutra para PNG/texto de pago (sin cobro)."""
    return {
        "banca": ticket.get("banca") or "",
        "ticket_id": ticket.get("id"),
        "serial": ticket.get("serial") or "",
        "cajero": cajero or "",
        "operacion_id": operacion_id or "",
        "fecha_hora": fecha_hora or "",
        "jugadas": jugadas,
        "total": str(_D(total)),
        "parcial": parcial,
        "nota_parcial": nota_parcial,
        "es_prueba": bool(ticket.get("es_prueba") or ticket.get("no_oficial")),
        "reimpresion": reimpresion,
    }
