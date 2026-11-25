"""Historial de ventas de la terminal: propios, paginado, sin reimprimir anulados."""


def test_historial_lista_solo_propios_y_pagina(entorno):
    castillo = entorno.banca(saldo=500, codigo="1301", nombre="BANCA CASTILLO", usuario="isaury")
    otra = entorno.banca(saldo=500, codigo="2200", nombre="BANCA PEGUERO", usuario="wanda")
    s = entorno.sorteo_id("La Primera 12")
    t1 = entorno.vender_ok(castillo["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "11", "monto": 10},
    ])
    t2 = entorno.vender_ok(castillo["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "22", "monto": 20},
    ])
    ajeno = entorno.vender_ok(otra["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "33", "monto": 30},
    ])

    r = entorno.c.get("/terminal/tickets/historial", headers=castillo["headers"])
    assert r.status_code == 200, r.text
    datos = r.json()
    ids = [fila["id"] for fila in datos["tickets"]]
    assert t2["id"] in ids
    assert t1["id"] in ids
    assert ajeno["id"] not in ids
    assert ids == sorted(ids, reverse=True)
    assert datos["pagina"] == 1
    assert datos["por_pagina"] == 20

    pagina1 = entorno.c.get(
        "/terminal/tickets/historial?por_pagina=1&pagina=1",
        headers=castillo["headers"],
    ).json()
    pagina2 = entorno.c.get(
        "/terminal/tickets/historial?por_pagina=1&pagina=2",
        headers=castillo["headers"],
    ).json()
    assert pagina1["paginas"] >= 2
    assert len(pagina1["tickets"]) == 1
    assert len(pagina2["tickets"]) == 1
    assert pagina1["tickets"][0]["id"] != pagina2["tickets"][0]["id"]
    assert pagina1["tickets"][0]["id"] == t2["id"]


def test_historial_busca_por_ticket_y_oculta_ajenos(entorno):
    a = entorno.banca(saldo=200, usuario="cajA")
    b = entorno.banca(saldo=200, codigo="3300", nombre="OTRA BANCA", usuario="cajB")
    s = entorno.sorteo_id("La Primera 12")
    propio = entorno.vender_ok(a["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "44", "monto": 15},
    ])
    ajeno = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "55", "monto": 15},
    ])

    ok = entorno.c.get(
        f"/terminal/tickets/historial?ticket_id={propio['id']}",
        headers=a["headers"],
    ).json()
    assert ok["total"] == 1
    assert ok["tickets"][0]["id"] == propio["id"]
    assert ok["tickets"][0]["puede_reimprimir"] is True

    vacío = entorno.c.get(
        f"/terminal/tickets/historial?ticket_id={ajeno['id']}",
        headers=a["headers"],
    ).json()
    assert vacío["total"] == 0
    assert vacío["tickets"] == []


def test_reimprimir_historial_exige_dueña_bloquea_anulado_y_no_mueve_caja(entorno):
    a = entorno.banca(saldo=300, usuario="dueña")
    b = entorno.banca(saldo=300, codigo="4400", nombre="BANCA B", usuario="otra")
    s = entorno.sorteo_id("La Primera 12")
    ticket = entorno.vender_ok(a["headers"], [
        {"tipo": "QN", "sorteos": [s], "numeros": "66", "monto": 25},
    ])
    antes = entorno.saldo(a["sucursal"]["id"])

    ajena = entorno.c.post(
        "/terminal/tickets/reimprimir",
        json={"id": ticket["id"], "serial": ticket["serial"]},
        headers=b["headers"],
    )
    assert ajena.status_code == 403, ajena.text

    ok = entorno.c.post(
        "/terminal/tickets/reimprimir",
        json={"id": ticket["id"], "serial": ticket["serial"]},
        headers=a["headers"],
    )
    assert ok.status_code == 200, ok.text
    copia = ok.json()
    assert copia["id"] == ticket["id"]
    assert copia["serial"] == ticket["serial"]
    assert copia["reimpresion"] is True
    assert copia["leyenda"] == "COPIA — REIMPRESIÓN"
    assert entorno.saldo(a["sucursal"]["id"]) == antes

    entorno.c.post(
        "/terminal/tickets/anular",
        json={"id": ticket["id"], "serial": ticket["serial"], "motivo": "error de prueba"},
        headers=a["headers"],
    )
    lista = entorno.c.get(
        f"/terminal/tickets/historial?ticket_id={ticket['id']}",
        headers=a["headers"],
    ).json()
    assert lista["tickets"][0]["estado"] == "anulado"
    assert lista["tickets"][0]["puede_reimprimir"] is False

    bloqueada = entorno.c.post(
        "/terminal/tickets/reimprimir",
        json={"id": ticket["id"], "serial": ticket["serial"]},
        headers=a["headers"],
    )
    assert bloqueada.status_code == 409, bloqueada.text
    assert "anulado" in bloqueada.json()["detail"].lower()
    assert entorno.saldo(a["sucursal"]["id"]) == 300.00
