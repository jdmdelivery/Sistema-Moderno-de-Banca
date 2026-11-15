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
    from .seed import sembrar_si_vacio, sembrar_sucursal_prueba

    Base.metadata.create_all(engine())
    _columnas_faltantes()
    db = nueva_sesion()
    try:
        sembrar_si_vacio(db)
        sembrar_sucursal_prueba(db)
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
        faltan = {
            "operacion_id": "VARCHAR(40)",
            "pago_operacion_id": "VARCHAR(40)",
            "anulado_motivo": "VARCHAR(200)",
            "es_prueba": "BOOLEAN NOT NULL DEFAULT FALSE" if eng.dialect.name == "postgresql" else "INTEGER NOT NULL DEFAULT 0",
            "reimpresiones": "INTEGER NOT NULL DEFAULT 0",
            "ultima_reimpresion_en": "TIMESTAMP",
        }
        with eng.begin() as conn:
            for columna, tipo in faltan.items():
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE tickets ADD COLUMN {columna} {tipo}"))
    if "resultados" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("resultados")}
        faltan = {
            "version": "INTEGER NOT NULL DEFAULT 1",
            "externo": "VARCHAR(80)",
            "recibido_en": "TIMESTAMP",
        }
        with eng.begin() as conn:
            for columna, tipo in faltan.items():
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE resultados ADD COLUMN {columna} {tipo}"))
    if "usuarios" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("usuarios")}
        tipo = "NUMERIC(12,2) NOT NULL DEFAULT 0"
        with eng.begin() as conn:
            for columna in ("saldo_caja", "saldo_caja_prueba"):
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE usuarios ADD COLUMN {columna} {tipo}"))
            for columna in ("ciclo_caja_movimiento_id", "ciclo_caja_prueba_movimiento_id"):
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE usuarios ADD COLUMN {columna} INTEGER"))
    if "terminales" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("terminales")}
        with eng.begin() as conn:
            if "modelo" not in cols:
                conn.execute(text("ALTER TABLE terminales ADD COLUMN modelo VARCHAR(80)"))
            if "android_api" not in cols:
                conn.execute(text("ALTER TABLE terminales ADD COLUMN android_api VARCHAR(10)"))
