"""Importador de Conectate: parseo contra fixture (sin red real), importación
como PROPUESTOS y fallo con gracia ante el 403 de Cloudflare (alcance 5).
"""
from datetime import date
from pathlib import Path

from apps.api import conectate
from apps.api import db as dbmod
from apps.api.models import Importacion, Resultado, Usuario

FIXTURE = Path(__file__).parent / "fixtures" / "conectate_ejemplo.html"
FECHA = date(2026, 11, 14)

ESPERADO = {
    "Nacional Tarde": (19, 3, 45),
    "Nacional Noche": (11, 22, 33),
    "LOTEKA": (5, 23, 87),
    "La Primera 12": (26, 58, 10),
    "La Primera 8PM": (7, 14, 21),
    "Real Tarde": (40, 41, 42),
    "Anguilla 1PM": (1, 2, 3),
    "Anguilla 6PM": (4, 5, 6),
    "Anguilla 9PM": (7, 8, 9),
    "King 12PM": (30, 31, 32),
    "King 07PM": (33, 34, 35),
    "NY Tarde": (50, 51, 52),
    "Florida Día": (60, 61, 62),
}


def _admin(db):
    return db.query(Usuario).filter_by(usuario="admin").first()


def test_parsear_fixture():
    html = FIXTURE.read_text(encoding="utf-8")
    encontrados = conectate.parsear_resultados(html)
    for nombre, numeros in ESPERADO.items():
        assert encontrados.get(nombre) == numeros, (nombre, encontrados.get(nombre))
    assert "Mega Millions" not in encontrados  # no es del catálogo


def test_importar_con_fixture_deja_propuestos(entorno):
    html = FIXTURE.read_text(encoding="utf-8")
    db = dbmod.nueva_sesion()
    try:
        resumen = conectate.importar_resultados(db, FECHA, _admin(db), html=html)
        assert resumen["ok"] is True
        assert resumen["propuestos"] == len(ESPERADO)
        filas = db.query(Resultado).filter_by(fecha=FECHA).all()
        assert len(filas) == len(ESPERADO)
        assert all(f.estado == "propuesto" and f.fuente == "conectate" for f in filas)
        intento = db.query(Importacion).order_by(Importacion.id.desc()).first()
        assert intento.ok is True and intento.encontrados == len(ESPERADO)
    finally:
        db.close()


def test_importar_no_toca_un_resultado_liquidado(entorno):
    s_loteka = entorno.sorteo_id("LOTEKA")
    entorno.liquidar(s_loteka, 1, 2, 3)  # resultado oficial ya liquidado: 01-02-03
    html = FIXTURE.read_text(encoding="utf-8")
    db = dbmod.nueva_sesion()
    try:
        resumen = conectate.importar_resultados(db, FECHA, _admin(db), html=html)
        assert resumen["ok"] is True
        assert any("LOTEKA" in d and "no se tocó" in d for d in resumen["detalle"])
        r = db.query(Resultado).filter_by(sorteo_id=s_loteka, fecha=FECHA).first()
        assert (r.premio1, r.premio2, r.premio3) == (1, 2, 3)  # intacto
        assert r.estado == "liquidado"
    finally:
        db.close()


def test_importar_falla_con_gracia_ante_403(entorno, monkeypatch):
    monkeypatch.setattr(conectate, "descargar_pagina", lambda url=conectate.URL_CONECTATE: (None, 403))
    db = dbmod.nueva_sesion()
    try:
        resumen = conectate.importar_resultados(db, FECHA, _admin(db))
        assert resumen["ok"] is False
        assert "403" in resumen["motivo"]
        assert resumen["propuestos"] == 0
        assert db.query(Resultado).count() == 0  # jamás inventa números
        intento = db.query(Importacion).order_by(Importacion.id.desc()).first()
        assert intento is not None and intento.ok is False and intento.estado_http == 403
    finally:
        db.close()


def test_importar_via_api_registra_el_intento_fallido(entorno, monkeypatch):
    monkeypatch.setattr(conectate, "descargar_pagina", lambda url=conectate.URL_CONECTATE: (None, 403))
    r = entorno.c.post("/resultados/importar", json={"fecha": "2026-11-14"}, headers=entorno.admin)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    intentos = entorno.c.get("/importaciones", headers=entorno.admin).json()
    assert intentos and intentos[0]["ok"] is False and intentos[0]["estado_http"] == 403
