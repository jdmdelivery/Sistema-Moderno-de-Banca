"""Base de datos: motor y sesiones SQLAlchemy.

Funciona con PostgreSQL (producción, vía DATABASE_URL) y con SQLite
(tests y desarrollo local). Todo el código usa SQLAlchemy portable.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

_engine = None
SessionLocal = None


def normalizar_url(url):
    """Apunta las URL de PostgreSQL al dialecto psycopg 3 (el instalado).

    Render entrega el connectionString como ``postgresql://…`` (antes
    ``postgres://…``); sin dialecto explícito, SQLAlchemy elegiría
    psycopg2, que no está en requirements. Las demás URL no se tocan.
    """
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


def url_por_defecto():
    return normalizar_url(os.environ.get("DATABASE_URL", "sqlite:///./sistema_loteria.db"))


def crear_engine(url):
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_engine(url, **kwargs)


def configurar(url=None):
    """(Re)crea el motor global y la fábrica de sesiones."""
    global _engine, SessionLocal
    _engine = crear_engine(normalizar_url(url) if url else url_por_defecto())
    SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    return _engine


def engine():
    if _engine is None:
        configurar()
    return _engine


def nueva_sesion():
    if SessionLocal is None:
        configurar()
    return SessionLocal()


def init_db():
    """Crea las tablas si no existen y siembra los datos iniciales."""
    from . import models  # noqa: F401  (registra los modelos)
    from .seed import sembrar_si_vacio

    Base.metadata.create_all(engine())
    _columnas_faltantes()
    db = nueva_sesion()
    try:
        sembrar_si_vacio(db)
    finally:
        db.close()


def _columnas_faltantes():
    """Agrega columnas nuevas a tablas ya creadas (create_all no altera
    tablas existentes). Idempotente: solo agrega la que falte."""
    from sqlalchemy import inspect, text

    eng = engine()
    insp = inspect(eng)
    if "tickets" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("tickets")}
        if "operacion_id" not in cols:
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE tickets ADD COLUMN operacion_id VARCHAR(40)"))
