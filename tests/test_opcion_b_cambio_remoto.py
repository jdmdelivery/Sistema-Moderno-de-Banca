"""Demo Opción B: el diseño cambia en el servidor y la imagen del ticket
se actualiza sin recompilar la APK (la APK solo descarga el PNG)."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image


OUT = Path(__file__).resolve().parents[1] / "docs" / "respaldos" / "capturas_ticket_opcion_b"


def test_cambio_diseno_remoto_sin_recompilar_apk(entorno, monkeypatch, fijar_hora):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    fijar_hora(datetime(2026, 11, 14, 10, 15, 0))
    OUT.mkdir(parents=True, exist_ok=True)

    banca = entorno.banca(saldo=8000, usuario="remoto1", clave="prueba123")
    sid = banca["sucursal"]["id"]
    lot = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(
        banca["headers"],
        [{"tipo": "QN", "sorteos": [lot], "numeros": "25", "monto": 10}],
    )
    url = ticket["impresion"]["url"]
    assert ticket["qr"] == f"LOT:{ticket['id']}:{ticket['serial']}"

    # --- Diseño A (baseline) ---
    a = entorno.c.put(
        f"/panel/diseno-ticket?sucursal_id={sid}",
        headers=entorno.admin,
        json={
            "activo": True,
            "config": {
                "encabezado": {"tamano_nombre": 26},
                "qr": {"posicion": "superior", "tamano_px": 160},
                "tipografia": {"jugada": 22, "total": 22},
                "secciones": {"qn": True, "pl": True, "sp": True, "tr": True},
                "mensaje_inferior": "DISENO-A-LOCAL",
            },
        },
    )
    assert a.status_code == 200, a.text

    img_a = entorno.c.get(url, headers=banca["headers"])
    assert img_a.status_code == 200
    assert img_a.content.startswith(b"\x89PNG")
    assert Image.open(BytesIO(img_a.content)).size[0] == 384
    (OUT / "remoto_antes_diseno_a.png").write_bytes(img_a.content)

    # --- Diseño B (cambio remoto: mensaje + tipografía mayor) ---
    b = entorno.c.put(
        f"/panel/diseno-ticket?sucursal_id={sid}",
        headers=entorno.admin,
        json={
            "activo": True,
            "config": {
                "encabezado": {"tamano_nombre": 32},
                "qr": {"posicion": "superior", "tamano_px": 180},
                "tipografia": {"jugada": 28, "total": 28},
                "secciones": {"qn": True, "pl": True, "sp": True, "tr": True},
                "mensaje_inferior": "DISENO-B-REMOTO-SIN-RECOMPILAR",
            },
        },
    )
    assert b.status_code == 200, b.text
    assert b.json()["config"]["mensaje_inferior"] == "DISENO-B-REMOTO-SIN-RECOMPILAR"

    img_b = entorno.c.get(url, headers=banca["headers"])
    assert img_b.status_code == 200
    assert img_b.content.startswith(b"\x89PNG")
    assert Image.open(BytesIO(img_b.content)).size[0] == 384
    (OUT / "remoto_despues_diseno_b.png").write_bytes(img_b.content)

    # Misma URL de ticket, PNG distinto → la APK nueva lo recibiría al reimprimir/vender
    # sin necesidad de recompilar (solo descarga bytes).
    assert img_a.content != img_b.content, "el PNG debe cambiar tras editar el diseño remoto"
    assert img_b.headers.get("x-ticket-qr") == ticket["qr"] or img_b.headers.get("X-Ticket-QR") == ticket["qr"]

    # Preview del panel también refleja el diseño B.
    prev = entorno.c.post(
        f"/panel/diseno-ticket/preview?sucursal_id={sid}",
        headers=entorno.admin,
        json={"config": b.json()["config"], "activo": True},
    )
    assert prev.status_code == 200
    (OUT / "remoto_preview_diseno_b.png").write_bytes(prev.content)
