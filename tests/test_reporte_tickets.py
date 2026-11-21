"""Menú de administradores y reporte de tickets (consulta local)."""
from pathlib import Path

import pypdfium2 as pdfium

RAIZ = Path(__file__).resolve().parent.parent
HTML = (RAIZ / "apps" / "web" / "index.html").read_text(encoding="utf-8")
JS = (RAIZ / "apps" / "web" / "app.js").read_text(encoding="utf-8")


def _nav(grupo):
    ini = HTML.index(f'data-grupo="{grupo}"')
    fin = HTML.index("</div>", HTML.index("nav-grupo-items", ini))
    return HTML[ini:fin]


def test_menu_admin_agrupa_sin_duplicar_reportes():
    orden = [
        HTML.index('data-grupo="inicio"'),
        HTML.index('data-grupo="operaciones"'),
        HTML.index('data-grupo="personal"'),
        HTML.index('data-grupo="reportes"'),
        HTML.index('data-grupo="config"'),
    ]
    assert orden == sorted(orden)
    assert "Cajeros</button>" not in HTML.split("<main")[0]
    personal = _nav("personal")
    assert 'data-sec="usuarios"' in personal
    assert 'data-sec="control-cajeros"' in personal
    assert 'data-sec="ventas-cajeros"' not in personal
    reportes = HTML.split('data-grupo="reportes"', 1)[1].split('data-grupo="config"', 1)[0]
    assert 'data-sec="reportes"' in reportes
    assert 'data-sec="ventas-cajeros"' in reportes
    assert "Centro de ventas resumida" in reportes
    centro = reportes.split('data-sub="centro-ventas"', 1)[1].split('data-sec="ventas-cajeros"', 1)[0]
    assert centro.index('data-sec="ventas-resumido"') < centro.index('data-sec="reporte-tickets"')
    assert reportes.count('data-sec="ventas-resumido"') == 1
    assert reportes.count('data-sec="reporte-tickets"') == 1
    assert reportes.index('data-sec="reportes"') < reportes.index('data-sub="centro-ventas"')
    assert reportes.index('data-sub="centro-ventas"') < reportes.index('data-sec="ventas-cajeros"')
    assert "sincronizarCentroVentas" in JS
    sucursal = HTML.split('id="sec-reportes"')[1].split("</section>")[0]
    assert "Resumen de ventas" in sucursal
    assert "Ventas por usuario" in sucursal
    assert "Tickets pendientes de pago" in sucursal
    assert 'id="sec-reporte-tickets"' not in sucursal
    tickets = HTML.split('id="sec-tickets"')[1].split("</section>")[0]
    assert "PAGAR TICKET" in tickets
    assert "ANULAR TICKET" in tickets
    assert "ELIMINAR / ANULAR" in tickets


def test_reporte_tickets_filtra_banca_y_pdf(entorno):
    a = entorno.banca(saldo=5000, codigo="TK01", nombre="BANCA TICKET A", usuario="tka")
    b = entorno.banca(saldo=5000, codigo="TK02", nombre="BANCA TICKET B", usuario="tkb")
    s = entorno.sorteo_id("La Primera 12")
    jugada = {"tipo": "QN", "sorteos": [s], "numeros": "15", "monto": 25}
    ta = entorno.vender_ok(a["headers"], [jugada])
    tb = entorno.vender_ok(b["headers"], [jugada])
    q = "desde=2026-11-14&hasta=2026-11-14"
    anon = entorno.c.get(f"/reportes/tickets?{q}")
    assert anon.status_code == 401
    r = entorno.c.get(
        f"/reportes/tickets?{q}&sucursal_id={a['sucursal']['id']}",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    ids = [t["id"] for t in datos["tickets"]]
    assert ta["id"] in ids
    assert tb["id"] not in ids
    assert datos["filtros"]["banca"].startswith("TK01")
    assert datos["tickets"][0]["estado"]
    uno = entorno.c.get(
        f"/reportes/tickets?{q}&ticket_id={ta['id']}&estado=vendido",
        headers=entorno.admin,
    )
    assert uno.status_code == 200
    assert [t["id"] for t in uno.json()["tickets"]] == [ta["id"]]
    pdf = entorno.c.get(
        f"/reportes/tickets.pdf?{q}&sucursal_id={a['sucursal']['id']}",
        headers=entorno.admin,
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")
    doc = pdfium.PdfDocument(pdf.content)
    assert len(doc) >= 1
    ancho, alto = doc[0].get_size()
    assert ancho > alto
    texto = doc[0].get_textpage().get_text_bounded()
    assert "BANCA TICKET A" in texto
    assert "BANCA TICKET B" not in texto
    assert str(ta["id"]) in texto
    assert "14/11/2026" in texto
    assert "reporte-tickets" in JS
    assert "/reportes/tickets.pdf" in JS
    assert "Usuario que pagó" in JS
    assert "rtk-hora-desde" in HTML
    assert "Ordenar por" in HTML


def test_reporte_tickets_hora_loteria_pago_y_grupos(entorno, monkeypatch):
    from datetime import datetime

    from apps.api import db as dbmod
    from apps.api.models import Ticket

    b = entorno.banca(saldo=8000, codigo="TK03", nombre="BANCA TICKET C", usuario="tkc")
    suerte = entorno.sorteo_id("La Suerte 12:30")
    primera = entorno.sorteo_id("La Primera 12")
    a = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [suerte], "numeros": "15", "monto": 10},
    ])
    pagado = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [primera], "numeros": "19", "monto": 20},
    ])
    sesion = dbmod.nueva_sesion()
    guardado = sesion.get(Ticket, pagado["id"])
    guardado.vendido_en = datetime(2026, 11, 14, 15, 30, 0)
    sesion.commit()
    sesion.close()
    entorno.liquidar(primera, 19, 3, 4)
    pago = entorno.c.post("/panel/tickets/pagar", json={
        "id": pagado["id"], "serial": pagado["serial"], "sucursal_id": b["sucursal"]["id"],
    }, headers=entorno.admin)
    assert pago.status_code == 200, pago.text
    anulado = entorno.c.post("/panel/tickets/anular", json={
        "id": a["id"], "serial": a["serial"], "motivo": "prueba de reporte",
    }, headers=entorno.admin)
    assert anulado.status_code == 200, anulado.text

    monkeypatch.setenv("MODO_DESARROLLO", "true")
    anguila = entorno.sorteo_id("La Anguila 11:00 AM")
    otra = entorno.sorteo_id("La Anguila 12:00 PM")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"],
        "usuario_id": next(u["id"] for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "tkc"),
        "monto": 5000, "tipo": "aporte_prueba", "operacion_id": "fondo-reporte-tickets",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    parcial = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [anguila, otra], "numeros": "25", "monto": 5},
    ])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": anguila, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    cobro = entorno.c.post("/terminal/tickets/pagar", json={
        "id": parcial["id"], "serial": parcial["serial"], "operacion_id": "op-reporte-parcial",
    }, headers=b["headers"])
    assert cobro.status_code == 200, cobro.text
    assert cobro.json()["estado"] == "parcial"
    sim2 = entorno.c.post("/resultados", json={
        "sorteo_id": otra, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 3, "premio3": 4, "simulado": True,
    }, headers=entorno.admin)
    assert sim2.status_code == 201, sim2.text
    sesion = dbmod.nueva_sesion()
    guardado = sesion.get(Ticket, parcial["id"])
    guardado.vendido_en = datetime(2026, 11, 14, 15, 40, 0)
    sesion.commit()
    sesion.close()

    q = "desde=2026-11-14&hasta=2026-11-14"
    todos = entorno.c.get(f"/reportes/tickets?{q}&orden=numero", headers=entorno.admin)
    assert todos.status_code == 200, todos.text
    datos = todos.json()
    assert datos["filtros"]["orden"] == "numero"
    assert datos["agrupar_estado"] is True
    previo = None
    for fila in datos["tickets"]:
        if previo is not None and previo["estado"] == fila["estado"]:
            assert fila["id"] > previo["id"]
        previo = fila
    solo_pagados = entorno.c.get(f"/reportes/tickets?{q}&estado=pagado", headers=entorno.admin)
    assert solo_pagados.status_code == 200
    ids_pagados = [t["id"] for t in solo_pagados.json()["tickets"]]
    assert ids_pagados == sorted(ids_pagados)
    assert solo_pagados.json()["agrupar_estado"] is False
    etiquetas = {g["etiqueta"]: g["cantidad"] for g in datos["grupos"]}
    assert etiquetas.get("Anulados", 0) >= 1
    assert etiquetas.get("Pagados", 0) >= 1
    assert etiquetas.get("Parcialmente pagados", 0) >= 1
    fila_pagada = next(t for t in datos["tickets"] if t["id"] == pagado["id"])
    assert fila_pagada["usuario_pago"]
    assert fila_pagada["fecha_pago"].startswith("2026-11-14")
    assert fila_pagada["usuario_anulo"] == ""
    assert float(fila_pagada["premio_total"]) > 0
    fila_anulada = next(t for t in datos["tickets"] if t["id"] == a["id"])
    assert fila_anulada["usuario_anulo"]
    assert fila_anulada["fecha_anulacion"]
    assert fila_anulada["usuario_pago"] == ""
    assert fila_anulada["fecha_pago"] == ""

    horas = entorno.c.get(
        f"/reportes/tickets?{q}&hora_desde=15:00&hora_hasta=16:00&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    )
    assert horas.status_code == 200, horas.text
    ids_hora = [t["id"] for t in horas.json()["tickets"]]
    assert pagado["id"] in ids_hora
    assert parcial["id"] in ids_hora
    assert a["id"] not in ids_hora

    loteria = entorno.c.get(
        f"/reportes/tickets?{q}&sorteo_id={primera}&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    )
    assert loteria.status_code == 200, loteria.text
    assert [t["id"] for t in loteria.json()["tickets"]] == [pagado["id"]]
    assert loteria.json()["filtros"]["loteria"]

    detalle = entorno.c.get(f"/reportes/tickets/{parcial['id']}", headers=entorno.admin)
    assert detalle.status_code == 200, detalle.text
    cuerpo = detalle.json()
    assert cuerpo["jugadas"]
    assert float(cuerpo["premio_ganado"]) > float(cuerpo["importe_pagado"]) > 0
    assert len(cuerpo["pagos"]) >= 1
    assert "comprobante" not in cuerpo
    assert "puede_anular" not in cuerpo
    assert len(cuerpo["grupos"]) >= 2
    nombres = " ".join(
        s["nombre"] for g in cuerpo["grupos"] for s in g["sorteos"]
    )
    assert "Anguila 11" in nombres and "Anguila 12" in nombres
    pdf_det = entorno.c.get(f"/reportes/tickets/{parcial['id']}/pdf", headers=entorno.admin)
    assert pdf_det.status_code == 200
    assert pdf_det.content.startswith(b"%PDF-")
    det_doc = pdfium.PdfDocument(pdf_det.content)
    det_texto = det_doc[0].get_textpage().get_text_bounded()
    assert f"Ticket #{parcial['id']}" in det_texto
    assert "Anguila" in det_texto
    assert "11:00 AM · 11:00 AM" not in det_texto
    assert "Total apostado" in det_texto and "Saldo pendiente" in det_texto
    assert "Historial de pagos" in det_texto
    assert 'id="rtk-modal"' not in HTML
    assert "Volver al listado" in HTML

    assert entorno.c.get(f"/reportes/tickets?{q}&grupo_id=principal", headers=entorno.admin).status_code == 200
    raro = entorno.c.get(f"/reportes/tickets?{q}&grupo_id=otro", headers=entorno.admin)
    assert raro.status_code == 400
    ruta = entorno.c.get(f"/reportes/tickets?{q}&ruta_id=1", headers=entorno.admin)
    assert ruta.status_code == 400

    pdf = entorno.c.get(
        f"/reportes/tickets.pdf?{q}&sucursal_id={b['sucursal']['id']}",
        headers=entorno.admin,
    )
    assert pdf.status_code == 200
    doc = pdfium.PdfDocument(pdf.content)
    texto = "\n".join(pagina.get_textpage().get_text_bounded() for pagina in doc)
    assert "Pagados" in texto
    assert "Anulados" in texto
    assert "Parcialmente pagados" in texto
    assert "BANCA TICKET C" in texto
    assert str(pagado["id"]) in texto
    assert "14/11/2026" in texto
    assert "Operador tkc" in texto
    assert "Usuario que pagó" in texto


def test_cajero_en_todos_los_estados_y_dos_recibos(entorno):
    import io

    from PIL import Image

    from apps.api import db as dbmod
    from apps.api.models import Ticket

    b = entorno.banca(saldo=8000, codigo="TKR1", nombre="BANCA CASTILLO", usuario="vendrecibo")
    sid = b["sucursal"]["id"]
    primera = entorno.sorteo_id("La Primera 12")
    vendido = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [primera], "numeros": "07", "monto": 10},
    ])
    otro = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [primera], "numeros": "08", "monto": 20},
    ])
    anulado = entorno.c.post("/panel/tickets/anular", json={
        "id": vendido["id"], "serial": vendido["serial"], "motivo": "sigue mostrando al cajero",
    }, headers=entorno.admin)
    assert anulado.status_code == 200, anulado.text
    sesion = dbmod.nueva_sesion()
    try:
        fila = sesion.get(Ticket, otro["id"])
        fila.usuario_id = None
        sesion.commit()
    finally:
        sesion.close()

    q = f"desde=2026-11-14&hasta=2026-11-14&sucursal_id={sid}"
    r = entorno.c.get(f"/reportes/tickets?{q}", headers=entorno.admin)
    assert r.status_code == 200, r.text
    por_id = {t["id"]: t for t in r.json()["tickets"]}
    assert por_id[vendido["id"]]["estado"] == "anulado"
    assert por_id[vendido["id"]]["cajera"] == "Operador vendrecibo"
    assert por_id[vendido["id"]]["usuario_pago"] == ""
    assert por_id[otro["id"]]["estado"] == "vendido"
    assert por_id[otro["id"]]["cajera"] == "Cajero sin registrar"

    pdf = entorno.c.get(f"/reportes/tickets.pdf?{q}", headers=entorno.admin)
    assert pdf.status_code == 200, pdf.text
    doc = pdfium.PdfDocument(pdf.content)
    texto = "\n".join(p.get_textpage().get_text_bounded() for p in doc)
    assert "Operador vendrecibo" in texto
    assert "Cajero sin registrar" in texto
    assert "Usuario que pagó" in texto
    assert "BANCA CASTILLO" in texto

    def png(ticket_id):
        img = entorno.c.get(f"/reportes/tickets/{ticket_id}/imagen", headers=entorno.admin)
        assert img.status_code == 200, img.text
        assert img.headers["content-type"] == "image/png"
        assert img.content.startswith(b"\x89PNG")
        im = Image.open(io.BytesIO(img.content))
        assert im.width == 384
        assert im.height > 200
        return img.content

    assert png(vendido["id"]) != png(otro["id"])
    assert entorno.c.get(f"/reportes/tickets/{vendido['id']}/imagen").status_code == 401
    recibo = entorno.c.get(
        f"/reportes/tickets/{vendido['id']}/recibo.pdf", headers=entorno.admin,
    )
    assert recibo.status_code == 200, recibo.text
    assert recibo.content.startswith(b"%PDF-")
    hoja = pdfium.PdfDocument(recibo.content)
    ancho, alto = hoja[0].get_size()
    assert alto > ancho
    assert "Cajero sin registrar" in JS
    assert "rtk-recibo" in JS
    assert "rtk-vendedor" in JS
    assert "/imagen" in JS
    assert "recibo.pdf" in JS
    assert "volverListadoTickets" in JS
