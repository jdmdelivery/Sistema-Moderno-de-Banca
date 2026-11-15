"""La Anguila y Haití Bolet: sesión firmada, tres lecturas y un solo pago."""
import json
from datetime import datetime
from decimal import Decimal

from apps.api import (
    conectate_firmado,
    conectate_widget,
    operador_king,
    operador_oficial,
    resultados_auto,
)
from apps.api import db as dbmod
from apps.api.models import Jugada, ObservacionResultado, Resultado, Sorteo, TipoJugada

FECHA = datetime(2026, 11, 14).date()
ANGUILA = [
    "8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
    "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM",
    "6:00 PM", "7:00 PM", "8:00 PM", "9:00 PM", "10:00 PM",
]
HAITI = ["9:30 AM", "10:30 AM", "11:30 AM", "5:30 PM", "6:30 PM", "7:30 PM"]


def _juego(titulo, gid, numeros, dia="2026-11-14T04:00:00.000Z", updated=None):
    return {
        "title": titulo,
        "game_id": gid,
        "game": {"sessions": [{
            "date": dia,
            "score": [f"{n:02d}" for n in numeros],
            "updatedAt": updated or dia,
        }]},
    }


def _empresa(juegos):
    return {"siteGames": juegos}


def _doc(anguila, haiti, senuelo_a=None, senuelo_h=None, firma=True):
    return {
        "firma": firma,
        "anguila": _empresa(anguila),
        "haiti": _empresa(haiti),
        "senuelo_anguila": _empresa(senuelo_a if senuelo_a is not None else []),
        "senuelo_haiti": _empresa(senuelo_h if senuelo_h is not None else []),
    }


def _par(horas, prefijo, base):
    reales = []
    senuelos = []
    esperados = {}
    for i, hora in enumerate(horas):
        real = (base + i, base + 20 + i, base + 40 + i)
        reales.append(_juego(f"{prefijo} {hora}", f"{prefijo}-{hora}", real))
        senuelos.append(_juego(f"{prefijo} {hora}", f"s-{prefijo}-{hora}", (90, 91, 92)))
        esperados[f"{prefijo} {hora}"] = real
    return reales, senuelos, esperados


def _widget(titulo, numeros):
    return {"game_title": titulo, "date": "14-11", "score": [str(n) for n in numeros]}


def _operador(firmado, fecha=FECHA):
    return {
        nombre: {"fecha": fecha, "numeros": dato["numeros"]}
        for nombre, dato in conectate_firmado.propuestos(firmado, fecha).items()
    }


def _filas():
    db = dbmod.nueva_sesion()
    filas = {
        fila.sorteo.nombre: (fila.premio1, fila.premio2, fila.premio3, fila.externo, fila.estado)
        for fila in db.query(Resultado)
    }
    db.close()
    return filas


def test_reconoce_los_21_horarios_y_rechaza_lo_inseguro():
    anguila, senuelo_a, esp_a = _par(ANGUILA, "La Anguila", 1)
    haiti, senuelo_h, esp_h = _par(HAITI, "Haiti Bolet", 2)
    haiti[0]["game"]["sessions"][0]["score"] = [[f"{n:02d}" for n in esp_h["Haiti Bolet 9:30 AM"]]]
    anguila.append(_juego("La Anguila Cuarteta 8:00 AM", "cuarteta", (1, 2, 3)))
    anguila.append(_juego("Anguila 7:00 AM", "fuera", (4, 5, 6)))
    anguila.append({"title": "Anguila 8:00 AM", "game": {"sessions": [
        {"date": "2026-11-14T04:00:00.000Z", "score": ["07", "08", "09"]},
    ]}})
    leidos = conectate_firmado.leer(_doc(anguila, haiti, senuelo_a, senuelo_h), FECHA)
    assert set(leidos) == set(esp_a) | set(esp_h)
    assert len(leidos) == 21
    for nombre, numeros in {**esp_a, **esp_h}.items():
        assert leidos[nombre]["numeros"] == numeros
        assert leidos[nombre]["fecha"] == FECHA
        assert leidos[nombre]["origen"] == "firmado"
    assert conectate_firmado.leer(_doc(anguila, haiti, senuelo_a, senuelo_h, firma=False), FECHA) == {}
    sin_senuelo = _doc(anguila, haiti, senuelo_a, senuelo_h)
    sin_senuelo["senuelo_anguila"] = None
    solo_haiti = conectate_firmado.leer(sin_senuelo, FECHA)
    assert set(solo_haiti) == set(esp_h)
    sin_senuelo["senuelo_haiti"] = None
    assert conectate_firmado.leer(sin_senuelo, FECHA) == {}

    otra_fecha = _juego("Anguila 9:00 AM", "ayer", (3, 23, 43), dia="2026-11-13T04:00:00.000Z")
    cuatro = _juego("Anguila 10:00 AM", "cuatro", (1, 2, 3))
    cuatro["game"]["sessions"][0]["score"] = ["01", "02", "03", "04"]
    conflicto_a = _juego("Anguila 11:00 AM", "a", (5, 25, 45))
    conflicto_b = _juego("Anguila 11:00 AM", "b", (6, 26, 46))
    igual = _juego("Anguila 12:00 PM", "igual", (7, 27, 47))
    distinto = _juego("Anguila 1:00 PM", "distinto", (8, 28, 48))
    parcial = conectate_firmado.leer(_doc(
        [otra_fecha, cuatro, conflicto_a, conflicto_b, igual, distinto],
        [],
        [
            _juego("Anguila 11:00 AM", "sa", (1, 2, 3)),
            igual,
            _juego("Anguila 1:00 PM", "sd", (9, 10, 11)),
        ],
        [],
    ), FECHA)
    assert parcial == {
        "La Anguila 1:00 PM": {
            "fecha": FECHA, "numeros": (8, 28, 48), "titulo": "La Anguila 1:00 PM", "origen": "firmado",
        },
    }
    reciente = _juego("Anguila 2:00 PM", "nuevo", (9, 29, 49), updated="2026-11-14T18:00:00.000Z")
    viejo = _juego("Anguila 2:00 PM", "viejo", (1, 2, 3), updated="2026-11-14T12:00:00.000Z")
    # El mismo game no se parte: dos sesiones del mismo juego quedan en un solo siteGame.
    reciente["game"]["sessions"].append(viejo["game"]["sessions"][0])
    elegido = conectate_firmado.extraer(_empresa([reciente]), FECHA, "anguila")
    assert elegido == {"2:00 PM": (9, 29, 49)}
    assert conectate_firmado._hora("Anguila 8 AM", "anguila") == "8:00 AM"
    assert conectate_firmado._hora("Haiti Bolet 6:30PM", "haiti") == "6:30 PM"


def test_tres_lecturas_confirman_los_21_y_dejan_quieta_la_otra_loteria(entorno, fijar_hora):
    anguila, senuelo_a, esp_a = _par(ANGUILA, "La Anguila", 1)
    haiti, senuelo_h, esp_h = _par(HAITI, "Haiti Bolet", 2)
    firmado = _doc(anguila, haiti, senuelo_a, senuelo_h)
    firmado["anguila"]["siteGames"].append(
        _juego("Quiniela Leidsa", "leidsa-falso", (4, 5, 6))
    )
    widget = [_widget("Quiniela Leidsa", (19, 3, 45))]
    base = datetime(2026, 11, 14, 10, 0)
    for minuto in (0, 4):
        fijar_hora(base.replace(minute=minuto))
        paso = resultados_auto.ciclo(
            forzar=True, payload=widget, firmado=firmado, operador=_operador(firmado),
        )
        assert paso["ok"] is True and paso["confirmados"] == 0 and paso["rdlotto"] is False
    fijar_hora(base.replace(minute=10))
    final = resultados_auto.ciclo(
        forzar=True, payload=widget, firmado=firmado, operador=_operador(firmado),
    )
    assert final["confirmados"] == 22
    filas = _filas()
    assert len(filas) == 22
    for nombre, numeros in {**esp_a, **esp_h}.items():
        assert filas[nombre][:4] == numeros + ("operador",)
        assert filas[nombre][4] == "liquidado"
    assert filas["Leidsa 8:55 PM"][:4] == (19, 3, 45, "widget")
    assert all(fila[:3] != (4, 5, 6) for fila in filas.values())


def test_el_widget_no_sustituye_al_operador(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0))
    solo_widget = [_widget("Anguila 10:00 AM", (19, 3, 45))]
    primero = resultados_auto.ciclo(forzar=True, payload=solo_widget, firmado=_doc([], []))
    assert primero["encontrados"] == 0
    assert "La Anguila 10:00 AM" not in _filas()
    firmado = _doc(
        [_juego("Anguila 8:00 AM", "g8", (1, 2, 3)), _juego("Anguila 10:00 AM", "g10", (7, 8, 9))],
        [],
        [_juego("Anguila 8:00 AM", "s8", (1, 2, 3)), _juego("Anguila 10:00 AM", "s10", (7, 8, 9))],
        [],
    )
    fijar_hora(datetime(2026, 11, 14, 10, 4))
    resultados_auto.ciclo(
        forzar=True, payload=solo_widget, firmado=firmado, operador=_operador(firmado),
    )
    filas = _filas()
    assert filas["La Anguila 8:00 AM"][:4] == (1, 2, 3, "operador")
    assert filas["La Anguila 10:00 AM"][:4] == (7, 8, 9, "operador")
    assert (19, 3, 45) not in {fila[:3] for fila in filas.values()}
    db = dbmod.nueva_sesion()
    sorteo = db.query(Sorteo).filter_by(nombre="La Anguila 10:00 AM").one()
    obs = db.query(ObservacionResultado).filter_by(sorteo_id=sorteo.id, fecha=FECHA).one()
    assert obs.lecturas == 1
    db.close()


def test_la_prueba_no_abre_el_websocket(entorno, monkeypatch):
    def prohibido(hoy):
        raise AssertionError("no debe consultar la red")

    monkeypatch.setattr(conectate_firmado, "descargar_ventana", prohibido)
    monkeypatch.setattr(operador_oficial, "confirmar_ventana", prohibido)
    monkeypatch.setattr(operador_king, "confirmar_ventana", prohibido)
    monkeypatch.setattr(conectate_widget, "descargar", lambda timeout=20: (None, "HTTP 403"))
    mal = resultados_auto.ciclo()
    assert mal["ok"] is False
    assert _filas() == {}


def test_si_el_widget_cae_la_firma_puede_seguir(entorno, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(conectate_widget, "descargar", lambda timeout=20: (None, "HTTP 403"))
    monkeypatch.setattr(operador_king, "confirmar_ventana", lambda hoy: ({}, None, []))
    doc = _doc(
        [_juego("Anguila 8:00 AM", "g8", (4, 5, 6))],
        [_juego("Haiti Bolet 9:30 AM", "h9", (7, 8, 9))],
        [_juego("Anguila 8:00 AM", "s8", (1, 2, 3))],
        [_juego("Haiti Bolet 9:30 AM", "sh", (1, 2, 3))],
    )

    def falso(hoy):
        candidatos = conectate_firmado.propuestos(doc, hoy)
        aceptados, difs = operador_oficial.cruzar(candidatos, _operador(doc, hoy), hoy)
        return aceptados, None, difs

    monkeypatch.setattr(operador_oficial, "confirmar_ventana", falso)
    paso = resultados_auto.ciclo(forzar=True)
    assert paso["ok"] is True and paso["encontrados"] == 2
    filas = _filas()
    assert set(filas) == {"La Anguila 8:00 AM", "Haiti Bolet 9:30 AM"}
    assert filas["La Anguila 8:00 AM"][3] == "operador"


def _preparar(entorno):
    b = entorno.banca(saldo=5764, nombre="BANCA CASTILLO (PRUEBA)", usuario="0219", clave="prueba123")
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-anguila",
    }, headers=entorno.admin)
    assert fondo.status_code == 201, fondo.text
    return b


def test_identifica_quiniela_y_pale_y_no_paga_dos_veces(entorno, fijar_hora, monkeypatch):
    monkeypatch.setenv("MODO_DESARROLLO", "true")
    db = dbmod.nueva_sesion()
    assert {fila.codigo for fila in db.query(TipoJugada).all()} == {"QN", "PL", "SP"}
    db.close()
    b = _preparar(entorno)
    anguila = entorno.sorteo_id("La Anguila 11:00 AM")
    haiti = entorno.sorteo_id("Haiti Bolet 11:30 AM")
    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [anguila], "numeros": "11", "monto": 10},
        {"tipo": "QN", "sorteos": [anguila], "numeros": "99", "monto": 10},
        {"tipo": "PL", "sorteos": [haiti], "numeros": "19-03", "monto": 5},
        {"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [florida], "numeros": "25", "monto": 10},
    ])
    firmado = _doc(
        [_juego("Anguila 11:00 AM", "g11", (11, 22, 33))],
        [_juego("Haiti Bolet 11:30 AM", "h11", (19, 3, 45))],
        [_juego("Anguila 11:00 AM", "s11", (1, 2, 3))],
        [_juego("Haiti Bolet 11:30 AM", "sh", (4, 5, 6))],
    )
    widget = [_widget("La Primera Día", (25, 54, 78))]
    base = datetime(2026, 11, 14, 10, 0)
    for minuto in (0, 4, 10):
        fijar_hora(base.replace(minute=minuto))
        resultados_auto.ciclo(
            forzar=True, payload=widget, firmado=firmado, operador=_operador(firmado),
        )
    consulta = entorno.c.post("/terminal/tickets/consultar", json={
        "id": ticket["id"], "serial": ticket["serial"],
    }, headers=b["headers"])
    assert consulta.status_code == 200, consulta.text
    cuerpo = consulta.json()
    assert cuerpo["estado"] == "vendido"
    assert cuerpo["puede_pagar"] is True
    assert cuerpo["premio_pendiente"] == "7200.00"
    assert cuerpo["texto_pago"].count("Lotería:") == 3
    assert "La Anguila 11:00 AM" in cuerpo["texto_pago"]
    assert "Haiti Bolet 11:30 AM" in cuerpo["texto_pago"]
    assert "La Primera 12:00 PM" in cuerpo["texto_pago"]
    assert "QUINIELA" in cuerpo["texto_pago"]
    assert "PALÉ" in cuerpo["texto_pago"]
    assert "Número ganador: 11-22-33" in cuerpo["texto_pago"]
    assert "Número ganador: 19-03-45" in cuerpo["texto_pago"]
    assert "Premio: RD$600.00" in cuerpo["texto_pago"]
    assert "Premio: RD$6000.00" in cuerpo["texto_pago"]
    assert "Jugada: 99" not in cuerpo["texto_pago"]
    assert "Florida 2:30 PM" in cuerpo["texto_pago"]
    assert "SORTEOS PENDIENTES" in cuerpo["texto_pago"]
    antes = float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"])
    caja_real = entorno.saldo(b["sucursal"]["id"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-anguila",
    }, headers=b["headers"])
    assert pago.status_code == 200, pago.text
    assert float(pago.json()["mi_caja"]) == antes - 7200
    assert entorno.saldo(b["sucursal"]["id"]) == caja_real
    otra = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-anguila-copia",
    }, headers=b["headers"])
    assert otra.status_code == 409
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == antes - 7200
    simulado = entorno.c.post("/resultados", json={
        "sorteo_id": florida, "fecha": "2026-11-14",
        "premio1": 25, "premio2": 1, "premio3": 2, "simulado": True,
    }, headers=entorno.admin)
    assert simulado.status_code == 201, simulado.text
    resto = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-florida",
    }, headers=b["headers"])
    assert resto.status_code == 200, resto.text
    assert resto.json()["estado"] == "pagado"
    assert float(resto.json()["mi_caja"]) == antes - 7800
    assert entorno.saldo(b["sucursal"]["id"]) == caja_real
    tercero = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pago-florida-copia",
    }, headers=b["headers"])
    assert tercero.status_code == 409
    assert float(entorno.c.get("/terminal/sorteos", headers=b["headers"]).json()["mi_caja"]) == antes - 7800


def test_el_reloj_de_cuatro_minutos_guarda_la_firma_y_usa_la_foto(entorno, fijar_hora):
    assert resultados_auto.INTERVALO_SEGUNDOS == 240
    fijar_hora(datetime(2026, 11, 14, 10, 0))
    b = entorno.banca()
    anguila = entorno.sorteo_id("La Anguila 11:00 AM")
    haiti = entorno.sorteo_id("Haiti Bolet 11:30 AM")
    tarde = entorno.sorteo_id("La Anguila 1:00 PM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [anguila], "numeros": "11", "monto": 10},
        {"tipo": "PL", "sorteos": [haiti], "numeros": "19-03", "monto": 5},
        {"tipo": "SP", "sorteos": [anguila, haiti], "numeros": "11-19", "monto": 5},
    ])
    for tipo, clave, factor in (("QN", "1ro", 80), ("PL", "1-2", 1500), ("SP", "sp", 3500)):
        cambio = entorno.c.post("/tabla-pagos", json={
            "tipo": tipo, "clave": clave, "factor": factor,
            "vigente_desde": "2026-11-14 10:05",
        }, headers=entorno.admin)
        assert cambio.status_code == 201, cambio.text
    fijar_hora(datetime(2026, 11, 14, 10, 6))
    posterior = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [tarde], "numeros": "01", "monto": 10},
    ])
    firmado = _doc(
        [_juego("Anguila 11:00 AM", "g11", (11, 22, 33))],
        [_juego("Haiti Bolet 11:30 AM", "h11", (19, 3, 45))],
        [_juego("Anguila 11:00 AM", "s11", (1, 2, 3))],
        [_juego("Haiti Bolet 11:30 AM", "sh", (4, 5, 6))],
    )
    base = datetime(2026, 11, 14, 10, 0)
    for minuto in (0, 4, 10):
        fijar_hora(base.replace(minute=minuto))
        paso = resultados_auto.ciclo(
            forzar=True, payload=[], firmado=firmado, operador=_operador(firmado),
        )
        assert paso["ok"] is True and paso["rdlotto"] is False
    fijar_hora(base.replace(minute=12))
    repetida = resultados_auto.ciclo(
        forzar=False, payload=[], firmado=firmado, operador=_operador(firmado),
    )
    assert repetida["omitido"] == "otra consulta ya corrió en este intervalo"
    db = dbmod.nueva_sesion()
    vendidas = db.query(Jugada).filter_by(ticket_id=ticket["id"]).all()
    foto = {j.tipo.codigo: json.loads(j.factores_json) for j in vendidas}
    premios = {j.tipo.codigo: str(j.premio) for j in vendidas}
    obs = db.query(ObservacionResultado).filter_by(
        sorteo_id=anguila, fecha=FECHA,
    ).one()
    nueva = db.query(Jugada).filter_by(ticket_id=posterior["id"]).one()
    db.close()
    assert Decimal(foto["QN"]["1ro"]) == Decimal("60")
    assert Decimal(foto["PL"]["1-2"]) == Decimal("1200")
    assert Decimal(foto["SP"]["sp"]) == Decimal("2500")
    assert premios == {"QN": "600.00", "PL": "6000.00", "SP": "12500.00"}
    assert Decimal(json.loads(nueva.factores_json)["1ro"]) == Decimal("80")
    assert nueva.evaluada is False
    assert obs.lecturas == 3
    filas = _filas()
    assert filas["La Anguila 11:00 AM"] == (11, 22, 33, "operador", "liquidado")
    assert filas["Haiti Bolet 11:30 AM"] == (19, 3, 45, "operador", "liquidado")
    assert "La Anguila 1:00 PM" not in filas
    assert entorno.saldo(b["sucursal"]["id"]) == 100030
    consulta = entorno.consultar(ticket)
    assert consulta["premio_total"] == "19100.00"
    assert consulta["estado"] == "ganador"
