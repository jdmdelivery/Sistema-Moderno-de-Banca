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
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        if os.environ.get("RENDER_SERVICE_ID"):
            raise RuntimeError(
                "DATABASE_URL es obligatoria en el servidor publicado. "
                "No se usa SQLite temporal."
            )
        url = "sqlite:///./sistema_loteria.db"
    return normalizar_url(url)


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
    from .seed import (
        aplicar_catalogo_sorteos,
        asegurar_tripleta,
        sembrar_si_vacio,
        sembrar_sucursal_prueba,
    )

    Base.metadata.create_all(engine())
    _columnas_faltantes()
    db = nueva_sesion()
    try:
        sembrar_si_vacio(db)
        asegurar_tripleta(db)
        aplicar_catalogo_sorteos(db)
        sembrar_sucursal_prueba(db)
    finally:
        db.close()


def _agregar_columna(eng):
    """PostgreSQL ignora la columna si otro arranque ya la creó."""
    if eng.dialect.name == "postgresql":
        return "ADD COLUMN IF NOT EXISTS"
    return "ADD COLUMN"


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
                    conn.execute(text(f"ALTER TABLE tickets {_agregar_columna(eng)} {columna} {tipo}"))
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
                    conn.execute(text(f"ALTER TABLE resultados {_agregar_columna(eng)} {columna} {tipo}"))
    if "usuarios" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("usuarios")}
        tipo = "NUMERIC(12,2) NOT NULL DEFAULT 0"
        bandera = "BOOLEAN NOT NULL DEFAULT FALSE" if eng.dialect.name == "postgresql" else "INTEGER NOT NULL DEFAULT 0"
        with eng.begin() as conn:
            for columna in ("saldo_caja", "saldo_caja_prueba"):
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} {columna} {tipo}"))
            for columna in (
                "ciclo_caja_movimiento_id",
                "ciclo_caja_prueba_movimiento_id",
                "ciclo_perfil_cierre_id",
                "ciclo_perfil_prueba_cierre_id",
            ):
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} {columna} INTEGER"))
            if "eliminado" not in cols:
                conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} eliminado {bandera}"))
            if "eliminado_en" not in cols:
                conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} eliminado_en TIMESTAMP"))
            if "eliminado_por" not in cols:
                conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} eliminado_por INTEGER"))
            if "motivo_eliminacion" not in cols:
                conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} motivo_eliminacion VARCHAR(200)"))
            if "suspendido" not in cols:
                conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} suspendido {bandera}"))
            if "estado_aprobacion" not in cols:
                conn.execute(text(
                    f"ALTER TABLE usuarios {_agregar_columna(eng)} estado_aprobacion "
                    f"VARCHAR(20) NOT NULL DEFAULT 'aprobado'"
                ))
            for columna in ("solicitado_por", "aprobado_por", "rechazado_por"):
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} {columna} INTEGER"))
            for columna in ("solicitado_en", "aprobado_en", "rechazado_en"):
                if columna not in cols:
                    conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} {columna} TIMESTAMP"))
            if "motivo_rechazo" not in cols:
                conn.execute(text(f"ALTER TABLE usuarios {_agregar_columna(eng)} motivo_rechazo VARCHAR(200)"))
            # Sanea filas previas: nadie queda pendiente por añadir la columna.
            if eng.dialect.name == "postgresql":
                conn.execute(text(
                    "UPDATE usuarios SET estado_aprobacion='aprobado' "
                    "WHERE estado_aprobacion IS NULL OR estado_aprobacion NOT IN "
                    "('aprobado','pendiente','rechazado')"
                ))
            else:
                conn.execute(text(
                    "UPDATE usuarios SET estado_aprobacion='aprobado' "
                    "WHERE estado_aprobacion IS NULL OR estado_aprobacion NOT IN "
                    "('aprobado','pendiente','rechazado')"
                ))
    # permisos_sucursal se crea con create_all; sembrar defaults si faltan filas
    if "permisos_sucursal" in insp.get_table_names() and "sucursales" in insp.get_table_names():
        with eng.begin() as conn:
            # Asegura DEFAULT TRUE en PG (create_all a veces omite server_default).
            if eng.dialect.name == "postgresql":
                for col in (
                    "puede_crear_cajeros", "puede_asignar_fondos", "puede_registrar_entregas",
                    "puede_ajustar_caja", "puede_configurar_limites", "puede_anular_tickets",
                    "puede_ver_reportes",
                ):
                    conn.execute(text(
                        f"ALTER TABLE permisos_sucursal ALTER COLUMN {col} SET DEFAULT TRUE"
                    ))
                    conn.execute(text(
                        f"UPDATE permisos_sucursal SET {col}=TRUE WHERE {col} IS NULL"
                    ))
            conn.execute(text(
                "INSERT INTO permisos_sucursal ("
                "sucursal_id, puede_crear_cajeros, puede_asignar_fondos, puede_registrar_entregas, "
                "puede_ajustar_caja, puede_configurar_limites, puede_anular_tickets, puede_ver_reportes"
                ") SELECT id, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE FROM sucursales s "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM permisos_sucursal p WHERE p.sucursal_id = s.id)"
            ))
    if "terminales" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("terminales")}
        with eng.begin() as conn:
            if "modelo" not in cols:
                conn.execute(text(f"ALTER TABLE terminales {_agregar_columna(eng)} modelo VARCHAR(80)"))
            if "android_api" not in cols:
                conn.execute(text(f"ALTER TABLE terminales {_agregar_columna(eng)} android_api VARCHAR(10)"))
    if "jugadas" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("jugadas")}
        bandera = "BOOLEAN NOT NULL DEFAULT FALSE" if eng.dialect.name == "postgresql" else "INTEGER NOT NULL DEFAULT 0"
        with eng.begin() as conn:
            if "pagada" not in cols:
                conn.execute(text(f"ALTER TABLE jugadas {_agregar_columna(eng)} pagada {bandera}"))
            if "pagado_en" not in cols:
                conn.execute(text(f"ALTER TABLE jugadas {_agregar_columna(eng)} pagado_en TIMESTAMP"))
            if "pagado_por_usuario_id" not in cols:
                conn.execute(text(
                    f"ALTER TABLE jugadas {_agregar_columna(eng)} pagado_por_usuario_id INTEGER"
                ))
            if "pago_operacion_id" not in cols:
                conn.execute(text(
                    f"ALTER TABLE jugadas {_agregar_columna(eng)} pago_operacion_id VARCHAR(40)"
                ))
            if "n3" not in cols:
                conn.execute(text(f"ALTER TABLE jugadas {_agregar_columna(eng)} n3 INTEGER"))
    for tabla in ("limites_cajera", "limites_venta"):
        if tabla in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns(tabla)}
            with eng.begin() as conn:
                if "sorteo2_id" not in cols:
                    conn.execute(text(
                        f"ALTER TABLE {tabla} {_agregar_columna(eng)} sorteo2_id INTEGER NOT NULL DEFAULT 0"
                    ))
    _proteger_pago_parcial()


def _proteger_pago_parcial():
    """Impide que un código anterior marque pagado un ticket con un tramo ya cobrado
    y otro todavía pendiente. El cobro nuevo marca las jugadas antes de cerrar el ticket,
    así que ese camino sigue pasando. Un ticket ya pagado no se vuelve a tocar."""
    from sqlalchemy import text

    eng = engine()
    with eng.begin() as conn:
        if eng.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(740513)"))
            conn.execute(text(
                """
                CREATE OR REPLACE FUNCTION bloquear_pago_duplicado_parcial()
                RETURNS trigger AS $$
                BEGIN
                  IF NEW.estado = 'pagado' AND OLD.estado IS DISTINCT FROM 'pagado'
                     AND EXISTS (
                       SELECT 1 FROM jugadas
                       WHERE ticket_id = NEW.id AND pagada IS TRUE AND premio > 0
                     )
                     AND EXISTS (
                       SELECT 1 FROM jugadas
                       WHERE ticket_id = NEW.id AND premio > 0 AND pagada IS NOT TRUE
                     )
                  THEN
                    RAISE EXCEPTION 'pago parcial ya registrado';
                  END IF;
                  RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            ))
            conn.execute(text("DROP TRIGGER IF EXISTS jugada_pagada_no_repite ON tickets"))
            conn.execute(text(
                """
                CREATE TRIGGER jugada_pagada_no_repite
                BEFORE UPDATE OF estado ON tickets
                FOR EACH ROW EXECUTE FUNCTION bloquear_pago_duplicado_parcial()
                """
            ))
            return
        existe = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = 'jugada_pagada_no_repite'"
        )).first()
        if existe is not None:
            return
        conn.execute(text(
            """
            CREATE TRIGGER jugada_pagada_no_repite
            BEFORE UPDATE OF estado ON tickets
            WHEN NEW.estado = 'pagado' AND OLD.estado != 'pagado'
             AND EXISTS (
               SELECT 1 FROM jugadas
               WHERE ticket_id = NEW.id AND pagada = 1 AND premio > 0
             )
             AND EXISTS (
               SELECT 1 FROM jugadas
               WHERE ticket_id = NEW.id AND premio > 0 AND pagada = 0
             )
            BEGIN
              SELECT RAISE(ABORT, 'pago parcial ya registrado');
            END
            """
        ))
