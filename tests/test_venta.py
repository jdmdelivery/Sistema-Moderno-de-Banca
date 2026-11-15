"""Venta: flujo válido y cada rechazo del servidor (Etapa 2, alcance 4)."""
from datetime import datetime


def test_venta_valida_sp_y_qn(entorno):
    b = entorno.banca(saldo=1000)
    s_real = entorno.sorteo_id("Real Tarde")
    s_primera = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "SP", "sorteos": [s_real, s_primera], "numeros": "26-58", "monto": 5},
        {"tipo": "QN", "sorteos": [s_primera], "numeros": "19", "monto": 10},
    ])
    assert t["id"] == 1  # primer ticket del consecutivo global
    assert len(t["serial"]) == 10 and t["serial"] != str(t["id"])
    assert t["qr"] == f"LOT:1:{t['serial']}"
    assert t["banca"] == "BANCA CASTILLO" and t["banca_codigo"] == "1301"
    assert float(t["total"]) == 15.00
    assert t["estado"] == "vendido"
    assert "saldo_restante" not in t
    assert entorno.saldo(b["sucursal"]["id"]) == 1015.00
    sp, qn = t["jugadas"]
    assert sp["loterias"] == ["Quiniela Real 12:55 PM", "La Primera 12:00 PM"] and sp["numeros"] == "26-58"
    assert qn["loterias"] == ["La Primera 12:00 PM"]
    # La venta SUMÓ a la caja y quedó en el historial de movimientos
    movs = entorno.c.get(f"/sucursales/{b['sucursal']['id']}/movimientos", headers=entorno.admin).json()
    venta = [m for m in movs if m["tipo"] == "venta"]
    assert len(venta) == 1 and float(venta[0]["monto"]) == 15.00
    assert float(venta[0]["saldo_resultante"]) == 1015.00


def test_venta_qn_multiloteria_replica_por_sorteo(entorno):
    b = entorno.banca(saldo=1000)
    s1, s2 = entorno.sorteo_id("Real Tarde"), entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s1, s2], "numeros": "07", "monto": 10},
    ])
    assert float(t["total"]) == 20.00  # $10 por cada lotería marcada
    assert len(t["jugadas"]) == 2


def test_consecutivo_global_entre_sucursales(entorno):
    b1 = entorno.banca(saldo=500, codigo="1301", usuario="vend1")
    b2 = entorno.banca(saldo=500, codigo="2200", nombre="BANCA PEGUERO", usuario="vend2")
    s = entorno.sorteo_id("La Primera 12")
    t1 = entorno.vender_ok(b1["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    t2 = entorno.vender_ok(b2["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "02", "monto": 5}])
    assert (t1["id"], t2["id"]) == (1, 2)  # un solo consecutivo para el consorcio


def test_venta_sin_ninguna_sesion_rechazada(entorno):
    b = entorno.banca(saldo=500)
    s = entorno.sorteo_id("La Primera 12")
    r = entorno.vender({}, [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    assert r.status_code == 401


def test_venta_sin_sesion_de_operador(entorno):
    b = entorno.banca(saldo=500)
    s = entorno.sorteo_id("La Primera 12")
    headers = {k: v for k, v in b["headers"].items() if k != "Authorization"}
    r = entorno.vender(headers, [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    assert r.status_code == 401


def test_venta_con_caja_menor_que_el_ticket_vende_igual(entorno):
    # Modelo de caja (corrección de Jose, 2026-11-14): vender NO exige
    # saldo; la venta cobra en efectivo y SUMA a la caja de la sucursal.
    b = entorno.banca(saldo=12)
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 15}])
    assert t["id"] == 1
    assert entorno.saldo(b["sucursal"]["id"]) == 27.00


def test_venta_sorteo_cerrado(entorno, fijar_hora):
    b = entorno.banca(saldo=500)
    s = entorno.sorteo_id("La Primera 12")  # cierra 11:50
    fijar_hora(datetime(2026, 11, 14, 12, 30))
    r = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    assert r.status_code == 400 and "La Primera 12" in r.json()["detail"] and "cerró" in r.json()["detail"]
    assert entorno.saldo(b["sucursal"]["id"]) == 500.00


def test_venta_ticket_mixto_con_un_sorteo_cerrado_se_rechaza_entero(entorno, fijar_hora):
    b = entorno.banca(saldo=500)
    abierto = entorno.sorteo_id("Nacional Noche")  # cierra 20:50
    cerrado = entorno.sorteo_id("La Primera 12")  # cierra 11:50
    fijar_hora(datetime(2026, 11, 14, 12, 30))
    r = entorno.vender(b["headers"], [
        {"tipo": "QN", "sorteos": [abierto], "numeros": "01", "monto": 5},
        {"tipo": "QN", "sorteos": [cerrado], "numeros": "02", "monto": 5},
    ])
    assert r.status_code == 400
    assert entorno.saldo(b["sucursal"]["id"]) == 500.00  # no se debitó nada


def test_venta_montos_fuera_de_rango(entorno):
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12")
    r1 = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 1}])
    assert r1.status_code == 400 and "mínimo" in r1.json()["detail"]
    r2 = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 99999}])
    assert r2.status_code == 400 and "máximo" in r2.json()["detail"]


def test_venta_numeros_invalidos(entorno):
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    casos = [
        {"tipo": "QN", "sorteos": [s], "numeros": "26-58", "monto": 5},   # quiniela con pareja
        {"tipo": "QN", "sorteos": [s], "numeros": "100", "monto": 5},     # fuera de 00-99
        {"tipo": "XX", "sorteos": [s], "numeros": "26", "monto": 5},      # tipo inexistente
    ]
    for jugada in casos:
        r = entorno.vender(b["headers"], [jugada])
        assert r.status_code == 400, (jugada, r.text)
    assert entorno.saldo(b["sucursal"]["id"]) == 1000.00


def test_venta_sp_requiere_dos_loterias_distintas(entorno):
    b = entorno.banca(saldo=1000)
    s = entorno.sorteo_id("La Primera 12")
    r1 = entorno.vender(b["headers"], [{"tipo": "SP", "sorteos": [s], "numeros": "26-58", "monto": 5}])
    assert r1.status_code == 400 and "dos loterías" in r1.json()["detail"]
    r2 = entorno.vender(b["headers"], [{"tipo": "SP", "sorteos": [s, s], "numeros": "26-58", "monto": 5}])
    assert r2.status_code == 400 and "diferentes" in r2.json()["detail"]


def test_venta_limite_por_numero(entorno):
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id("La Primera 12")
    r = entorno.c.post("/limites", json={
        "sorteo_id": s, "tipo": "QN", "numeros": "26", "monto_max_acumulado": 100,
    }, headers=entorno.admin)
    assert r.status_code == 201, r.text
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 60}])
    r = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "26", "monto": 50}])
    assert r.status_code == 409 and "Límite alcanzado" in r.json()["detail"] and "26" in r.json()["detail"]
    # Otro número sin límite vende sin problema
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "27", "monto": 50}])


def test_venta_sin_jugadas(entorno):
    b = entorno.banca(saldo=1000)
    r = entorno.vender(b["headers"], [])
    assert r.status_code == 400


def test_modo_desarrollo_no_abre_sorteos_cerrados(entorno, fijar_hora, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    monkeypatch.setenv("LOTERIAS_ABIERTAS_DESARROLLO", "SI")
    b = entorno.banca(saldo=0)
    catalogo = entorno.c.get("/sorteos", headers=entorno.admin).json()
    antes = {
        s["nombre"]: (s["hora_sorteo"], s["hora_cierre"], s["dias_activos"], s["activo"])
        for s in catalogo
    }
    primera = next(s["id"] for s in catalogo if s["nombre"] == "La Primera 12:00 PM")
    fijar_hora(datetime(2026, 11, 14, 10, 0))
    headers = entorno.login_terminal()
    abierta = entorno.vender_ok(headers, [{"tipo": "QN", "sorteos": [primera], "numeros": "19", "monto": 10}])
    assert abierta["es_prueba"] is True
    assert entorno.saldo(b["sucursal"]["id"]) == 0.00
    fijar_hora(datetime(2026, 11, 14, 23, 30))
    headers = entorno.login_terminal()
    lista = entorno.c.get("/terminal/sorteos", headers=headers)
    assert lista.status_code == 200
    sorteos = lista.json()["sorteos"]
    assert len(sorteos) == 40 and all(s["abierto"] is False for s in sorteos)
    cerrada = entorno.vender(headers, [{"tipo": "QN", "sorteos": [primera], "numeros": "19", "monto": 10}])
    assert cerrada.status_code == 400 and "cerró" in cerrada.json()["detail"]
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert admin.status_code == 200
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    assert entorno.saldo(b["sucursal"]["id"]) == 0.00
    despues = {
        s["nombre"]: (s["hora_sorteo"], s["hora_cierre"], s["dias_activos"], s["activo"])
        for s in entorno.c.get("/sorteos", headers={"Authorization": f"Bearer {admin.json()['token']}"}).json()
    }
    assert despues == antes
    salud = entorno.c.get("/health").json()
    assert salud["modo_desarrollo"] is True
    assert salud["loterias_abiertas_desarrollo"] is False
    assert salud["leyenda_loterias"] == ""


def test_sin_loterias_abiertas_el_horario_vuelve_a_cerrar(entorno, fijar_hora, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    monkeypatch.delenv("LOTERIAS_ABIERTAS_DESARROLLO", raising=False)
    b = entorno.banca(saldo=0)
    catalogo = entorno.c.get("/sorteos", headers=entorno.admin).json()
    antes = {
        s["nombre"]: (s["hora_sorteo"], s["hora_cierre"], s["dias_activos"], s["activo"])
        for s in catalogo
    }
    primera = next(s["id"] for s in catalogo if s["nombre"] == "La Primera 12:00 PM")
    fijar_hora(datetime(2026, 11, 14, 23, 30))
    headers = entorno.login_terminal()
    lista = entorno.c.get("/terminal/sorteos", headers=headers).json()["sorteos"]
    assert len(lista) == 40
    assert all(s["abierto"] is False for s in lista)
    venta = entorno.vender(headers, [{"tipo": "QN", "sorteos": [primera], "numeros": "19", "monto": 10}])
    assert venta.status_code == 400 and "cerró" in venta.json()["detail"]
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert admin.status_code == 200
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    assert entorno.saldo(b["sucursal"]["id"]) == 0.00
    despues = {
        s["nombre"]: (s["hora_sorteo"], s["hora_cierre"], s["dias_activos"], s["activo"])
        for s in entorno.c.get("/sorteos", headers=entorno.admin).json()
    }
    assert despues == antes
    assert entorno.c.get("/health").json()["loterias_abiertas_desarrollo"] is False


def test_modo_desarrollo_mantiene_inactivo_cerrado(entorno, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    b = entorno.banca(saldo=0)
    s = entorno.sorteo_id("La Primera 12")
    r = entorno.c.put("/sorteos/" + str(s), json={
        "nombre": "La Primera 12:00 PM", "hora_sorteo": "12:00", "hora_cierre": "11:55",
        "dias_activos": [1, 2, 3, 4, 5, 6, 7], "activo": False, "orden": 10,
    }, headers=entorno.admin)
    assert r.status_code == 200 and r.json()["activo"] is False
    venta = entorno.vender(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 10}])
    assert venta.status_code == 400 and "inactivo" in venta.json()["detail"]
    assert entorno.saldo(b["sucursal"]["id"]) == 0.00
