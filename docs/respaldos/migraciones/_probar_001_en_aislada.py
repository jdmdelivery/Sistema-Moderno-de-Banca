"""Aplica migración 001 en BD temporal restaurada desde el último dump.

NO toca sistema_de_banca_moderna. Exit 1 si cambian conteos/saldos críticos.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

DIR = Path(__file__).resolve().parent
ROOT = DIR.parent
PSQL = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"
PG_RESTORE = r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe"
TMP = "banca_moderna_mig_superadmin_test"


def load_bak():
    spec = importlib.util.spec_from_file_location("bak", ROOT / "_backup_pre_publish_parciales.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def admin_url(url: str) -> str:
    u = urlparse(url)
    return urlunparse((u.scheme, u.netloc, "/postgres", "", "", ""))


def db_url(url: str, db: str) -> str:
    u = urlparse(url)
    return urlunparse((u.scheme, u.netloc, f"/{db}", "", "", ""))


def ka(url: str) -> str:
    return url + ("&" if "?" in url else "?") + "keepalives=1&keepalives_idle=30"


def run(args, timeout=600):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def fingerprints(m, url: str) -> dict:
    return {
        "conteos": m.counts(url),
        "fp_cajas": m.psql(url, "SELECT COALESCE(string_agg(id::text||':'||COALESCE(saldo_caja::text,'0')||':'||COALESCE(saldo_caja_prueba::text,'0'), ',' ORDER BY id),'') FROM usuarios;").strip(),
        "fp_suc": m.psql(url, "SELECT COALESCE(string_agg(id::text||':'||COALESCE(saldo_actual::text,'0'), ',' ORDER BY id),'') FROM sucursales;").strip(),
        "fp_tix": m.psql(url, "SELECT COALESCE(string_agg(id::text||':'||sucursal_vendedora_id::text||':'||COALESCE(usuario_id::text,'')||':'||total::text||':'||estado, ',' ORDER BY id),'') FROM tickets;").strip(),
        "roles": m.psql(url, "SELECT id::text||'|'||usuario||'|'||rol FROM usuarios ORDER BY id;").strip().splitlines(),
        "claves": m.psql(url, "SELECT id::text||'|'||COALESCE(clave_hash,'') FROM usuarios ORDER BY id;").strip().splitlines(),
    }


def main() -> int:
    m = load_bak()
    url = m.connection_url()
    aurl = admin_url(url)
    dumps = sorted(ROOT.glob("banca_moderna_pre_multisucursal_*.dump"), reverse=True)
    sqls = sorted(ROOT.glob("banca_moderna_pre_multisucursal_*.sql"), reverse=True)
    if not dumps and not sqls:
        dumps = sorted(ROOT.glob("banca_moderna_pre_limpieza_*.dump"), reverse=True)
        sqls = sorted(ROOT.glob("banca_moderna_pre_limpieza_*.sql"), reverse=True)
    if not dumps and not sqls:
        raise SystemExit("No hay dump reciente para restaurar")
    dump = dumps[0] if dumps else None
    sql = sqls[0] if sqls else None

    run([PSQL, "--dbname", aurl, "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TMP}';"], timeout=60)
    run([PSQL, "--dbname", aurl, "-c", f'DROP DATABASE IF EXISTS "{TMP}";'], timeout=60)
    c = run([PSQL, "--dbname", aurl, "-c", f'CREATE DATABASE "{TMP}";'], timeout=60)
    if c.returncode != 0:
        raise SystemExit(c.stderr or c.stdout)

    turl = db_url(url, TMP)
    print("RESTORE", TMP, "from", (sql or dump).name)
    if sql:
        r = run([PSQL, "--dbname", ka(turl), "-v", "ON_ERROR_STOP=1", "-f", str(sql)], timeout=600)
        if r.returncode != 0:
            raise SystemExit(r.stderr or r.stdout)
    else:
        r = run([PG_RESTORE, "--dbname", ka(turl), "--no-owner", "--no-acl", "--exit-on-error", str(dump)], timeout=600)
        if r.returncode != 0:
            raise SystemExit(r.stderr or r.stdout)

    antes = fingerprints(m, turl)
    mig = DIR / "_001_super_admin_aditiva.sql"
    print("APPLY", mig.name)
    a = run([PSQL, "--dbname", ka(turl), "-v", "ON_ERROR_STOP=1", "-f", str(mig)], timeout=120)
    if a.returncode != 0:
        raise SystemExit(a.stderr or a.stdout)
    despues = fingerprints(m, turl)

    # Re-aplicar (idempotencia)
    a2 = run([PSQL, "--dbname", ka(turl), "-v", "ON_ERROR_STOP=1", "-f", str(mig)], timeout=120)
    if a2.returncode != 0:
        raise SystemExit("NO IDEMPOTENTE: " + (a2.stderr or a2.stdout))

    # Revert + re-apply smoke
    rev = DIR / "_001_super_admin_revert.sql"
    rv = run([PSQL, "--dbname", ka(turl), "-v", "ON_ERROR_STOP=1", "-f", str(rev)], timeout=120)
    if rv.returncode != 0:
        raise SystemExit("REVERT FAIL: " + (rv.stderr or rv.stdout))
    tras_revert = fingerprints(m, turl)
    a3 = run([PSQL, "--dbname", ka(turl), "-v", "ON_ERROR_STOP=1", "-f", str(mig)], timeout=120)
    if a3.returncode != 0:
        raise SystemExit(a3.stderr or a3.stdout)

    pendientes = m.psql(turl, "SELECT COUNT(*)::text FROM usuarios WHERE estado_aprobacion='pendiente';").strip()
    permisos = m.psql(turl, "SELECT COUNT(*)::text FROM permisos_sucursal;").strip()
    sucs = m.psql(turl, "SELECT COUNT(*)::text FROM sucursales;").strip()

    ok = (
        antes["fp_cajas"] == despues["fp_cajas"] == tras_revert["fp_cajas"]
        and antes["fp_suc"] == despues["fp_suc"] == tras_revert["fp_suc"]
        and antes["fp_tix"] == despues["fp_tix"] == tras_revert["fp_tix"]
        and antes["roles"] == despues["roles"] == tras_revert["roles"]
        and antes["claves"] == despues["claves"] == tras_revert["claves"]
        and pendientes == "0"
        and permisos == sucs
    )

    # Cleanup
    run([PSQL, "--dbname", aurl, "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{TMP}';"], timeout=60)
    run([PSQL, "--dbname", aurl, "-c", f'DROP DATABASE IF EXISTS "{TMP}";'], timeout=60)

    report = {
        "ok": ok,
        "stamp": datetime.now().isoformat(timespec="seconds"),
        "source": str(sql or dump),
        "pendientes_tras_mig": pendientes,
        "permisos_filas": permisos,
        "sucursales": sucs,
        "cajas_intactas": antes["fp_cajas"] == despues["fp_cajas"],
        "tickets_intactos": antes["fp_tix"] == despues["fp_tix"],
        "roles_intactos": antes["roles"] == despues["roles"],
        "claves_intactas": antes["claves"] == despues["claves"],
        "idempotente": True,
        "reversible": tras_revert["fp_tix"] == antes["fp_tix"],
    }
    out = DIR / f"resultado_prueba_001_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
