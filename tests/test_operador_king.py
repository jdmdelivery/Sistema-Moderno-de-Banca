"""King Lottery: operador oficial + RDLotto verified, sin RDLotto global."""
from datetime import datetime, timedelta

from apps.api import operador_king, resultados_auto, servicios
from apps.api import db as dbmod
from apps.api.models import Auditoria, ObservacionResultado, Resultado, Sorteo

HOY = datetime(2026, 11, 15).date()
AYER = HOY - timedelta(days=1)
DIA = "King Lottery 12:30 PM"
NOCHE = "King Lottery 7:30 PM"


def _articulo(clase, numeros, fecha):
    mes = (
        "noviembre" if fecha.month == 11 else
        "octubre" if fecha.month == 10 else
        "diciembre"
    )
    nums = "".join(
        f'<div class="elementor-widget elementor-widget-text-editor">'
        f'<div class="elementor-widget-container"> {n:02d} </div></div>'
        for n in numeros
    )
    return (
        f'<article class="elementor-post numeros-ganadores {clase} '
        f'loterias-king-lottery-by-freddy-fernandez">'
        f'<div>{nums}'
        f'<span itemprop="datePublished"><time>{mes} {fecha.day}, {fecha.year}</time></span>'
        f"</div></article>"
    )


def _html(dia=None, noche=None, extras=""):
    partes = ['<h2>Quiniela SXM - Medio Día</h2>']
    if dia is not None:
        partes.append(_articulo("sorteos-quiniela-sxm", dia[0], dia[1]))
    partes.append('<h2>Quiniela SXM - Noche</h2>')
    if noche is not None:
        partes.append(_articulo("sorteos-quiniela-sxm-noche", noche[0], noche[1]))
    # Ruido: otros juegos del operador no deben entrar.
    partes.append(_articulo("sorteos-sxm-pick-3-pick-4-medio-dia", (1, 0, 1), HOY))
    partes.append(_articulo("sorteos-loto-pool-sxm-medio-dia", (24, 42, 75), HOY))
    partes.append(_articulo("sorteos-philipsburg-pick-4-medio-dia", (12, 63, 54), HOY))
    partes.append(extras)
    return "\n".join(partes)


def _draw(sesion, fecha, numeros, status="verified", time=None, game="king-lottery-quiniela"):
    hora = "12:30" if sesion == "dia" else "19:30"
    if time is not None:
        hora = time
    return {
        "game": game,
        "name": "Quiniela King Lottery",
        "date": fecha.isoformat(),
        "session": sesion,
        "time": hora,
        "status": status,
        "numbers": [f"{n:02d}" for n in numeros],
        "reportedBy": ["kinglotterysxm"],
    }


def _rd(*draws):
    return {"draws": list(draws)}


def _filas():
    db = dbmod.nueva_sesion()
    filas = {
        fila.sorteo.nombre: (
            fila.premio1, fila.premio2, fila.premio3, fila.estado, fila.externo, fila.fecha,
        )
        for fila in db.query(Resultado)
        if fila.sorteo and "King Lottery" in fila.sorteo.nombre
    }
    db.close()
    return filas


def _obs(nombre):
    db = dbmod.nueva_sesion()
    sorteo = db.query(Sorteo).filter_by(nombre=nombre, activo=True).one()
    fila = db.query(ObservacionResultado).filter_by(sorteo_id=sorteo.id, fecha=HOY).first()
    out = None if fila is None else (fila.lecturas, fila.premio1, fila.premio2, fila.premio3)
    db.close()
    return out


def test_ids_catalogo_king():
    """En producción son 28/29; en semilla limpia basta nombre, hora y activo."""
    db = dbmod.nueva_sesion()
    dia = db.query(Sorteo).filter_by(nombre=DIA, activo=True).one()
    noche = db.query(Sorteo).filter_by(nombre=NOCHE, activo=True).one()
    assert dia.hora_sorteo.hour == 12 and dia.hora_sorteo.minute == 30
    assert noche.hora_sorteo.hour == 19 and noche.hora_sorteo.minute == 30
    db.close()


def test_lee_solo_quiniela_sxm_con_fecha():
    html = _html(dia=((1, 55, 2), HOY), noche=((31, 5, 30), AYER))
    leidos = operador_king.leer_operador(html, HOY)
    assert (DIA, HOY) in leidos
    assert leidos[(DIA, HOY)]["numeros"] == (1, 55, 2)
    assert leidos[(DIA, HOY)]["sesion"] == "dia"
    assert (NOCHE, HOY) not in leidos
    assert (NOCHE, AYER) in leidos
    assert leidos[(NOCHE, AYER)]["numeros"] == (31, 5, 30)


def test_rdlotto_exige_verified_sesion_y_hora():
    doc = _rd(
        _draw("dia", HOY, (1, 55, 2)),
        _draw("noche", HOY, (9, 8, 7), status="live"),
        _draw("dia", HOY, (10, 11, 12), game="king-lottery-pick-3"),
        _draw("dia", HOY, (13, 14, 15), time="13:00"),
    )
    leidos = operador_king.leer_rdlotto(doc, HOY)
    assert set(leidos) == {(DIA, HOY)}
    assert leidos[(DIA, HOY)]["numeros"] == (1, 55, 2)


def test_triple_acepta_repetidos_y_rechaza_invalidos():
    assert operador_king._triple([27, 21, 21]) == (27, 21, 21)
    assert operador_king._triple([53, 9, 9]) == (53, 9, 9)
    assert operador_king._triple([21, 21, 21]) == (21, 21, 21)
    assert operador_king._triple([0, 0, 0]) == (0, 0, 0)
    assert operador_king._triple([87, 40, 9]) == (87, 40, 9)
    assert operador_king._triple([1, 2, 100]) is None
    assert operador_king._triple([1, 2]) is None
    assert operador_king._triple(None) is None


def test_confirma_king_con_numeros_repetidos():
    html = _html(dia=((53, 9, 9), HOY), noche=((0, 0, 0), HOY))
    doc = _rd(_draw("dia", HOY, (53, 9, 9)), _draw("noche", HOY, (0, 0, 0)))
    aceptados, aviso, difs = operador_king.confirmar(HOY, html=html, documento=doc)
    assert aviso is None
    assert difs == []
    assert aceptados[DIA]["numeros"] == (53, 9, 9)
    assert aceptados[NOCHE]["numeros"] == (0, 0, 0)
    assert aceptados[DIA]["fecha"] == HOY
    assert aceptados[NOCHE]["fecha"] == HOY


def test_coincide_dia_y_noche_sigue_pendiente_si_es_de_ayer():
    html = _html(dia=((1, 55, 2), HOY), noche=((31, 5, 30), AYER))
    doc = _rd(_draw("dia", HOY, (1, 55, 2)))
    aceptados, aviso, difs = operador_king.confirmar(HOY, html=html, documento=doc)
    assert aviso is None
    assert difs == []
    assert set(aceptados) == {DIA}
    assert aceptados[DIA]["numeros"] == (1, 55, 2)
    assert aceptados[DIA]["fecha"] == HOY
    assert NOCHE not in aceptados


def test_fecha_incorrecta_no_confirma_hoy():
    html = _html(dia=((1, 55, 2), AYER), noche=None)
    doc = _rd(_draw("dia", AYER, (1, 55, 2)))
    aceptados, _, difs = operador_king.confirmar(HOY, html=html, documento=doc)
    assert aceptados == {}
    assert difs == []


def test_horarios_cruzados_no_mezclan_sesiones():
    # Operador publica día; RDLotto trae esos números en sesión noche.
    # Cada sesión se evalúa sola: noche puede entrar por RDLotto; día sigue
    # pendiente (operador sin verified de día).
    html = _html(dia=((1, 55, 2), HOY), noche=None)
    doc = _rd(_draw("noche", HOY, (1, 55, 2)))
    aceptados, _, difs = operador_king.confirmar(HOY, html=html, documento=doc)
    assert set(aceptados) == {NOCHE}
    assert aceptados[NOCHE]["numeros"] == (1, 55, 2)
    assert aceptados[NOCHE]["origen"] == "rdlotto"
    assert DIA not in aceptados
    assert any(d.get("causa") == "operador_hoy_sin_rdlotto_verified" for d in difs)


def test_numeros_diferentes_registran_discrepancia():
    html = _html(dia=((1, 55, 2), HOY))
    doc = _rd(_draw("dia", HOY, (9, 8, 7)))
    aceptados, _, difs = operador_king.confirmar(HOY, html=html, documento=doc)
    assert aceptados == {}
    assert len(difs) == 1
    assert difs[0]["sorteo"] == DIA
    assert difs[0]["operador"] == [1, 55, 2]
    assert difs[0]["rdlotto"] == [9, 8, 7]


def test_rdlotto_verified_sin_operador_confirma():
    html = _html(dia=None, noche=None)
    doc = _rd(_draw("dia", HOY, (1, 55, 2)))
    aceptados, _, difs = operador_king.confirmar(HOY, html=html, documento=doc)
    assert set(aceptados) == {DIA}
    assert aceptados[DIA]["numeros"] == (1, 55, 2)
    assert aceptados[DIA]["origen"] == "rdlotto"
    assert difs == []


def test_operador_atrasado_acepta_rdlotto_hoy():
    """Caso LIVE: sitio oficial muestra ayer; RDLotto ya verified hoy."""
    html = _html(dia=((1, 55, 2), AYER), noche=((31, 5, 30), AYER - timedelta(days=1)))
    doc = _rd(_draw("dia", HOY, (45, 0, 18)))
    aceptados, _, difs = operador_king.confirmar(HOY, html=html, documento=doc)
    assert set(aceptados) == {DIA}
    assert aceptados[DIA]["numeros"] == (45, 0, 18)
    assert aceptados[DIA]["origen"] == "rdlotto"
    assert aceptados[DIA]["fecha"] == HOY
    assert any(d.get("causa") == "operador_atrasado_acepta_rdlotto" for d in difs)


def test_operador_sin_conexion_usa_rdlotto(monkeypatch):
    monkeypatch.setattr(
        operador_king, "descargar_operador",
        lambda: ("", "operador king sin respuesta"),
    )
    monkeypatch.setattr(
        operador_king, "descargar_rdlotto",
        lambda hoy: (_rd(_draw("dia", hoy, (1, 55, 2))), None),
    )
    aceptados, aviso, difs = operador_king.confirmar_ventana(HOY)
    assert set(aceptados) == {DIA}
    assert aceptados[DIA]["origen"] == "rdlotto"
    assert "sin respuesta" in (aviso or "")
    assert difs == []


def test_ciclo_tres_lecturas_y_cuatro_minutos(entorno, fijar_hora):
    html = _html(dia=((1, 55, 2), HOY), noche=((31, 5, 30), AYER))
    doc = _rd(_draw("dia", HOY, (1, 55, 2)))
    base = datetime(2026, 11, 15, 12, 40)
    marcas = []
    for minuto in (40, 44, 48):
        fijar_hora(base.replace(minute=minuto))
        resumen = resultados_auto.ciclo(
            forzar=True, payload=[], king_html=html, king_rdlotto=doc,
        )
        assert resumen["ok"] is True
        marcas.append(resumen["confirmados"])
    assert marcas == [0, 0, 1]
    filas = _filas()
    assert filas[DIA][0:3] == (1, 55, 2)
    assert filas[DIA][3] in ("confirmado", "liquidado")
    assert filas[DIA][4] == "operador"
    assert filas[DIA][5] == HOY
    assert NOCHE not in filas
    assert _obs(DIA)[0] >= 3


def test_discrepancia_queda_en_auditoria_y_no_confirma(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 15, 12, 45))
    html = _html(dia=((1, 55, 2), HOY))
    doc = _rd(_draw("dia", HOY, (9, 8, 7)))
    resumen = resultados_auto.ciclo(
        forzar=True, payload=[], king_html=html, king_rdlotto=doc,
    )
    assert resumen["ok"] is True
    assert resumen.get("king", 0) == 0
    assert _filas() == {}
    db = dbmod.nueva_sesion()
    aud = (
        db.query(Auditoria)
        .filter_by(accion="discrepancia_operador")
        .order_by(Auditoria.id.desc())
        .first()
    )
    assert aud is not None
    assert "King Lottery 12:30 PM" in str(aud.detalle_json)
    db.close()


def test_reinicio_del_reloj_conserva_lecturas(entorno, fijar_hora):
    html = _html(dia=((1, 55, 2), HOY))
    doc = _rd(_draw("dia", HOY, (1, 55, 2)))
    base = datetime(2026, 11, 15, 12, 40)
    fijar_hora(base)
    resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)
    fijar_hora(base.replace(minute=44))
    resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)
    assert _obs(DIA)[0] == 2
    # Simula reinicio: el estado en memoria no importa; la base conserva.
    resultados_auto._estado["ultimo_ok"] = None
    fijar_hora(base.replace(minute=48))
    resumen = resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)
    assert resumen["confirmados"] == 1
    assert _filas()[DIA][3] in ("confirmado", "liquidado")


def test_terminal_resultados_muestra_confirmado_y_noche_pendiente(entorno, fijar_hora):
    html = _html(dia=((1, 55, 2), HOY), noche=((31, 5, 30), AYER))
    doc = _rd(_draw("dia", HOY, (1, 55, 2)))
    base = datetime(2026, 11, 15, 12, 40)
    for minuto in (40, 44, 48):
        fijar_hora(base.replace(minute=minuto))
        resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)
    db = dbmod.nueva_sesion()
    tablero = servicios.consulta_resultados(db, HOY)
    db.close()
    por_nombre = {fila["nombre"]: fila for fila in tablero["sorteos"]}
    assert por_nombre[DIA]["pendiente"] is False
    assert por_nombre[DIA]["confirmado"] is True
    assert por_nombre[DIA]["premio1"] == "01"
    assert por_nombre[DIA]["premio2"] == "55"
    assert por_nombre[DIA]["premio3"] == "02"
    assert por_nombre[DIA]["vigente"] is True
    assert por_nombre[NOCHE]["pendiente"] is True
    assert por_nombre[NOCHE]["confirmado"] is False


def test_no_modifica_resultado_ya_confirmado(entorno, fijar_hora):
    html = _html(dia=((1, 55, 2), HOY))
    doc = _rd(_draw("dia", HOY, (1, 55, 2)))
    base = datetime(2026, 11, 15, 12, 40)
    for minuto in (40, 44, 48):
        fijar_hora(base.replace(minute=minuto))
        resultados_auto.ciclo(forzar=True, payload=[], king_html=html, king_rdlotto=doc)
    html2 = _html(dia=((9, 8, 7), HOY))
    doc2 = _rd(_draw("dia", HOY, (9, 8, 7)))
    fijar_hora(base.replace(hour=13, minute=10))
    resultados_auto.ciclo(forzar=True, payload=[], king_html=html2, king_rdlotto=doc2)
    assert _filas()[DIA][0:3] == (1, 55, 2)
    assert _filas()[DIA][3] in ("confirmado", "liquidado")
