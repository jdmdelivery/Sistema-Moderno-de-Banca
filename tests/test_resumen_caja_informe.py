"""Informe de Resumen de caja: mismos montos en pantalla y papel, sin tocar la caja."""
import io
import os
from datetime import date, datetime
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
        "Ventas",
        "Premios",
        "Comisión",
        "Balance",
        "Recargas",
        "Total",
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
    assert oficial["resultado_ventas"] == "-2376.25"
    assert oficial["balance"] == "-2376.25"
    assert oficial["total"] == oficial["balance"]
    assert oficial["premios_sorteos_periodo"] == "14170.00"
    assert oficial["premios_anteriores_pagados"] == "0.00"
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
    assert mes_inf["resultado_ventas"] == "-2376.25"
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


def _lineas(montos):
    conceptos = (
        "Ventas",
        "Premios",
        "Comisión",
        "Balance",
        "Recargas",
        "Total",
    )
    return [
        {
            "concepto": concepto,
            "monto": monto,
            "destacar": concepto == "Total",
        }
        for concepto, monto in zip(conceptos, montos)
    ]


def test_el_papel_imprime_el_bloque_de_abajo_sin_ceros_ni_rotulo():
    """Isaury, mes completo: el oficial está en cero y el período trae los importes."""
    from apps.api.recibos_imagen import seleccion_recibo
    from apps.api.servicios import _texto_resumen

    oficial = {
        "ventas": "0.00", "premios_pagados": "0.00", "comision": "0.00",
        "resultado_ventas": "0.00",
        "balance": "0.00", "recargas": "0.00", "total": "0.00",
        "lineas": _lineas([
            "RD$0.00", "RD$0.00", "RD$0.00", "RD$0.00", "RD$0.00", "RD$0.00",
        ]),
    }
    prueba = {
        "ventas": "28465.00", "premios_pagados": "17290.00", "comision": "4269.75",
        "resultado_ventas": "6905.25",
        "balance": "6905.25", "recargas": "0.00", "total": "6905.25",
        "lineas": _lineas([
            "RD$28,465.00", "RD$17,290.00", "RD$4,269.75",
            "RD$6,905.25", "RD$0.00", "RD$6,905.25",
        ]),
    }
    assert seleccion_recibo(oficial, prueba) is prueba
    assert prueba["lineas"][1]["concepto"] == "Premios"
    # Pantalla: un solo RESUMEN FINAL con el bloque activo (sin rótulo PRUEBA).
    datos = {
        "impreso": "21-11-2026 12:23 AM",
        "informe": {
            "banca": "BANCA CASTILLO",
            "codigo": "1301",
            "cajera": "Isaury",
            "terminal": "SUNMI",
            "periodo": "01/11/2026 al 30/11/2026",
            "oficial": seleccion_recibo(oficial, prueba),
            "prueba": None,
        },
    }
    assert datos["informe"]["oficial"]["ventas"] == "28465.00"
    texto = _texto_resumen(datos)
    assert texto.count("RESUMEN DE CAJA") == 1
    assert "RESUMEN FINAL" not in texto
    assert "PRUEBA" not in texto
    assert "Premios pagados" in texto
    assert texto.count("Ventas") == 1
    assert texto.count("Total") == 1
    assert "Balance" in texto
    assert "Cajera: Isaury" in texto
    assert "Período: 01/11/2026 al 30/11/2026" in texto
    assert "Impreso: 21-11-2026 12:23 AM" in texto
    assert "RD$28,465.00" in texto
    assert "RD$17,290.00" in texto
    assert "RD$4,269.75" in texto
    assert texto.count("RD$6,905.25") == 2
    png = render_resumen_png(datos)
    _margenes_blancos(png)
    destino = os.environ.get("RESUMEN_VISTA_DIR")
    if destino:
        carpeta = Path(destino)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "recibo-isaury-ejemplo-mes.png").write_bytes(png)


def test_modo_desarrollo_pone_la_bolsa_activa_en_resumen_final(entorno, monkeypatch):
    """Con MODO_DESARROLLO, las ventas es_prueba=True no dejan ceros en RESUMEN FINAL."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(
        saldo=100000, codigo="RCDEV", nombre="BANCA DEV RESUMEN", usuario="cajdev", clave="1234",
    )
    uid = _usuario(entorno, "cajdev")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin,
    )
    assert alta.status_code == 201, alta.text
    sorteo = entorno.sorteo_id("La Primera 12")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "44", "monto": 1000},
    ])
    assert ticket["es_prueba"] is True
    dia = entorno.c.get(
        "/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14",
        headers=b["headers"],
    )
    assert dia.status_code == 200, dia.text
    datos = dia.json()
    assert datos["real"]["ventas"] == "0.00"
    assert datos["prueba"]["ventas"] == "1000.00"
    oficial = datos["informe"]["oficial"]
    assert oficial["ventas"] == "1000.00"
    assert oficial["comision"] == "150.00"
    assert oficial["premios_pagados"] == "0.00"
    assert oficial["resultado_ventas"] == "850.00"
    assert oficial["balance"] == "850.00"
    assert oficial["recargas"] == "0.00"
    assert oficial["total"] == "850.00"
    assert [fila["concepto"] for fila in oficial["lineas"]] == [
        "Ventas",
        "Premios",
        "Comisión",
        "Balance",
        "Recargas",
        "Total",
    ]
    assert datos["informe"]["prueba"] is None
    assert "PRUEBA — NO OFICIAL" not in datos["texto"]
    assert "RD$1,000.00" in datos["texto"]
    papel = entorno.c.get(datos["impresion"]["url"], headers=b["headers"])
    assert papel.status_code == 200, papel.text
    assert papel.content.startswith(b"\x89PNG")
    mes = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=11", headers=b["headers"])
    assert mes.status_code == 200, mes.text
    assert mes.json()["informe"]["oficial"]["ventas"] == "1000.00"
    assert mes.json()["informe"]["prueba"] is None


def test_los_dos_grupos_con_movimiento_avisan_y_no_eligen():
    from apps.api.recibos_imagen import seleccion_recibo
    from apps.api.servicios import _texto_resumen

    oficial = {
        "lineas": _lineas([
            "RD$10.00", "RD$0.00", "RD$0.00", "RD$10.00", "RD$0.00", "RD$10.00",
        ]),
        "ventas": "10.00",
    }
    prueba = {
        "lineas": _lineas([
            "RD$50.00", "RD$0.00", "RD$0.00", "RD$50.00", "RD$0.00", "RD$50.00",
        ]),
        "ventas": "50.00",
    }
    assert seleccion_recibo(oficial, prueba) is None
    datos = {
        "impreso": "14-11-2026 10:00 AM",
        "informe": {
            "banca": "BANCA CASTILLO",
            "codigo": "1301",
            "cajera": "Ana",
            "terminal": "APP-1",
            "periodo": "14/11/2026",
            "oficial": oficial,
            "prueba": prueba,
        },
    }
    texto = _texto_resumen(datos)
    assert "NO SE IMPRIMIÓ EL TOTAL" in texto
    assert "RD$10.00" not in texto
    assert "RD$50.00" not in texto
    assert "Ventas" not in texto
    assert "PRUEBA — NO OFICIAL" not in texto
    png = render_resumen_png(datos)
    _margenes_blancos(png)
    destino = os.environ.get("RESUMEN_VISTA_DIR")
    if destino:
        carpeta = Path(destino)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "recibo-aviso-dos-grupos.png").write_bytes(png)


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
    assert oficial["resultado_ventas"] == "929.05"
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


def test_dos_cajeras_fecha_y_mes_usan_la_misma_plantilla(entorno):
    """ELEGIR FECHA y MES COMPLETO, cada cajera con sus datos de consulta."""
    castillo = entorno.banca(
        saldo=50000, codigo="1301", nombre="BANCA CASTILLO", usuario="isaury", clave="1234",
    )
    peguero = entorno.banca(
        saldo=50000, codigo="2200", nombre="BANCA PEGUERO", usuario="wanda", clave="1234",
    )
    for usuario, porcentaje in (("isaury", 15), ("wanda", 10)):
        alta = entorno.c.post("/comisiones", json={
            "usuario_id": _usuario(entorno, usuario), "porcentaje": porcentaje,
        }, headers=entorno.admin)
        assert alta.status_code == 201, alta.text
    sorteo = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(castillo["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "07", "monto": 200}])
    entorno.vender_ok(peguero["headers"], [{"tipo": "QN", "sorteos": [sorteo], "numeros": "08", "monto": 80}])

    def papel(headers, dia):
        ruta = (
            "/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14"
            if dia else "/terminal/reportes/mes?anio=2026&mes=11"
        )
        datos = entorno.c.get(ruta, headers=headers)
        assert datos.status_code == 200, datos.text
        cuerpo = datos.json()
        imagen = entorno.c.get(cuerpo["impresion"]["url"], headers=headers)
        assert imagen.status_code == 200, imagen.text
        assert imagen.content.startswith(b"\x89PNG")
        _margenes_blancos(imagen.content)
        return cuerpo, imagen.content

    esperados = (
        (castillo, "BANCA CASTILLO", "1301", "Operador isaury", "200.00", "30.00", "170.00"),
        (peguero, "BANCA PEGUERO", "2200", "Operador wanda", "80.00", "8.00", "72.00"),
    )
    destino = os.environ.get("RESUMEN_VISTA_DIR")
    carpeta = Path(destino) if destino else None
    if carpeta:
        carpeta.mkdir(parents=True, exist_ok=True)
    for banca, nombre, codigo, cajera, ventas, comision, total in esperados:
        for dia, marca in ((True, "fecha"), (False, "mes")):
            datos, png = papel(banca["headers"], dia)
            texto = datos["texto"]
            inf = datos["informe"]
            assert inf["banca"] == nombre
            assert inf["codigo"] == codigo
            assert inf["cajera"] == cajera
            assert inf["terminal"].startswith("APP-")
            assert texto.count("RESUMEN DE CAJA") == 1
            assert "RESUMEN FINAL" not in texto
            assert "PRUEBA" not in texto
            assert "Premios pagados" in texto
            assert texto.count("Ventas") == 1
            assert texto.count("Total") == 1
            assert "Balance" in texto
            assert f"Código: {codigo}" in texto
            assert f"Cajera: {cajera}" in texto
            assert f"Terminal: {inf['terminal']}" in texto
            assert "Impreso:" in texto
            periodo = "14/11/2026" if dia else "01/11/2026 al 30/11/2026"
            assert inf["periodo"] == periodo
            assert f"Período: {periodo}" in texto
            oficial = inf["oficial"]
            assert oficial["ventas"] == ventas
            assert oficial["premios_pagados"] == "0.00"
            assert oficial["comision"] == comision
            assert oficial["resultado_ventas"] == total
            assert oficial["balance"] == total
            assert oficial["recargas"] == "0.00"
            assert oficial["total"] == total
            assert oficial["lineas"][1]["concepto"] == "Premios"
            assert oficial["lineas"][2]["concepto"] == "Comisión"
            assert oficial["lineas"][-1]["concepto"] == "Total"
            assert not any(
                "anteriores" in str(fila.get("concepto") or "").lower()
                for fila in oficial["lineas"]
            )
            assert inf["prueba"] is None
            if carpeta:
                (carpeta / f"recibo-{cajera.split()[-1]}-{marca}.png").write_bytes(png)


def _fijar_premio_pagado(ticket_id, premio, fecha_sorteo=None, pagado_en=None):
    db = nueva_sesion()
    ticket = db.get(Ticket, ticket_id)
    assert ticket is not None
    if fecha_sorteo is not None:
        ticket.fecha = fecha_sorteo
    ticket.premio_total = Decimal(str(premio))
    pagadas = [j for j in ticket.jugadas if j.pagada]
    assert pagadas
    for jugada in pagadas:
        jugada.premio = Decimal(str(premio))
        if fecha_sorteo is not None:
            jugada.fecha = fecha_sorteo
        if pagado_en is not None:
            jugada.pagado_en = pagado_en
    if pagado_en is not None:
        ticket.pagado_en = pagado_en
    db.commit()
    db.close()


def test_isaury_premio_dia_anterior_no_resta_balance_ni_total(entorno):
    """Ventas 2985, comisión 447.75, premio 1870 del día anterior → Balance/Total 2537.25."""
    b = entorno.banca(
        saldo=200000,
        codigo="C23",
        nombre="BANCA CASTILLO",
        usuario="isaury23",
        clave="1234",
    )
    uid = _usuario(entorno, "isaury23")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin,
    )
    assert alta.status_code == 201, alta.text
    sorteo = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(
        b["headers"],
        [{"tipo": "QN", "sorteos": [sorteo], "numeros": "11", "monto": 2985}],
    )
    ganador = entorno.vender_ok(
        b["headers"],
        [{"tipo": "QN", "sorteos": [sorteo], "numeros": "19", "monto": 10}],
    )
    entorno.liquidar(sorteo, 19, 3, 45)
    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ganador["id"], "serial": ganador["serial"]},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    _fijar_premio_pagado(
        ganador["id"],
        "1870.00",
        fecha_sorteo=date(2026, 11, 13),
        pagado_en=datetime(2026, 11, 14, 12, 0, 0),
    )

    dia = entorno.c.get(
        "/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14",
        headers=b["headers"],
    )
    assert dia.status_code == 200, dia.text
    datos = dia.json()
    oficial = datos["informe"]["oficial"]
    assert oficial["ventas"] == "2985.00"
    assert datos["real"]["ventas"] == "2985.00"
    assert oficial["premios_pagados"] == "1870.00"
    assert oficial["premios_anteriores_pagados"] == "1870.00"
    assert oficial["premios_sorteos_periodo"] == "0.00"
    assert oficial["comision"] == "447.75"
    assert oficial["resultado_ventas"] == "2537.25"
    assert oficial["balance"] == "2537.25"
    assert oficial["total"] == "2537.25"
    assert "667.25" not in oficial["total"]
    assert oficial["lineas"][1]["concepto"] == "Premios"
    assert oficial["lineas"][1]["monto"] == "RD$0.00"
    assert oficial["lineas"][2]["concepto"] == "Comisión"
    assert oficial["lineas"][3]["concepto"] == "Balance"
    assert oficial["lineas"][3]["monto"] == "RD$2,537.25"
    assert oficial["lineas"][-1]["concepto"] == "Total"
    assert oficial["lineas"][-1]["monto"] == "RD$2,537.25"
    assert not any(
        "anteriores" in str(fila.get("concepto") or "").lower()
        for fila in oficial["lineas"]
    )
    assert "RD$2,537.25" in datos["texto"]
    assert "RD$667.25" not in datos["texto"]
    assert "días anteriores" not in datos["texto"].lower()
    assert "anteriores pagados" not in datos["texto"].lower()
    papel = entorno.c.get(datos["impresion"]["url"], headers=b["headers"])
    assert papel.status_code == 200, papel.text
    assert papel.content.startswith(b"\x89PNG")


def test_dia_con_premio_mismo_dia_y_anteriores(entorno):
    """Mismo día resta al Balance; el pago anterior se registra sin mostrarse."""
    b = entorno.banca(
        saldo=200000, codigo="CMIX", nombre="BANCA MIXTA", usuario="cajmix", clave="1234",
    )
    uid = _usuario(entorno, "cajmix")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 10}, headers=entorno.admin,
    )
    assert alta.status_code == 201, alta.text
    sorteo = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(
        b["headers"],
        [{"tipo": "QN", "sorteos": [sorteo], "numeros": "21", "monto": 1000}],
    )
    mismo = entorno.vender_ok(
        b["headers"],
        [{"tipo": "QN", "sorteos": [sorteo], "numeros": "19", "monto": 5}],
    )
    anterior = entorno.vender_ok(
        b["headers"],
        [{"tipo": "QN", "sorteos": [sorteo], "numeros": "19", "monto": 5}],
    )
    entorno.liquidar(sorteo, 19, 3, 45)
    for ticket in (mismo, anterior):
        pago = entorno.c.post(
            "/terminal/tickets/pagar",
            json={"id": ticket["id"], "serial": ticket["serial"]},
            headers=b["headers"],
        )
        assert pago.status_code == 200, pago.text
    _fijar_premio_pagado(mismo["id"], "200.00", fecha_sorteo=date(2026, 11, 14))
    _fijar_premio_pagado(
        anterior["id"],
        "500.00",
        fecha_sorteo=date(2026, 11, 12),
        pagado_en=datetime(2026, 11, 14, 15, 0, 0),
    )

    dia = entorno.c.get(
        "/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14",
        headers=b["headers"],
    )
    assert dia.status_code == 200, dia.text
    oficial = dia.json()["informe"]["oficial"]
    # Ventas del 14: 1000 + 5 (mismo) = 1005; el anterior quedó fechado el 12.
    assert oficial["ventas"] == "1005.00"
    assert oficial["premios_pagados"] == "700.00"
    assert oficial["premios_anteriores_pagados"] == "500.00"
    assert oficial["premios_sorteos_periodo"] == "200.00"
    assert oficial["comision"] == "100.50"
    assert oficial["balance"] == "704.50"  # 1005 - 100.50 - 200
    assert oficial["total"] == "704.50"
    assert oficial["lineas"][1]["monto"] == "RD$200.00"
    assert not any(
        "anteriores" in str(fila.get("concepto") or "").lower()
        for fila in oficial["lineas"]
    )


def test_mes_premio_fin_de_mes_pagado_al_mes_siguiente(entorno, fijar_hora):
    """Noviembre resta el premio por sorteo; diciembre solo lo muestra como referencia."""
    b = entorno.banca(
        saldo=200000, codigo="CMES", nombre="BANCA MES", usuario="cajmes", clave="1234",
    )
    uid = _usuario(entorno, "cajmes")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 0}, headers=entorno.admin,
    )
    assert alta.status_code == 201, alta.text
    sorteo = entorno.sorteo_id("La Primera 12")
    ganador = entorno.vender_ok(
        b["headers"],
        [{"tipo": "QN", "sorteos": [sorteo], "numeros": "19", "monto": 5}],
    )
    entorno.liquidar(sorteo, 19, 3, 45)
    db = nueva_sesion()
    ticket = db.get(Ticket, ganador["id"])
    premio = Decimal(str(ticket.premio_total or 0))
    if premio <= 0:
        premio = sum((Decimal(str(j.premio or 0)) for j in ticket.jugadas if j.evaluada), Decimal("0"))
    db.close()
    assert premio > 0
    premio_txt = f"{premio:.2f}"
    balance_nov = f"{(Decimal('5.00') - premio):.2f}"

    nov = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=11", headers=b["headers"])
    assert nov.status_code == 200, nov.text
    nov_inf = nov.json()["informe"]["oficial"]
    assert nov_inf["ventas"] == "5.00"
    assert nov_inf["premios_pagados"] == "0.00"
    assert nov_inf["premios_sorteos_periodo"] == premio_txt
    assert nov_inf["premios_anteriores_pagados"] == "0.00"
    assert nov_inf["balance"] == balance_nov
    assert nov_inf["total"] == balance_nov
    assert not any(
        "anteriores" in str(fila.get("concepto") or "").lower()
        for fila in nov_inf["lineas"]
    )

    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        json={"id": ganador["id"], "serial": ganador["serial"]},
        headers=b["headers"],
    )
    assert pago.status_code == 200, pago.text
    _fijar_premio_pagado(
        ganador["id"],
        premio_txt,
        fecha_sorteo=date(2026, 11, 14),
        pagado_en=datetime(2026, 12, 1, 11, 5, 0),
    )
    fijar_hora(datetime(2026, 12, 1, 11, 0, 0))
    headers = entorno.login_terminal("cajmes", "1234")

    nov2 = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=11", headers=headers)
    assert nov2.status_code == 200, nov2.text
    nov2_inf = nov2.json()["informe"]["oficial"]
    assert nov2_inf["premios_pagados"] == "0.00"
    assert nov2_inf["premios_sorteos_periodo"] == premio_txt
    assert nov2_inf["balance"] == balance_nov
    assert nov2_inf["total"] == balance_nov

    dic = entorno.c.get("/terminal/reportes/mes?anio=2026&mes=12", headers=headers)
    assert dic.status_code == 200, dic.text
    dic_inf = dic.json()["informe"]["oficial"]
    assert dic_inf["ventas"] == "0.00"
    assert dic_inf["premios_pagados"] == premio_txt
    assert dic_inf["premios_anteriores_pagados"] == premio_txt
    assert dic_inf["premios_sorteos_periodo"] == "0.00"
    assert dic_inf["balance"] == "0.00"
    assert dic_inf["total"] == "0.00"
    assert dic_inf["lineas"][1]["monto"] == "RD$0.00"
    assert not any(
        "anteriores" in str(fila.get("concepto") or "").lower()
        for fila in dic_inf["lineas"]
    )


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
