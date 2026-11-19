"""BALANCE DE COMISIÓN: % al momento de venta, sin retroactivo salvo autorización."""
from datetime import datetime


def _id(entorno, usuario):
    for fila in entorno.c.get("/usuarios", headers=entorno.admin).json():
        if fila["usuario"] == usuario:
            return fila["id"]
    raise AssertionError(usuario)


def _detalle(entorno, usuario_id, desde="2026-11-14", hasta="2026-11-14"):
    r = entorno.c.get(
        f"/reportes/ventas-cajeros/{usuario_id}?desde={desde}&hasta={hasta}",
        headers=entorno.admin,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _entregar_todo(entorno, headers, op="ent-bal"):
    mi = float(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"])
    if mi <= 0:
        return
    r = entorno.c.post("/terminal/entregas", json={"monto": mi, "operacion_id": op}, headers=headers)
    assert r.status_code == 201, r.text


def test_ventas_antes_del_porcentaje_balance_cero_y_nota(entorno, monkeypatch, fijar_hora):
    """Caso Wanda: ventas del ciclo con % asignado después → balance 0 (sin inventar)."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=20000, usuario="wanda0", clave="prueba123", codigo="1308", nombre="BANCA CASTILLO")
    uid = _id(entorno, "wanda0")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "10", "monto": 1000}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "11", "monto": 500}])
    fijar_hora(datetime(2026, 11, 14, 16, 42, 0))
    asig = entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin)
    assert asig.status_code == 201, asig.text

    det = _detalle(entorno, uid)
    assert det["resumen"]["ventas_ciclo"] == "1500.00"
    assert det["comision"]["porcentaje_vigente"] == "15"
    assert det["comision"]["comision_pendiente"] == "0.00"
    assert det["comision"]["ventas_sin_porcentaje"] == "1500.00"
    assert det["comision"]["tickets_sin_porcentaje"] == 2
    assert det["comision"]["nota_balance"]
    assert "sin porcentaje" in det["comision"]["nota_balance"].lower()


def test_autorizar_aplicar_desde_ciclo_corrige_balance(entorno, monkeypatch, fijar_hora):
    """Autorización expresa: aplicar 15% desde inicio del ciclo → balance correcto."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=30000, usuario="wanda1", clave="prueba123")
    uid = _id(entorno, "wanda1")
    lot = entorno.sorteo_id("LOTEDOM")
    # Réplica Wanda: RD$14,745 en varias jugadas (tope $5,000 c/u).
    for i, monto in enumerate((5000, 5000, 4745), start=20):
        entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": str(i), "monto": monto}])
    fijar_hora(datetime(2026, 11, 14, 16, 42, 0))
    entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin)
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "0.00"

    caja_antes = entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]
    general_antes = entorno.saldo(b["sucursal"]["id"])
    auth = entorno.c.post(
        "/comisiones",
        json={"usuario_id": uid, "porcentaje": 15, "aplicar_desde_inicio_ciclo": True},
        headers=entorno.admin,
    )
    assert auth.status_code == 201, auth.text
    det = _detalle(entorno, uid)
    # 14745 × 15% = 2211.75
    assert det["comision"]["comision_pendiente"] == "2211.75"
    assert det["comision"]["comision_acumulada"] == "2211.75"
    assert det["comision"]["ventas_sin_porcentaje"] == "0.00"
    assert det["comision"]["nota_balance"] is None
    assert entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"] == caja_antes
    assert entorno.saldo(b["sucursal"]["id"]) == general_antes

    # Guardar dos veces con la misma autorización no duplica comisión ni filas efectivas.
    hist1 = entorno.c.get(f"/comisiones?usuario_id={uid}", headers=entorno.admin).json()
    n1 = len(hist1)
    rep = entorno.c.post(
        "/comisiones",
        json={"usuario_id": uid, "porcentaje": 15, "aplicar_desde_inicio_ciclo": True},
        headers=entorno.admin,
    )
    assert rep.status_code == 201, rep.text
    assert rep.json()["id"] == auth.json()["id"]
    hist2 = entorno.c.get(f"/comisiones?usuario_id={uid}", headers=entorno.admin).json()
    assert len(hist2) == n1
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "2211.75"

    # Nueva venta del ciclo sigue acumulando (hora con sorteo abierto).
    fijar_hora(datetime(2026, 11, 14, 10, 30, 0))
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "40", "monto": 100}])
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "2226.75"


def test_aplicar_ciclo_respeta_pagos_previos(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=20000, usuario="pagprev", clave="prueba123")
    uid = _id(entorno, "pagprev")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin)
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "50", "monto": 1000}])
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "150.00"
    pago = entorno.c.post(
        "/comisiones/pagos",
        json={"usuario_id": uid, "monto": 50, "operacion_id": "pago-prev-1"},
        headers=entorno.admin,
    )
    assert pago.status_code == 201, pago.text
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "100.00"
    # Reaplicar desde ciclo no reinicia ni duplica lo ya pagado.
    entorno.c.post(
        "/comisiones",
        json={"usuario_id": uid, "porcentaje": 15, "aplicar_desde_inicio_ciclo": True},
        headers=entorno.admin,
    )
    det = _detalle(entorno, uid)
    assert det["comision"]["comision_acumulada"] == "150.00"
    assert det["comision"]["comision_pagada"] == "50.00"
    assert det["comision"]["comision_pendiente"] == "100.00"


def test_ventas_sucesivas_15_anulacion_cierre_y_nuevo_ciclo(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=15000, usuario="balok", clave="prueba123")
    uid = _id(entorno, "balok")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin)

    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "31", "monto": 1000}])
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "150.00"

    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "32", "monto": 400}])
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "210.00"

    anulado = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "33", "monto": 200}])
    entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": anulado["id"], "serial": anulado["serial"], "motivo": "error"},
        headers=b["headers"],
    )
    det = _detalle(entorno, uid)
    assert det["comision"]["comision_pendiente"] == "210.00"  # anulado no suma ni duplica descuento
    assert det["comision"]["tickets_anulados"] == 1

    # Filtro de fechas del dashboard no altera el balance del ciclo.
    otro = _detalle(entorno, uid, desde="2026-11-01", hasta="2026-11-01")
    assert otro["comision"]["comision_pendiente"] == "210.00"

    _entregar_todo(entorno, b["headers"], op="ent-bal-1")
    cierre = entorno.c.post(
        "/comisiones/cierres",
        json={"usuario_id": uid, "operacion_id": "cierre-bal-1", "monto": 210},
        headers=entorno.admin,
    )
    assert cierre.status_code == 201, cierre.text
    assert cierre.json()["comision_nueva"]["comision_pendiente"] == "0.00"
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "0.00"

    # Tras el cierre, avanzar la hora para que vendido_en > cerrado_en.
    fijar_hora(datetime(2026, 11, 14, 11, 0, 0))
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "34", "monto": 200}])
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "30.00"


def test_preview_y_aplicar_ciclo_caso_parcial_tipo_isaury(entorno, monkeypatch, fijar_hora):
    """Ventas sin % + ventas con %: preview y aplicar unifican el ciclo al %.

    Réplica del patrón Isaury/Lizbech (parcial_sin_pct_al_vender).
    """
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    b = entorno.banca(saldo=20000, usuario="isauryx", clave="prueba123")
    uid = _id(entorno, "isauryx")
    lot = entorno.sorteo_id("LOTEDOM")
    # Ventas antes del %
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "60", "monto": 1000}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "61", "monto": 500}])
    fijar_hora(datetime(2026, 11, 14, 10, 30, 0))
    entorno.c.post("/comisiones", json={"usuario_id": uid, "porcentaje": 15}, headers=entorno.admin)
    # Venta después del % (200 × 15% = 30) — patrón Isaury
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "62", "monto": 200}])
    det = _detalle(entorno, uid)
    assert det["resumen"]["ventas_ciclo"] == "1700.00"
    assert det["comision"]["comision_pendiente"] == "30.00"

    prev = entorno.c.get(
        f"/comisiones/preview-aplicar-ciclo?usuario_id={uid}&porcentaje=15",
        headers=entorno.admin,
    )
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["ventas_validas"] == "1700.00"
    assert body["ventas_sin_porcentaje"] == "1500.00"
    assert body["balance_actual"] == "30.00"
    assert body["balance_proyectado"] == "255.00"  # 1700 × 15%
    assert body["descuenta_mi_caja"] is False

    entorno.c.post(
        "/comisiones",
        json={"usuario_id": uid, "porcentaje": 15, "aplicar_desde_inicio_ciclo": True},
        headers=entorno.admin,
    )
    assert _detalle(entorno, uid)["comision"]["comision_pendiente"] == "255.00"


def test_dos_sucursales_aisladas_y_cambio_porcentaje(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    a = entorno.banca(saldo=10000, usuario="caj_a15", clave="prueba123", codigo="A150", nombre="BANCA A")
    b = entorno.banca(saldo=10000, usuario="caj_b10", clave="prueba123", codigo="B150", nombre="BANCA B")
    ua = _id(entorno, "caj_a15")
    ub = _id(entorno, "caj_b10")
    lot = entorno.sorteo_id("LOTEDOM")
    entorno.c.post("/comisiones", json={"usuario_id": ua, "porcentaje": 15}, headers=entorno.admin)
    entorno.c.post("/comisiones", json={"usuario_id": ub, "porcentaje": 10}, headers=entorno.admin)
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "70", "monto": 1000}])
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "71", "monto": 1000}])
    assert _detalle(entorno, ua)["comision"]["comision_pendiente"] == "150.00"
    assert _detalle(entorno, ub)["comision"]["comision_pendiente"] == "100.00"

    # Cambio de % a 20% solo afecta ventas posteriores de A.
    fijar_hora(datetime(2026, 11, 14, 11, 0, 0))
    entorno.c.post("/comisiones", json={"usuario_id": ua, "porcentaje": 20}, headers=entorno.admin)
    entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "72", "monto": 500}])
    assert _detalle(entorno, ua)["comision"]["comision_pendiente"] == "250.00"  # 150 + 100
    assert _detalle(entorno, ub)["comision"]["comision_pendiente"] == "100.00"


def test_ui_balance_y_aplicar_ciclo_presentes():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "apps/web/app.js").read_text(encoding="utf-8")
    html = (root / "apps/web/index.html").read_text(encoding="utf-8")
    assert "BALANCE DE COMISIÓN" in js
    assert "PORCENTAJE VIGENTE" in js
    assert "PAGAR COMISIÓN Y CERRAR CICLO" in js
    assert "nota_balance" in js
    assert "aplicar_desde_inicio_ciclo" in js
    assert "previewComisionCiclo" in js
    assert "preview-aplicar-ciclo" in js
    assert "com-aplicar-ciclo" in html
    assert "btn-com-preview" in html
    assert '[fmt(bloque.comision), "Comisión"]' not in js
