"""King 12:30 y 7:30: ambos horarios, premios y sin mezclar fechas."""
from datetime import datetime, timedelta

from apps.api import operador_king, resultados_auto, servicios
from apps.api import db as dbmod
from apps.api.models import ColaPremio, ObservacionResultado, Resultado

from tests.test_operador_king import (
    AYER,
    DIA,
    HOY,
    NOCHE,
    _draw,
    _filas,
    _html,
    _rd,
)

BASE_DIA = datetime(2026, 11, 15, 12, 40)
BASE_NOCHE = datetime(2026, 11, 15, 19, 40)


def _pasar_king(fijar_hora, html, doc, base, minutos=(40, 44, 48)):
    for minuto in minutos:
        fijar_hora(base.replace(minute=minuto))
        resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)


def _sesion_hoy(entorno, fijar_hora, momento=None):
    """El fixture arranca el 14; King usa el 15 — hay que renovar tokens."""
    fijar_hora(momento or datetime(2026, 11, 15, 11, 0))
    r = entorno.c.post("/auth/login", json={"usuario": "admin", "clave": "admin123"})
    assert r.status_code == 200, r.text
    entorno.admin = {"Authorization": f"Bearer {r.json()['token']}"}


def test_1_king_1230_valido(entorno, fijar_hora):
    html = _html(dia=((45, 0, 18), HOY), noche=None)
    doc = _rd(_draw("dia", HOY, (45, 0, 18)))
    _pasar_king(fijar_hora, html, doc, BASE_DIA)
    fila = _filas()[DIA]
    assert fila[0:3] == (45, 0, 18)
    assert fila[3] in ("confirmado", "liquidado")
    assert fila[5] == HOY
    assert NOCHE not in _filas()


def test_2_king_730_valido(entorno, fijar_hora):
    html = _html(dia=None, noche=((87, 8, 31), HOY))
    doc = _rd(_draw("noche", HOY, (87, 8, 31)))
    _pasar_king(fijar_hora, html, doc, BASE_NOCHE)
    fila = _filas()[NOCHE]
    assert fila[0:3] == (87, 8, 31)
    assert fila[3] in ("confirmado", "liquidado")
    assert fila[5] == HOY
    assert DIA not in _filas()


def test_3_ambos_el_mismo_dia(entorno, fijar_hora):
    html = _html(dia=((45, 0, 18), HOY), noche=((87, 8, 31), HOY))
    doc = _rd(_draw("dia", HOY, (45, 0, 18)), _draw("noche", HOY, (87, 8, 31)))
    _pasar_king(fijar_hora, html, doc, BASE_DIA)
    _pasar_king(fijar_hora, html, doc, BASE_NOCHE)
    filas = _filas()
    assert filas[DIA][0:3] == (45, 0, 18)
    assert filas[NOCHE][0:3] == (87, 8, 31)
    assert filas[DIA][5] == filas[NOCHE][5] == HOY


def test_4_ayer_no_paga_ticket_hoy(entorno, fijar_hora):
    _sesion_hoy(entorno, fijar_hora)
    b = entorno.banca(saldo=100000)
    s = entorno.sorteo_id(DIA)
    ticket = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [s], "numeros": "01", "monto": 5}])
    # Solo ayer en ambas fuentes: no confirma hoy.
    html = _html(dia=((1, 55, 2), AYER), noche=None)
    doc = _rd(_draw("dia", AYER, (1, 55, 2)))
    fijar_hora(BASE_DIA)
    resumen = resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)
    assert resumen.get("king", 0) == 0
    assert DIA not in _filas()
    _sesion_hoy(entorno, fijar_hora, BASE_DIA)
    assert entorno.consultar(ticket)["estado"] == "vendido"
    assert entorno.consultar(ticket)["puede_pagar"] is False


def test_5_resultado_ausente(entorno, fijar_hora):
    fijar_hora(BASE_DIA)
    resumen = resultados_auto.ciclo(
        forzar=True, payload=[], king_html=_html(dia=None, noche=None), king_rdlotto=_rd(),
    )
    assert resumen.get("king", 0) == 0
    assert _filas() == {}


def test_6_provisional_que_cambia(entorno, fijar_hora):
    html1 = _html(dia=((1, 2, 3), HOY))
    doc1 = _rd(_draw("dia", HOY, (1, 2, 3)))
    fijar_hora(BASE_DIA)
    resultados_auto.ciclo(forzar=True, payload=[], king_html=html1, king_rdlotto=doc1)
    fijar_hora(BASE_DIA.replace(minute=44))
    resultados_auto.ciclo(forzar=True, payload=[], king_html=html1, king_rdlotto=doc1)
    html2 = _html(dia=((9, 8, 7), HOY))
    doc2 = _rd(_draw("dia", HOY, (9, 8, 7)))
    fijar_hora(BASE_DIA.replace(minute=48))
    resultados_auto.ciclo(forzar=True, payload=[], king_html=html2, king_rdlotto=doc2)
    db = dbmod.nueva_sesion()
    from apps.api.models import Sorteo
    sorteo = db.query(Sorteo).filter_by(nombre=DIA, activo=True).one()
    fila = db.query(ObservacionResultado).filter_by(sorteo_id=sorteo.id, fecha=HOY).one()
    assert fila.lecturas == 1
    assert (fila.premio1, fila.premio2, fila.premio3) == (9, 8, 7)
    assert db.query(Resultado).one().estado == "propuesto"
    db.close()


def test_7_repeticion_sin_duplicar_premios(entorno, fijar_hora):
    html = _html(dia=((45, 0, 18), HOY))
    doc = _rd(_draw("dia", HOY, (45, 0, 18)))
    _pasar_king(fijar_hora, html, doc, BASE_DIA)
    fijar_hora(BASE_DIA.replace(hour=13, minute=10))
    resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)
    db = dbmod.nueva_sesion()
    assert db.query(Resultado).count() == 1
    assert db.query(ColaPremio).count() == 1
    db.close()


def test_8_premios_qn_pl_sp_tr(entorno, fijar_hora):
    _sesion_hoy(entorno, fijar_hora)
    b = entorno.banca(saldo=200000)
    dia = entorno.sorteo_id(DIA)
    noche = entorno.sorteo_id(NOCHE)
    qn = entorno.vender_ok(b["headers"], [{"tipo": "QN", "sorteos": [dia], "numeros": "45", "monto": 5}])
    pl = entorno.vender_ok(b["headers"], [{"tipo": "PL", "sorteos": [dia], "numeros": "45-00", "monto": 5}])
    sp = entorno.vender_ok(
        b["headers"],
        [{"tipo": "SP", "sorteos": [dia, noche], "numeros": "45-87", "monto": 5}],
    )
    tr = entorno.vender_ok(b["headers"], [{"tipo": "TR", "sorteos": [dia], "numeros": "45-00-18", "monto": 5}])
    caja = entorno.saldo(b["sucursal"]["id"])
    html_dia = _html(dia=((45, 0, 18), HOY), noche=None)
    doc_dia = _rd(_draw("dia", HOY, (45, 0, 18)))
    _pasar_king(fijar_hora, html_dia, doc_dia, BASE_DIA)
    _sesion_hoy(entorno, fijar_hora, BASE_DIA.replace(minute=50))
    assert entorno.consultar(qn)["estado"] == "ganador"
    assert entorno.consultar(pl)["estado"] == "ganador"
    assert entorno.consultar(tr)["estado"] == "ganador"
    assert entorno.consultar(sp)["estado"] == "vendido"
    html = _html(dia=((45, 0, 18), HOY), noche=((87, 8, 31), HOY))
    doc = _rd(_draw("dia", HOY, (45, 0, 18)), _draw("noche", HOY, (87, 8, 31)))
    _pasar_king(fijar_hora, html, doc, BASE_NOCHE)
    _sesion_hoy(entorno, fijar_hora, BASE_NOCHE.replace(minute=50))
    assert entorno.consultar(sp)["estado"] == "ganador"
    # Premios pendientes: no descuenta MI CAJA / saldo sucursal hasta pagar.
    assert entorno.saldo(b["sucursal"]["id"]) == caja


def test_9_ticket_varias_loterias(entorno, fijar_hora):
    _sesion_hoy(entorno, fijar_hora)
    b = entorno.banca(saldo=100000)
    dia = entorno.sorteo_id(DIA)
    primera = entorno.sorteo_id("La Primera 12:00 PM")
    ticket = entorno.vender_ok(
        b["headers"],
        [
            {"tipo": "QN", "sorteos": [dia], "numeros": "45", "monto": 5},
            {"tipo": "QN", "sorteos": [primera], "numeros": "19", "monto": 5},
        ],
    )
    html = _html(dia=((45, 0, 18), HOY))
    doc = _rd(_draw("dia", HOY, (45, 0, 18)))
    _pasar_king(fijar_hora, html, doc, BASE_DIA)
    _sesion_hoy(entorno, fijar_hora, BASE_DIA.replace(minute=50))
    consulta = entorno.consultar(ticket)
    assert consulta["estado"] in ("ganador", "parcial", "vendido")
    assert float(consulta["premio_total"]) > 0


def test_10_sunmi_tablero_verde_y_pendiente(entorno, fijar_hora):
    html = _html(dia=((45, 0, 18), HOY), noche=None)
    doc = _rd(_draw("dia", HOY, (45, 0, 18)))
    _pasar_king(fijar_hora, html, doc, BASE_DIA)
    fijar_hora(BASE_DIA.replace(minute=50))
    db = dbmod.nueva_sesion()
    tablero = servicios.tablero_resultados(db, HOY)
    db.close()
    por = {f["nombre"]: f for f in tablero["sorteos"]}
    assert por[DIA]["confirmado"] is True
    assert por[DIA]["pendiente"] is False
    assert por[DIA]["vigente"] is True
    assert por[DIA]["premio1"] == "45"
    assert por[NOCHE]["pendiente"] is True
    assert por[NOCHE]["confirmado"] is False


def test_live_simulado_operador_atrasado_ambos(entorno, fijar_hora):
    """Réplica del fallo LIVE: operador ayer + RDLotto verified hoy."""
    html = _html(dia=((1, 55, 2), AYER), noche=((31, 5, 30), AYER - timedelta(days=1)))
    doc = _rd(
        _draw("dia", HOY, (45, 0, 18)),
        _draw("noche", HOY, (87, 8, 31)),
    )
    _pasar_king(fijar_hora, html, doc, BASE_DIA)
    _pasar_king(fijar_hora, html, doc, BASE_NOCHE)
    filas = _filas()
    assert filas[DIA][0:3] == (45, 0, 18)
    assert filas[NOCHE][0:3] == (87, 8, 31)
    assert filas[DIA][4] == "rdlotto"
    assert filas[NOCHE][4] == "rdlotto"


def test_king_repetidos_liquida_sin_usar_ayer(entorno, fijar_hora):
    html = _html(dia=((53, 9, 9), HOY), noche=((21, 21, 21), AYER))
    doc = _rd(
        _draw("dia", HOY, (53, 9, 9)),
        _draw("noche", HOY, (27, 21, 21)),
    )
    _pasar_king(fijar_hora, html, doc, BASE_DIA)
    _pasar_king(fijar_hora, html, doc, BASE_NOCHE)
    filas = _filas()
    assert filas[DIA][0:3] == (53, 9, 9)
    assert filas[DIA][5] == HOY
    assert filas[NOCHE][0:3] == (27, 21, 21)
    assert filas[NOCHE][4] == "rdlotto"
    assert filas[NOCHE][5] == HOY
