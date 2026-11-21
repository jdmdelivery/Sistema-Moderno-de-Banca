"""Informe de Resumen de caja: mismos montos en pantalla y papel, sin tocar la caja."""
import io
import os
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from apps.api.db import nueva_sesion
from apps.api.models import Ticket
from apps.api.recibos_imagen import render_resumen_png


def _usuario(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila["id"]
    raise AssertionError(usuario)


def _margenes_blancos(png: bytes):
    imagen = Image.open(io.BytesIO(png)).convert("L")
    assert imagen.size[0] == 384
    alto = imagen.size[1]
    assert imagen.crop((0, 0, 6, alto)).getextrema() == (255, 255)
    assert imagen.crop((378, 0, 384, alto)).getextrema() == (255, 255)
    return imagen


def test_dia_vacio_balance_negativo_mes_y_papel(entorno):
    b = entorno.banca(
        saldo=500000,
        codigo="RC01",
        nombre="BANCA CONTROL DE CAJA",
        usuario="caja1",
        clave="1234",
    )
    caja = _usuario(entorno, "caja1")
    alta = entorno.c.post(
        "/comisiones",
        json={"usuario_id": caja, "porcentaje": 15},
        headers=entorno.admin,
    )
    assert alta.status_code == 201, alta.text
    antes = entorno.saldo(b["sucursal"]["id"])
    vacio = entorno.c.get(
        "/terminal/reportes/dia?desde=2026-11-13&hasta=2026-11-13",
        headers=b["headers"],
    )
    assert vacio.status_code == 200, vacio.text
    cero = vacio.json()["informe"]["oficial"]
    assert cero["ventas"] == "0.00"
    assert cero["premios_pagados"] == "0.00"
    assert cero["comision"] == "0.00"
    assert cero["balance"] == "0.00"
    assert cero["recargas"] == "0.00"
    assert cero["total"] == "0.00"
    assert vacio.json()["informe"]["prueba"] is None
    assert "PRUEBA — NO OFICIAL" not in vacio.json()["texto"]

    sorteo = entorno.sorteo_id("La Primera 12")
    headers = b["headers"]
    entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 5000}])
    entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "26", "monto": 5000}])
    entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "27", "monto": 3865}])
    ganador = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "19", "monto": 10}])
    entorno.liquidar(sorteo, 19, 3, 45)
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ganador["id"], "serial": ganador["serial"]},
        headers=headers,
    )
    assert pago.status_code == 200, pago.text
    db = nueva_sesion()
    ticket = db.get(Ticket, ganador["id"])
    ticket.premio_total = Decimal("14170.00")
    pagadas = [j for j in ticket.jugadas if j.pagada]
    assert pagadas
    for jugada in pagadas:
        jugada.premio = Decimal("14170.00")
    db.commit()
    db.close()

    dia = entorno.c.get(
        "/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14",
        headers=headers,
    )
    assert dia.status_code == 200, dia.text
    datos = dia.json()
    oficial = datos["informe"]["oficial"]
    assert [fila["concepto"] for fila in oficial["lineas"]] == [
        "Ventas", "Premios", "Comisión", "Balance", "Recargas", "Total",
    ]
    assert [fila["monto"] for fila in oficial["lineas"]] == [
        "RD$13,875.00",
        "RD$14,170.00",
        "RD$2,081.25",
        "-RD$2,376.25",
        "RD$0.00",
        "-RD$2,376.25",
    ]
    assert oficial["lineas"][-1]["destacar"] is True
    assert oficial["balance"] == "-2376.25"
    assert oficial["total"] == oficial["balance"]
    # La caja operativa sigue siendo ventas − premios, sin restar la comisión.
    assert datos["real"]["neto"] == "-295.00"
    assert datos["real"]["quedo"] == "-295.00"
    assert datos["informe"]["codigo"] == "RC01"
    assert datos["informe"]["cajera"] == "Operador caja1"
    assert datos["informe"]["terminal"].startswith("APP-")
    assert datos["informe"]["periodo"] == "14/11/2026"
    assert "impreso" not in datos["informe"]
    assert "Impreso:" in datos["texto"]
    assert datos["texto"].count("PRUEBA — NO OFICIAL") == 0
    assert "desde=2026-11-14" in datos["impresion"]["url"]
    assert "hasta=2026-11-14" in datos["impresion"]["url"]
    assert entorno.saldo(b["sucursal"]["id"]) != antes

    papel = entorno.c.get(datos["impresion"]["url"], headers=headers)
    assert papel.status_code == 200, papel.text
    assert papel.content.startswith(b"\x89PNG")
    _margenes_blancos(papel.content)

    mes = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=11", headers=headers)
    assert mes.status_code == 200, mes.text
    mes_inf = mes.json()["informe"]["oficial"]
    assert mes.json()["informe"]["periodo"] == "01/11/2026 al 30/11/2026"
    assert mes_inf["ventas"] == "13875.00"
    assert mes_inf["premios_pagados"] == "14170.00"
    assert mes_inf["comision"] == "2081.25"
    assert mes_inf["balance"] == "-2376.25"
    assert mes_inf["total"] == "-2376.25"
    assert mes.json()["totales"]["quedo"] == "-295.00"
    papel_mes = entorno.c.get(mes.json()["impresion"]["url"], headers=headers)
    assert papel_mes.status_code == 200
    assert papel_mes.content.startswith(b"\x89PNG")

    destino = os.environ.get("RESUMEN_VISTA_DIR")
    if destino:
        carpeta = Path(destino)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "papel-ticket8-control.png").write_bytes(papel.content)
        _vista(datos, carpeta / "vista-resumen-control.png")


def test_el_papel_no_corta_nombre_largo_ni_monto_grande():
    nombre = "BANCA MODERNA DE EJEMPLO CON UN NOMBRE LARGO DE SUCURSAL"
    cajera = "Cajera con nombre compuesto muy largo para el papel"
    terminal = "SUNMI-V2-SERIAL-LARGO-1234567890"
    monto = "-RD$12,345,678.90"
    lineas = [
        {"concepto": "Ventas", "monto": "RD$98,765,432.10", "destacar": False},
        {"concepto": "Premios", "monto": monto, "destacar": False},
        {"concepto": "Comisión", "monto": "RD$1,234,567.89", "destacar": False},
        {"concepto": "Balance", "monto": monto, "destacar": False},
        {"concepto": "Recargas", "monto": "RD$0.00", "destacar": False},
        {"concepto": "Total", "monto": monto, "destacar": True},
    ]
    png = render_resumen_png({
        "impreso": "20-11-2026 09:15 PM",
        "informe": {
            "banca": nombre,
            "codigo": "RC-LARGO-01",
            "cajera": cajera,
            "terminal": terminal,
            "periodo": "01/11/2026 al 30/11/2026",
            "oficial": {"lineas": lineas},
            "prueba": None,
        },
    })
    _margenes_blancos(png)


def test_la_prueba_no_se_repite_en_el_papel():
    oficial = [
        {"concepto": "Ventas", "monto": "RD$10.00", "destacar": False},
        {"concepto": "Total", "monto": "RD$10.00", "destacar": True},
    ]
    prueba = [
        {"concepto": "Ventas", "monto": "RD$50.00", "destacar": False},
        {"concepto": "Total", "monto": "RD$50.00", "destacar": True},
    ]
    base = {
        "impreso": "14-11-2026 10:00 AM",
        "informe": {
            "banca": "BANCA",
            "codigo": "1",
            "cajera": "Ana",
            "terminal": "APP-1",
            "periodo": "14/11/2026",
            "oficial": {"lineas": oficial},
            "prueba": None,
        },
    }
    solo = render_resumen_png(base)
    con_prueba = render_resumen_png({
        **base,
        "informe": {**base["informe"], "prueba": {"lineas": prueba}},
    })
    alto_solo = _margenes_blancos(solo).size[1]
    alto_ambos = _margenes_blancos(con_prueba).size[1]
    assert alto_ambos > alto_solo
    assert alto_ambos < alto_solo * 2


def test_mil_noventa_y_tres_al_quince_porciento_sale_una_sola_vez(entorno):
    """RD$1,093.00 válidos al 15% = RD$163.95. El anulado no entra. La comisión no se resta dos veces."""
    b = entorno.banca(
        saldo=50000, codigo="RC15", nombre="BANCA CASTILLO", usuario="isaury15", clave="1234",
    )
    uid = _usuario(entorno, "isaury15")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin,
    )
    assert alta.status_code == 201, alta.text
    sorteo = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "01", "monto": 1093}])
    anulado = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "02", "monto": 100}])
    baja = entorno.c.post("/panel/tickets/anular", json={
        "id": anulado["id"], "serial": anulado["serial"], "motivo": "no entra en la comisión",
    }, headers=entorno.admin)
    assert baja.status_code == 200, baja.text

    dia = entorno.c.get(
        "/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14",
        headers=b["headers"],
    )
    assert dia.status_code == 200, dia.text
    datos = dia.json()
    oficial = datos["informe"]["oficial"]
    assert oficial["ventas"] == "1093.00"
    assert oficial["premios_pagados"] == "0.00"
    assert oficial["comision"] == "163.95"
    assert oficial["recargas"] == "0.00"
    assert oficial["balance"] == "929.05"
    assert oficial["total"] == "929.05"
    assert datos["real"]["neto"] == "1093.00"
    assert datos["real"]["quedo"] == "1093.00"
    assert datos["informe"]["cajera"] == "Operador isaury15"
    assert datos["informe"]["periodo"] == "14/11/2026"
    assert "Cajera: Operador isaury15" in datos["texto"]
    assert datos["informe"]["prueba"] is None
    assert "PRUEBA — NO OFICIAL" not in datos["texto"]
    papel = entorno.c.get(datos["impresion"]["url"], headers=b["headers"])
    assert papel.status_code == 200, papel.text
    assert papel.content.startswith(b"\x89PNG")
    _margenes_blancos(papel.content)

    mes = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=11", headers=b["headers"])
    assert mes.status_code == 200, mes.text
    mes_inf = mes.json()["informe"]
    assert mes_inf["periodo"] == "01/11/2026 al 30/11/2026"
    assert mes_inf["cajera"] == "Operador isaury15"
    assert mes_inf["oficial"]["ventas"] == "1093.00"
    assert mes_inf["oficial"]["comision"] == "163.95"
    assert mes_inf["oficial"]["balance"] == "929.05"
    assert "Cajera: Operador isaury15" in mes.json()["texto"]
    papel_mes = entorno.c.get(mes.json()["impresion"]["url"], headers=b["headers"])
    assert papel_mes.status_code == 200
    assert papel_mes.content.startswith(b"\x89PNG")

    destino = os.environ.get("RESUMEN_VISTA_DIR")
    if destino:
        carpeta = Path(destino)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "papel-caja-1093.png").write_bytes(papel.content)
        (carpeta / "papel-caja-mes.png").write_bytes(papel_mes.content)
        _vista(datos, carpeta / "pantalla-caja-1093.png")


def _vista(datos, ruta: Path):
    inf = datos["informe"]
    ancho, alto = 480, 860
    imagen = Image.new("RGB", (ancho, alto), (232, 238, 244))
    draw = ImageDraw.Draw(imagen)
    regular = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
    bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 20)
    titulo = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)

    def boton(y, texto):
        draw.rounded_rectangle((16, y, ancho - 16, y + 46), 8, fill=(21, 101, 192))
        box = draw.textbbox((0, 0), texto, font=bold)
        draw.text(((ancho - (box[2] - box[0])) / 2, y + 10), texto, fill="white", font=bold)

    boton(16, "ELEGIR FECHA")
    boton(70, "MES COMPLETO")
    draw.rectangle((16, 130, ancho - 16, alto - 70), fill="white")
    y = 146
    for linea, fuente in (
        (inf["banca"], titulo),
        ("RESUMEN DE CAJA", bold),
    ):
        box = draw.textbbox((0, 0), linea, font=fuente)
        draw.text(((ancho - (box[2] - box[0])) / 2, y), linea, fill="black", font=fuente)
        y += 32
    for linea in (
        f"Código: {inf['codigo']}",
        f"Cajera: {inf['cajera']}",
        f"Terminal: {inf['terminal']}",
        f"Período: {inf['periodo']}",
    ):
        draw.text((32, y), linea, fill="black", font=regular)
        y += 28
    y += 8
    box = draw.textbbox((0, 0), "RESUMEN FINAL", font=bold)
    draw.text(((ancho - (box[2] - box[0])) / 2, y), "RESUMEN FINAL", fill="black", font=bold)
    y += 36
    for fila in inf["oficial"]["lineas"]:
        fuente = titulo if fila["destacar"] else regular
        if fila["destacar"]:
            draw.rectangle((24, y - 4, ancho - 24, y + 32), fill=(227, 242, 253))
        draw.text((36, y), fila["concepto"], fill="black", font=fuente)
        monto = fila["monto"]
        caja = draw.textbbox((0, 0), monto, font=bold)
        draw.text((ancho - 36 - (caja[2] - caja[0]), y), monto, fill="black", font=bold)
        y += 36
    boton(alto - 60, "IMPRIMIR RESUMEN")
    imagen.save(ruta)
