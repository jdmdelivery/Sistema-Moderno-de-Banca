"""Render de tickets térmicos 384 px controlado por el servidor (Opción B).

No modifica jugadas, premios ni el payload del QR (LOT:id:serial).
Solo dibuja una imagen a partir del ticket y de un diseño configurable.
"""
from __future__ import annotations

import io
import json
from decimal import Decimal
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ANCHO_DEFAULT = 384
MARGEN_X = 8

# Etiquetas de sección (solo si hay jugadas de ese tipo).
_SECCION = {
    "QN": "QN",
    "PL": "PL",
    "SP": "SP",
    "TR": "TR",
}
_ORDEN_TIPOS = ("QN", "PL", "SP", "TR")


def diseno_por_defecto() -> dict:
    return {
        "ancho_px": ANCHO_DEFAULT,
        "encabezado": {
            "mostrar_nombre_banca": True,
            # Código de banca (ej. 1301): no se imprime; sigue en datos internos.
            "mostrar_codigo": False,
            "tamano_nombre": 28,
            "tamano_nombre_min": 16,
            "centrado": True,
        },
        "qr": {
            "posicion": "superior",  # superior | inferior | oculto
            # Proporción cercana a la foto de referencia (~1/3 del ancho útil).
            "tamano_px": 108,
        },
        "tipografia": {
            "cuerpo": 16,
            # FECHA, código banca, TICKET y S/N (negrita; sin cortar el serial).
            "meta": 23,
            # Números y montos (mismo tamaño, negrita).
            "jugada": 26,
            # Etiqueta MONTO TOTAL (sin cambio de estilo de etiqueta).
            "total": 24,
            # Importe del total (~+10 % sobre 24).
            "total_importe": 26,
            # QN / PL / SP / TR
            "titulo_seccion": 26,
            # Nombre de lotería (centrado, negrita; mismo tamaño que QN/PL/SP/TR).
            "loteria": 26,
            # Pareja Super Palé (SP-> lot1 - lot2); distinta del título -------SP-------.
            "super_pale": 20,
        },
        "espaciado": {
            "linea": 2,
            "tras_nombre": 3,
            "tras_qr": 4,
            "tras_seccion": 2,
            "entre_jugadas": 2,
            "tras_loteria": 3,
            "antes_loteria": 3,
        },
        "secciones": {"qn": True, "pl": True, "sp": True, "tr": True},
        "moneda_prefijo": "$ ",
        "mensaje_inferior": "",
        "mostrar_linea_sistema": False,
        "etiqueta_ticket": "TICKET:",
        "etiqueta_sn": "S/N:",
        "etiqueta_fecha": "FECHA:",
        "etiqueta_total": "MONTO TOTAL:",
        "titulo_loterias": "LOTERIAS",
    }


def fusionar_diseno(guardado: dict | None) -> dict:
    base = diseno_por_defecto()
    if not guardado:
        return base
    out = json.loads(json.dumps(base))
    for clave, valor in guardado.items():
        if isinstance(valor, dict) and isinstance(out.get(clave), dict):
            out[clave].update(valor)
        else:
            out[clave] = valor
    # Diseño final: nunca imprimir el código de banca bajo el nombre.
    enc = out.setdefault("encabezado", {})
    if isinstance(enc, dict):
        enc["mostrar_codigo"] = False
    return out


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


def _decimal(valor) -> Decimal:
    try:
        return Decimal(str(valor))
    except Exception:
        return Decimal("0")


def _dinero(valor, prefijo: str) -> str:
    """Columna derecha estilo foto: `$ 50.00` / `$100.00`."""
    n = _decimal(valor)
    entero = f"{n:,.2f}"
    if n < 100 and prefijo.endswith(" "):
        return f"{prefijo}{entero}"
    if prefijo.endswith(" "):
        return f"{prefijo.rstrip()}{entero}"
    return f"{prefijo}{entero}"


def _monto_columna_qn(valor) -> str:
    """Primera columna QN: el mismo monto de la jugada (sin inventar).

    En la foto aparece como entero cuando no hay centavos (50, 100).
    """
    n = _decimal(valor)
    if n == n.to_integral_value():
        return str(int(n))
    return f"{n:.2f}"


def suma_montos_jugadas(jugadas: list[dict] | None) -> Decimal:
    total = Decimal("0")
    for j in jugadas or []:
        total += _decimal(j.get("monto") or 0)
    return total


def _fmt_fecha(crudo: str | None, diseno: dict) -> str:
    if not crudo:
        return ""
    s = str(crudo).strip().replace("T", " ")
    if "." in s:
        s = s.split(".", 1)[0]
    try:
        from datetime import datetime

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(s[:19], fmt)
                return dt.strftime("%d-%m-%Y %I:%M:%S %p")
            except ValueError:
                continue
    except Exception:
        pass
    return s


def _qr_bitmap(payload: str, tamano: int) -> Image.Image:
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=3,
        border=1,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("L")
    return img.resize((tamano, tamano), Image.Resampling.NEAREST)


def _clave_loteria(j: dict) -> str:
    """Clave estable por sorteo(s) de la jugada (no mezcla distintos sorteos)."""
    lots = [str(x).strip() for x in (j.get("loterias") or []) if str(x).strip()]
    if not lots:
        return ""
    return " - ".join(lots)


def _agrupar_jugadas(jugadas: list[dict], diseno: dict, tr_habilitado: bool) -> dict[str, list[dict]]:
    secs = diseno.get("secciones") or {}
    flags = {
        "QN": bool(secs.get("qn", True)),
        "PL": bool(secs.get("pl", True)),
        "SP": bool(secs.get("sp", True)),
        "TR": bool(secs.get("tr", True)) and tr_habilitado,
    }
    grupos: dict[str, list[dict]] = {k: [] for k in _ORDEN_TIPOS}
    for j in jugadas or []:
        tipo = str(j.get("tipo") or j.get("tipo_nombre") or "").upper().strip()
        if tipo not in flags or not flags[tipo]:
            continue
        grupos[tipo].append(j)
    return {k: v for k, v in grupos.items() if v}


def _subgrupos_por_loteria(filas: list[dict]) -> list[tuple[str, list[dict]]]:
    """Mantiene el orden de aparición; nunca mezcla claves de lotería distintas."""
    orden: list[str] = []
    buckets: dict[str, list[dict]] = {}
    for j in filas:
        clave = _clave_loteria(j)
        if clave not in buckets:
            buckets[clave] = []
            orden.append(clave)
        buckets[clave].append(j)
    return [(k, buckets[k]) for k in orden]


def _medir(draw: ImageDraw.ImageDraw, texto: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), texto, font=font)
    return box[2] - box[0], box[3] - box[1]


def _alto_fuente(font) -> int:
    try:
        ascent, descent = font.getmetrics()
        return int(ascent + descent)
    except Exception:
        return int(getattr(font, "size", 16) + 4)


def _centrar_x(ancho: int, w: int) -> int:
    return max(0, (ancho - w) // 2)


def _fuente_nombre_ajustada(draw: ImageDraw.ImageDraw, texto: str, util: int, enc: dict):
    """Reduce el tamaño del encabezado hasta que quepa en el ancho útil."""
    max_t = int(enc.get("tamano_nombre") or 28)
    min_t = int(enc.get("tamano_nombre_min") or 16)
    for tam in range(max_t, min_t - 1, -1):
        font = _fuente(tam, negrita=True)
        if _medir(draw, texto, font)[0] <= util - 4:
            return font
    return _fuente(min_t, negrita=True)


def _recortar_si_hace_falta(draw: ImageDraw.ImageDraw, texto: str, font, util: int) -> str:
    """Último recurso: elide con … si aún no cabe (evita corte duro a 384)."""
    if _medir(draw, texto, font)[0] <= util:
        return texto
    if not texto:
        return texto
    recorte = texto
    while len(recorte) > 1 and _medir(draw, recorte + "…", font)[0] > util:
        recorte = recorte[:-1]
    return recorte + "…"


def render_ticket_png(
    ticket: dict[str, Any],
    diseno: dict | None = None,
    *,
    tr_habilitado: bool = True,
) -> bytes:
    """Devuelve PNG monocromo/gris del ticket a ancho configurable (default 384)."""
    cfg = fusionar_diseno(diseno)
    ancho = int(cfg.get("ancho_px") or ANCHO_DEFAULT)
    util = ancho - MARGEN_X * 2
    tip = cfg.get("tipografia") or {}
    esp = cfg.get("espaciado") or {}
    gap = int(esp.get("linea") or 2)
    gap_jugada = int(esp.get("entre_jugadas") or 2)
    gap_sec = int(esp.get("tras_seccion") or 2)
    gap_qr = int(esp.get("tras_qr") or 4)
    gap_antes_lot = int(esp.get("antes_loteria") or 3)
    gap_tras_lot = int(esp.get("tras_loteria") or 3)

    f_cuerpo = _fuente(int(tip.get("cuerpo") or 16))
    f_meta = _fuente(int(tip.get("meta") or 23), negrita=True)
    f_jugada = _fuente(int(tip.get("jugada") or 22), negrita=True)
    f_total = _fuente(int(tip.get("total") or 24), negrita=True)
    f_total_importe = _fuente(int(tip.get("total_importe") or tip.get("total") or 26), negrita=True)
    f_titulo = _fuente(int(tip.get("titulo_seccion") or 15), negrita=True)
    f_super_pale = _fuente(int(tip.get("super_pale") or 20), negrita=True)
    tam_loteria = int(tip.get("loteria") or 21)
    prefijo = str(cfg.get("moneda_prefijo") or "$ ")

    alto_tmp = 2400
    img = Image.new("L", (ancho, alto_tmp), 255)
    draw = ImageDraw.Draw(img)
    y = 6

    def linea_texto(texto: str, font, *, centrado: bool = False, relleno: int = 0, extra: int | None = None):
        nonlocal y
        texto = _recortar_si_hace_falta(draw, str(texto), font, util)
        w, _ = _medir(draw, texto, font)
        h = max(_medir(draw, texto, font)[1], _alto_fuente(font))
        x = _centrar_x(ancho, w) if centrado else MARGEN_X
        draw.text((x, y), texto, fill=relleno, font=font)
        y += h + (gap if extra is None else extra)

    def linea_loteria(texto: str, *, extra: int | None = None):
        """Nombre de lotería centrado, negrita 26 px; hasta 2 líneas sin cortar."""
        nonlocal y
        texto = str(texto or "").strip()
        if not texto:
            return
        y += gap_antes_lot
        font = _fuente(tam_loteria, negrita=True)
        lineas: list[str]
        if _medir(draw, texto, font)[0] <= util:
            lineas = [texto]
        else:
            # Partir por palabras en 2 líneas centradas (sin elidir nombre/horario).
            partes = texto.split()
            if len(partes) < 2:
                lineas = [texto]
            else:
                mejor = None
                for i in range(1, len(partes)):
                    l1 = " ".join(partes[:i])
                    l2 = " ".join(partes[i:])
                    if _medir(draw, l1, font)[0] <= util and _medir(draw, l2, font)[0] <= util:
                        # Preferir el corte más equilibrado en ancho.
                        desbalance = abs(_medir(draw, l1, font)[0] - _medir(draw, l2, font)[0])
                        if mejor is None or desbalance < mejor[0]:
                            mejor = (desbalance, [l1, l2])
                lineas = mejor[1] if mejor else [texto]
        for i, ln in enumerate(lineas):
            w, _ = _medir(draw, ln, font)
            h = max(_medir(draw, ln, font)[1], _alto_fuente(font))
            draw.text((_centrar_x(ancho, w), y), ln, fill=0, font=font)
            if i < len(lineas) - 1:
                y += h + 1
            else:
                y += h + (gap_tras_lot if extra is None else extra)

    def linea_meta(texto: str, *, centrado: bool = False, extra: int | None = None):
        """FECHA / código / TICKET / S/N: negrita; no elide (el S/N debe verse completo)."""
        nonlocal y
        texto = str(texto or "")
        font = f_meta
        # Si por extremo no cupiera, bajar 1–2 px antes de cortar; el serial nunca se elide.
        tam = int(tip.get("meta") or 23)
        while tam > 18 and _medir(draw, texto, font)[0] > util:
            tam -= 1
            font = _fuente(tam, negrita=True)
        w, _ = _medir(draw, texto, font)
        h = max(_medir(draw, texto, font)[1], _alto_fuente(font))
        x = _centrar_x(ancho, w) if centrado else MARGEN_X
        draw.text((x, y), texto, fill=0, font=font)
        y += h + (gap if extra is None else extra)

    def linea_super_pale(lots: list[str], *, extra: int | None = None):
        """Pareja SP-> lot1 - lot2 en negrita; 2 líneas si no cabe; sin cortar nombres."""
        nonlocal y
        limpios = [str(x).strip() for x in (lots or []) if str(x).strip()]
        if len(limpios) < 2:
            return
        lot1, lot2 = limpios[0], limpios[1]
        una = f"SP-> {lot1} - {lot2}"
        lineas: list[str]
        if _medir(draw, una, f_super_pale)[0] <= util:
            lineas = [una]
        else:
            # Dos líneas organizadas: anuncio + segunda lotería completa.
            l1 = f"SP-> {lot1}"
            l2 = f"- {lot2}"
            # Si aún no cabe el nombre, bajar px mínimo (no elidir horarios/nombres).
            font = f_super_pale
            tam = int(tip.get("super_pale") or 20)
            while tam > 16 and (
                _medir(draw, l1, font)[0] > util or _medir(draw, l2, font)[0] > util
            ):
                tam -= 1
                font = _fuente(tam, negrita=True)
            lineas = [l1, l2]
            for i, ln in enumerate(lineas):
                w, _ = _medir(draw, ln, font)
                h = max(_medir(draw, ln, font)[1], _alto_fuente(font))
                draw.text((MARGEN_X, y), ln, fill=0, font=font)
                y += h + (1 if i == 0 else (gap_sec if extra is None else extra))
            return
        for i, ln in enumerate(lineas):
            w, _ = _medir(draw, ln, f_super_pale)
            h = max(_medir(draw, ln, f_super_pale)[1], _alto_fuente(f_super_pale))
            draw.text((MARGEN_X, y), ln, fill=0, font=f_super_pale)
            y += h + (gap_sec if extra is None else extra)

    def separador(titulo: str | None = None):
        nonlocal y
        if titulo:
            guion = "-"
            etiqueta = f"{guion * 7}{titulo}{guion * 7}"
            while _medir(draw, etiqueta, f_titulo)[0] > util and len(guion) > 1:
                guion = guion[:-1]
                etiqueta = f"{guion * 7}{titulo}{guion * 7}"
            if _medir(draw, etiqueta, f_titulo)[0] > util:
                etiqueta = titulo
            linea_texto(etiqueta, f_titulo, centrado=True, extra=gap_sec)
        else:
            # Línea sólida compacta (estilo foto).
            y += 1
            draw.line((MARGEN_X, y, ancho - MARGEN_X, y), fill=0, width=1)
            y += 1 + gap

    # Columnas QN estilo foto: monto | número | $ monto
    col_monto_w = 56
    col_num_x = MARGEN_X + col_monto_w + 8

    def fila_qn(j: dict):
        """Quiniela compacta: `50    05           $ 50.00` (mismo monto real)."""
        nonlocal y
        bruto = j.get("monto") or "0"
        izq = _monto_columna_qn(bruto)
        nums = str(j.get("numeros") or "")
        der = _dinero(bruto, prefijo)
        izq = _recortar_si_hace_falta(draw, izq, f_jugada, col_monto_w)
        nums = _recortar_si_hace_falta(draw, nums, f_jugada, util // 3)
        der = _recortar_si_hace_falta(draw, der, f_jugada, util // 3)
        h = max(
            _medir(draw, izq, f_jugada)[1],
            _medir(draw, nums, f_jugada)[1],
            _medir(draw, der, f_jugada)[1],
            _alto_fuente(f_jugada),
        )
        der_w, _ = _medir(draw, der, f_jugada)
        draw.text((MARGEN_X, y), izq, fill=0, font=f_jugada)
        draw.text((col_num_x, y), nums, fill=0, font=f_jugada)
        draw.text((ancho - MARGEN_X - der_w, y), der, fill=0, font=f_jugada)
        y += h + gap_jugada

    def fila_numero_monto(nums: str, monto_valor):
        """PL / SP / TR: números a la izquierda, monto a la derecha."""
        nonlocal y
        nums = str(nums or "")
        der = _dinero(monto_valor, prefijo)
        nums = _recortar_si_hace_falta(draw, nums, f_jugada, util // 2)
        der = _recortar_si_hace_falta(draw, der, f_jugada, util // 2)
        h = max(
            _medir(draw, nums, f_jugada)[1],
            _medir(draw, der, f_jugada)[1],
            _alto_fuente(f_jugada),
        )
        der_w, _ = _medir(draw, der, f_jugada)
        draw.text((MARGEN_X, y), nums, fill=0, font=f_jugada)
        draw.text((ancho - MARGEN_X - der_w, y), der, fill=0, font=f_jugada)
        y += h + gap_jugada

    gap_nombre = int(esp.get("tras_nombre") or 3)
    enc = cfg.get("encabezado") or {}
    if enc.get("mostrar_nombre_banca", True):
        # En papel no se imprime el sufijo de semilla "(PRUEBA)"; el nombre
        # en BD/admin se conserva intacto.
        banca = str(ticket.get("banca") or "BANCA").strip()
        if banca.upper().endswith("(PRUEBA)"):
            banca = banca[: banca.upper().rfind("(PRUEBA)")].rstrip(" -")
        banca = (banca or "BANCA").upper()
        f_nombre = _fuente_nombre_ajustada(draw, banca, util, enc)
        linea_texto(banca, f_nombre, centrado=bool(enc.get("centrado", True)), extra=gap_nombre)
    if enc.get("mostrar_codigo", False):
        codigo = str(ticket.get("banca_codigo") or "").strip()
        if codigo:
            linea_meta(codigo, centrado=True, extra=gap)
    if cfg.get("mostrar_linea_sistema"):
        linea_texto("Sistema de Banca Moderna", f_cuerpo, centrado=True)

    separador()
    fecha = _fmt_fecha(ticket.get("fecha_hora"), cfg)
    if fecha:
        linea_meta(f"{cfg.get('etiqueta_fecha', 'FECHA:')} {fecha}", extra=gap)

    qr_cfg = cfg.get("qr") or {}
    qr_payload = str(ticket.get("qr") or f"LOT:{ticket.get('id')}:{ticket.get('serial')}")
    qr_pos = str(qr_cfg.get("posicion") or "superior")
    qr_tam = int(qr_cfg.get("tamano_px") or 108)
    qr_tam = max(80, min(qr_tam, util))
    qr_img = None
    if qr_pos != "oculto" and qr_payload:
        qr_img = _qr_bitmap(qr_payload, qr_tam)

    if qr_pos == "superior" and qr_img is not None:
        x = _centrar_x(ancho, qr_img.width)
        img.paste(qr_img, (x, y))
        y += qr_img.height + gap_qr

    linea_meta(f"{cfg.get('etiqueta_ticket', 'TICKET:')} {ticket.get('id', '')}", extra=1)
    serial = str(ticket.get("serial") or "")
    if serial:
        # Conservar ceros iniciales; no pasar por elide de cuerpo.
        linea_meta(f"{cfg.get('etiqueta_sn', 'S/N:')} {serial}", extra=gap)

    grupos = _agrupar_jugadas(ticket.get("jugadas") or [], cfg, tr_habilitado=tr_habilitado)
    if grupos:
        separador(str(cfg.get("titulo_loterias") or "LOTERIAS"))

        # Super Palé: anunciar pareja de loterías (distinto del título -------SP-------).
        sps = grupos.get("SP") or []
        for j in sps:
            lots = [str(x).strip() for x in (j.get("loterias") or []) if str(x).strip()]
            if len(lots) >= 2:
                linea_super_pale(lots, extra=gap_sec)

        # Agrupar por sorteo sin mezclar. Orden foto: QN → PL → SP → TR.
        loterias_orden: list[str] = []
        por_loteria: dict[str, dict[str, list[dict]]] = {}
        for tipo in ("QN", "PL", "TR"):
            for j in grupos.get(tipo) or []:
                clave = _clave_loteria(j)
                if clave not in por_loteria:
                    por_loteria[clave] = {t: [] for t in ("QN", "PL", "TR")}
                    loterias_orden.append(clave)
                por_loteria[clave][tipo].append(j)

        def _emitir_tipos(clave_lot: str, tipos: tuple[str, ...], *, forzar_nombre: bool):
            tipos_lot = por_loteria.get(clave_lot) or {}
            filas_tipos = [(t, tipos_lot.get(t) or []) for t in tipos if tipos_lot.get(t)]
            if not filas_tipos:
                return False
            if forzar_nombre and clave_lot:
                linea_loteria(clave_lot, extra=1)
            for tipo, filas in filas_tipos:
                separador(_SECCION[tipo])
                for j in filas:
                    if tipo == "QN":
                        fila_qn(j)
                    else:
                        fila_numero_monto(j.get("numeros") or "", j.get("monto") or "0")
            return True

        # 1) Por sorteo: QN y PL (nombre del sorteo una sola vez).
        loterias_ya_nombradas: set[str] = set()
        for clave_lot in loterias_orden:
            if _emitir_tipos(clave_lot, ("QN", "PL"), forzar_nombre=True):
                loterias_ya_nombradas.add(clave_lot)

        # 2) SP (dos loterías ya anunciadas con SP->).
        if sps:
            separador(_SECCION["SP"])
            for j in sps:
                fila_numero_monto(j.get("numeros") or "", j.get("monto") or "0")

        # 3) TR por sorteo (sin repetir el nombre si ya salió arriba).
        for clave_lot in loterias_orden:
            _emitir_tipos(
                clave_lot,
                ("TR",),
                forzar_nombre=clave_lot not in loterias_ya_nombradas,
            )

    separador()
    total = _dinero(ticket.get("total") or "0", prefijo)
    etiqueta = str(cfg.get("etiqueta_total") or "MONTO TOTAL:")
    # Etiqueta al tamaño actual; importe ~+10 % y más destacado.
    esp_et = " "
    w_et = _medir(draw, etiqueta + esp_et, f_total)[0]
    w_imp = _medir(draw, total, f_total_importe)[0]
    h_tot = max(
        _medir(draw, etiqueta, f_total)[1],
        _medir(draw, total, f_total_importe)[1],
        _alto_fuente(f_total),
        _alto_fuente(f_total_importe),
    )
    x_tot = _centrar_x(ancho, w_et + w_imp)
    draw.text((x_tot, y), etiqueta + esp_et, fill=0, font=f_total)
    draw.text((x_tot + w_et, y), total, fill=0, font=f_total_importe)
    y += h_tot + gap

    msg = str(cfg.get("mensaje_inferior") or "").strip()
    if msg:
        linea_texto(msg, f_cuerpo, centrado=True)

    if ticket.get("reimpresion") or ticket.get("leyenda"):
        linea_texto(str(ticket.get("leyenda") or "COPIA — REIMPRESIÓN"), f_cuerpo, centrado=True)

    # es_prueba se conserva en BD/payload; no se imprime marca en el ticket.

    if qr_pos == "inferior" and qr_img is not None:
        x = _centrar_x(ancho, qr_img.width)
        img.paste(qr_img, (x, y))
        y += qr_img.height + gap_qr

    y += 8
    recorte = img.crop((0, 0, ancho, min(y, alto_tmp)))
    bw = recorte.point(lambda p: 0 if p < 180 else 255, mode="1")
    buf = io.BytesIO()
    bw.convert("L").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def preview_png(diseno: dict | None = None, *, tr_habilitado: bool = True) -> bytes:
    """Muestra estilo foto. El total = suma real de las jugadas (no un valor inventado)."""
    jugadas = [
        # QUINIELAS compactas (monto | número | $ monto) — montos reales.
        {"tipo": "QN", "numeros": "05", "monto": "50.00", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "08", "monto": "50.00", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "11", "monto": "50.00", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "50", "monto": "50.00", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "55", "monto": "100.00", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "80", "monto": "50.00", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "88", "monto": "100.00", "loterias": ["Real Tarde"]},
        # PALÉS
        {"tipo": "PL", "numeros": "05-50", "monto": "25.00", "loterias": ["Real Tarde"]},
        {"tipo": "PL", "numeros": "08-80", "monto": "25.00", "loterias": ["Real Tarde"]},
        {"tipo": "PL", "numeros": "11-55", "monto": "25.00", "loterias": ["Real Tarde"]},
        {"tipo": "PL", "numeros": "55-88", "monto": "25.00", "loterias": ["Real Tarde"]},
        # SUPER PALÉ + TRIPLETA
        {"tipo": "SP", "numeros": "26-58", "monto": "5.00", "loterias": ["Real Tarde", "La Primera 12"]},
        {"tipo": "TR", "numeros": "12-25-38", "monto": "50.00", "loterias": ["Real Tarde"]},
    ]
    total = suma_montos_jugadas(jugadas)  # 555.00 — coincide con las filas visibles
    muestra = {
        "id": 645478,
        "serial": "000000645478",
        "qr": "LOT:645478:000000645478",
        "banca": "BANCA CASTILLO",
        "banca_codigo": "1302",
        "fecha_hora": "2026-04-28 12:42:12",
        "total": f"{total:.2f}",
        "jugadas": jugadas,
    }
    return render_ticket_png(muestra, diseno, tr_habilitado=tr_habilitado)
