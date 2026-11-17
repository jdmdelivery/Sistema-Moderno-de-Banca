"""Entorno de pruebas: BD SQLite temporal nueva por test, hora fija
(sábado 2026-11-14 10:00 AST, con todos los sorteos abiertos) y helpers
para montar bancas, terminales y operadores sin repetir código.
"""
import os
import tempfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from apps.api import comun, db as dbmod
from apps.api import servicios
from apps.api.main import app

AHORA_FIJO = datetime(2026, 11, 14, 10, 0, 0)  # sábado 10:00 a. m.
FECHA = "2026-11-14"

# Los tests antiguos nombran el catálogo previo. La venta usa el sorteo activo nuevo.
_NOMBRES_ACTUALES = {
    "La Primera 12": "La Primera 12:00 PM",
    "La Suerte 12:30": "La Suerte Dominicana 12:30 PM",
    "King 12PM": "King Lottery 12:30 PM",
    "Real Tarde": "Quiniela Real 12:55 PM",
    "Florida Día": "Florida 2:30 PM",
    "Anguilla 1PM": "La Anguila 1:00 PM",
    "NY Tarde": "New York 3:30 PM",
    "Nacional Tarde": "Lotería Nacional 2:30 PM",
    "LOTEDOM": "Lotedom 12:00 PM",
    "La Primera 8PM": "La Primera 7:00 PM",
    "La Suerte 6PM": "La Suerte Dominicana 6:00 PM",
    "Anguilla 6PM": "La Anguila 6:00 PM",
    "LOTEKA": "Loteka 7:55 PM",
    "King 07PM": "King Lottery 7:30 PM",
    "Nacional Noche": "Lotería Nacional 9:00 PM",
    "Anguilla 9PM": "La Anguila 9:00 PM",
    "Florida Noche": "Florida 10:45 PM",
    "NY Noche": "New York 11:30 PM",
}


class Entorno:
    def __init__(self, client):
        self.c = client
        r = client.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
        assert r.status_code == 200, r.text
        self.admin = {"Authorization": f"Bearer {r.json()['token']}"}
        self._n = 0

    # ------------------------------------------------------------ catálogos
    def sorteo_id(self, nombre):
        nombre = _NOMBRES_ACTUALES.get(nombre, nombre)
        for s in self.c.get("/sorteos", headers=self.admin).json():
            if s["nombre"] == nombre and s["activo"]:
                return s["id"]
        raise AssertionError(f"Sorteo no encontrado: {nombre}")

    # ------------------------------------------------------------- sucursal
    def _headers_gestion(self):
        """Tras existir Super Admin, crear sucursales exige su token (o compat)."""
        return getattr(self, "super_admin", None) or self.admin

    def sucursal(self, codigo="1301", nombre="BANCA CASTILLO", comision=10):
        r = self.c.post(
            "/sucursales",
            json={"codigo": codigo, "nombre": nombre, "comision_porcentaje": comision},
            headers=self._headers_gestion(),
        )
        assert r.status_code == 201, r.text
        return r.json()

    def recargar(self, sucursal_id, monto):
        r = self.c.post(
            f"/sucursales/{sucursal_id}/recargar",
            json={"monto": monto, "referencia": "Efectivo de prueba"},
            headers=self._headers_gestion(),
        )
        assert r.status_code == 200, r.text
        return r.json()

    def saldo(self, sucursal_id):
        for s in self.c.get("/sucursales", headers=self._headers_gestion()).json():
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
            headers=self._headers_gestion(),
        )
        assert r.status_code == 201, r.text
        datos = r.json()
        return {"id": datos["id"], "serial": serial, "sucursal_id": sucursal_id}

    def operador(self, usuario, clave, sucursal_id):
        r = self.c.post(
            "/usuarios",
            json={"nombre": f"Operador {usuario}", "usuario": usuario, "rol": "operador",
                  "sucursal_id": sucursal_id, "clave": clave},
            headers=self._headers_gestion(),
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
        usuarios = self.c.get("/usuarios", headers=self.admin).json()
        existente = next((u for u in usuarios if u.get("usuario") == usuario), None)
        if existente and existente.get("sucursal_id"):
            sucursales = self.c.get("/sucursales", headers=self.admin).json()
            suc = next(s for s in sucursales if s["id"] == existente["sucursal_id"])
            if saldo:
                actual = float(suc.get("saldo_actual") or 0)
                if saldo > actual:
                    self.recargar(suc["id"], saldo - actual)
                    sucursales = self.c.get("/sucursales", headers=self.admin).json()
                    suc = next(s for s in sucursales if s["id"] == suc["id"])
            headers = self.login_terminal(usuario, clave)
            return {"sucursal": suc, "headers": headers}
        if codigo == "1301" and any(s.get("codigo") == "1301" for s in self.c.get("/sucursales", headers=self.admin).json()):
            self._n += 1
            codigo = f"T{self._n:04d}"
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
            headers=self._headers_gestion(),
        )
        assert r.status_code == 201, r.text
        return r.json()

    def confirmar(self, resultado_id):
        r = self.c.post(f"/resultados/{resultado_id}/confirmar", headers=self._headers_gestion())
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
    monkeypatch.setattr(comun, "ahora_local", lambda: AHORA_FIJO)
    client = TestClient(app)
    yield Entorno(client)
    client.close()
    if dbmod._engine is not None:
        dbmod._engine.dispose()
    os.unlink(ruta)


@pytest.fixture()
def fijar_hora(monkeypatch):
    """Permite a un test mover el reloj del servidor (ahora_local / ahora_oficial)."""

    def _fijar(dt):
        monkeypatch.setattr(servicios, "ahora_local", lambda: dt)
        monkeypatch.setattr(comun, "ahora_local", lambda: dt)

    return _fijar
