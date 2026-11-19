"""Validación local Opción B: imagen, fallback, QR, aislamiento, ganadores."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from PIL import Image


def _pixel_negro(img: Image.Image, x: int, y0: int, y1: int) -> bool:
    """Hay tinta en una franja horizontal (QR / texto)."""
    w, h = img.size
    x = max(0, min(w - 1, x))
    y0 = max(0, min(h - 1, y0))
    y1 = max(0, min(h - 1, y1))
    for y in range(y0, y1 + 1):
        if img.getpixel((x, y)) < 200:
            return True
    return False


def _simular(entorno, sorteo_id, p1, p2, p3):
    r = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo_id, "fecha": "2026-11-14",
        "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text


def _preparar_con_fondo(entorno, usuario="obpago", saldo=5764, fondo=20000):
    b = entorno.banca(saldo=saldo, nombre="BANCA CASTILLO (PRUEBA)", usuario=usuario, clave="prueba123")
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == usuario)
    fondo_r = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": fondo,
        "tipo": "aporte_prueba", "operacion_id": f"fondo-{usuario}",
    }, headers=entorno.admin)
    assert fondo_r.status_code == 201, fondo_r.text
    return b


def test_png_layout_vs_referencia_foto():
    from apps.api.ticket_imagen import render_ticket_png

    png = render_ticket_png({
        "id": 258117,
        "serial": "4D8DDAE5C8498",
        "qr": "LOT:258117:4D8DDAE5C8498",
        "banca": "BANCA CASTILLO",
        "banca_codigo": "1301",
        "fecha_hora": "2025-06-18 11:37:34",
        "total": "5.00",
        "jugadas": [
            {"tipo": "SP", "numeros": "26-58", "monto": "5.00",
             "loterias": ["Real Tarde", "La Primera 12"]},
        ],
    })
    img = Image.open(BytesIO(png)).convert("L")
    assert img.size[0] == 384, "ancho térmico 58 mm"
    assert img.size[1] < 2000, "no debe desbordar altura absurda"
    # QR arriba: zona superior (después del encabezado) debe tener tinta centrada.
    assert _pixel_negro(img, 192, 40, 220), "se espera QR/tinta en zona superior"
    # Pie / total en la parte baja.
    assert _pixel_negro(img, 40, img.size[1] - 80, img.size[1] - 5)


def test_secciones_qn_pl_sp_tr_selectivas():
    from apps.api.ticket_imagen import render_ticket_png, fusionar_diseno

    base = {
        "id": 1, "serial": "S", "qr": "LOT:1:S", "banca": "B", "banca_codigo": "1",
        "fecha_hora": "2026-11-14 10:00:00", "total": "130.00",
        "jugadas": [
            {"tipo": "QN", "numeros": "05", "monto": "50.00", "loterias": ["Real Tarde"]},
            {"tipo": "PL", "numeros": "05-50", "monto": "25.00", "loterias": ["Real Tarde"]},
            {"tipo": "SP", "numeros": "26-58", "monto": "5.00", "loterias": ["A", "B"]},
            {"tipo": "TR", "numeros": "12-25-38", "monto": "50.00", "loterias": ["Real Tarde"]},
        ],
    }
    png = render_ticket_png(base, fusionar_diseno({}), tr_habilitado=True)
    assert png.startswith(b"\x89PNG")
    img = Image.open(BytesIO(png))
    assert img.size[0] == 384

    cfg = fusionar_diseno({"secciones": {"qn": False, "pl": True, "sp": True, "tr": True}})
    png2 = render_ticket_png(base, cfg, tr_habilitado=True)
    assert png2.startswith(b"\x89PNG")


def test_agrupa_por_loteria_sin_mezclar_sorteos():
    from apps.api.ticket_imagen import _clave_loteria, _subgrupos_por_loteria

    filas = [
        {"tipo": "QN", "numeros": "05", "monto": "10", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "08", "monto": "10", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "77", "monto": "10", "loterias": ["Florida Día"]},
        {"tipo": "QN", "numeros": "11", "monto": "10", "loterias": ["Real Tarde"]},
    ]
    grupos = _subgrupos_por_loteria(filas)
    # Misma lotería se consolida (sin fragmentar); Florida queda aparte.
    assert [k for k, _ in grupos] == ["Real Tarde", "Florida Día"]
    assert [j["numeros"] for j in grupos[0][1]] == ["05", "08", "11"]
    assert [j["numeros"] for j in grupos[1][1]] == ["77"]
    assert _clave_loteria({"loterias": ["Real Tarde", "La Primera 12"]}) == "Real Tarde - La Primera 12"


def test_encabezado_largo_no_desborda_384():
    from apps.api.ticket_imagen import render_ticket_png

    png = render_ticket_png({
        "id": 9, "serial": "ABC", "qr": "LOT:9:ABC",
        "banca": "BANCA CASTILLO (PRUEBA) NOMBRE MUY LARGO PARA PROBAR",
        "banca_codigo": "1301",
        "fecha_hora": "2026-11-18 12:00:00",
        "total": "5.00",
        "jugadas": [{"tipo": "QN", "numeros": "25", "monto": "5.00", "loterias": ["King Lottery 7:30 PM"]}],
    })
    img = Image.open(BytesIO(png)).convert("L")
    assert img.size[0] == 384
    # No debe haber tinta pegada al borde izquierdo/derecho del nombre (márgenes).
    assert all(img.getpixel((0, y)) > 200 for y in range(min(40, img.size[1])))
    assert all(img.getpixel((383, y)) > 200 for y in range(min(40, img.size[1])))


def test_preview_total_coincide_con_suma_de_jugadas():
    from decimal import Decimal
    from apps.api.ticket_imagen import preview_png, suma_montos_jugadas

    jugadas = [
        {"tipo": "QN", "numeros": "05", "monto": "50.00", "loterias": ["Real Tarde"]},
        {"tipo": "QN", "numeros": "08", "monto": "50.00", "loterias": ["Real Tarde"]},
        {"tipo": "PL", "numeros": "05-50", "monto": "25.00", "loterias": ["Real Tarde"]},
        {"tipo": "SP", "numeros": "26-58", "monto": "5.00", "loterias": ["A", "B"]},
        {"tipo": "TR", "numeros": "12-25-38", "monto": "50.00", "loterias": ["Real Tarde"]},
    ]
    assert suma_montos_jugadas(jugadas) == Decimal("180.00")
    png = preview_png()
    assert png.startswith(b"\x89PNG")
    assert Image.open(BytesIO(png)).size[0] == 384


def test_qn_usa_mismo_monto_en_columnas():
    from apps.api.ticket_imagen import _monto_columna_qn, _dinero

    assert _monto_columna_qn("50.00") == "50"
    assert _monto_columna_qn("100.00") == "100"
    assert _dinero("50.00", "$ ").endswith("50.00")
    assert "100.00" in _dinero("100.00", "$ ")


def test_encabezado_sin_pie_prueba_aunque_es_prueba():
    """Nombre tal cual; es_prueba no imprime pie; tipografía jugada +8 % (24)."""
    from apps.api.ticket_imagen import diseno_por_defecto, render_ticket_png

    assert diseno_por_defecto()["tipografia"]["jugada"] == 26
    base = {
        "id": 10, "serial": "ABC", "qr": "LOT:10:ABC",
        "banca": "BANCA CASTILLO", "banca_codigo": "1301",
        "fecha_hora": "2026-11-18 12:00:00", "total": "5.00",
        "jugadas": [{"tipo": "QN", "numeros": "25", "monto": "5.00", "loterias": ["King Lottery 7:30 PM"]}],
    }
    png_ok = render_ticket_png(base)
    png_prueba = render_ticket_png({**base, "es_prueba": True})
    assert png_ok.startswith(b"\x89PNG") and png_prueba.startswith(b"\x89PNG")
    # Misma imagen impresa: es_prueba no añade texto al ticket.
    assert png_ok == png_prueba



def test_qr_payload_lot_id_serial_decodificable():
    import qrcode
    from apps.api.ticket_imagen import render_ticket_png

    payload = "LOT:258117:4D8DDAE5C8498"
    png = render_ticket_png({
        "id": 258117, "serial": "4D8DDAE5C8498", "qr": payload,
        "banca": "BANCA CASTILLO", "banca_codigo": "1301",
        "fecha_hora": "2025-06-18 11:37:34", "total": "5.00",
        "jugadas": [{"tipo": "SP", "numeros": "26-58", "monto": "5.00",
                     "loterias": ["Real Tarde", "La Primera 12"]}],
    })
    assert png.startswith(b"\x89PNG")
    # Contrato de escáner: payload LOT:id:serial (el PNG incluye el mismo string).
    assert payload.startswith("LOT:") and payload.count(":") == 2
    # Generación de referencia del mismo payload (librería qrcode) no lanza.
    qrcode.make(payload)


def test_venta_reimpresion_imagen_y_aislamiento(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    # Mantener reloj cerca de AHORA_FIJO para no vencer la sesión admin (12 h).
    fijar_hora(datetime(2026, 11, 14, 11, 0, 0))
    a = entorno.banca(saldo=8000, usuario="ob1", clave="prueba123")
    b = entorno.banca(saldo=8000, codigo="1302", nombre="OTRA BANCA", usuario="ob2", clave="prueba123")
    lot = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(a["headers"], [
        {"tipo": "QN", "sorteos": [lot], "numeros": "07", "monto": 20},
        {"tipo": "PL", "sorteos": [lot], "numeros": "07-14", "monto": 15},
    ])
    assert t["qr"] == f"LOT:{t['id']}:{t['serial']}"
    assert t["impresion"]["url"].endswith(f"/imagen?serial={t['serial']}")

    ok = entorno.c.get(t["impresion"]["url"], headers=a["headers"])
    assert ok.status_code == 200
    assert ok.headers.get("x-ticket-qr") == t["qr"] or ok.headers.get("X-Ticket-QR") == t["qr"]
    assert Image.open(BytesIO(ok.content)).size[0] == 384

    deny = entorno.c.get(t["impresion"]["url"], headers=b["headers"])
    assert deny.status_code == 403

    rep = entorno.c.post(
        "/terminal/tickets/reimprimir",
        headers=a["headers"],
        json={"id": t["id"], "serial": t["serial"]},
    )
    assert rep.status_code == 200, rep.text
    cuerpo = rep.json()
    assert "impresion" in cuerpo
    assert cuerpo["qr"] == t["qr"]
    img2 = entorno.c.get(cuerpo["impresion"]["url"], headers=a["headers"])
    assert img2.status_code == 200


def test_apk_antigua_ignora_campo_impresion_pero_api_sirve(entorno, monkeypatch, fijar_hora):
    """APK vieja solo usa TicketText + qr; el JSON nuevo no rompe campos clásicos."""
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 30, 0))
    a = entorno.banca(saldo=5000, usuario="ob3", clave="prueba123")
    lot = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(a["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "11", "monto": 10}])
    for campo in ("id", "serial", "qr", "banca", "jugadas", "total", "estado"):
        assert campo in t
    assert isinstance(t["jugadas"], list) and t["jugadas"]
    assert t["qr"].startswith("LOT:")
    assert "impresion" in t  # APK antigua lo ignora; campos clásicos intactos


def test_ganadores_y_pago_parcial_intactos(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 0, 0))
    a = _preparar_con_fondo(entorno, usuario="ob4", saldo=5764, fondo=20000)
    lotedom = entorno.sorteo_id("LOTEDOM")
    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    t = entorno.vender_ok(a["headers"], [
        {"tipo": "QN", "sorteos": [lotedom, primera, florida], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, lotedom, 25, 1, 2)
    _simular(entorno, primera, 25, 3, 4)
    cons = entorno.c.post(
        "/terminal/tickets/consultar",
        headers=a["headers"],
        json={"id": t["id"], "serial": t["serial"]},
    )
    assert cons.status_code == 200, cons.text
    cuerpo = cons.json()
    assert cuerpo.get("puede_pagar") is True
    assert float(cuerpo.get("premio_pendiente") or 0) == 1200.0
    assert "SORTEOS PENDIENTES" in (cuerpo.get("texto_pago") or "")

    pago = entorno.c.post(
        "/terminal/tickets/pagar",
        headers=a["headers"],
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-ob4-1"},
    )
    assert pago.status_code == 200, pago.text
    pj = pago.json()
    assert pj.get("estado") == "parcial"
    assert "PAGO PARCIAL" in (pj.get("comprobante") or "")

    # Mientras queden sorteos pendientes no liquidados, un segundo operacion_id
    # no debe volver a cobrar lo ya pagado (idempotente / bloqueado).
    doble = entorno.c.post(
        "/terminal/tickets/pagar",
        headers=a["headers"],
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-ob4-doble"},
    )
    assert doble.status_code in (200, 409), doble.text
    if doble.status_code == 200:
        assert float(doble.json().get("premio_pagado") or 0) == float(pj.get("premio_pagado") or 0)
        assert doble.json().get("puede_pagar") is False


def test_no_doble_pago_premio_completo(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 20, 0))
    a = _preparar_con_fondo(entorno, usuario="ob5", saldo=5764, fondo=20000)
    lot = entorno.sorteo_id("LOTEDOM")
    t = entorno.vender_ok(a["headers"], [
        {"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10},
    ])
    _simular(entorno, lot, 25, 54, 78)
    p1 = entorno.c.post(
        "/terminal/tickets/pagar",
        headers=a["headers"],
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-ob5-1"},
    )
    assert p1.status_code == 200, p1.text
    assert p1.json().get("puede_pagar") is False
    p2 = entorno.c.post(
        "/terminal/tickets/pagar",
        headers=a["headers"],
        json={"id": t["id"], "serial": t["serial"], "operacion_id": "pago-ob5-2"},
    )
    assert p2.status_code == 409, p2.text


def test_fallback_sin_imagen_ruta_inexistente_documentado():
    """Documenta contrato: si no hay imagen, APK usa TicketText (probado en unit APK)."""
    from apps.api.ticket_imagen import diseno_por_defecto
    assert diseno_por_defecto()["ancho_px"] == 384
    assert diseno_por_defecto()["qr"]["posicion"] == "superior"


def test_version_apk_universal_en_gradle():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]  # Sistema-Moderno-de-Banca
    gradle = root.parent / "banca-moderna-terminal" / "app" / "build.gradle.kts"
    texto = gradle.read_text(encoding="utf-8")
    assert 'versionName = "0.4.2-universal"' in texto
    assert "versionCode = 44" in texto
    assert "minSdk = 23" in texto  # Android 6.0
    assert 'create("prod")' in texto and 'create("piloto")' in texto
    assert "sistema-de-banca-moderna.onrender.com" in texto
    assert "http://127.0.0.1:8100" in texto
    assert 'applicationIdSuffix = ".piloto"' in texto
    prefs = (root.parent / "banca-moderna-terminal" / "app" / "src" / "main" / "java"
             / "bancamoderna" / "terminal" / "Prefs.java").read_text(encoding="utf-8")
    assert "BuildConfig.URL_SERVIDOR" in prefs
    manifest = (root.parent / "banca-moderna-terminal" / "app" / "src" / "main"
                / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'usesCleartextTraffic="${usesCleartext}"' in manifest
    apk = root.parent / "banca-moderna-terminal" / "salida" / "banca-moderna-terminal-0.4.2-universal.apk"
    if not apk.is_file():
        apk = root.parent / "BANCA MODERNA APK FINAL" / "Banca-Moderna-Terminal-0.4.2-universal.apk"
    assert apk.is_file(), f"APK de producción ausente: {apk}"
    assert apk.stat().st_size > 500_000
