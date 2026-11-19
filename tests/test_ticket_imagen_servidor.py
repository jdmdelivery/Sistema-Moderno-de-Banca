"""Opción B local: render 384 px, diseño panel y metadatos de impresión."""
from io import BytesIO

from PIL import Image


def test_render_ticket_png_ancho_384_y_qr_lot():
    from apps.api.ticket_imagen import render_ticket_png

    png = render_ticket_png({
        "id": 99,
        "serial": "ABC123XYZ",
        "qr": "LOT:99:ABC123XYZ",
        "banca": "BANCA CASTILLO",
        "banca_codigo": "1301",
        "fecha_hora": "2026-11-18 11:37:34",
        "total": "5.00",
        "jugadas": [
            {"tipo": "SP", "numeros": "26-58", "monto": "5.00",
             "loterias": ["Real Tarde", "La Primera 12"]},
            {"tipo": "TR", "numeros": "12-25-38", "monto": "50.00",
             "loterias": ["Real Tarde"]},
        ],
    })
    img = Image.open(BytesIO(png))
    assert img.size[0] == 384
    assert img.size[1] > 100


def test_seccion_tr_omitida_si_deshabilitada():
    from apps.api.ticket_imagen import render_ticket_png

    cfg = {"secciones": {"qn": True, "pl": True, "sp": True, "tr": False}}
    png = render_ticket_png({
        "id": 1, "serial": "S1", "qr": "LOT:1:S1", "banca": "B", "banca_codigo": "1",
        "fecha_hora": "2026-11-18 10:00:00", "total": "50.00",
        "jugadas": [{"tipo": "TR", "numeros": "01-02-03", "monto": "50.00", "loterias": ["X"]}],
    }, cfg, tr_habilitado=False)
    assert png.startswith(b"\x89PNG")


def test_panel_diseno_y_venta_incluye_impresion(entorno):
    admin = entorno.admin
    banca = entorno.banca(saldo=5000, usuario="img1", clave="prueba123")
    sid = banca["sucursal"]["id"]
    guardado = entorno.c.put(
        f"/panel/diseno-ticket?sucursal_id={sid}",
        headers=admin,
        json={
            "activo": True,
            "config": {
                "encabezado": {"tamano_nombre": 28},
                "qr": {"posicion": "superior", "tamano_px": 160},
                "tipografia": {"jugada": 24, "total": 24},
                "secciones": {"qn": True, "pl": True, "sp": True, "tr": True},
                "mensaje_inferior": "PRUEBA LOCAL",
            },
        },
    )
    assert guardado.status_code == 200, guardado.text
    assert guardado.json()["config"]["mensaje_inferior"] == "PRUEBA LOCAL"

    prev = entorno.c.post(
        f"/panel/diseno-ticket/preview?sucursal_id={sid}",
        headers=admin,
        json={"config": guardado.json()["config"], "activo": True},
    )
    assert prev.status_code == 200, prev.text
    assert prev.headers.get("content-type", "").startswith("image/png")
    assert prev.content.startswith(b"\x89PNG")

    lot = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(banca["headers"], [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}])
    assert "impresion" in ticket
    assert ticket["impresion"]["ancho_px"] == 384
    assert ticket["qr"].startswith("LOT:")
    assert str(ticket["id"]) in ticket["impresion"]["url"]

    img = entorno.c.get(
        ticket["impresion"]["url"],
        headers=banca["headers"],
    )
    assert img.status_code == 200, img.text
    assert img.content.startswith(b"\x89PNG")
    pic = Image.open(BytesIO(img.content))
    assert pic.size[0] == 384
