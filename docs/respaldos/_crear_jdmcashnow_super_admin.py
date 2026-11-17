"""Crea o actualiza la cuenta Super Admin JDMCASHNOW.

SEGURIDAD:
- La contraseña NUNCA va en el código.
- Se lee de la variable de entorno JDMCASHNOW_CLAVE (o --clave solo en shell local).
- Por defecto apunta a una BD aislada / DATABASE_URL local.
- Para LIVE exige --live y la confirmación exacta: SI-AUTORIZO-LIVE
- No borra usuarios, tickets ni saldos. No cambia la clave de Alfredo.
- Si JDMCASHNOW ya existe: solo asegura rol=super_admin y aprobado (clave
  intacta salvo --reset-clave).

Ejemplos:
  set JDMCASHNOW_CLAVE=********
  python docs/respaldos/_crear_jdmcashnow_super_admin.py --sqlite-tmp

  set JDMCASHNOW_CLAVE=********
  python docs/respaldos/_crear_jdmcashnow_super_admin.py --database-url "postgresql://..."
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

USUARIO = "JDMCASHNOW"
NOMBRE = "JDMCASHNOW"


def _clave(args) -> str:
    clave = (args.clave or os.environ.get("JDMCASHNOW_CLAVE") or "").strip()
    if not clave:
        raise SystemExit(
            "Falta la contraseña. Defina JDMCASHNOW_CLAVE en el entorno "
            "o pase --clave (solo en máquina local, nunca en el repo)."
        )
    if len(clave) < 8:
        raise SystemExit("La clave de JDMCASHNOW debe tener al menos 8 caracteres.")
    return clave


def main() -> int:
    p = argparse.ArgumentParser(description="Crear Super Admin JDMCASHNOW de forma segura")
    p.add_argument("--database-url", default="", help="URL SQLAlchemy/Postgres o sqlite")
    p.add_argument("--sqlite-tmp", action="store_true", help="BD SQLite temporal (prueba aislada)")
    p.add_argument("--live", action="store_true", help="Permitir escribir en PostgreSQL LIVE")
    p.add_argument("--confirm", default="", help="Debe ser SI-AUTORIZO-LIVE con --live")
    p.add_argument("--clave", default="", help="Evitar: preferir JDMCASHNOW_CLAVE")
    p.add_argument("--reset-clave", action="store_true", help="Si ya existe, también cambia la clave")
    p.add_argument("--dry-run", action="store_true", help="Solo muestra el plan, no escribe")
    args = p.parse_args()

    if args.sqlite_tmp:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        os.environ["DATABASE_URL"] = "sqlite:///" + tmp.name.replace("\\", "/")
        print("BD_AISLADA", tmp.name)
    elif args.database_url:
        os.environ["DATABASE_URL"] = args.database_url.strip()
    elif not os.environ.get("DATABASE_URL"):
        raise SystemExit("Indique --sqlite-tmp, --database-url o DATABASE_URL")

    url = os.environ["DATABASE_URL"]
    es_live = "render.com" in url or "dpg-dbslergae00c738d56j0" in url or "sistema_de_banca_moderna" in url
    if es_live and not args.live:
        raise SystemExit("Esta URL parece LIVE. Use --live --confirm SI-AUTORIZO-LIVE o una BD aislada.")
    if args.live and args.confirm != "SI-AUTORIZO-LIVE":
        raise SystemExit("Para LIVE debe pasar --confirm SI-AUTORIZO-LIVE")

    from apps.api.db import configurar, init_db, nueva_sesion
    from apps.api.models import Usuario
    from apps.api.security import hash_clave

    configurar()
    init_db()
    clave = _clave(args)

    db = nueva_sesion()
    try:
        alfredo = db.query(Usuario).filter_by(usuario="admin").first()
        existente = db.query(Usuario).filter_by(usuario=USUARIO).first()
        plan = {
            "usuario": USUARIO,
            "rol": "super_admin",
            "alfred_intact": True,
            "alfred_usuario": alfredo.usuario if alfredo else None,
            "alfred_rol": alfredo.rol if alfredo else None,
            "existe": existente is not None,
            "accion": "crear" if existente is None else ("reset_clave" if args.reset_clave else "asegurar_rol"),
            "dry_run": args.dry_run,
        }
        print("PLAN", plan)
        if args.dry_run:
            return 0

        if existente is None:
            db.add(Usuario(
                nombre=NOMBRE,
                usuario=USUARIO,
                rol="super_admin",
                sucursal_id=None,
                activo=True,
                eliminado=False,
                suspendido=False,
                estado_aprobacion="aprobado",
                clave_hash=hash_clave(clave),
            ))
        else:
            existente.rol = "super_admin"
            existente.sucursal_id = None
            existente.activo = True
            existente.eliminado = False
            existente.suspendido = False
            existente.estado_aprobacion = "aprobado"
            if args.reset_clave or not existente.clave_hash:
                existente.clave_hash = hash_clave(clave)
        # Alfredo: no tocar
        if alfredo is not None:
            assert alfredo.usuario == "admin"
        db.commit()
        from apps.api import permisos as perm
        print("OK", {
            "usuario": USUARIO,
            "rol": "super_admin",
            "alfred_rol": alfredo.rol if alfredo else None,
            "alfred_usuario": alfredo.usuario if alfredo else None,
            "compat_global": perm.compat_global_activo(db),
            "compat_global_forzado": perm.compat_global_forzado(),
            "aviso": (
                "Aislamiento diferido: COMPAT_GLOBAL_FORZADO=1 está activo. "
                "Verifique el login de JDMCASHNOW y luego quite la variable para aislar admins."
                if perm.compat_global_forzado()
                else (
                    "Aislamiento activo (hay super_admin). "
                    "Si aún no verificó el login, reinicie con COMPAT_GLOBAL_FORZADO=1."
                    if not perm.compat_global_activo(db)
                    else "Sin aislamiento (no hay super_admin activo)."
                )
            ),
        })
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
