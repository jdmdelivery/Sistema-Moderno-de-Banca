"""VER PREMIOS / pago por escáner: solo tickets vendidos por la cajera autenticada.

Cubre consulta, pago, aislamiento entre cajeras/sucursales, parciales,
idempotencia, multi-lotería, sorteos pendientes, total pendientes y caja.
El panel sigue sin la restricción de vendedor.
"""


MSG = "ESTE TICKET PERTENECE A OTRA CAJERA"


def _fondo(entorno, usuario, sucursal_id, monto, op):
    users = entorno.c.get("/usuarios", headers=entorno.admin).json()
    uid = next(u["id"] for u in users if u["usuario"] == usuario)
    r = entorno.c.post("/fondos", json={
        "sucursal_id": sucursal_id, "usuario_id": uid, "monto": monto,
        "tipo": "aporte_prueba", "operacion_id": op,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _dos_cajeras(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    a = entorno.banca(saldo=0, codigo="VP01", nombre="BANCA VER PREMIOS",
                      usuario="cajera_a", clave="prueba123")
    entorno.operador("cajera_b", "prueba123", a["sucursal"]["id"])
    _fondo(entorno, "cajera_a", a["sucursal"]["id"], 10000, "fondo-vp-a")
    _fondo(entorno, "cajera_b", a["sucursal"]["id"], 10000, "fondo-vp-b")
    ha = entorno.login_terminal("cajera_a", "prueba123")
    hb = entorno.login_terminal("cajera_b", "prueba123")
    return a, ha, hb


def _vender_qn(entorno, headers, sorteo, numero="25", monto=10):
    return entorno.vender_ok(headers, [
        {"tipo": "QN", "sorteos": [sorteo], "numeros": numero, "monto": monto},
    ])


def _simular(entorno, sorteo, p1, p2=1, p3=2):
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text


def _ganar_qn(entorno, headers, numero="25", monto=10):
    sorteo = entorno.sorteo_id("LOTEDOM")
    ticket = _vender_qn(entorno, headers, sorteo, numero, monto)
    _simular(entorno, sorteo, int(numero))
    return ticket, sorteo


def _consultar(entorno, headers, ticket):
    return entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=headers)


def _pagar(entorno, headers, ticket, op):
    return entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": op,
    }, headers=headers)


def _pendientes(entorno, headers):
    return entorno.c.get(
        "/terminal/reportes/pendientes?desde=2026-11-14&hasta=2026-11-14&formato=json",
        headers=headers,
    )


def test_1_cajera_a_consulta_su_ticket(entorno, monkeypatch):
    _, ha, _ = _dos_cajeras(entorno, monkeypatch)
    ticket, _ = _ganar_qn(entorno, ha)
    r = _consultar(entorno, ha, ticket)
    assert r.status_code == 200, r.text
    assert r.json()["puede_pagar"] is True
    assert float(r.json()["premio_pendiente"]) == 600.00


def test_2_cajera_a_paga_su_ticket(entorno, monkeypatch):
    _, ha, _ = _dos_cajeras(entorno, monkeypatch)
    ticket, _ = _ganar_qn(entorno, ha)
    caja0 = float(entorno.c.get("/terminal/sorteos", headers=ha).json()["mi_caja"])
    r = _pagar(entorno, ha, ticket, "vp-pago-propio")
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "pagado"
    assert float(entorno.c.get("/terminal/sorteos", headers=ha).json()["mi_caja"]) == caja0 - 600


def test_3_cajera_a_consulta_ticket_de_b(entorno, monkeypatch):
    _, ha, hb = _dos_cajeras(entorno, monkeypatch)
    ticket_b, _ = _ganar_qn(entorno, hb, numero="25")
    r = _consultar(entorno, ha, ticket_b)
    assert r.status_code == 403
    assert r.json()["detail"] == MSG


def test_4_cajera_a_paga_ticket_de_b(entorno, monkeypatch):
    _, ha, hb = _dos_cajeras(entorno, monkeypatch)
    ticket_b, _ = _ganar_qn(entorno, hb, numero="25")
    r = _pagar(entorno, ha, ticket_b, "vp-pago-ajeno")
    assert r.status_code == 403
    assert r.json()["detail"] == MSG
    # Spoof de cajero_id en el cuerpo no cambia la decisión del servidor.
    spoof = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket_b["id"], "serial": ticket_b["serial"],
        "operacion_id": "vp-spoof", "cajero_id": 99999, "vendedor_id": 1,
    }, headers=ha)
    assert spoof.status_code == 403


def test_5_ticket_otra_sucursal(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    a = entorno.banca(saldo=5000, codigo="VP02", nombre="BANCA A", usuario="caja_suc_a", clave="1234")
    b = entorno.banca(saldo=5000, codigo="VP03", nombre="BANCA B", usuario="caja_suc_b", clave="1234")
    ticket, _ = _ganar_qn(entorno, a["headers"])
    assert _consultar(entorno, b["headers"], ticket).status_code == 403
    assert _pagar(entorno, b["headers"], ticket, "vp-otra-suc").status_code == 403
    # Panel admin sigue pudiendo consultar/pagar.
    panel = entorno.c.post("/panel/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=entorno.admin)
    assert panel.status_code == 200


def test_6_pago_parcial(entorno, monkeypatch):
    a, ha, _ = _dos_cajeras(entorno, monkeypatch)
    a11 = entorno.sorteo_id("La Anguila 11:00 AM")
    a12 = entorno.sorteo_id("La Anguila 12:00 PM")
    ticket = entorno.vender_ok(ha, [
        {"tipo": "QN", "sorteos": [a11, a12], "numeros": "25", "monto": 5},
    ])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": a11, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    vista = _consultar(entorno, ha, ticket).json()
    assert vista["puede_pagar"] is True
    assert float(vista["premio_pendiente"]) == 300.00
    assert len(vista["sorteos_pendientes"]) >= 1
    pago = _pagar(entorno, ha, ticket, "vp-parcial-1")
    assert pago.status_code == 200
    assert pago.json()["estado"] == "parcial"


def test_7_segundo_intento_idempotente(entorno, monkeypatch):
    _, ha, _ = _dos_cajeras(entorno, monkeypatch)
    ticket, _ = _ganar_qn(entorno, ha)
    op = "vp-idempotente"
    assert _pagar(entorno, ha, ticket, op).status_code == 200
    segundo = _pagar(entorno, ha, ticket, op)
    assert segundo.status_code == 200
    assert segundo.json()["estado"] == "pagado"
    otro = _pagar(entorno, ha, ticket, "vp-otro-op")
    assert otro.status_code == 409


def test_8_varias_loterias_solo_confirmadas(entorno, monkeypatch):
    _, ha, _ = _dos_cajeras(entorno, monkeypatch)
    lotedom = entorno.sorteo_id("LOTEDOM")
    anguila = entorno.sorteo_id("La Anguila 1:00 PM")
    ticket = entorno.vender_ok(ha, [
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [anguila], "numeros": "25", "monto": 5},
    ])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": lotedom, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    vista = _consultar(entorno, ha, ticket).json()
    assert float(vista["premio_pendiente"]) == 600.00
    assert len(vista["premios_por_pagar"]) >= 1
    assert len(vista["sorteos_pendientes"]) >= 1
    pend = _pendientes(entorno, ha)
    assert pend.status_code == 200
    fila = next(p for p in pend.json()["pendientes"] if p["id"] == ticket["id"])
    assert "lineas_premio" in fila
    assert fila["puede_pagar"] is True
    assert any(l.get("estado") == "PENDIENTE" for l in fila["lineas_premio"])
    assert len(fila.get("sorteos_pendientes") or []) >= 1


def test_9_sorteos_pendientes_conservados(entorno, monkeypatch):
    _, ha, _ = _dos_cajeras(entorno, monkeypatch)
    a11 = entorno.sorteo_id("La Anguila 11:00 AM")
    a12 = entorno.sorteo_id("La Anguila 12:00 PM")
    ticket = entorno.vender_ok(ha, [
        {"tipo": "QN", "sorteos": [a11, a12], "numeros": "25", "monto": 5},
    ])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": a11, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    _pagar(entorno, ha, ticket, "vp-deja-pendiente")
    vista = _consultar(entorno, ha, ticket).json()
    assert "SORTEOS PENDIENTES" in vista.get("texto_pago", "")
    assert vista["puede_pagar"] is False


def test_10_actualizacion_total_premios(entorno, monkeypatch):
    _, ha, hb = _dos_cajeras(entorno, monkeypatch)
    sorteo = entorno.sorteo_id("LOTEDOM")
    ta = _vender_qn(entorno, ha, sorteo, "25")
    tb = _vender_qn(entorno, hb, sorteo, "25")
    _simular(entorno, sorteo, 25)
    antes = _pendientes(entorno, ha).json()
    assert float(antes["monto_pendiente"]) == 600.00
    assert [p["id"] for p in antes["pendientes"]] == [ta["id"]]
    # B ve solo el suyo.
    pend_b = _pendientes(entorno, hb).json()
    assert [p["id"] for p in pend_b["pendientes"]] == [tb["id"]]
    assert _pagar(entorno, ha, ta, "vp-baja-total").status_code == 200
    despues = _pendientes(entorno, ha).json()
    assert float(despues["monto_pendiente"]) == 0.00
    assert despues["pendientes"] == []


def test_11_descuento_caja(entorno, monkeypatch):
    _, ha, _ = _dos_cajeras(entorno, monkeypatch)
    ticket, _ = _ganar_qn(entorno, ha)
    ind0 = entorno.c.get("/terminal/sorteos", headers=ha).json()
    caja0 = float(ind0["mi_caja"])
    pend0 = float(ind0["premios_por_pagar"])
    assert pend0 == 600.00
    assert _pagar(entorno, ha, ticket, "vp-caja").status_code == 200
    ind1 = entorno.c.get("/terminal/sorteos", headers=ha).json()
    assert float(ind1["mi_caja"]) == caja0 - 600
    assert float(ind1["premios_por_pagar"]) == 0.00


def test_12_compat_apk_antigua_sigue_bloqueada_en_servidor(entorno, monkeypatch):
    """APK 0.3.34 (sin VER PREMIOS) también choca con el 403 del servidor."""
    _, ha, hb = _dos_cajeras(entorno, monkeypatch)
    ticket_b, _ = _ganar_qn(entorno, hb)
    # Misma llamada que haría el escáner de 0.3.34 / 0.3.35.
    for headers in (ha,):
        c = _consultar(entorno, headers, ticket_b)
        p = _pagar(entorno, headers, ticket_b, "vp-apk-old")
        assert c.status_code == 403 and c.json()["detail"] == MSG
        assert p.status_code == 403 and p.json()["detail"] == MSG
    # La dueña sigue pudiendo operar (0.3.34 y 0.3.35).
    assert _consultar(entorno, hb, ticket_b).status_code == 200
    assert _pagar(entorno, hb, ticket_b, "vp-apk-own").status_code == 200
