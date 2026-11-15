"""El administrador entra por la misma terminal. El cajero no ve datos ajenos."""
from datetime import date

from apps.api import conectate, rdlotto
from apps.api import db as dbmod
from apps.api.models import Resultado, Usuario


def test_el_administrador_entra_y_el_cajero_no_ve_la_administracion(entorno):
    admin = entorno.c.post("/terminal/login", json={"usuario": "admin", "clave": "admin123"})
    assert admin.status_code == 200, admin.text
    cuerpo = admin.json()
    assert cuerpo["rol"] == "admin"
    assert "clave" not in cuerpo["operador"]
    token = {"Authorization": f"Bearer {cuerpo['token']}"}
    panel = entorno.c.get("/movil/admin?seccion=inicio", headers=token)
    assert panel.status_code == 200, panel.text
    assert "reales" in panel.json() and "prueba" in panel.json()

    b = entorno.banca(saldo=100)
    otra = entorno.banca(saldo=80, codigo="2200", nombre="BANCA PEGUERO", usuario="ana", clave="1234")
    s = entorno.sorteo_id("La Primera 12:00 PM")
    entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "11", "monto": 10}])
    entorno.vender_ok(otra["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "22", "monto": 25}])
    ajeno = entorno.c.get("/movil/admin", headers=b["headers"])
    assert ajeno.status_code == 401
    assert entorno.c.get("/reportes/inicio", headers=b["headers"]).status_code == 401
    propio = entorno.c.get("/terminal/reportes/dia", headers=b["headers"])
    assert propio.status_code == 200
    assert propio.json()["real"]["ventas"] == "10.00"

    ventas = entorno.c.get("/movil/admin?seccion=ventas", headers=token).json()
    por_sucursal = {fila["nombre"]: fila["real"] for fila in ventas["por_sucursal"]}
    assert por_sucursal["BANCA CASTILLO"] == "10.00"
    assert por_sucursal["BANCA PEGUERO"] == "25.00"
    usuarios = entorno.c.get("/usuarios", headers=token).json()
    vend1 = next(u["id"] for u in usuarios if u["usuario"] == "vend1")
    cambio = entorno.c.put(
        f"/usuarios/{vend1}",
        json={"nombre": "Cajero", "usuario": "vend1", "rol": "admin", "activo": True},
        headers=b["headers"],
    )
    assert cambio.status_code == 401
    db = dbmod.nueva_sesion()
    assert db.query(Usuario).filter_by(usuario="vend1").one().rol == "operador"
    db.close()


def test_la_busqueda_de_tickets_respeta_la_sucursal(entorno):
    admin = entorno.c.post("/terminal/login", json={"usuario": "admin", "clave": "admin123"})
    token = {"Authorization": f"Bearer {admin.json()['token']}"}
    b = entorno.banca()
    s = entorno.sorteo_id("La Primera 12:00 PM")
    vendido = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "19", "monto": 10}])
    hallado = entorno.c.get(f"/movil/admin?seccion=tickets&q={vendido['id']}", headers=token)
    assert hallado.status_code == 200, hallado.text
    ticket = hallado.json()["tickets"][0]
    assert ticket["serial"] == vendido["serial"]
    assert ticket["jugadas"][0]["numeros"] == "19"
    assert ticket["jugadas"][0]["loterias"] == ["La Primera 12:00 PM"]
    assert "clave" not in ticket


def test_el_tablero_marca_fuente_y_no_mezcla_resultados(entorno):
    admin = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    token = {"Authorization": f"Bearer {admin.json()['token']}"}
    tablero = entorno.c.get("/resultados/tablero", headers=token)
    assert tablero.status_code == 200, tablero.text
    filas = {fila["nombre"]: fila for fila in tablero.json()["sorteos"]}
    assert len(filas) == 40
    assert filas["Haiti Bolet 9:30 AM"]["estado_panel"] == "PENDIENTE"
    assert filas["Leidsa 8:55 PM"]["estado_panel"] == "PENDIENTE"
    assert filas["La Primera 12:00 PM"]["estado_panel"] == "PENDIENTE"
    from pathlib import Path
    html = Path(__file__).parent.joinpath("fixtures", "conectate_ejemplo.html").read_text(encoding="utf-8")
    db = dbmod.nueva_sesion()
    conectate.importar_resultados(db, date(2026, 11, 14), db.query(Usuario).filter_by(usuario="admin").one(), html=html)
    doc = {
        "date": "2026-11-14",
        "draws": [{
            "game": "la-primera-quiniela", "session": "dia", "date": "2026-11-14",
            "time": "12:00", "status": "verified", "numbers": ["01", "02", "03"],
            "reportedBy": ["enloteria", "conectate"], "url": "https://rdlotto.com/x",
        }],
    }
    resumen = rdlotto.sincronizar(db, date(2026, 11, 14), documento=doc)
    assert any("no coinciden" in alerta for alerta in resumen["alertas"])
    fila = db.query(Resultado).filter_by(sorteo_id=entorno.sorteo_id("La Primera 12:00 PM"), fecha=date(2026, 11, 14)).one()
    assert (fila.premio1, fila.premio2, fila.premio3) == (26, 58, 10)
    assert fila.fuente == "conectate"
    assert fila.estado == "propuesto"
    db.close()
