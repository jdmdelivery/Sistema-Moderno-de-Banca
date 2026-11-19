"""S/N numérico para tickets nuevos; compatibilidad con S/N alfanumérico legado."""
from apps.api import servicios
from apps.api.security import es_serial_numerico, generar_serial
from apps.api.servicios import normalizar_serial_busqueda


def test_generar_serial_solo_digitos_con_ceros():
    vistos = set()
    for _ in range(40):
        s = generar_serial()
        assert len(s) == 12
        assert s.isdigit()
        assert es_serial_numerico(s)
        vistos.add(s)
    assert len(vistos) >= 35


def test_normalizar_serial_conserva_ceros_y_legacy_upper():
    assert normalizar_serial_busqueda("000000012345") == "000000012345"
    assert normalizar_serial_busqueda(" 000000012345 ") == "000000012345"
    assert normalizar_serial_busqueda("tmfm38gphx") == "TMFM38GPHX"
    assert normalizar_serial_busqueda("TMFM38GPHX") == "TMFM38GPHX"


def test_venta_nueva_serial_numerico_consultable(entorno):
    b = entorno.banca(saldo=1000, codigo="SN01", nombre="BANCA SERIAL", usuario="vend_sn", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "25", "monto": 5},
    ])
    assert t["serial"].isdigit() and len(t["serial"]) == 12
    assert t["qr"] == f"LOT:{t['id']}:{t['serial']}"

    c = entorno.c.post(
        "/terminal/tickets/consultar",
        headers=b["headers"],
        json={"id": t["id"], "serial": t["serial"]},
    )
    assert c.status_code == 200, c.text
    assert c.json()["serial"] == t["serial"]


def test_consulta_acepta_serial_alfanumerico_legado(entorno, monkeypatch):
    """Tickets antiguos con S/N alfanumérico siguen consultables (case-insensitive)."""
    monkeypatch.setattr(servicios, "generar_serial", lambda: "LEGACY9ABC")
    b = entorno.banca(saldo=1000, codigo="SN02", nombre="BANCA LEGACY", usuario="vend_lg", clave="1234")
    s = entorno.sorteo_id("La Primera 12")
    t = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "11", "monto": 5},
    ])
    assert t["serial"] == "LEGACY9ABC"
    c = entorno.c.post(
        "/terminal/tickets/consultar",
        headers=b["headers"],
        json={"id": t["id"], "serial": "legacy9abc"},
    )
    assert c.status_code == 200, c.text
    assert c.json()["serial"] == "LEGACY9ABC"
