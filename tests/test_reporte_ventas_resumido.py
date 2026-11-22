"""Reporte de ventas resumido (Lotería): filtros, fórmulas y aislamiento."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium

from apps.api import db as dbmod
from apps.api.comun import D
from apps.api.models import Jugada, Ticket, Usuario
from apps.api.pdf_ventas_resumido import FUENTE_PT, construir, formato_monto
from apps.api.security import hash_clave


def _get(entorno, extra=""):
    r = entorno.c.get(
        f"/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14{extra}",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _fila(datos, nombre):
    for g in datos["grupos"]:
        for b in g["bancas"]:
            if b["banca"] == nombre:
                return b
    raise AssertionError(f"Banca no encontrada: {nombre}")


def test_filtros_autorizados(entorno):
    b1 = entorno.banca(saldo=5000, codigo="VR01", nombre="BANCA ALPHA", usuario="vra1")
    entorno.banca(saldo=5000, codigo="VR02", nombre="BANCA BETA", usuario="vra2")
    r = entorno.c.get("/reportes/ventas-resumido/filtros", headers=entorno.admin)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["empresa"] == "BANCA MODERNA"
    assert datos["incluye_recargas"] is False
    assert any(g["id"] == "principal" for g in datos["grupos"])
    ids = {b["id"] for b in datos["bancas"]}
    assert b1["sucursal"]["id"] in ids
    assert datos["rutas"] == []


def test_una_banca_y_formulas(entorno):
    b = entorno.banca(saldo=50000, codigo="VR10", nombre="BANCA FORMULA", usuario="vrf1")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    uid = next(u["id"] for u in usuarios if u["usuario"] == "vrf1")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 10}, headers=entorno.admin,
    )
    assert alta.status_code in (200, 201), alta.text
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "11", "monto": 100}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "12", "monto": 50}])

    datos = _get(entorno, f"&sucursal_id={b['sucursal']['id']}")
    assert datos["total"]["bancas"] == 1
    fila = _fila(datos, "BANCA FORMULA")
    assert Decimal(fila["loteria"]["venta"]) == Decimal("150.00")
    assert Decimal(fila["loteria"]["comision"]) == Decimal("15.00")  # suma cajeras 10 %
    assert Decimal(fila["loteria"]["neto"]) == Decimal("135.00")  # venta - comisión
    assert Decimal(fila["loteria"]["premios"]) == Decimal("0")
    assert Decimal(fila["loteria"]["resultado"]) == Decimal("135.00")
    assert Decimal(fila["resultado_total"]) == Decimal("135.00")
    assert Decimal(fila["total_comision_cajeras"]) == Decimal("15.00")
    assert Decimal(datos["total"]["promedio_venta"]) == Decimal("150.00")


def test_anulacion_no_suma_venta(entorno):
    b = entorno.banca(saldo=50000, codigo="VR11", nombre="BANCA ANULA", usuario="vra3")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "21", "monto": 40}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "22", "monto": 60}])
    r = entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": t["id"], "serial": t["serial"], "motivo": "error"},
        headers=b["headers"],
    )
    assert r.status_code == 200, r.text
    datos = _get(entorno, f"&sucursal_id={b['sucursal']['id']}")
    fila = _fila(datos, "BANCA ANULA")
    assert Decimal(fila["loteria"]["venta"]) == Decimal("60.00")


def test_multiples_bancas_subtotales(entorno):
    b1 = entorno.banca(saldo=50000, codigo="VR20", nombre="BANCA NORTE", usuario="vrn1")
    b2 = entorno.banca(saldo=50000, codigo="VR21", nombre="BANCA SUR", usuario="vrs1")
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b1["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 100}])
    entorno.vender_ok(b2["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "02", "monto": 200}])
    datos = _get(entorno)
    assert datos["total"]["bancas"] >= 2
    assert Decimal(datos["total"]["loteria"]["venta"]) >= Decimal("300.00")
    # Subtotal del grupo principal incluye ambas
    g = datos["grupos"][0]
    assert g["subtotal"]["bancas"] >= 2
    venta_tot = Decimal(datos["total"]["loteria"]["venta"])
    n = Decimal(datos["total"]["bancas"])
    esperado = (venta_tot / n).quantize(Decimal("0.01"))
    assert Decimal(datos["total"]["promedio_venta"]) == esperado


def test_premios_superan_ventas_resultado_negativo(entorno):
    b = entorno.banca(saldo=100000, codigo="VR30", nombre="BANCA PREMIO", usuario="vrp1")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    uid = next(u["id"] for u in usuarios if u["usuario"] == "vrp1")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 10}, headers=entorno.admin,
    )
    assert alta.status_code in (200, 201), alta.text
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)  # premio 10×60 = 600
    r = entorno.c.post(
        "/panel/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "sucursal_id": b["sucursal"]["id"]},
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text

    datos = _get(entorno, f"&sucursal_id={b['sucursal']['id']}")
    fila = _fila(datos, "BANCA PREMIO")
    # venta 10, comisión 1, neto 9, premios 600 → resultado -591
    assert Decimal(fila["loteria"]["venta"]) == Decimal("10.00")
    assert Decimal(fila["loteria"]["comision"]) == Decimal("1.00")
    assert Decimal(fila["loteria"]["neto"]) == Decimal("9.00")
    assert Decimal(fila["loteria"]["premios"]) == Decimal("600.00")
    assert Decimal(fila["loteria"]["resultado"]) == Decimal("-591.00")
    assert Decimal(fila["resultado_total"]) == Decimal("-591.00")


def test_premios_completos_incluyen_pendiente_y_no_cambian_al_pagar(entorno):
    """Aceptación: neto 72,610.25; pagados 51,250 + pendiente 5,000 → Premios 56,250.

    Resultado = Neto − Premios = 16,360.25. Al pagar los 5,000 ambos importes
    siguen iguales. Visor y PDF cuadran.
    """
    suc = entorno.sucursal(codigo="P562", nombre="BANCA PREMIO COMPLETO", comision=0)
    entorno.recargar(suc["id"], 500000)
    entorno.operador("vend562", "1234", suc["id"])
    headers = entorno.login_terminal("vend562", "1234")
    sorteo = entorno.sorteo_id("La Primera 12")

    n = 10
    for _ in range(14):
        entorno.vender_ok(headers, [{
            "tipo": "QN", "sorteos": [sorteo], "numeros": f"{n:02d}", "monto": 5000,
        }])
        n += 1
    entorno.vender_ok(headers, [{
        "tipo": "QN", "sorteos": [sorteo], "numeros": f"{n:02d}", "monto": 2600,
    }])
    t_pagado = entorno.vender_ok(headers, [{
        "tipo": "QN", "sorteos": [sorteo], "numeros": "03", "monto": 5,
    }])
    t_pend = entorno.vender_ok(headers, [{
        "tipo": "QN", "sorteos": [sorteo], "numeros": "04", "monto": 5,
    }])
    # 14×5000 + 2600 + 5 + 5 = 72,610.00; el +0.25 se ajusta en BD.
    entorno.liquidar(sorteo, 3, 4, 45)

    pago = entorno.c.post(
        "/panel/tickets/pagar",
        json={"id": t_pagado["id"], "serial": t_pagado["serial"], "sucursal_id": suc["id"]},
        headers=entorno.admin,
    )
    assert pago.status_code == 200, pago.text

    db = dbmod.nueva_sesion()
    try:
        for tid, monto in ((t_pagado["id"], "51250"), (t_pend["id"], "5000")):
            ticket = db.get(Ticket, tid)
            ticket.premio_total = D(monto)
            for jugada in ticket.jugadas:
                if jugada.evaluada and D(jugada.premio or 0) > 0:
                    jugada.premio = D(monto)
        # Centavos del neto de aceptación sin romper el mínimo de jugada.
        ajuste = db.get(Ticket, t_pend["id"])
        ajuste.total = D(ajuste.total) + D("0.25")
        db.commit()
    finally:
        db.close()

    def leer():
        r = entorno.c.get(
            f"/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14&sucursal_id={suc['id']}",
            headers=entorno.admin,
        )
        assert r.status_code == 200, r.text
        return r.json()

    datos = leer()
    fila = _fila(datos, "BANCA PREMIO COMPLETO")
    assert Decimal(fila["loteria"]["venta"]) == Decimal("72610.25")
    assert Decimal(fila["loteria"]["neto"]) == Decimal("72610.25")
    assert Decimal(fila["loteria"]["premios"]) == Decimal("56250.00")
    assert Decimal(fila["loteria"]["resultado"]) == Decimal("16360.25")
    assert Decimal(datos["total"]["loteria"]["premios"]) == Decimal("56250.00")
    assert Decimal(datos["total"]["loteria"]["resultado"]) == Decimal("16360.25")
    cajero = fila["cajeros"][0]
    assert Decimal(cajero["neto"]) == Decimal("72610.25")
    assert Decimal(cajero["premios"]) == Decimal("56250.00")
    assert Decimal(cajero["resultado"]) == Decimal("16360.25")

    pdf = entorno.c.get(
        f"/reportes/ventas-resumido.pdf?desde=2026-11-14&hasta=2026-11-14"
        f"&sucursal_id={suc['id']}&desglose=cajeros",
        headers=entorno.admin,
    )
    assert pdf.status_code == 200, pdf.text
    texto = "\n".join(_texto(_pdf(pdf.content)))
    assert formato_monto("56250.00") in texto
    assert formato_monto("16360.25") in texto
    assert formato_monto("72610.25") in texto

    # Simula el cobro de los RD$5,000.00 en datos locales (sin alterar el factor).
    db = dbmod.nueva_sesion()
    try:
        pendiente = db.get(Ticket, t_pend["id"])
        for jugada in pendiente.jugadas:
            if jugada.evaluada and D(jugada.premio or 0) > 0 and not jugada.pagada:
                jugada.pagada = True
                jugada.pagado_en = datetime(2026, 11, 14, 18, 0)
                jugada.pagado_por_usuario_id = pendiente.usuario_id
        pendiente.estado = "pagado"
        pendiente.premio_total = D("5000")
        pendiente.pagado_en = datetime(2026, 11, 14, 18, 0)
        pendiente.pagado_por_usuario_id = pendiente.usuario_id
        pendiente.pagado_en_sucursal_id = suc["id"]
        db.commit()
    finally:
        db.close()

    datos2 = leer()
    fila2 = _fila(datos2, "BANCA PREMIO COMPLETO")
    assert Decimal(fila2["loteria"]["premios"]) == Decimal("56250.00")
    assert Decimal(fila2["loteria"]["resultado"]) == Decimal("16360.25")
    assert Decimal(fila2["cajeros"][0]["premios"]) == Decimal("56250.00")
    assert Decimal(fila2["cajeros"][0]["resultado"]) == Decimal("16360.25")


def test_rango_fechas_sin_ventas(entorno):
    b = entorno.banca(saldo=5000, codigo="VR40", nombre="BANCA VACIA", usuario="vrv1")
    r = entorno.c.get(
        f"/reportes/ventas-resumido?desde=2026-01-01&hasta=2026-01-02&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    fila = _fila(datos, "BANCA VACIA")
    assert Decimal(fila["loteria"]["venta"]) == Decimal("0")
    assert Decimal(fila["resultado_total"]) == Decimal("0")


def test_fecha_invalida(entorno):
    r = entorno.c.get(
        "/reportes/ventas-resumido?desde=2026-11-15&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert r.status_code == 400


def test_grupo_desconocido(entorno):
    r = entorno.c.get(
        "/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14&grupo_id=otro",
        headers=entorno.admin,
    )
    assert r.status_code == 400


def test_ruta_inexistente_rechazada(entorno):
    r = entorno.c.get(
        "/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14&ruta_id=x",
        headers=entorno.admin,
    )
    assert r.status_code == 400


def test_filtro_grupo_principal(entorno):
    b = entorno.banca(saldo=5000, codigo="VR50", nombre="BANCA GRUPO", usuario="vrg1")
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "33", "monto": 25}])
    datos = _get(entorno, "&grupo_id=principal")
    assert any(x["banca"] == "BANCA GRUPO" for g in datos["grupos"] for x in g["bancas"])


def _bloque(venta="0.00", comision="0.00", neto="0.00", premios="0.00", resultado="0.00", total=None):
    rec = {"venta": "0.00", "comision": "0.00", "neto": "0.00"}
    return {
        "loteria": {
            "venta": venta, "comision": comision, "neto": neto,
            "premios": premios, "resultado": resultado,
        },
        "recargas": rec,
        "resultado_total": total if total is not None else resultado,
    }


def _datos_sinteticos(n, negativo_en=2):
    bancas = []
    for i in range(n):
        if i == negativo_en:
            bloque = _bloque("10.00", "1.00", "9.00", "1234576.89", "-1234567.89", "-1234567.89")
        else:
            bloque = _bloque("100.00", "10.00", "90.00", "0.00", "90.00", "90.00")
        bancas.append({
            "codigo": f"B{i:02d}",
            "banca": f"BANCA PRUEBA {i:02d}",
            **bloque,
        })
    sub = _bloque("100.00", "10.00", "90.00", "0.00", "90.00", "90.00")
    sub["bancas"] = n
    return {
        "empresa": "BANCA MODERNA",
        "desde": "2026-11-20",
        "hasta": "2026-11-20",
        "impreso": "20/11/2026 07:00 PM",
        "grupos": [{
            "grupo_nombre": "GRUPO PRINCIPAL",
            "bancas": bancas,
            "subtotal": sub,
        }],
        "total": {**sub, "bancas": n, "promedio_venta": "100.00"},
    }


def _pdf(pdf_bytes):
    doc = pdfium.PdfDocument(pdf_bytes)
    assert abs(doc[0].get_size()[0] - 841.89) < 1.5
    assert abs(doc[0].get_size()[1] - 595.28) < 1.5
    return doc


def _texto(doc):
    partes = []
    for i in range(len(doc)):
        partes.append(doc[i].get_textpage().get_text_bounded())
    return partes


def _tiene_color(pil, pred):
    pixels = pil.getdata()
    paso = max(1, len(pixels) // 80000)
    for i in range(0, len(pixels), paso):
        if pred(pixels[i]):
            return True
    return False


def test_pdf_pocas_bancas_cabe_en_una_pagina_a4():
    assert FUENTE_PT >= 9
    datos = _datos_sinteticos(3)
    pdf = construir(datos)
    assert pdf.startswith(b"%PDF")
    doc = _pdf(pdf)
    assert len(doc) == 1
    texto = _texto(doc)[0]
    assert "BANCA PRUEBA 00" in texto
    assert "BANCA PRUEBA 02" in texto
    assert "LOTERÍA" in texto or "LOTERIA" in texto
    assert "RECARGAS" in texto
    assert formato_monto("-1234567.89") in texto
    assert "Sub-Total" in texto
    assert "Promedio de Ventas por Banca" in texto
    pil = doc[0].render(scale=2).to_pil()
    assert _tiene_color(pil, lambda p: p[2] > 180 and p[0] < 160 and p[1] > 90)
    assert _tiene_color(pil, lambda p: p[0] > 200 and p[1] < 80 and p[2] < 80)
    assert _tiene_color(pil, lambda p: abs(p[0] - 211) < 18 and abs(p[1] - 211) < 18 and abs(p[2] - 211) < 18)


def test_pdf_muchas_bancas_repite_encabezado_sin_cortar_filas():
    datos = _datos_sinteticos(40, negativo_en=35)
    pdf = construir(datos)
    doc = _pdf(pdf)
    assert len(doc) >= 2
    textos = _texto(doc)
    unido = "\n".join(textos)
    for i in range(40):
        nombre = f"BANCA PRUEBA {i:02d}"
        assert nombre in unido
        assert sum(nombre in pagina for pagina in textos) == 1
    for pagina in textos:
        assert "RECARGAS" in pagina
        assert "Banca" in pagina
    assert formato_monto("-1234567.89") in unido
    alto = doc[0].get_size()[1]
    for pagina in doc:
        assert abs(pagina.get_size()[0] - doc[0].get_size()[0]) < 0.2
        assert abs(pagina.get_size()[1] - alto) < 0.2


def test_endpoint_pdf_local_a4_sin_impresora(entorno):
    b = entorno.banca(saldo=100000, codigo="VR30", nombre="BANCA PREMIO", usuario="vrpdf")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    uid = next(u["id"] for u in usuarios if u["usuario"] == "vrpdf")
    alta = entorno.c.post(
        "/comisiones", json={"usuario_id": uid, "porcentaje": 10}, headers=entorno.admin,
    )
    assert alta.status_code in (200, 201), alta.text
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    entorno.liquidar(s, 19, 3, 45)
    pago = entorno.c.post(
        "/panel/tickets/pagar",
        json={"id": t["id"], "serial": t["serial"], "sucursal_id": b["sucursal"]["id"]},
        headers=entorno.admin,
    )
    assert pago.status_code == 200, pago.text
    r = entorno.c.get(
        f"/reportes/ventas-resumido.pdf?desde=2026-11-14&hasta=2026-11-14&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].startswith("inline;")
    assert "Resumen-de-Ventas-" in r.headers["content-disposition"]
    doc = _pdf(r.content)
    assert len(doc) == 1
    texto = _texto(doc)[0]
    assert "BANCA PREMIO" in texto
    assert formato_monto("-591.00") in texto
    assert formato_monto("1.00") in texto
    anon = entorno.c.get("/reportes/ventas-resumido.pdf?desde=2026-11-14&hasta=2026-11-14")
    assert anon.status_code == 401


def test_pdf_con_totales_en_cero_se_descarga_en_a4(entorno):
    entorno.banca(saldo=1000, codigo="VR0", nombre="BANCA SIN VENTAS", usuario="vr0")
    for extra in ("", "&desglose=cajeros"):
        r = entorno.c.get(
            "/reportes/ventas-resumido.pdf?desde=2026-11-14&hasta=2026-11-14" + extra,
            headers=entorno.admin,
        )
        assert r.status_code == 200, r.text[:300]
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.headers["content-disposition"].startswith("inline;")
        doc = _pdf(r.content)
        texto = "\n".join(_texto(doc))
        assert "BANCA SIN VENTAS" in texto
        assert "14/11/2026" in texto
        assert formato_monto("0.00") in texto
        assert "Promedio de Ventas por Banca" in texto


def test_pdf_cabe_aunque_la_fuente_sea_mas_ancha(entorno, monkeypatch):
    """DejaVu en Render es más ancha que Arial. El encabezado no puede tumbar el PDF."""
    from reportlab.pdfbase import pdfmetrics

    original = pdfmetrics.stringWidth

    def mas_ancho(texto, fuente, tam, *args, **kwargs):
        return original(texto, fuente, tam, *args, **kwargs) * 1.2

    monkeypatch.setattr(pdfmetrics, "stringWidth", mas_ancho)
    entorno.banca(saldo=1000, codigo="VRW", nombre="BANCA FUENTE ANCHA", usuario="vrw")
    r = entorno.c.get(
        "/reportes/ventas-resumido.pdf?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text[:300]
    doc = _pdf(r.content)
    texto = "\n".join(_texto(doc))
    assert "Resultado" in texto and "Total" in texto
    assert "BANCA FUENTE" in texto and "ANCHA" in texto


def test_pdf_castillo_rango_con_montos_anchos_como_en_render(monkeypatch):
    """Reproduce el 500 de producción: $167,245.00 no cabía en 66 pt (DejaVu Bold)."""
    from reportlab.pdfbase import pdfmetrics
    import apps.api.pdf_ventas_resumido as pdfmod

    original = pdfmetrics.stringWidth

    def como_dejavu_bold(texto, fuente, tam, *args, **kwargs):
        # DejaVu Bold ≈ 1.26× Arial en montos con $ y comas.
        return original(texto, fuente, tam, *args, **kwargs) * 1.26

    monkeypatch.setattr(pdfmetrics, "stringWidth", como_dejavu_bold)
    monkeypatch.setattr(pdfmod, "_FUENTES", ("Helvetica", "Helvetica-Bold"))

    bloque = _bloque("167245.00", "16724.50", "150520.50", "80000.00", "70520.50", "70520.50")
    datos = {
        "empresa": "BANCA CASTILLO",
        "desde": "2026-11-19",
        "hasta": "2026-11-21",
        "impreso": "21/11/2026 02:56 AM",
        "desglose_cajeros": True,
        "grupos": [{
            "grupo_nombre": "GRUPO PRINCIPAL",
            "bancas": [{
                "codigo": "BC",
                "banca": "BANCA CASTILLO",
                **bloque,
                "cajeros": [{
                    "nombre": "Wanda",
                    "venta": "167245.00",
                    "comision": "16724.50",
                    "neto": "150520.50",
                    "premios": "80000.00",
                    "resultado": "70520.50",
                }],
                "total_comision_cajeras": "16724.50",
            }],
            "subtotal": {**bloque, "bancas": 1},
        }],
        "total": {**bloque, "bancas": 1, "promedio_venta": "167245.00"},
    }
    assert como_dejavu_bold("$167,245.00", "Helvetica-Bold", 9) > (66 - 6)
    pdf = construir(datos)
    assert pdf.startswith(b"%PDF")
    doc = _pdf(pdf)
    texto = "\n".join(_texto(doc))
    assert "BANCA CASTILLO" in texto
    assert "19/11/2026" in texto and "21/11/2026" in texto
    assert formato_monto("167245.00") in texto
    assert "Cajero: Wanda" in texto


def test_el_boton_pdf_no_usa_el_dialogo_de_windows():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    css = (raiz / "apps" / "web" / "style.css").read_text(encoding="utf-8")
    assert "/reportes/ventas-resumido.pdf" in js
    assert "abrirDocumentoVentasResumido" not in js
    assert "Guardar como PDF" not in js
    assert "a.download" in js
    assert "navigator.share" in js
    assert "esTelefonoApple" in js
    assert "abrirPdfVentasResumido" in js
    assert "abrirPdfEnVisor" in js
    assert "size: A4 landscape" in css
    assert "table-header-group" in css
    html = (raiz / "apps" / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-rvr-abrir-pdf"' in html
    assert 'id="btn-rvr-abrir-pdf-filtro"' in html
    assert "ABRIR PDF" in html
    ventas = html.split('id="rvr-zoom"', 1)[1].split("</select>", 1)[0]
    assert ventas.index('value="25"') < ventas.index('value="50"') < ventas.index('value="75"')
    assert ventas.index('value="75"') < ventas.index('value="100" selected') < ventas.index('value="125"')
    tickets = html.split('id="rtk-zoom"', 1)[1].split("</select>", 1)[0]
    assert 'value="25"' not in tickets and 'value="50"' not in tickets
    assert '#rvr-hoja[data-zoom="25"]{transform:scale(.25)}' in css
    assert '#rvr-hoja[data-zoom="50"]{transform:scale(.5)}' in css
    assert "rvrAjustarMarcoZoom" in js


def _super(entorno):
    db = dbmod.nueva_sesion()
    try:
        existente = db.query(Usuario).filter_by(usuario="JDMCASHNOW").first()
        if existente is None:
            db.add(Usuario(
                nombre="JDMCASHNOW", usuario="JDMCASHNOW", rol="super_admin",
                sucursal_id=None, activo=True, eliminado=False, suspendido=False,
                estado_aprobacion="aprobado", clave_hash=hash_clave("SuperTest123!"),
            ))
        db.commit()
    finally:
        db.close()
    login = entorno.c.post("/auth/login", json={"usuario": "JDMCASHNOW", "clave": "SuperTest123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_desglose_cajeros_dos_bancas_y_admin_de_sucursal(entorno):
    html = entorno.c.get("/").text
    assert 'id="btn-rvr-ver"' in html
    assert 'id="btn-rvr-cajeros"' in html
    assert 'id="btn-rvr-todos"' in html
    assert 'id="btn-rvr-visor-regresar"' in html
    js = (Path(__file__).resolve().parent.parent / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    assert "mostrarCajeros" in js
    assert 'id="btn-rvr-todos"' in js or "btn-rvr-todos" in js

    norte = entorno.banca(saldo=50000, codigo="VC01", nombre="BANCA NORTE CAJ", usuario="vcn1")
    sur = entorno.banca(saldo=50000, codigo="VC02", nombre="BANCA SUR CAJ", usuario="vcs1")
    entorno.operador("vcn2", "1234", norte["sucursal"]["id"])
    h2 = entorno.login_terminal("vcn2", "1234")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    for usuario in ("vcn1", "vcn2", "vcs1"):
        uid = next(u["id"] for u in usuarios if u["usuario"] == usuario)
        alta = entorno.c.post(
            "/comisiones", json={"usuario_id": uid, "porcentaje": 10}, headers=entorno.admin,
        )
        assert alta.status_code in (200, 201), alta.text
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(norte["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "07", "monto": 100}])
    entorno.vender_ok(h2, [{"tipo": "QN", "sorteos": [s], "numeros": "08", "monto": 40}])
    entorno.vender_ok(sur["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "09", "monto": 200}])

    datos = _get(entorno)
    fila_n = _fila(datos, "BANCA NORTE CAJ")
    fila_s = _fila(datos, "BANCA SUR CAJ")
    ventas_n = sorted(Decimal(c["venta"]) for c in fila_n["cajeros"])
    assert ventas_n == [Decimal("40.00"), Decimal("100.00")]
    assert sum(ventas_n, Decimal("0")) == Decimal(fila_n["loteria"]["venta"]) == Decimal("140.00")
    assert Decimal(fila_n["loteria"]["comision"]) == Decimal("14.00")
    assert Decimal(fila_n["total_comision_cajeras"]) == Decimal("14.00")
    assert Decimal(fila_n["loteria"]["premios"]) == Decimal("0")
    assert [c["nombre"] for c in fila_s["cajeros"]] == ["Operador vcs1"]
    assert Decimal(fila_s["cajeros"][0]["venta"]) == Decimal(fila_s["loteria"]["venta"]) == Decimal("200.00")
    assert Decimal(fila_s["loteria"]["comision"]) == Decimal("20.00")
    assert Decimal(fila_s["total_comision_cajeras"]) == Decimal("20.00")

    super_h = _super(entorno)
    creado = entorno.c.post("/usuarios", json={
        "nombre": "Admin Norte", "usuario": "admnorte", "rol": "admin",
        "sucursal_id": norte["sucursal"]["id"], "clave": "AdminNorte123!", "activo": True,
    }, headers=super_h)
    assert creado.status_code in (200, 201), creado.text
    login = entorno.c.post("/auth/login", json={"usuario": "admnorte", "clave": "AdminNorte123!"})
    assert login.status_code == 200, login.text
    propio = entorno.c.get(
        "/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert propio.status_code == 200, propio.text
    cuerpo = propio.json()
    nombres = [b["banca"] for g in cuerpo["grupos"] for b in g["bancas"]]
    assert nombres == ["BANCA NORTE CAJ"]
    cajeros = cuerpo["grupos"][0]["bancas"][0]["cajeros"]
    assert sorted(c["nombre"] for c in cajeros) == ["Operador vcn1", "Operador vcn2"]
    assert "BANCA SUR CAJ" not in nombres
    ajena = entorno.c.get(
        f"/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14&sucursal_id={sur['sucursal']['id']}",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert ajena.status_code == 403


def _vender_montos(entorno, headers, montos):
    sorteo = entorno.sorteo_id("La Primera 12")
    tickets = []
    for i, monto in enumerate(montos):
        tickets.append(entorno.vender_ok(headers, [{
            "tipo": "QN", "sorteos": [sorteo], "numeros": f"{i + 1:02d}", "monto": monto,
        }]))
    return tickets


def test_columnas_cajero_comision_perfil_y_premios_pagados(entorno):
    """18–19/11/2026: RD$34,633.00 al 15% dan RD$5,194.95 en la fila de la banca.

    Isaury pagó RD$12,040.00 y Wanda RD$17,400.00. La banca usa la suma de
    esas comisiones; el desglose no vuelve a sumar venta ni premios.
    """
    js = (Path(__file__).resolve().parent.parent / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    assert "Total comisión de cajeras" in js
    assert "rvrMonto(c.comision)" in js and "rvrMonto(c.premios)" in js
    assert 'q.set("desglose", "cajeros")' in js

    banca = entorno.banca(
        saldo=200000, codigo="C18", nombre="BANCA CASTILLO ESPERADA", usuario="isaury",
    )
    sucursal_id = banca["sucursal"]["id"]
    wanda = entorno.operador("wanda", "1234", sucursal_id)
    hw = entorno.login_terminal("wanda", "1234")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    isaury_id = next(u["id"] for u in usuarios if u["usuario"] == "isaury")
    for uid in (isaury_id, wanda["id"]):
        alta = entorno.c.post(
            "/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin,
        )
        assert alta.status_code in (200, 201), alta.text

    _vender_montos(entorno, banca["headers"], [5000, 5000, 5000, 5000])
    _vender_montos(entorno, hw, [5000, 5000, 4633])
    anulado = entorno.vender_ok(banca["headers"], [{
        "tipo": "QN", "sorteos": [entorno.sorteo_id("La Primera 12")], "numeros": "90", "monto": 1000,
    }])
    baja = entorno.c.post("/terminal/tickets/anular", json={
        "id": anulado["id"], "serial": anulado["serial"], "motivo": "error de prueba",
    }, headers=banca["headers"])
    assert baja.status_code == 200, baja.text

    s12 = entorno.sorteo_id("La Primera 12")
    s7 = entorno.sorteo_id("La Primera 8PM")
    suerte = entorno.sorteo_id("La Suerte 12:30")
    parcial = entorno.vender_ok(banca["headers"], [
        {"tipo": "QN", "sorteos": [s12, s7], "numeros": "25", "monto": 5},
    ])
    # 98/99 evitan que las ventas 01–04 del rango entren como premios pendientes.
    entorno.liquidar(s12, 25, 98, 99)
    pago_isa = entorno.c.post("/terminal/tickets/pagar", json={
        "id": parcial["id"], "serial": parcial["serial"], "confirmar_caja_negativa": True,
    }, headers=banca["headers"])
    assert pago_isa.status_code == 200, pago_isa.text
    assert pago_isa.json()["estado"] == "parcial"
    completo = entorno.vender_ok(hw, [{
        "tipo": "QN", "sorteos": [suerte], "numeros": "33", "monto": 5,
    }])
    entorno.liquidar(suerte, 33, 97, 96)
    pago_w = entorno.c.post("/terminal/tickets/pagar", json={
        "id": completo["id"], "serial": completo["serial"], "confirmar_caja_negativa": True,
    }, headers=hw)
    assert pago_w.status_code == 200, pago_w.text

    db = dbmod.nueva_sesion()
    try:
        isaury = db.query(Usuario).filter_by(usuario="isaury").one()
        wanda_u = db.query(Usuario).filter_by(usuario="wanda").one()
        isaury.nombre = "Isaury"
        wanda_u.nombre = "Wanda"
        ids_premio = {parcial["id"], completo["id"]}
        for ticket in db.query(Ticket).filter(Ticket.sucursal_vendedora_id == sucursal_id):
            if D(ticket.total) >= 1000:
                ticket.fecha = date(2026, 11, 18)
            elif ticket.id in ids_premio:
                # Entran al rango por fecha de venta; su monto no altera el caso 34,633.
                ticket.fecha = date(2026, 11, 18)
                ticket.total = D(0)
        for jugada in db.query(Jugada).filter(Jugada.pagada.is_(True)):
            if jugada.pagado_por_usuario_id == isaury.id:
                jugada.premio = D("12040")
                jugada.pagado_en = datetime(2026, 11, 19, 15, 0)
            elif jugada.pagado_por_usuario_id == wanda_u.id:
                jugada.premio = D("17400")
                jugada.pagado_en = datetime(2026, 11, 19, 16, 0)
        db.commit()
    finally:
        db.close()

    r = entorno.c.get(
        "/reportes/ventas-resumido?desde=2026-11-18&hasta=2026-11-19"
        f"&sucursal_id={sucursal_id}",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    fila = _fila(datos, "BANCA CASTILLO ESPERADA")
    assert Decimal(fila["loteria"]["venta"]) == Decimal("34633.00")
    assert Decimal(fila["loteria"]["comision"]) == Decimal("5194.95")
    assert Decimal(fila["loteria"]["neto"]) == Decimal("29438.05")
    assert Decimal(fila["loteria"]["premios"]) == Decimal("29440.00")
    assert Decimal(fila["loteria"]["resultado"]) == Decimal("-1.95")
    por_nombre = {c["nombre"]: c for c in fila["cajeros"]}
    assert set(por_nombre) == {"Isaury", "Wanda"}
    isa = por_nombre["Isaury"]
    wan = por_nombre["Wanda"]
    assert Decimal(isa["venta"]) == Decimal("20000.00")
    assert Decimal(isa["comision"]) == Decimal("3000.00")
    assert Decimal(isa["neto"]) == Decimal("17000.00")
    assert Decimal(isa["premios"]) == Decimal("12040.00")
    assert Decimal(isa["resultado"]) == Decimal("4960.00")
    assert Decimal(wan["venta"]) == Decimal("14633.00")
    assert Decimal(wan["comision"]) == Decimal("2194.95")
    assert Decimal(wan["neto"]) == Decimal("12438.05")
    assert Decimal(wan["premios"]) == Decimal("17400.00")
    assert Decimal(wan["resultado"]) == Decimal("-4961.95")
    assert Decimal(fila["total_comision_cajeras"]) == Decimal("5194.95")
    assert Decimal(fila["loteria"]["comision"]) == Decimal(fila["total_comision_cajeras"])
    assert sum((Decimal(c["premios"]) for c in fila["cajeros"]), Decimal("0")) == Decimal("29440.00")
    assert Decimal(datos["total"]["loteria"]["venta"]) == Decimal("34633.00")
    assert Decimal(datos["total"]["loteria"]["comision"]) == Decimal(fila["loteria"]["comision"])
    assert Decimal(datos["total"]["loteria"]["premios"]) == Decimal(fila["loteria"]["premios"])
    assert Decimal(datos["total"]["loteria"]["resultado"]) == Decimal("-1.95")

    pdf = entorno.c.get(
        "/reportes/ventas-resumido.pdf?desde=2026-11-18&hasta=2026-11-19"
        f"&sucursal_id={sucursal_id}&desglose=cajeros",
        headers=entorno.admin,
    )
    assert pdf.status_code == 200, pdf.text
    texto = _texto(_pdf(pdf.content))[0]
    assert "Cajero: Isaury" in texto
    assert "Cajero: Wanda" in texto
    assert "Total comisión de cajeras" in texto
    assert formato_monto("5194.95") in texto
    assert formato_monto("12040.00") in texto
    assert formato_monto("17400.00") in texto
    assert formato_monto("34633.00") in texto
    plano = entorno.c.get(
        "/reportes/ventas-resumido.pdf?desde=2026-11-18&hasta=2026-11-19"
        f"&sucursal_id={sucursal_id}",
        headers=entorno.admin,
    )
    assert "Total comisión de cajeras" not in _texto(_pdf(plano.content))[0]

    def detalle(desde, hasta):
        resp = entorno.c.get(
            f"/reportes/ventas-cajeros/{wanda['id']}?desde={desde}&hasta={hasta}",
            headers=entorno.admin,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    rango = detalle("2026-11-18", "2026-11-19")
    periodo = rango["resultado_periodo"]
    assert periodo["desde"] == "2026-11-18" and periodo["hasta"] == "2026-11-19"
    assert Decimal(periodo["ventas_validas"]) == Decimal("14633.00")
    assert Decimal(periodo["premios_pagados"]) == Decimal("17400.00")
    assert Decimal(periodo["comision"]) == Decimal("2194.95")
    assert Decimal(periodo["quedo"]) == Decimal("-4961.95")
    dia = detalle("2026-11-18", "2026-11-18")
    assert dia["resultado_periodo"]["desde"] == dia["resultado_periodo"]["hasta"] == "2026-11-18"
    assert Decimal(dia["resultado_periodo"]["ventas_validas"]) == Decimal("14633.00")
    # Mismo desglose que Ventas Resumido: premio completo por fecha de venta.
    assert Decimal(dia["resultado_periodo"]["premios_pagados"]) == Decimal("17400.00")
    assert Decimal(dia["resultado_periodo"]["comision"]) == Decimal("2194.95")
    assert Decimal(dia["resultado_periodo"]["quedo"]) == Decimal("-4961.95")
    assert dia["resumen"]["mi_caja"] == rango["resumen"]["mi_caja"]
    assert dia["resumen"]["ventas_ciclo"] == rango["resumen"]["ventas_ciclo"]
    otro = detalle("2026-11-19", "2026-11-19")
    assert Decimal(otro["resultado_periodo"]["ventas_validas"]) == Decimal("0.00")
    assert Decimal(otro["resultado_periodo"]["premios_pagados"]) == Decimal("0.00")
    assert Decimal(otro["resultado_periodo"]["comision"]) == Decimal("0.00")
    assert Decimal(otro["resultado_periodo"]["quedo"]) == Decimal("0.00")
    invertido = entorno.c.get(
        f"/reportes/ventas-cajeros/{wanda['id']}?desde=2026-11-19&hasta=2026-11-18",
        headers=entorno.admin,
    )
    assert invertido.status_code == 400


def test_pago_fuera_del_rango_de_venta_no_mueve_premios_del_resumido(entorno, monkeypatch):
    """Premios del resumido siguen la fecha de venta, no la de pago."""
    banca = entorno.banca(saldo=50000, codigo="C19", nombre="BANCA PAGO SOLO", usuario="vende")
    sid = banca["sucursal"]["id"]
    solo = entorno.operador("solopago", "1234", sid)
    hs = entorno.login_terminal("solopago", "1234")
    sorteo = entorno.sorteo_id("La Primera 12")
    ticket = entorno.vender_ok(hs, [{
        "tipo": "QN", "sorteos": [sorteo], "numeros": "19", "monto": 10,
    }])
    entorno.liquidar(sorteo, 19, 3, 45)
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "confirmar_caja_negativa": True,
    }, headers=hs)
    assert pago.status_code == 200, pago.text
    db = dbmod.nueva_sesion()
    try:
        vendido = db.get(Ticket, ticket["id"])
        vendido.fecha = date(2026, 11, 1)
        for jugada in vendido.jugadas:
            if jugada.pagada:
                jugada.pagado_en = datetime(2026, 11, 19, 12, 0)
        db.commit()
    finally:
        db.close()

    r = entorno.c.get(
        f"/reportes/ventas-resumido?desde=2026-11-18&hasta=2026-11-19&sucursal_id={sid}",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    fila = _fila(r.json(), "BANCA PAGO SOLO")
    assert Decimal(fila["loteria"]["venta"]) == Decimal("0.00")
    assert Decimal(fila["loteria"]["premios"]) == Decimal("0.00")
    assert fila["cajeros"] == []

    abierto = entorno.sorteo_id("Florida Día")
    entorno.vender_ok(banca["headers"], [{
        "tipo": "QN", "sorteos": [abierto], "numeros": "44", "monto": 15,
    }])
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    entorno.vender_ok(banca["headers"], [{
        "tipo": "QN", "sorteos": [abierto], "numeros": "45", "monto": 20,
    }])
    prueba = entorno.c.get(
        f"/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14&sucursal_id={sid}",
        headers=entorno.admin,
    )
    assert Decimal(_fila(prueba.json(), "BANCA PAGO SOLO")["loteria"]["venta"]) == Decimal("20.00")
    monkeypatch.delenv("MODO_DESARROLLO", raising=False)
    real = entorno.c.get(
        f"/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14&sucursal_id={sid}",
        headers=entorno.admin,
    )
    assert Decimal(_fila(real.json(), "BANCA PAGO SOLO")["loteria"]["venta"]) == Decimal("15.00")


def test_pdf_con_comision_de_cajeras_de_la_captura_no_revienta():
    """132,697 − 19,904.55 − 71,630 = 41,162.45 en la fila de la banca y en el PDF."""
    ventas, premios, comision = 13269700, 7163000, 1990455
    assert ventas - comision - premios == 4116245
    banca = {
        "codigo": "1301",
        "banca": "BANCA CASTILLO",
        "loteria": {
            "venta": "132697.00", "comision": "19904.55", "neto": "112792.45",
            "premios": "71630.00", "resultado": "41162.45",
        },
        "recargas": {"venta": "0.00", "comision": "0.00", "neto": "0.00"},
        "resultado_total": "41162.45",
        "cajeros": [{
            "nombre": "Wanda", "venta": "132697.00", "comision": "19904.55",
            "neto": "112792.45", "premios": "71630.00", "resultado": "41162.45",
        }],
        "total_comision_cajeras": "19904.55",
    }
    sub = {
        "loteria": banca["loteria"], "recargas": banca["recargas"],
        "resultado_total": "41162.45", "bancas": 1,
    }
    pdf = construir({
        "empresa": "BANCA MODERNA",
        "desde": "2026-11-20",
        "hasta": "2026-11-21",
        "impreso": "21/11/2026 01:00 AM",
        "desglose_cajeros": True,
        "grupos": [{"grupo_nombre": "GRUPO", "bancas": [banca], "subtotal": sub}],
        "total": {**sub, "bancas": 1, "promedio_venta": "132697.00"},
    })
    assert pdf.startswith(b"%PDF")
    texto = _texto(_pdf(pdf))[0]
    assert formato_monto("19904.55") in texto
    assert formato_monto("41162.45") in texto
    assert formato_monto("132697.00") in texto


def test_captura_castillo_19_21_comision_en_fila_subtotal_y_pdf():
    """Captura Castillo 19–21/11/2026: la fila usa la suma de cajeras, no RD$0.

    Neto = Venta − Comisión; Resultado = Neto − Premios; Resultado Total = Resultado
    (+ neto de recargas). Subtotal y total conservan el signo.
    """
    venta = Decimal("287795.00")
    comision = Decimal("43162.80")
    neto = venta - comision
    premios = Decimal("243160.00")
    resultado = neto - premios
    assert neto == Decimal("244632.20")
    assert resultado == Decimal("1472.20")
    banca = {
        "codigo": "1301",
        "banca": "BANCA CASTILLO",
        "loteria": {
            "venta": str(venta), "comision": str(comision), "neto": str(neto),
            "premios": str(premios), "resultado": str(resultado),
        },
        "recargas": {"venta": "0.00", "comision": "0.00", "neto": "0.00"},
        "resultado_total": str(resultado),
        "cajeros": [
            {
                "nombre": "Cajera A", "venta": "150000.00", "comision": "22500.00",
                "neto": "127500.00", "premios": "120000.00", "resultado": "7500.00",
            },
            {
                "nombre": "Cajera B", "venta": "137795.00", "comision": "20662.80",
                "neto": "117132.20", "premios": "123160.00", "resultado": "-6027.80",
            },
        ],
        "total_comision_cajeras": str(comision),
    }
    assert Decimal(banca["loteria"]["comision"]) == Decimal(banca["total_comision_cajeras"])
    assert sum((Decimal(c["comision"]) for c in banca["cajeros"]), Decimal("0")) == comision
    sub = {
        "loteria": banca["loteria"], "recargas": banca["recargas"],
        "resultado_total": str(resultado), "bancas": 1,
    }
    payload = {
        "empresa": "BANCA MODERNA",
        "desde": "2026-11-19",
        "hasta": "2026-11-21",
        "impreso": "21/11/2026 08:00 PM",
        "desglose_cajeros": False,
        "grupos": [{"grupo_nombre": "GRUPO", "bancas": [banca], "subtotal": sub}],
        "total": {**sub, "bancas": 1, "promedio_venta": str(venta)},
    }
    for con_desglose in (False, True):
        payload["desglose_cajeros"] = con_desglose
        pdf = construir(payload)
        assert pdf.startswith(b"%PDF")
        texto = _texto(_pdf(pdf))[0]
        assert formato_monto(str(venta)) in texto
        assert formato_monto(str(comision)) in texto
        assert formato_monto(str(neto)) in texto
        assert formato_monto(str(premios)) in texto
        assert formato_monto(str(resultado)) in texto
        if con_desglose:
            assert "Total comisión de cajeras" in texto
            assert "Cajero: Cajera A" in texto
        else:
            assert "Total comisión de cajeras" not in texto


def test_el_boton_resultado_no_cambia_la_fila_ni_mi_caja():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    html = (raiz / "apps" / "web" / "index.html").read_text(encoding="utf-8")
    css = (raiz / "apps" / "web" / "style.css").read_text(encoding="utf-8")
    assert 'id="btn-rvr-resultado"' in html
    assert 'id="btn-vc-resultado"' in js
    assert "calcularResultadoBanca" in js
    assert "total_comision_cajeras" in js
    assert "rvrCeldasLoteria(b.loteria)" in js
    assert "MI CAJA no cambia" in js
    assert "navigator.share" in js
    assert "a.download" in js
    compacto = css.replace(" ", "")
    assert "#sec-reporte-tickets.rvr-scroll" in compacto
    assert "touch-action:pan-xpan-y" in compacto
    assert 'id="vc-resultado-desde"' in js and 'id="vc-resultado-hasta"' in js
    assert "Desde ${desde} · Hasta ${hasta}" in js
    assert "HASTA no puede ser anterior a DESDE" in js
    assert "const comision = centavos(p.comision);" in js
    assert "const quedo = ventas - premios - comision;" in js
    assert "no se resta otra vez" in js
    assert "resultado_periodo" in js


def _resultado_ui(venta, premios, comision):
    """La misma resta del botón: ventas − premios pagados − comisión ganada, una vez."""
    return Decimal(venta) - Decimal(premios) - Decimal(comision)


def test_resultado_resta_la_comision_ganada_una_vez_antes_y_despues_de_pagarla(entorno):
    """132,697 − 71,630 − 19,904.55 = 41,162.45 con la comisión pendiente y ya pagada.

    El pago no cierra el ciclo, no cambia MI CAJA y no cambia la fila de la banca.
    """
    suc = entorno.sucursal(codigo="R132", nombre="BANCA RESULTADO", comision=0)
    entorno.recargar(suc["id"], 300000)
    cajera = entorno.operador("cajera132", "1234", suc["id"])
    headers = entorno.login_terminal("cajera132", "1234")
    alta = entorno.c.post(
        "/comisiones",
        json={"usuario_id": cajera["id"], "porcentaje": 15},
        headers=entorno.admin,
    )
    assert alta.status_code in (200, 201), alta.text
    factor = entorno.c.post(
        "/tabla-pagos",
        json={"tipo": "QN", "clave": "1ro", "factor": 71.63, "vigente_desde": "2026-11-14 09:00"},
        headers=entorno.admin,
    )
    assert factor.status_code == 201, factor.text

    sorteo = entorno.sorteo_id("La Primera 12")
    for i, monto in enumerate([5000] * 26 + [1697], start=1):
        entorno.vender_ok(headers, [{
            "tipo": "QN", "sorteos": [sorteo], "numeros": f"{i:02d}", "monto": monto,
        }])
    ganador = entorno.vender_ok(headers, [{
        "tipo": "QN", "sorteos": [sorteo], "numeros": "77", "monto": 1000,
    }])
    entorno.liquidar(sorteo, 77, 98, 99)
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ganador["id"], "serial": ganador["serial"],
    }, headers=headers)
    assert pago.status_code == 200, pago.text

    def leer():
        reporte = entorno.c.get(
            f"/reportes/ventas-resumido?desde=2026-11-14&hasta=2026-11-14&sucursal_id={suc['id']}",
            headers=entorno.admin,
        )
        assert reporte.status_code == 200, reporte.text
        banca = _fila(reporte.json(), "BANCA RESULTADO")
        detalle = entorno.c.get(
            f"/reportes/ventas-cajeros/{cajera['id']}?desde=2026-11-14&hasta=2026-11-14",
            headers=entorno.admin,
        )
        assert detalle.status_code == 200, detalle.text
        return banca, detalle.json()

    banca, detalle = leer()
    com = detalle["comision"]
    resumen = detalle["resumen"]
    assert Decimal(banca["loteria"]["venta"]) == Decimal("132697.00")
    assert Decimal(banca["loteria"]["comision"]) == Decimal("19904.55")
    assert Decimal(banca["loteria"]["neto"]) == Decimal("112792.45")
    assert Decimal(banca["loteria"]["premios"]) == Decimal("71630.00")
    assert Decimal(banca["loteria"]["resultado"]) == Decimal("41162.45")
    assert Decimal(banca["resultado_total"]) == Decimal("41162.45")
    assert Decimal(banca["total_comision_cajeras"]) == Decimal("19904.55")
    assert _resultado_ui(
        banca["loteria"]["venta"], banca["loteria"]["premios"], banca["total_comision_cajeras"],
    ) == Decimal("41162.45")
    assert Decimal(resumen["ventas_ciclo"]) == Decimal("132697.00")
    assert Decimal(resumen["premios_pagados"]) == Decimal("71630.00")
    assert Decimal(com["comision_acumulada"]) == Decimal("19904.55")
    assert Decimal(com["comision_pendiente"]) == Decimal("19904.55")
    assert Decimal(com["comision_pagada"]) == Decimal("0.00")
    assert _resultado_ui(
        resumen["ventas_ciclo"], resumen["premios_pagados"], com["comision_acumulada"],
    ) == Decimal("41162.45")
    assert Decimal(detalle["resultado_periodo"]["quedo"]) == Decimal("41162.45")
    assert Decimal(detalle["resultado_periodo"]["comision"]) == Decimal("19904.55")
    mi_caja = Decimal(resumen["mi_caja"])
    saldo_banca = Decimal(str(entorno.saldo(suc["id"])))

    cobro = entorno.c.post("/comisiones/pagos", json={
        "usuario_id": cajera["id"], "monto": 19904.55, "operacion_id": "pago-comision-132",
    }, headers=entorno.admin)
    assert cobro.status_code == 201, cobro.text

    banca2, detalle2 = leer()
    com2 = detalle2["comision"]
    resumen2 = detalle2["resumen"]
    assert Decimal(banca2["loteria"]["venta"]) == Decimal("132697.00")
    assert Decimal(banca2["loteria"]["comision"]) == Decimal("19904.55")
    assert Decimal(banca2["loteria"]["neto"]) == Decimal("112792.45")
    assert Decimal(banca2["loteria"]["premios"]) == Decimal("71630.00")
    assert Decimal(banca2["loteria"]["resultado"]) == Decimal("41162.45")
    assert Decimal(banca2["resultado_total"]) == Decimal("41162.45")
    assert Decimal(banca2["total_comision_cajeras"]) == Decimal("19904.55")
    assert _resultado_ui(
        banca2["loteria"]["venta"], banca2["loteria"]["premios"], banca2["total_comision_cajeras"],
    ) == Decimal("41162.45")
    assert Decimal(resumen2["ventas_ciclo"]) == Decimal("132697.00")
    assert Decimal(resumen2["premios_pagados"]) == Decimal("71630.00")
    assert Decimal(com2["comision_acumulada"]) == Decimal("19904.55")
    assert Decimal(com2["comision_pagada"]) == Decimal("19904.55")
    assert Decimal(com2["comision_pendiente"]) == Decimal("0.00")
    assert _resultado_ui(
        resumen2["ventas_ciclo"], resumen2["premios_pagados"], com2["comision_acumulada"],
    ) == Decimal("41162.45")
    assert Decimal(detalle2["resultado_periodo"]["quedo"]) == Decimal("41162.45")
    assert Decimal(detalle2["resultado_periodo"]["comision"]) == Decimal("19904.55")
    assert Decimal(resumen2["mi_caja"]) == mi_caja
    assert Decimal(str(entorno.saldo(suc["id"]))) == saldo_banca
