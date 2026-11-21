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
    # Comisión sucursal por defecto 10 %
    s = entorno.sorteo_id("La Primera 12")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "11", "monto": 100}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "12", "monto": 50}])

    datos = _get(entorno, f"&sucursal_id={b['sucursal']['id']}")
    assert datos["total"]["bancas"] == 1
    fila = _fila(datos, "BANCA FORMULA")
    assert Decimal(fila["loteria"]["venta"]) == Decimal("150.00")
    assert Decimal(fila["loteria"]["comision"]) == Decimal("15.00")  # 10 %
    assert Decimal(fila["loteria"]["neto"]) == Decimal("135.00")  # venta - comisión
    assert Decimal(fila["loteria"]["premios"]) == Decimal("0")
    assert Decimal(fila["loteria"]["resultado"]) == Decimal("135.00")
    assert Decimal(fila["resultado_total"]) == Decimal("135.00")
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
    assert "Resumen-de-Ventas-" in r.headers["content-disposition"]
    doc = _pdf(r.content)
    assert len(doc) == 1
    texto = _texto(doc)[0]
    assert "BANCA PREMIO" in texto
    assert formato_monto("-591.00") in texto
    anon = entorno.c.get("/reportes/ventas-resumido.pdf?desde=2026-11-14&hasta=2026-11-14")
    assert anon.status_code == 401


def test_el_boton_pdf_no_usa_el_dialogo_de_windows():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    css = (raiz / "apps" / "web" / "style.css").read_text(encoding="utf-8")
    assert "/reportes/ventas-resumido.pdf" in js
    assert "abrirDocumentoVentasResumido" not in js
    assert "Guardar como PDF" not in js
    assert "a.download" in js
    assert "size: A4 landscape" in css
    assert "table-header-group" in css


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
    js = (Path(__file__).resolve().parent.parent / "apps" / "web" / "app.js").read_text(encoding="utf-8")
    assert "mostrarCajeros" in js
    assert 'id="btn-rvr-todos"' in js or "btn-rvr-todos" in js

    norte = entorno.banca(saldo=50000, codigo="VC01", nombre="BANCA NORTE CAJ", usuario="vcn1")
    sur = entorno.banca(saldo=50000, codigo="VC02", nombre="BANCA SUR CAJ", usuario="vcs1")
    entorno.operador("vcn2", "1234", norte["sucursal"]["id"])
    h2 = entorno.login_terminal("vcn2", "1234")
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
    assert Decimal(fila_n["loteria"]["premios"]) == Decimal("0")
    assert [c["nombre"] for c in fila_s["cajeros"]] == ["Operador vcs1"]
    assert Decimal(fila_s["cajeros"][0]["venta"]) == Decimal(fila_s["loteria"]["venta"]) == Decimal("200.00")
    assert Decimal(fila_s["loteria"]["comision"]) == Decimal("20.00")

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
    """18–19/11/2026: RD$34,633.00 al 15% dan RD$5,194.95.

    Isaury pagó RD$12,040.00 y Wanda RD$17,400.00. El subtotal de la banca
    no suma otra vez esas filas.
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
    entorno.liquidar(s12, 25, 1, 2)
    pago_isa = entorno.c.post("/terminal/tickets/pagar", json={
        "id": parcial["id"], "serial": parcial["serial"], "confirmar_caja_negativa": True,
    }, headers=banca["headers"])
    assert pago_isa.status_code == 200, pago_isa.text
    assert pago_isa.json()["estado"] == "parcial"
    completo = entorno.vender_ok(hw, [{
        "tipo": "QN", "sorteos": [suerte], "numeros": "33", "monto": 5,
    }])
    entorno.liquidar(suerte, 33, 4, 8)
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
        for ticket in db.query(Ticket).filter(Ticket.sucursal_vendedora_id == sucursal_id):
            if D(ticket.total) >= 1000:
                ticket.fecha = date(2026, 11, 18)
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
    assert Decimal(fila["loteria"]["comision"]) == Decimal("3463.30")
    assert Decimal(fila["loteria"]["neto"]) == Decimal("31169.70")
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
    assert sum((Decimal(c["premios"]) for c in fila["cajeros"]), Decimal("0")) == Decimal("29440.00")
    assert Decimal(datos["total"]["loteria"]["venta"]) == Decimal("34633.00")
    assert Decimal(datos["total"]["loteria"]["comision"]) == Decimal(fila["loteria"]["comision"])
    assert Decimal(datos["total"]["loteria"]["premios"]) == Decimal(fila["loteria"]["premios"])
    assert Decimal(datos["total"]["loteria"]["comision"]) != Decimal("5194.95")

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


def test_cajero_sin_venta_entra_por_premio_y_no_mezcla_prueba(entorno, monkeypatch):
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
    assert [c["nombre"] for c in fila["cajeros"]] == ["Operador solopago"]
    cajero = fila["cajeros"][0]
    assert cajero["usuario_id"] == solo["id"]
    assert Decimal(cajero["venta"]) == Decimal("0.00")
    assert Decimal(cajero["comision"]) == Decimal("0.00")
    assert Decimal(cajero["premios"]) == Decimal("600.00")
    assert Decimal(cajero["neto"]) == Decimal("0.00")
    assert Decimal(cajero["resultado"]) == Decimal("-600.00")

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
