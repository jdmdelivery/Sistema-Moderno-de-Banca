"""Modo producción: la app respeta DATABASE_URL (PostgreSQL de Render).

Render entrega el connectionString como ``postgresql://…``; sin dialecto
explícito SQLAlchemy elegiría psycopg2 (no instalado). Estos tests fijan
que toda URL de PostgreSQL termina en el dialecto psycopg 3 y que el
motor se crea sin tocar la red (la conexión es perezosa).
"""
from apps.api import db


def test_normaliza_postgres_legacy():
    assert db.normalizar_url("postgres://u:p@host:5432/bd") == \
        "postgresql+psycopg://u:p@host:5432/bd"


def test_normaliza_postgresql_render():
    assert db.normalizar_url("postgresql://u:p@host:5432/bd") == \
        "postgresql+psycopg://u:p@host:5432/bd"


def test_no_toca_dialectos_explicitos_ni_sqlite():
    assert db.normalizar_url("postgresql+psycopg://u:p@h/bd") == \
        "postgresql+psycopg://u:p@h/bd"
    assert db.normalizar_url("sqlite:///./x.db") == "sqlite:///./x.db"


def test_url_por_defecto_usa_el_entorno(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/bd")
    assert db.url_por_defecto() == "postgresql+psycopg://u:p@host:5432/bd"


def test_render_sin_database_url_no_cae_en_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-prueba")
    try:
        db.url_por_defecto()
        raise AssertionError("debio rechazar SQLite")
    except RuntimeError as e:
        assert "DATABASE_URL" in str(e)


def test_engine_postgres_sin_conectar():
    engine = db.crear_engine(db.normalizar_url("postgresql://u:p@host:5432/bd"))
    assert engine.url.drivername == "postgresql+psycopg"
    engine.dispose()
