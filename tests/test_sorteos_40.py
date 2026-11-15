"""Cuarenta sorteos, cierre cinco minutos antes y catálogo idempotente.

La hora la fija el servidor. Un reloj de teléfono no abre un sorteo cerrado
y una venta con un sorteo cerrado no guarda nada.
"""
import threading
from datetime import date, datetime, timedelta

from apps.api import db as dbmod
from apps.api import rdlotto, servicios
from apps.api.comun import ErrorServicio
from apps.api.models import MovimientoSaldo, Resultado, Sorteo, Ticket, Terminal, Usuario
from apps.api.seed import HORAS_CATALOGO, aplicar_catalogo_sorteos


def test_hay_exactamente_cuarenta_activos_con_cierre_cinco_minutos_antes(entorno):
    filas = entorno.c.get("/sorteos", headers=entorno.admin).json()
    activos = [s for s in filas if s["activo"]]
    assert len(activos) == 40
    assert len({s["nombre"] for s in activos}) == 40
    assert {s["nombre"] for s in activos} == {nombre for nombre, _hora in HORAS_CATALOGO}
    for fila in activos:
        sorteo = datetime.strptime(fila["hora_sorteo"], "%H:%M")
        cierre = datetime.strptime(fila["hora_cierre"], "%H:%M")
        assert sorteo - cierre == timedelta(minutes=5), fila["nombre"]
    cobertura = {fila["sorteo"] for fila in rdlotto.cobertura()}
    assert cobertura == {s["nombre"] for s in activos}


def test_abre_a_las_seis_y_cierra_en_el_segundo_exacto(entorno, monkeypatch):
    anguila = None
    b = None
    for momento, esperado in (
        (datetime(2026, 11, 15, 5, 59, 59), 400),
        (datetime(2026, 11, 15, 6, 0, 0), 201),
        (datetime(2026, 11, 15, 7, 54, 59), 201),
        (datetime(2026, 11, 15, 7, 55, 0), 400),
        (datetime(2026, 11, 15, 7, 55, 1), 400),
    ):
        monkeypatch.setattr(servicios, "ahora_local", lambda momento=momento: momento)
        admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
        entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
        if b is None:
            b = entorno.banca(saldo=500)
            anguila = entorno.sorteo_id("La Anguila 8:00 AM")
        headers = entorno.login_terminal()
        antes = entorno.saldo(b["sucursal"]["id"])
        r = entorno.vender(headers, [{"tipo": "QN", "sorteos": [anguila], "numeros": "19", "monto": 5}])
        assert r.status_code == esperado, (momento, r.text)
        if esperado == 400:
            assert "6:00" in r.json()["detail"] or "cerró" in r.json()["detail"]
            assert entorno.saldo(b["sucursal"]["id"]) == antes
        lista = entorno.c.get("/terminal/sorteos", headers=headers).json()["sorteos"]
        fila = next(s for s in lista if s["id"] == anguila)
        if momento.hour == 7 and momento.minute == 54:
            assert fila["estado"] == "proxima" and fila["abierto"] is True
            assert fila["segundos_para_cierre"] == 1
        if momento == datetime(2026, 11, 15, 7, 55, 0):
            assert fila["estado"] == "cerrada" and fila["abierto"] is False


def test_un_sorteo_cerrado_rechaza_toda_la_venta_y_los_demas_siguen(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 15, 10, 0, 0))
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    b = entorno.banca(saldo=500)
    cerrada = entorno.sorteo_id("La Anguila 8:00 AM")
    abierta = entorno.sorteo_id("La Primera 12:00 PM")
    headers = entorno.login_terminal()
    antes = entorno.saldo(b["sucursal"]["id"])
    r = entorno.vender(headers, [
        {"tipo": "QN", "sorteos": [abierta], "numeros": "19", "monto": 10},
        {"tipo": "QN", "sorteos": [cerrada], "numeros": "25", "monto": 10},
    ])
    assert r.status_code == 400 and "cerró" in r.json()["detail"]
    assert entorno.saldo(b["sucursal"]["id"]) == antes
    db = dbmod.nueva_sesion()
    assert db.query(Ticket).count() == 0
    assert db.query(MovimientoSaldo).count() == 1  # solo la recarga inicial
    db.close()
    sola = entorno.vender(headers, [{"tipo": "QN", "sorteos": [abierta], "numeros": "19", "monto": 10}])
    assert sola.status_code == 201, sola.text


def test_al_dia_siguiente_vuelve_a_abrir_y_el_reloj_del_telefono_no_cuenta(entorno, monkeypatch):
    monkeypatch.setattr(servicios, "ahora_local", lambda: datetime(2026, 11, 15, 7, 55, 0))
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    b = entorno.banca(saldo=500)
    anguila = entorno.sorteo_id("La Anguila 8:00 AM")
    headers = entorno.login_terminal()
    tarde = entorno.vender(headers, [{"tipo": "QN", "sorteos": [anguila], "numeros": "19", "monto": 5}])
    assert tarde.status_code == 400
    falso = entorno.c.post(
        "/terminal/venta",
        json={"jugadas": [{"tipo": "QN", "sorteos": [anguila], "numeros": "19", "monto": 5}],
              "vendido_en": "2026-11-15T06:30:00"},
        headers=headers,
    )
    assert falso.status_code in (400, 422)
    db = dbmod.nueva_sesion()
    assert db.query(Ticket).count() == 0
    db.close()
    monkeypatch.setattr(servicios, "ahora_local", lambda: datetime(2026, 11, 16, 6, 0, 0))
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    entorno.admin = {"Authorization": f"Bearer {admin.json()['token']}"}
    headers = entorno.login_terminal()
    nueva = dbmod.nueva_sesion()
    assert nueva.query(Sorteo).filter_by(id=anguila, activo=True).count() == 1
    nueva.close()
    otra = entorno.vender(headers, [{"tipo": "QN", "sorteos": [anguila], "numeros": "19", "monto": 5}])
    assert otra.status_code == 201, otra.text


def test_si_el_dia_cambia_durante_la_venta_no_se_guarda(entorno, monkeypatch):
    b = entorno.banca(saldo=500)
    s = entorno.sorteo_id("La Primera 12:00 PM")
    monkeypatch.setattr(servicios, "ahora_local", lambda: datetime(2026, 11, 16, 6, 0, 0))
    db = dbmod.nueva_sesion()
    usuario = db.query(Usuario).filter_by(usuario="vend1").one()
    terminal = db.query(Terminal).filter_by(sucursal_id=b["sucursal"]["id"]).one()
    try:
        servicios.vender(
            db, terminal, usuario,
            [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 5}],
            ahora=datetime(2026, 11, 15, 10, 0, 0),
        )
        raise AssertionError("la venta debió rechazarse")
    except ErrorServicio as exc:
        assert exc.status == 400 and "cambió el día" in exc.mensaje
    assert db.query(Ticket).count() == 0
    db.close()


def test_dos_cajeras_venden_a_la_vez_sin_duplicar_la_operacion(entorno):
    b = entorno.banca(saldo=0)
    entorno.operador("ana", "1234", b["sucursal"]["id"])
    s = entorno.sorteo_id("La Primera 12:00 PM")
    db = dbmod.nueva_sesion()
    vend1 = db.query(Usuario).filter_by(usuario="vend1").one().id
    ana = db.query(Usuario).filter_by(usuario="ana").one().id
    terminal = db.query(Terminal).filter_by(sucursal_id=b["sucursal"]["id"]).one().id
    db.close()
    barrera = threading.Barrier(2)
    resultados = []

    def intento(usuario_id, operacion, esperar=True):
        sesion = dbmod.nueva_sesion()
        try:
            if esperar:
                barrera.wait(10)
            servicios.vender(
                sesion,
                sesion.get(Terminal, terminal),
                sesion.get(Usuario, usuario_id),
                [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}],
                operacion_id=operacion,
            )
            resultados.append("ok")
        except Exception as exc:
            resultados.append(f"{type(exc).__name__}: {exc}")
        finally:
            sesion.close()

    hilos = [
        threading.Thread(target=intento, args=(vend1, "op-vend1")),
        threading.Thread(target=intento, args=(ana, "op-ana")),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert resultados.count("ok") == 2, resultados
    intento(vend1, "op-vend1", False)
    assert resultados.count("ok") == 3, resultados
    db = dbmod.nueva_sesion()
    tickets = db.query(Ticket).all()
    assert len(tickets) == 2
    assert {t.operacion_id for t in tickets} == {"op-vend1", "op-ana"}
    db.close()
    headers = entorno.login_terminal()
    repetida = entorno.c.post(
        "/terminal/venta",
        json={"jugadas": [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}],
              "operacion_id": "op-vend1"},
        headers=headers,
    )
    assert repetida.status_code == 201
    db = dbmod.nueva_sesion()
    assert db.query(Ticket).count() == 2
    db.close()


def test_archivar_conserva_el_ticket_y_el_resultado_y_puede_repetirse(entorno):
    b = entorno.banca()
    s = entorno.sorteo_id("Lotedom 12:00 PM")
    vendido = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "25", "monto": 10}])
    db = dbmod.nueva_sesion()
    viejo = db.get(Sorteo, s)
    viejo.nombre = "LOTEDOM"
    db.add(Resultado(
        sorteo_id=s, fecha=date(2026, 11, 14), premio1=25, premio2=54, premio3=78,
        estado="propuesto", fuente="simulado",
    ))
    db.commit()
    db.close()
    db = dbmod.nueva_sesion()
    aplicar_catalogo_sorteos(db)
    aplicar_catalogo_sorteos(db)
    assert db.query(Sorteo).filter_by(activo=True).count() == 40
    assert db.query(Sorteo).filter_by(nombre="Lotedom 12:00 PM", activo=True).count() == 1
    archivado = db.get(Sorteo, s)
    assert archivado.activo is False and archivado.nombre == "LOTEDOM"
    ticket = db.get(Ticket, vendido["id"])
    assert ticket.jugadas[0].sorteo_id == s
    assert db.query(Resultado).filter_by(sorteo_id=s).one().premio1 == 25
    db.close()


def test_nacional_noche_no_se_copia_a_otro_sorteo(entorno):
    doc = {
        "date": "2026-11-14",
        "draws": [{
            "game": "nacional-noche", "session": "noche", "date": "2026-11-14",
            "time": "20:55", "status": "verified", "numbers": ["11", "22", "33"],
            "reportedBy": ["enloteria"], "url": "https://rdlotto.com/x",
        }],
    }
    resumen = rdlotto.sincronizar(dbmod.nueva_sesion(), date(2026, 11, 14), documento=doc)
    assert resumen["guardados"] == 0
    db = dbmod.nueva_sesion()
    assert db.query(Resultado).count() == 0
    db.close()
