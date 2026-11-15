"""La Anguila y Haití Bolet solo se confirman si el operador coincide.

El widget no sustituye esa verificación. Una caída del operador deja
el sorteo pendiente y no detiene las demás loterías.
"""
import json
import urllib.error
from datetime import datetime, timedelta

from apps.api import (
    conectate_firmado,
    conectate_widget,
    operador_king,
    operador_oficial,
    resultados_auto,
)
from apps.api import db as dbmod
from apps.api.models import Auditoria, ObservacionResultado, Resultado

FECHA = datetime(2026, 11, 14).date()
ANGUILA = [
    "8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
    "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM",
    "6:00 PM", "7:00 PM", "8:00 PM", "9:00 PM", "10:00 PM",
]
HAITI = ["9:30 AM", "10:30 AM", "11:30 AM", "5:30 PM", "6:30 PM", "7:30 PM"]


def _juego(titulo, gid, numeros, dia="2026-11-14T04:00:00.000Z"):
    return {
        "title": titulo,
        "game_id": gid,
        "game": {"sessions": [{
            "date": dia,
            "score": [f"{n:02d}" for n in numeros],
            "updatedAt": dia,
        }]},
    }


def _doc(anguila, haiti, senuelo_a=None, senuelo_h=None):
    return {
        "firma": True,
        "anguila": {"siteGames": anguila},
        "haiti": {"siteGames": haiti},
        "senuelo_anguila": {"siteGames": senuelo_a if senuelo_a is not None else []},
        "senuelo_haiti": {"siteGames": senuelo_h if senuelo_h is not None else []},
    }


def _triple(indice):
    return (indice, indice + 10, indice + 20)


def _html_anguila(filas, fecha):
    dia = fecha.strftime("%d/%m/%Y")
    partes = []
    for hora, numeros in filas:
        marca = hora.replace(" ", "")
        if hora == "3:00 PM":
            partes.append(
                '<div class="result-sorteo">'
                f'<div class="horassorteo">Draw {marca}. {dia}</div>'
                f'<span class="numero"><span class="small">FIRST</span>{numeros[0]:02d}</span>'
                f'<span class="numero"><span class="small">SECOND</span>{numeros[1]:02d}</span>'
                f'<span class="numero"><span class="small">THIRD</span>{numeros[2]:02d}</span>'
                "</div>"
            )
            continue
        partes.append(
            '<div class="result-sorteo"><div class="fecha">'
            f"{marca}<br />{dia}</div>"
            f'<span class="numero">{numeros[0]:02d}</span>'
            f'<span class="numero">{numeros[1]:02d}</span>'
            f'<span class="numero">{numeros[2]:02d}</span></div>'
        )
    partes.append(
        '<div class="result-sorteo"><img src="cuarteta.jpg">'
        f'<div class="fecha">8:00AM<br />{dia}</div>'
        '<span class="numero">90</span><span class="numero">91</span>'
        '<span class="numero">92</span><span class="numero">93</span></div>'
    )
    partes.append(
        '<div class="result-sorteo rapidita"><div class="fecha">'
        f"8:05AM<br />{dia}</div>"
        '<span class="numero">01</span><span class="numero">02</span>'
        '<span class="numero">03</span></div>'
    )
    return "\n".join(partes)


def _haiti(hora, fecha, numeros, nombre=None):
    return {
        "message": "ok",
        "data": {
            "name_sorteo": nombre or operador_oficial._NOMBRES[hora],
            "date": fecha.isoformat() + "T00:00:00.000Z",
            "numeros_ganadores": {
                "tradicional": [f"{n:02d}" for n in numeros],
                "pick3": ["111", "222", "333"],
            },
        },
    }


def _filas():
    db = dbmod.nueva_sesion()
    filas = {
        fila.sorteo.nombre: (
            fila.premio1, fila.premio2, fila.premio3, fila.fuente, fila.externo, fila.estado,
        )
        for fila in db.query(Resultado)
    }
    db.close()
    return filas


def _anguila():
    return [(hora, _triple(i + 1)) for i, hora in enumerate(ANGUILA)]


def _boletos_haiti():
    return [(hora, _triple(i + 30)) for i, hora in enumerate(HAITI)]


def test_los_21_horarios_coinciden_en_fecha_hora_y_tres_numeros():
    anguila = _anguila()
    haiti = _boletos_haiti()
    html = _html_anguila(anguila, FECHA)
    leidos = operador_oficial.leer_anguila(html, FECHA)
    assert len(leidos) == 15
    candidatos = {}
    for hora, numeros in anguila:
        nombre = "La Anguila " + hora
        candidatos[nombre] = {"fecha": FECHA, "numeros": numeros}
        assert leidos[(nombre, FECHA)]["numeros"] == numeros
    for hora, numeros in haiti:
        nombre = "Haiti Bolet " + hora
        fila = operador_oficial.interpretar_haiti(_haiti(hora, FECHA, numeros), hora, FECHA, FECHA)
        assert fila["numeros"] == numeros
        leidos[(nombre, FECHA)] = {"fecha": FECHA, "numeros": numeros}
        candidatos[nombre] = {"fecha": FECHA, "numeros": numeros}
    aceptados, discrepancias = operador_oficial.cruzar(candidatos, leidos, FECHA)
    assert discrepancias == []
    assert len(aceptados) == 21
    assert all(dato["origen"] == "operador" for dato in aceptados.values())


def test_el_senuelo_igual_se_acepta_solo_si_el_operador_coincide(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0))
    juego = _juego("Anguila 10:00 AM", "g10", (89, 17, 9))
    firmado = _doc([juego], [], [juego], [])
    assert conectate_firmado.leer(firmado, FECHA) == {}
    operador = {"La Anguila 10:00 AM": {"fecha": FECHA, "numeros": (89, 17, 9)}}
    paso = resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado, operador=operador)
    assert paso["ok"] is True and paso["confirmados"] == 0
    assert _filas()["La Anguila 10:00 AM"][:5] == (89, 17, 9, "conectate", "operador")


def test_numeros_distintos_se_rechazan_y_quedan_auditados(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0))
    firmado = _doc(
        [_juego("Anguila 10:00 AM", "g10", (11, 22, 33))],
        [],
        [_juego("Anguila 10:00 AM", "s10", (1, 2, 3))],
        [],
    )
    operador = {"La Anguila 10:00 AM": {"fecha": FECHA, "numeros": (44, 55, 66)}}
    widget = [{"game_title": "La Primera Día", "date": "14-11", "score": ["19", "3", "45"]}]
    paso = resultados_auto.ciclo(
        forzar=True, payload=widget, firmado=firmado, operador=operador,
    )
    assert paso["ok"] is True
    filas = _filas()
    assert "La Anguila 10:00 AM" not in filas
    assert filas["La Primera 12:00 PM"][:3] == (19, 3, 45)
    db = dbmod.nueva_sesion()
    fila = db.query(Auditoria).filter_by(accion="discrepancia_operador").one()
    detalle = json.loads(fila.detalle_json)
    db.close()
    assert detalle["sorteo"] == "La Anguila 10:00 AM"
    assert detalle["fecha"] == "2026-11-14"
    assert detalle["conectate"] == [11, 22, 33]
    assert detalle["operador"] == [44, 55, 66]


def test_sin_operador_el_sorteo_sigue_pendiente(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0))
    firmado = _doc(
        [_juego("Anguila 10:00 AM", "g10", (11, 22, 33))],
        [_juego("Haiti Bolet 9:30 AM", "h9", (7, 8, 9))],
        [_juego("Anguila 10:00 AM", "s10", (1, 2, 3))],
        [_juego("Haiti Bolet 9:30 AM", "sh", (4, 5, 6))],
    )
    paso = resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado, operador={})
    assert paso["ok"] is True and paso["confirmados"] == 0
    assert _filas() == {}
    db = dbmod.nueva_sesion()
    assert db.query(Auditoria).filter_by(accion="discrepancia_operador").count() == 0
    db.close()


def test_fecha_u_horario_incorrectos_no_confirman():
    numeros = (11, 22, 33)
    nombre = "La Anguila 10:00 AM"
    candidatos = {nombre: {"fecha": FECHA, "numeros": numeros}}
    ayer = {"fecha": FECHA - timedelta(days=1), "numeros": numeros}
    aceptados, discrepancias = operador_oficial.cruzar(
        candidatos, {nombre: ayer}, FECHA,
    )
    assert aceptados == {} and discrepancias == []
    otra_hora = {"La Anguila 11:00 AM": {"fecha": FECHA, "numeros": numeros}}
    aceptados, discrepancias = operador_oficial.cruzar(candidatos, otra_hora, FECHA)
    assert aceptados == {} and discrepancias == []
    manana = FECHA + timedelta(days=1)
    futuros = {nombre: {"fecha": manana, "numeros": numeros}}
    aceptados, discrepancias = operador_oficial.cruzar(
        futuros, {nombre: {"fecha": manana, "numeros": numeros}}, FECHA,
    )
    assert aceptados == {} and discrepancias == []


def test_el_operador_rechaza_fecha_hora_y_sorteos_que_no_son_quiniela():
    numeros = (11, 22, 33)
    nombre = "La Anguila 10:00 AM"
    html = _html_anguila([("10:00 AM", numeros)], FECHA - timedelta(days=1))
    leidos = operador_oficial.leer_anguila(html, FECHA)
    assert (nombre, FECHA) not in leidos
    assert leidos[(nombre, FECHA - timedelta(days=1))]["numeros"] == numeros
    futuro = _html_anguila([("10:00 AM", numeros)], FECHA + timedelta(days=1))
    assert operador_oficial.leer_anguila(futuro, FECHA) == {}
    doble = _html_anguila([("9:00 AM", (1, 2, 3)), ("9:00 AM", (4, 5, 6))], FECHA)
    assert ("La Anguila 9:00 AM", FECHA) not in operador_oficial.leer_anguila(doble, FECHA)
    cuerpo = _haiti("9:30 AM", FECHA, numeros, nombre="HAITI BOLET 10:30")
    assert operador_oficial.interpretar_haiti(cuerpo, "9:30 AM", FECHA, FECHA) is None
    otra_fecha = _haiti("9:30 AM", FECHA - timedelta(days=1), numeros)
    assert operador_oficial.interpretar_haiti(otra_fecha, "9:30 AM", FECHA, FECHA) is None
    por_venir = _haiti("9:30 AM", FECHA + timedelta(days=1), numeros)
    assert operador_oficial.interpretar_haiti(
        por_venir, "9:30 AM", FECHA + timedelta(days=1), FECHA,
    ) is None


def test_la_caida_del_operador_no_detiene_las_demas_loterias(entorno, fijar_hora, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def caido(hoy):
        return {}, "operador anguila sin respuesta", []

    monkeypatch.setattr(operador_oficial, "confirmar_ventana", caido)
    monkeypatch.setattr(operador_king, "confirmar_ventana", lambda hoy: ({}, None, []))
    monkeypatch.setattr(
        conectate_widget, "descargar",
        lambda timeout=20: ([{
            "game_title": "La Primera Día", "date": "14-11", "score": ["19", "3", "45"],
        }], None),
    )
    paso = resultados_auto.ciclo(forzar=True)
    assert paso["ok"] is True
    filas = _filas()
    assert filas["La Primera 12:00 PM"][:3] == (19, 3, 45)
    assert not any(nombre.startswith(("La Anguila", "Haiti")) for nombre in filas)

    def falla(*args, **kwargs):
        raise urllib.error.URLError("caido")

    monkeypatch.setattr(urllib.request, "urlopen", falla)
    html, error = operador_oficial.descargar_anguila()
    mapa, error_haiti = operador_oficial.descargar_haiti(FECHA)
    assert html == "" and "sin respuesta" in error
    assert mapa == {} and "sin respuesta" in error_haiti


def test_el_manual_confirmado_no_se_reemplaza(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 10, 0))
    sorteo = entorno.sorteo_id("La Anguila 8:00 AM")
    alta = entorno.c.post("/resultados", json={
        "sorteo_id": sorteo, "fecha": "2026-11-14",
        "premio1": 1, "premio2": 2, "premio3": 3,
    }, headers=entorno.admin)
    assert alta.status_code == 201, alta.text
    conf = entorno.c.post(f"/resultados/{alta.json()['id']}/confirmar", headers=entorno.admin)
    assert conf.status_code == 200, conf.text
    firmado = _doc(
        [_juego("Anguila 8:00 AM", "g8", (7, 8, 9))],
        [],
        [_juego("Anguila 8:00 AM", "s8", (4, 5, 6))],
        [],
    )
    operador = {"La Anguila 8:00 AM": {"fecha": FECHA, "numeros": (7, 8, 9)}}
    for minuto in (0, 4, 10):
        fijar_hora(datetime(2026, 11, 14, 10, minuto))
        resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado, operador=operador)
    assert _filas()["La Anguila 8:00 AM"] == (1, 2, 3, "manual", None, "liquidado")


def test_tres_lecturas_y_diez_minutos_confirman_y_sobreviven_al_reinicio(entorno, fijar_hora):
    firmado = _doc(
        [_juego("Anguila 11:00 AM", "g11", (11, 22, 33))],
        [_juego("Haiti Bolet 11:30 AM", "h11", (19, 3, 45))],
        [_juego("Anguila 11:00 AM", "s11", (1, 2, 3))],
        [_juego("Haiti Bolet 11:30 AM", "sh", (4, 5, 6))],
    )
    operador = {
        "La Anguila 11:00 AM": {"fecha": FECHA, "numeros": (11, 22, 33)},
        "Haiti Bolet 11:30 AM": {"fecha": FECHA, "numeros": (19, 3, 45)},
    }
    for minuto in (0, 4, 8):
        fijar_hora(datetime(2026, 11, 14, 10, minuto))
        paso = resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado, operador=operador)
        assert paso["confirmados"] == 0
        dbmod.engine().dispose()
    db = dbmod.nueva_sesion()
    lecturas = {
        fila.sorteo_id: fila.lecturas
        for fila in db.query(ObservacionResultado)
    }
    db.close()
    assert lecturas[entorno.sorteo_id("La Anguila 11:00 AM")] == 3
    assert lecturas[entorno.sorteo_id("Haiti Bolet 11:30 AM")] == 3
    fijar_hora(datetime(2026, 11, 14, 10, 10))
    final = resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado, operador=operador)
    assert final["confirmados"] == 2
    filas = _filas()
    assert filas["La Anguila 11:00 AM"] == (11, 22, 33, "conectate", "operador", "liquidado")
    assert filas["Haiti Bolet 11:30 AM"] == (19, 3, 45, "conectate", "operador", "liquidado")
