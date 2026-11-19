"""Ventas por cajero: premios al pagador, fondo separado, permisos admin."""
from datetime import datetime


def test_dos_cajeros_separados_y_premio_de_otro(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    a = entorno.banca(saldo=5000, usuario="vc1", clave="prueba123")
    entorno.operador("vc2", "prueba123", a["sucursal"]["id"])
    paga = entorno.login_terminal("vc2", "prueba123")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    vc1 = next(u for u in usuarios if u["usuario"] == "vc1")
    vc2 = next(u for u in usuarios if u["usuario"] == "vc2")
    fondo_vc1 = entorno.c.post("/fondos", json={
        "sucursal_id": a["sucursal"]["id"], "usuario_id": vc1["id"], "monto": 1000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-vc1",
    }, headers=entorno.admin)
    assert fondo_vc1.status_code == 201, fondo_vc1.text
    fondo_vc2 = entorno.c.post("/fondos", json={
        "sucursal_id": a["sucursal"]["id"], "usuario_id": vc2["id"], "monto": 500,
        "tipo": "aporte_prueba", "operacion_id": "fondo-vc2",
    }, headers=entorno.admin)
    assert fondo_vc2.status_code == 201, fondo_vc2.text
    lot = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    entorno.vender_ok(paga, [{"tipo": "QN", "sorteos": [lot], "numeros": "11", "monto": 5}])
    sim = entorno.c.post("/resultados", json={
        "sorteo_id": lot, "fecha": "2026-11-14", "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert sim.status_code == 201, sim.text
    # Terminal: otra cajera de la misma sucursal NO puede pagar el ticket ajeno.
    ajeno = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "pago-vc2-bloqueado",
    }, headers=paga)
    assert ajeno.status_code == 403, ajeno.text
    assert "OTRA CAJERA" in ajeno.json()["detail"]
    # Solo la cajera vendedora cobra; el premio se atribuye al pagador (= vendedor).
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": t["id"], "serial": t["serial"], "operacion_id": "pago-vc1",
    }, headers=a["headers"])
    assert pago.status_code == 200, pago.text

    r = entorno.c.get("/reportes/ventas-cajeros?desde=2026-11-14&hasta=2026-11-14", headers=entorno.admin)
    assert r.status_code == 200, r.text
    filas = {f["usuario"]: f for f in r.json()["cajeros"]}
    assert "vc1" in filas and "vc2" in filas
    assert float(filas["vc1"]["ventas_netas"]) == 10
    assert float(filas["vc1"]["premios_pagados"]) == 600  # vendió y cobró
    assert float(filas["vc2"]["ventas_netas"]) == 5
    assert float(filas["vc2"]["premios_pagados"]) == 0  # no pudo cobrar el ajeno
    assert float(filas["vc1"]["fondo_asignado"]) == 1000
    assert float(filas["vc2"]["fondo_asignado"]) == 500
    assert float(filas["vc2"]["recaudacion"]) == 5

    det = entorno.c.get(
        f"/reportes/ventas-cajeros/{vc1['id']}?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert det.status_code == 200
    assert det.json()["premios_pagados"]
    assert det.json()["premios_pagados"][0]["vendedor_usuario"] == "vc1"


def test_supervisor_no_ve_ventas_cajeros(entorno):
    entorno.c.post("/usuarios", json={
        "nombre": "SUPER VC", "usuario": "supvc", "rol": "supervisor", "clave": "prueba123", "activo": True,
    }, headers=entorno.admin)
    login = entorno.c.post("/auth/login", json={"usuario": "supvc", "clave": "prueba123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    r = entorno.c.get("/reportes/ventas-cajeros", headers=headers)
    assert r.status_code == 403


def test_panel_tiene_seccion_ventas_cajeros(entorno):
    html = entorno.c.get("/").text
    assert 'data-sec="ventas-cajeros"' in html
    assert 'id="sec-ventas-cajeros"' in html
    assert 'id="vc-lista"' in html
    assert 'vc-lista' in html
    assert 'id="vc-modal-volver"' in html
    assert "VOLVER A USUARIOS" in html
    js = entorno.c.get("/static/app.js").text
    assert "cargarVentasCajeros" in js
    assert "verDetalleCajero" in js
    assert "filaCajeroCompacta" in js
    assert "cerrarDetalleCajero" in js
    assert "VC_DETALLE_SCROLL" in js
    assert "VER DETALLE" in js
    assert "vc-card" in js
    assert "vc-hist" in js
    assert "COMISIÓN GANADA" in js
    assert "BALANCE DE COMISIÓN" in js
    assert "PORCENTAJE VIGENTE" in js
    assert "PAGAR COMISIÓN Y CERRAR CICLO" in js
    assert "cerrarCicloCajeraPerfil" in js
    assert "refrescarDashboardCajeroTrasCierre" in js
    assert "/comisiones/cierres" in js
    assert "vc-comision-card" in js
    assert "porcentaje_vigente" in js
    assert "Ventas del ciclo" in js
    assert "Premios del ciclo" in js
    assert "MI CAJA" in js
    # Dashboard RESUMEN: sin tarjeta Comisión; el cálculo/API y el perfil siguen.
    assert "function tarjetasInicio" in js
    assert '[fmt(bloque.comision), "Comisión"]' not in js
    assert 'fmt(bloque.ventas), "Ventas"' in js
    assert 'fmt(bloque.neto), "Neto"' in js
    # Panel reducido: sin acumulada/pagada ni pago parcial en UI.
    assert "Comisión acumulada" not in js
    assert "Comisión pagada" not in js
    assert "COMISIÓN PENDIENTE" not in js
    assert "data-pagar-comision-cajera" not in js
    assert "pagarComisionCajeraPerfil" not in js
    # Perfil simplificado: brutas/anulaciones/recaudación siguen en API, no en tarjetas.
    assert "Ventas brutas" not in js
    assert ">Anulaciones<" not in js and "Anulaciones</span>" not in js
    assert "Recaudación del período" not in js
    css = entorno.c.get("/static/style.css").text
    assert ".vc-card" in css
    assert ".vc-lista" in css
    assert ".vc-volver" in css
    assert ".vc-detalle-hero" in css
    assert ".vc-hist" in css
    assert ".vc-comision-card" in css
    assert ".vc-comision-grid" in css
    assert ".vc-comision-grid-simple" in css
    assert ".vc-comision-pendiente" in css
    assert ".vc-monto-dest" in css
    assert "auto-fit" in css and "cards-inicio" in css


def test_lista_compacta_coincide_con_detalle(entorno, monkeypatch, fijar_hora):
    """La fila compacta usa las mismas ventas_netas / tickets que el detalle."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    a = entorno.banca(saldo=5000, usuario="vc3", clave="prueba123")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "07", "monto": 20}])
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "08", "monto": 15}])
    lista = entorno.c.get(
        "/reportes/ventas-cajeros?desde=2026-11-14&hasta=2026-11-14&usuario_id="
        + str(next(u["id"] for u in entorno.c.get("/usuarios", headers=entorno.admin).json() if u["usuario"] == "vc3")),
        headers=entorno.admin,
    )
    assert lista.status_code == 200, lista.text
    fila = lista.json()["cajeros"][0]
    det = entorno.c.get(
        f"/reportes/ventas-cajeros/{fila['usuario_id']}?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert det.status_code == 200, det.text
    r = det.json()["resumen"]
    assert r["ventas_netas"] == fila["ventas_netas"]
    assert r["tickets_vendidos"] == fila["tickets_vendidos"]
    assert r["premios_pagados"] == fila["premios_pagados"]
    assert r["mi_caja"] == fila["mi_caja"]
    assert float(fila["ventas_netas"]) == 35
    assert fila["tickets_vendidos"] == 2


def test_detalle_muestra_comision_ganada_por_periodo(entorno, monkeypatch, fijar_hora):
    """Perfil individual: comisión con % vigente al vender; anulados fuera; no toca cajas."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    a = entorno.banca(saldo=8000, usuario="vccom1", clave="prueba123")
    otra = entorno.banca(saldo=500, codigo="3300", nombre="OTRA BANCA VC", usuario="vccom2", clave="prueba123")
    usuarios = entorno.c.get("/usuarios", headers=entorno.admin).json()
    u1 = next(u for u in usuarios if u["usuario"] == "vccom1")
    u2 = next(u for u in usuarios if u["usuario"] == "vccom2")
    # Sin porcentaje: comisión 0 aunque haya ventas.
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "01", "monto": 100}])
    sin = entorno.c.get(
        f"/reportes/ventas-cajeros/{u1['id']}?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert sin.status_code == 200, sin.text
    assert sin.json()["comision"]["comision"] == "0.00"
    assert sin.json()["comision"]["porcentaje_vigente"] == "0"
    assert sin.json()["comision"]["descuenta_mi_caja"] is False

    # Asignar % después de la venta sin comisión (no reescribe el pasado).
    fijar_hora(datetime(2026, 11, 14, 10, 30, 0))
    asig = entorno.c.post("/comisiones", json={"usuario_id": u1["id"], "porcentaje": 15},
                          headers=entorno.admin)
    assert asig.status_code == 201, asig.text
    entorno.c.post("/comisiones", json={"usuario_id": u2["id"], "porcentaje": 10},
                   headers=entorno.admin)
    # Venta bajo 15% + anulado (no cuenta) + cambio a 10% + venta bajo 10%.
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "02", "monto": 1000}])
    anulado = entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "03", "monto": 200}])
    entorno.c.post("/terminal/tickets/anular", json={
        "id": anulado["id"], "serial": anulado["serial"], "motivo": "error",
    }, headers=a["headers"])
    fijar_hora(datetime(2026, 11, 14, 15, 0, 0))
    cambio = entorno.c.post("/comisiones", json={"usuario_id": u1["id"], "porcentaje": 10},
                            headers=entorno.admin)
    assert cambio.status_code == 201, cambio.text
    tarde = entorno.sorteo_id("Leidsa 3:55 PM")
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [tarde], "numeros": "04", "monto": 500}])
    entorno.vender_ok(otra["headers"], [{"tipo": "QN", "sorteos": [tarde], "numeros": "05", "monto": 800}])

    caja_antes = entorno.c.get("/terminal/sorteos", headers=a["headers"]).json()["mi_caja"]
    general_antes = entorno.saldo(a["sucursal"]["id"])
    det = entorno.c.get(
        f"/reportes/ventas-cajeros/{u1['id']}?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert det.status_code == 200, det.text
    com = det.json()["comision"]
    # 100×0% + 1000×15% + 500×10% = 200; anulado fuera; venta ajena fuera.
    assert com["comision"] == "200.00"
    assert com["comision_periodo"] == "200.00"
    assert com["comision_acumulada"] == "200.00"
    assert com["comision_pagada"] == "0.00"
    assert com["comision_pendiente"] == "200.00"
    assert com["porcentaje_vigente"] == "10"
    assert com["tickets_anulados"] == 1
    assert len(com["desglose"]) >= 2
    assert com["descuenta_mi_caja"] is False
    assert com["informativa"] is True
    assert isinstance(com.get("historial_pagos"), list)
    assert entorno.c.get("/terminal/sorteos", headers=a["headers"]).json()["mi_caja"] == caja_antes
    assert entorno.saldo(a["sucursal"]["id"]) == general_antes

    ajena = entorno.c.get(
        f"/reportes/ventas-cajeros/{u2['id']}?desde=2026-11-14&hasta=2026-11-14",
        headers=entorno.admin,
    )
    assert ajena.status_code == 200, ajena.text
    assert ajena.json()["comision"]["comision"] == "80.00"  # 800 × 10%
    assert "800.00" not in det.json()["comision"]["ventas_validas"]

    # El filtro DESDE/HASTA ya no reinicia la comisión del ciclo abierto.
    vacio = entorno.c.get(
        f"/reportes/ventas-cajeros/{u1['id']}?desde=2026-11-13&hasta=2026-11-13",
        headers=entorno.admin,
    )
    assert vacio.json()["comision"]["comision_pendiente"] == "200.00"
    # 100 (sin %) + 1000 + 500; anulado fuera del neto del ciclo.
    assert vacio.json()["resumen"]["ventas_ciclo"] == "1600.00"
