"""Validación rápida del retraso: 4 minutos estables + intervalo adaptativo."""
from datetime import datetime, time

from apps.api import estabilizacion, resultados_auto
from apps.api import db as dbmod
from apps.api.models import ObservacionResultado, Resultado, Sorteo


def test_constantes_de_velocidad():
    assert estabilizacion.LECTURAS_MINIMAS == 3
    assert estabilizacion.MINUTOS_ESTABLES == 4
    assert resultados_auto.INTERVALO_SEGUNDOS == 240
    assert resultados_auto.INTERVALO_RAPIDO_SEGUNDOS == 60


def test_intervalo_rapido_cerca_de_sorteo_pendiente(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 12, 2))
    db = dbmod.nueva_sesion()
    assert resultados_auto.intervalo_actual(db, datetime(2026, 11, 14, 12, 2)) == 60
    db.close()


def test_intervalo_normal_fuera_de_ventana(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 3, 0))
    db = dbmod.nueva_sesion()
    assert resultados_auto.intervalo_actual(db, datetime(2026, 11, 14, 3, 0)) == 240
    db.close()


def test_intervalo_rapido_con_provisional(entorno, fijar_hora):
    fijar_hora(datetime(2026, 11, 14, 3, 0))
    db = dbmod.nueva_sesion()
    sorteo = db.query(Sorteo).filter_by(nombre="La Primera 12:00 PM", activo=True).one()
    db.add(ObservacionResultado(
        sorteo_id=sorteo.id, fecha=datetime(2026, 11, 14).date(),
        premio1=1, premio2=2, premio3=3, lecturas=1,
        primera_en=datetime(2026, 11, 14, 12, 5),
        ultima_en=datetime(2026, 11, 14, 12, 5),
        fuente="conectate",
    ))
    db.add(Resultado(
        sorteo_id=sorteo.id, fecha=datetime(2026, 11, 14).date(),
        premio1=1, premio2=2, premio3=3, estado="propuesto", fuente="conectate",
        propuesto_en=datetime(2026, 11, 14, 12, 5),
    ))
    db.commit()
    assert resultados_auto.intervalo_actual(db, datetime(2026, 11, 14, 3, 0)) == 60
    db.close()


def test_terminal_actualizar_no_paga(entorno, fijar_hora):
    b = entorno.banca(saldo=50000)
    fijar_hora(datetime(2026, 11, 14, 12, 20))
    r = entorno.c.post("/terminal/resultados/actualizar", json={}, headers=b["headers"])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "sorteos" in cuerpo
    assert "actualizado_en" in cuerpo
    assert "sincronizacion" in cuerpo
    assert cuerpo["sincronizacion"].get("premios", 0) == 0 or "omitido" in cuerpo["sincronizacion"]
