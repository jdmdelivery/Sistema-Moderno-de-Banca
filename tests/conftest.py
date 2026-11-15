"""Entorno de pruebas: BD SQLite temporal nueva por test, hora fija
(sábado 2026-11-14 10:00 AST, con todos los sorteos abiertos) y helpers
para montar bancas, terminales y operadores sin repetir código.
"""
import os
import tempfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from apps.api import db as dbmod
from apps.api import servicios
from apps.api.main import app

AHORA_FIJO = datetime(2026, 11, 14, 10, 0, 0)  # sábado 10:00 a. m.
FECHA = "2026-11-14"


class Entorno:
    def __init__(self, client):
        self.c = client
        r = client.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
        assert r.status_code == 200, r.text
        self.admin = {"Authorization": f"Bearer {r.json()['token']}"}
        self._n = 0

    # ------------------------------------------------------------ catálogos
    def sorteo_id(self, nombre):
        for s in self.c.get("/sorteos", headers=self.admin).json():
            if s["nombre"] == nombre:
                return s["id"]
        raise AssertionError(f"Sorteo no encontrado: {nombre}")

    # ------------------------------------------------------------- sucursal
    def sucursal(self, codigo="1301", nombre="BANCA CASTILLO", comision=10):
        r = self.c.post(
            "/sucursales",
            json={"codigo": codigo, "nombre": nombre, "comision_porcentaje": comision},
            headers=self.admin,
        )
        assert r.status_code == 201, r.text
        return r.json()

    def recargar(self, sucursal_id, monto):
        r = self.c.post(
            f"/sucursales/{sucursal_id}/recargar",
            json={"monto": monto, "referencia": "Efectivo de prueba"},
            headers=self.admin,
        )
        assert r.status_code == 200, r.text
        return r.json()

    def saldo(self, sucursal_id):
        for s in self.c.get("/sucursales", headers=self.admin).json():
            if s["id"] == sucursal_id:
                return float(s["saldo_actual"])
        raise AssertionError("sucursal no encontrada")

    # ------------------------------------------------------------- terminal
    def terminal(self, sucursal_id, numero=1):
        self._n += 1
        serial = f"SUNMI{self._n:06d}"
        r = self.c.post(
            "/terminales",
            json={"sucursal_id": sucursal_id, "numero_terminal": numero, "serial_sunmi": serial},
            headers=self.admin,
        )
        assert r.status_code == 201, r.text
        datos = r.json()
        return {"id": datos["id"], "serial": serial, "sucursal_id": sucursal_id}

    def operador(self, usuario, clave, sucursal_id):
        r = self.c.post(
            "/usuarios",
            json={"nombre": f"Operador {usuario}", "usuario": usuario, "rol": "operador",
                  "sucursal_id": sucursal_id, "clave": clave},
            headers=self.admin,
        )
        assert r.status_code == 201, r.text
        return r.json()

    def login_terminal(self, usuario="vend1", clave="1234"):
        # Desde 2026-11-14 la terminal entra SOLO con usuario y contraseña:
        # sin serial, sin token de activación, sin cabeceras de terminal.
        r = self.c.post("/terminal/login", json={"usuario": usuario, "clave": clave})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def banca(self, saldo=100000, codigo="1301", nombre="BANCA CASTILLO", usuario="vend1", clave="1234"):
        """Sucursal + operador + sesión, lista para vender (la terminal se
        resuelve sola desde la sucursal del operador al entrar)."""
        suc = self.sucursal(codigo=codigo, nombre=nombre)
        if saldo:
            self.recargar(suc["id"], saldo)
        self.operador(usuario, clave, suc["id"])
        headers = self.login_terminal(usuario, clave)
        return {"sucursal": suc, "headers": headers}

    # ---------------------------------------------------------------- venta
    def vender(self, headers, jugadas):
        return self.c.post("/terminal/venta", json={"jugadas": jugadas}, headers=headers)

    def vender_ok(self, headers, jugadas):
        r = self.vender(headers, jugadas)
        assert r.status_code == 201, r.text
        return r.json()

    # ------------------------------------------------------------ resultados
    def guardar_resultado(self, sorteo_id, p1, p2, p3, fecha=FECHA):
        r = self.c.post(
            "/resultados",
            json={"sorteo_id": sorteo_id, "fecha": fecha, "premio1": p1, "premio2": p2, "premio3": p3},
            headers=self.admin,
        )
        assert r.status_code == 201, r.text
        return r.json()

    def confirmar(self, resultado_id):
        r = self.c.post(f"/resultados/{resultado_id}/confirmar", headers=self.admin)
        assert r.status_code == 200, r.text
        return r.json()

    def liquidar(self, sorteo_id, p1, p2, p3, fecha=FECHA):
        r = self.guardar_resultado(sorteo_id, p1, p2, p3, fecha)
        return self.confirmar(r["id"])

    # -------------------------------------------------------------- tickets
    def consultar(self, ticket):
        r = self.c.post(
            "/panel/tickets/consultar",
            json={"id": ticket["id"], "serial": ticket["serial"]},
            headers=self.admin,
        )
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    fd, ruta = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    dbmod.configurar(f"sqlite:///{ruta}")
    dbmod.init_db()
    monkeypatch.setattr(servicios, "ahora_local", lambda: AHORA_FIJO)
    client = TestClient(app)
    yield Entorno(client)
    client.close()
    os.unlink(ruta)


@pytest.fixture()
def fijar_hora(monkeypatch):
    """Permite a un test mover el reloj del servidor (servicios.ahora_local)."""

    def _fijar(dt):
        monkeypatch.setattr(servicios, "ahora_local", lambda: dt)

    return _fijar
