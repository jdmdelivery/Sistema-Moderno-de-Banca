"""Compatibilidad APK 0.3.34 ↔ servidor con regla de dueño (pre-0.3.35).

Simula exactamente las llamadas del escáner PAGAR de 0.3.34:
POST /terminal/tickets/consultar y /pagar con {id, serial[, operacion_id]}.
No usa VER PREMIOS (solo existe en 0.3.35).
"""


def _fondo(entorno, usuario, sucursal_id, monto, op):
    users = entorno.c.get("/usuarios", headers=entorno.admin).json()
    uid = next(u["id"] for u in users if u["usuario"] == usuario)
    r = entorno.c.post("/fondos", json={
        "sucursal_id": sucursal_id, "usuario_id": uid, "monto": monto,
        "tipo": "aporte_prueba", "operacion_id": op,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _simular(entorno, sorteo, p1, p2=1, p3=2):
    r = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _apk034_consultar(entorno, headers, ticket):
    """Payload idéntico a PagarActivity.llave() de 0.3.34 (sin VER PREMIOS)."""
    return entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=headers)


def _apk034_pagar(entorno, headers, ticket, operacion_id):
    return entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": operacion_id,
    }, headers=headers)


def _campos_pantalla_pago(vista):
    """Campos que lee PagarActivity 0.3.34 para mostrar y habilitar cobro."""
    assert "texto_pago" in vista
    assert "puede_pagar" in vista
    cobrar = vista.get("importe_a_cobrar") or vista.get("premio_pendiente") or ""
    return cobrar


def test_034_escanea_y_paga_ticket_propio(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0, codigo="C034", usuario="caja034", clave="prueba123")
    _fondo(entorno, "caja034", b["sucursal"]["id"], 10000, "fondo-034-propio")
    h = entorno.login_terminal("caja034", "prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(h, [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, sorteo, 25)
    consulta = _apk034_consultar(entorno, h, ticket)
    assert consulta.status_code == 200, consulta.text
    vista = consulta.json()
    cobrar = _campos_pantalla_pago(vista)
    assert vista["puede_pagar"] is True
    assert float(cobrar) == 600.00
    assert "SE COBRARÁ" in vista["texto_pago"] or "PENDIENTE" in vista["texto_pago"].upper()
    caja0 = float(entorno.c.get("/terminal/sorteos", headers=h).json()["mi_caja"])
    pago = _apk034_pagar(entorno, h, ticket, "apk034-pago-1")
    assert pago.status_code == 200, pago.text
    datos = pago.json()
    assert datos["estado"] == "pagado"
    assert datos.get("comprobante")  # impresión local 0.3.34 usa este campo
    assert float(entorno.c.get("/terminal/sorteos", headers=h).json()["mi_caja"]) == caja0 - 600


def test_034_pago_parcial_varias_loterias(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0, codigo="C034P", usuario="caja034p", clave="prueba123")
    _fondo(entorno, "caja034p", b["sucursal"]["id"], 10000, "fondo-034-parcial")
    h = entorno.login_terminal("caja034p", "prueba123")
    a11 = entorno.sorteo_id("La Anguila 11:00 AM")
    a12 = entorno.sorteo_id("La Anguila 12:00 PM")
    ticket = entorno.vender_ok(h, [
        {"tipo": "QN", "sorteos": [a11, a12], "numeros": "25", "monto": 5},
    ])
    _simular(entorno, a11, 25)
    vista = _apk034_consultar(entorno, h, ticket).json()
    assert vista["puede_pagar"] is True
    assert float(vista["premio_pendiente"]) == 300.00
    assert len(vista["sorteos_pendientes"]) >= 1
    assert "SORTEOS PENDIENTES" in vista["texto_pago"] or len(vista["sorteos_pendientes"]) >= 1
    pago1 = _apk034_pagar(entorno, h, ticket, "apk034-parcial-1")
    assert pago1.status_code == 200, pago1.text
    assert pago1.json()["estado"] == "parcial"
    medio = _apk034_consultar(entorno, h, ticket).json()
    assert medio["puede_pagar"] is False  # solo queda sorteo sin liquidar
    assert "SORTEOS PENDIENTES" in medio["texto_pago"]
    _simular(entorno, a12, 25)
    segundo = _apk034_consultar(entorno, h, ticket).json()
    assert segundo["puede_pagar"] is True
    assert float(segundo["premio_pendiente"]) == 300.00
    pago2 = _apk034_pagar(entorno, h, ticket, "apk034-parcial-2")
    assert pago2.status_code == 200, pago2.text
    final = _apk034_consultar(entorno, h, ticket).json()
    assert final["puede_pagar"] is False
    assert final["estado"] == "pagado"


def test_034_reconoce_ticket_ya_pagado(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0, codigo="C034Y", usuario="caja034y", clave="prueba123")
    _fondo(entorno, "caja034y", b["sucursal"]["id"], 10000, "fondo-034-ya")
    h = entorno.login_terminal("caja034y", "prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(h, [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, sorteo, 25)
    assert _apk034_pagar(entorno, h, ticket, "apk034-ya-1").status_code == 200
    # Reescaneo 0.3.34: consulta muestra pagado y no ofrece cobro.
    vista = _apk034_consultar(entorno, h, ticket).json()
    assert vista["puede_pagar"] is False
    assert vista["estado"] == "pagado"
    assert "PAGADO" in vista.get("veredicto", "").upper() or "PAGADO" in vista["texto_pago"].upper()
    # Segundo intento con otra operacion_id → 409 (no doble cobro).
    doble = _apk034_pagar(entorno, h, ticket, "apk034-ya-2")
    assert doble.status_code == 409
    # Reintento idempotente con la misma operacion_id → 200 sin recobrar.
    idem = _apk034_pagar(entorno, h, ticket, "apk034-ya-1")
    assert idem.status_code == 200
    assert idem.json()["estado"] == "pagado"


def test_034_ticket_ajeno_bloqueado_pero_propio_sigue(entorno, monkeypatch):
    """Único cambio de comportamiento 0.3.34: tickets de otra cajera → 403."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    a = entorno.banca(saldo=0, codigo="C034A", usuario="a034", clave="prueba123")
    entorno.operador("b034", "prueba123", a["sucursal"]["id"])
    _fondo(entorno, "a034", a["sucursal"]["id"], 5000, "fondo-a034")
    _fondo(entorno, "b034", a["sucursal"]["id"], 5000, "fondo-b034")
    ha = entorno.login_terminal("a034", "prueba123")
    hb = entorno.login_terminal("b034", "prueba123")
    sorteo = entorno.sorteo_id("LOTEDOM")
    ta = entorno.vender_ok(ha, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    tb = entorno.vender_ok(hb, [{"tipo": "QN", "sorteos": [sorteo], "numeros": "25", "monto": 10}])
    _simular(entorno, sorteo, 25)
    assert _apk034_consultar(entorno, ha, tb).status_code == 403
    assert _apk034_pagar(entorno, ha, tb, "apk034-ajeno").status_code == 403
    assert _apk034_consultar(entorno, ha, ta).status_code == 200
    assert _apk034_pagar(entorno, ha, ta, "apk034-propio-ok").status_code == 200


def test_034_venta_reimpresion_anular_sorteos_intactos(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0, codigo="C034V", usuario="caja034v", clave="prueba123")
    _fondo(entorno, "caja034v", b["sucursal"]["id"], 3000, "fondo-034-venta")
    h = entorno.login_terminal("caja034v", "prueba123")
    # Menú / indicadores (lo que refresca VentaActivity).
    sorteos = entorno.c.get("/terminal/sorteos", headers=h)
    assert sorteos.status_code == 200
    assert "mi_caja" in sorteos.json()
    s = entorno.sorteo_id("LOTEDOM")
    # Venta QN (impresión usa respuesta de venta en cliente).
    venta = entorno.c.post("/terminal/venta", json={
        "jugadas": [{"tipo": "QN", "sorteos": [s], "numeros": "11", "monto": 10}],
        "operacion_id": "apk034-venta-1",
    }, headers=h)
    assert venta.status_code == 201, venta.text
    ticket = venta.json()
    assert ticket.get("serial")
    # Reimpresión.
    reprint = entorno.c.post("/terminal/tickets/reimprimir", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=h)
    assert reprint.status_code == 200, reprint.text
    # Anulación dentro de ventana.
    anula = entorno.c.post("/terminal/tickets/anular", json={
        "id": ticket["id"], "serial": ticket["serial"], "motivo": "compat 034",
    }, headers=h)
    assert anula.status_code == 200, anula.text
    # Resumen día (ResumenActivity 0.3.34).
    dia = entorno.c.get(
        "/terminal/reportes/dia?desde=2026-11-14&hasta=2026-11-14&alcance=cajero",
        headers=h,
    )
    assert dia.status_code == 200
