"""Validación contra un PostgreSQL local aislado.

Solo acepta 127.0.0.1:55432/banca_moderna_aislada. No lee DATABASE_URL
de producción y no llama a init_db del código viejo.
"""
import os
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

HOST = "127.0.0.1"
PUERTO = 55432
BASE = "banca_moderna_aislada"
USUARIO_PG = "banca_test"
RAIZ = Path(__file__).resolve().parents[1]
WT = Path(os.environ["LOCALAPPDATA"]) / "banca-wt-7505f09"
PWFILE = Path(os.environ["LOCALAPPDATA"]) / "banca-moderna-pg-aislada-pw.txt"

fallos = []


def dinero(valor):
    return Decimal(str(valor)).quantize(Decimal("0.01"))


def punto(nombre, ok, detalle=""):
    marca = "PASÓ" if ok else "FALLÓ"
    print(f"{marca}  {nombre}" + (f" — {detalle}" if detalle else ""))
    if not ok:
        fallos.append(nombre)


def url_aislada():
    clave = PWFILE.read_text(encoding="ascii").strip()
    return f"postgresql+psycopg://{USUARIO_PG}:{clave}@{HOST}:{PUERTO}/{BASE}", clave


def limpiar(texto, clave):
    return str(texto).replace(clave, "***")


def main():
    os.chdir(RAIZ)
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    if not PWFILE.is_file():
        print("No está el clúster aislado.")
        return 1
    url, clave = url_aislada()
    os.environ["DATABASE_URL"] = url
    os.environ["MODO_DESARROLLO"] = "true"
    os.environ["PYTEST_CURRENT_TEST"] = "validar_postgres_aislado"
    os.environ.pop("RENDER_SERVICE_ID", None)

    from apps.api import db as dbmod
    from apps.api import resultados_auto, servicios
    from apps.api.comun import ErrorServicio
    from apps.api.main import app
    from apps.api.models import Jugada, ObservacionResultado, Resultado, Sucursal, Ticket, Usuario
    from fastapi.testclient import TestClient
    from tests.conftest import Entorno
    from tests.test_anguila_haiti import _doc, _juego

    reloj = {"ahora": datetime(2026, 11, 14, 10, 0, 0)}
    servicios.ahora_local = lambda: reloj["ahora"]
    dbmod.configurar(url)
    with dbmod.engine().connect() as conn:
        donde = conn.execute(text(
            "SELECT current_database(), inet_server_port(), current_user, split_part(version(), ' ', 2)"
        )).one()
    punto(
        "1. Base aislada",
        donde[0] == BASE and int(donde[1]) == PUERTO and donde[2] == USUARIO_PG,
        f"PostgreSQL {donde[3]} en {HOST}:{PUERTO}/{BASE}",
    )
    if fallos:
        return 1

    dbmod.init_db()
    with dbmod.engine().connect() as conn:
        creadas = {
            fila[0] for fila in conn.execute(text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'jugadas'
                  AND column_name IN ('pagada', 'pagado_en', 'pagado_por_usuario_id', 'pago_operacion_id')
                """
            ))
        }
    punto("2. create_all trae las cuatro columnas", creadas == {
        "pagada", "pagado_en", "pagado_por_usuario_id", "pago_operacion_id",
    }, " ".join(sorted(creadas)))

    db = dbmod.nueva_sesion()
    sucursal_vieja = db.query(Sucursal).filter_by(codigo="1301").one()
    tipo = db.execute(text("SELECT id FROM tipos_jugada WHERE codigo = 'QN'")).scalar()
    sorteo = db.execute(text("SELECT id FROM sorteos WHERE nombre = 'La Primera 12:00 PM'")).scalar()
    saldo_viejo = dinero(sucursal_vieja.saldo_actual)
    db.close()

    with dbmod.engine().begin() as conn:
        for columna in ("pagada", "pagado_en", "pagado_por_usuario_id", "pago_operacion_id"):
            conn.execute(text(f"ALTER TABLE jugadas DROP COLUMN IF EXISTS {columna}"))
        conn.execute(text(
            """
            INSERT INTO tickets (
                id, serial, sucursal_vendedora_id, vendido_en, fecha, total, estado,
                premio_total, es_prueba, reimpresiones
            ) VALUES
            (900001, 'HIST900001', :suc, '2026-11-01 09:00:00', '2026-11-01', 10, 'pagado', 19100, true, 0),
            (900002, 'HIST900002', :suc, '2026-11-01 09:05:00', '2026-11-01', 10, 'ganador', 600, true, 0),
            (900003, 'HIST900003', :suc, '2026-11-01 09:10:00', '2026-11-01', 10, 'vendido', 0, true, 0)
            """
        ), {"suc": sucursal_vieja.id})
        conn.execute(text(
            """
            INSERT INTO jugadas (
                ticket_id, tipo_jugada_id, sorteo_id, fecha, numeros, n1, monto,
                factores_json, evaluada, premio
            ) VALUES
            (900001, :tipo, :sorteo, '2026-11-01', '25', 25, 10, '{"1ro": "60.00"}', true, 19100),
            (900002, :tipo, :sorteo, '2026-11-01', '25', 25, 10, '{"1ro": "60.00"}', true, 600),
            (900003, :tipo, :sorteo, '2026-11-01', '99', 99, 10, '{"1ro": "60.00"}', false, NULL)
            """
        ), {"tipo": tipo, "sorteo": sorteo})

    dbmod._columnas_faltantes()
    with dbmod.engine().connect() as conn:
        tipos = {
            fila.column_name: (fila.data_type, fila.is_nullable, fila.column_default, fila.character_maximum_length)
            for fila in conn.execute(text(
                """
                SELECT column_name, data_type, is_nullable, column_default, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'jugadas'
                  AND column_name IN ('pagada', 'pagado_en', 'pagado_por_usuario_id', 'pago_operacion_id')
                """
            ))
        }
        disparador = conn.execute(text(
            """
            SELECT pg_get_triggerdef(t.oid)
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE t.tgname = 'jugada_pagada_no_repite' AND c.relname = 'tickets' AND NOT t.tgisinternal
            """
        )).scalar()
        funcion = conn.execute(text(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p WHERE p.proname = 'bloquear_pago_duplicado_parcial'"
        )).scalar()
    punto(
        "2. La migración agrega las cuatro columnas",
        tipos.get("pagada", (None, None, None, None))[0] == "boolean"
        and tipos.get("pagada", (None, "YES", None, None))[1] == "NO"
        and "false" in str(tipos.get("pagada", (None, None, "", None))[2]).lower()
        and "timestamp" in str(tipos.get("pagado_en", ("",))[0])
        and tipos.get("pagado_por_usuario_id", ("",))[0] == "integer"
        and tipos.get("pago_operacion_id", ("", None, None, None))[0] == "character varying"
        and tipos.get("pago_operacion_id", (None, None, None, None))[3] == 40,
        "pagada boolean, pagado_en timestamp, pagado_por_usuario_id integer, pago_operacion_id varchar(40)",
    )
    punto(
        "3. El disparador queda instalado",
        bool(disparador) and "BEFORE UPDATE OF estado" in disparador
        and "bloquear_pago_duplicado_parcial" in (disparador or "")
        and "pago parcial ya registrado" in (funcion or ""),
        "BEFORE UPDATE OF estado",
    )

    def foto_historica():
        db = dbmod.nueva_sesion()
        tickets = {
            fila.id: (fila.estado, dinero(fila.premio_total), dinero(fila.total))
            for fila in db.query(Ticket).filter(Ticket.id >= 900000)
        }
        jugadas = {
            fila.id: (fila.ticket_id, None if fila.premio is None else dinero(fila.premio), bool(fila.evaluada), bool(fila.pagada))
            for fila in db.query(Jugada).filter(Jugada.ticket_id >= 900000)
        }
        saldo = dinero(db.query(Sucursal).filter_by(codigo="1301").one().saldo_actual)
        db.close()
        return tickets, jugadas, saldo

    antes_hist = foto_historica()
    dbmod.init_db()
    db = dbmod.nueva_sesion()
    from apps.api import motor
    for ticket in db.query(Ticket).filter(Ticket.id >= 900000):
        motor.recomputar_ticket(db, ticket)
    db.commit()
    db.close()
    despues_recomputar = foto_historica()

    client = TestClient(app)
    entorno = Entorno(client)
    b = entorno.banca(saldo=5764, codigo="1302", nombre="BANCA AISLADA", usuario="0219", clave="prueba123")
    jose = next(f for f in entorno.c.get("/usuarios", headers=entorno.admin).json() if f["usuario"] == "0219")
    fondo = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": jose["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-pg",
    }, headers=entorno.admin)
    punto("Fondo de prueba", fondo.status_code == 201, fondo.text[:180])
    otra = entorno.operador("caja2", "1234", b["sucursal"]["id"])
    fondo2 = entorno.c.post("/fondos", json={
        "sucursal_id": b["sucursal"]["id"], "usuario_id": otra["id"], "monto": 20000,
        "tipo": "aporte_prueba", "operacion_id": "fondo-pg-2",
    }, headers=entorno.admin)
    punto("Segundo cajero", fondo2.status_code == 201, fondo2.text[:180])

    def consultar(ticket):
        r = entorno.c.post("/terminal/tickets/consultar", json={
            "id": ticket["id"], "serial": ticket["serial"],
        }, headers=b["headers"])
        return r

    def simular(sorteo_id, p1, p2, p3):
        r = entorno.c.post("/resultados", json={
            "sorteo_id": sorteo_id, "fecha": "2026-11-14",
            "premio1": p1, "premio2": p2, "premio3": p3, "simulado": True,
        }, headers=entorno.admin)
        return r

    def caja(headers):
        return dinero(entorno.c.get("/terminal/sorteos", headers=headers).json()["mi_caja"])

    primera = entorno.sorteo_id("La Primera 12")
    florida = entorno.sorteo_id("Florida Día")
    lotedom = entorno.sorteo_id("LOTEDOM")
    ticket = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [primera], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [florida], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [lotedom], "numeros": "99", "monto": 5},
    ])
    punto("4. Ticket de varias loterías", len(ticket["jugadas"]) == 3, f"ticket {ticket['id']}")
    saldo_banca = dinero(entorno.saldo(b["sucursal"]["id"]))
    sim = simular(primera, 25, 1, 2)
    punto("Resultado de la primera lotería", sim.status_code == 201, sim.text[:160])
    antes = caja(b["headers"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pg-tramo-1",
    }, headers=b["headers"])
    consulta = consultar(ticket)
    cuerpo = consulta.json()
    punto(
        "5. Cobra el tramo listo y deja el otro pendiente",
        pago.status_code == 200 and cuerpo["premio_pagado"] == "600.00"
        and cuerpo["importe_a_cobrar"] == "0.00" and "Florida 2:30 PM" in cuerpo["texto_pago"]
        and caja(b["headers"]) == antes - Decimal("600.00")
        and dinero(entorno.saldo(b["sucursal"]["id"])) == saldo_banca,
        f"pagado {cuerpo.get('premio_pagado')} estado {cuerpo.get('estado')}",
    )
    dbmod.engine().dispose()
    consulta = consultar(ticket)
    cuerpo = consulta.json()
    repetido = entorno.c.post("/terminal/tickets/pagar", json={
        "id": ticket["id"], "serial": ticket["serial"], "operacion_id": "pg-tras-reinicio",
    }, headers=b["headers"])
    punto(
        "7. El reinicio conserva el pago",
        cuerpo["premio_pagado"] == "600.00" and cuerpo["premio_total"] == "600.00"
        and repetido.status_code == 409 and caja(b["headers"]) == antes - Decimal("600.00"),
        f"sigue pagado {cuerpo.get('premio_pagado')}",
    )
    simular(lotedom, 25, 54, 78)
    simular(florida, 25, 8, 9)
    consulta = consultar(ticket)
    cuerpo = consulta.json()
    punto(
        "5. Al salir la otra lotería el pendiente es solo ese premio",
        cuerpo["estado"] == "parcial" and cuerpo["premio_total"] == "1200.00"
        and cuerpo["premio_pagado"] == "600.00" and cuerpo["importe_a_cobrar"] == "600.00"
        and any(j["numeros"] == "99" for j in cuerpo["jugadas"]),
        f"total {cuerpo.get('premio_total')} a cobrar {cuerpo.get('importe_a_cobrar')}",
    )

    resultados = []
    barrera = threading.Barrier(2)

    def intento(usuario_id):
        sesion = dbmod.nueva_sesion()
        try:
            barrera.wait(timeout=10)
            servicios.pagar_ticket(
                sesion, ticket["id"], ticket["serial"], b["sucursal"]["id"], None, usuario_id,
            )
            resultados.append("ok")
        except ErrorServicio as exc:
            resultados.append(exc.status)
        finally:
            sesion.close()

    hilos = [
        threading.Thread(target=intento, args=(jose["id"],)),
        threading.Thread(target=intento, args=(otra["id"],)),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=30)
    otra_headers = entorno.login_terminal("caja2", "1234")
    punto(
        "6. Dos cajeros, un solo cobro",
        resultados.count("ok") == 1 and resultados.count(409) == 1
        and caja(b["headers"]) + caja(otra_headers) == antes + Decimal("20000.00") - Decimal("1200.00")
        and dinero(entorno.saldo(b["sucursal"]["id"])) == saldo_banca,
        str(resultados),
    )

    suerte = entorno.sorteo_id("La Suerte 12:30")
    king = entorno.sorteo_id("King 12PM")
    reversion = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [suerte], "numeros": "25", "monto": 10},
        {"tipo": "QN", "sorteos": [king], "numeros": "25", "monto": 10},
    ])
    simular(suerte, 25, 1, 2)
    antes_rev = caja(b["headers"])
    pago = entorno.c.post("/terminal/tickets/pagar", json={
        "id": reversion["id"], "serial": reversion["serial"], "operacion_id": "pg-rev-1",
    }, headers=b["headers"])
    punto("Reversión: primer tramo cobrado", pago.status_code == 200, pago.text[:160])
    simular(king, 25, 3, 4)
    dbmod.engine().dispose()
    if WT.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(WT)], cwd=RAIZ, check=False)
    alta = subprocess.run(
        ["git", "worktree", "add", "--detach", str(WT), "7505f09"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    punto("8. El commit 7505f09 se lee sin modificarlo", alta.returncode == 0, limpiar(alta.stderr, clave)[-240:])
    runner = WT / "_reversion_aislada.py"
    runner.write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "from sqlalchemy import text\n"
        "from sqlalchemy.exc import DatabaseError\n"
        "clave = Path(os.environ['BANCA_PG_PWFILE']).read_text(encoding='ascii').strip()\n"
        "url = f'postgresql+psycopg://banca_test:{clave}@127.0.0.1:55432/banca_moderna_aislada'\n"
        "os.environ['MODO_DESARROLLO'] = 'true'\n"
        "os.environ['PYTEST_CURRENT_TEST'] = 'reversion-7505f09'\n"
        "os.environ.pop('DATABASE_URL', None)\n"
        "from apps.api import db as dbmod, servicios\n"
        "from apps.api.comun import ErrorServicio\n"
        "dbmod.configurar(url)\n"
        "modo, ticket_id, serial, sucursal, usuario = sys.argv[1:6]\n"
        "sufijo = sys.argv[6] if len(sys.argv) > 6 else modo\n"
        "db = dbmod.nueva_sesion()\n"
        "try:\n"
        "    if modo == 'forzar':\n"
        "        cambiadas = db.execute(text(\"UPDATE tickets SET estado = 'ganador' WHERE id = :id AND estado = 'parcial'\"), {'id': int(ticket_id)}).rowcount\n"
        "        db.commit()\n"
        "        if cambiadas != 1:\n"
        "            print('RESULTADO no-parcial')\n"
        "            raise SystemExit(0)\n"
        "    servicios.pagar_ticket(db, int(ticket_id), serial, int(sucursal), None, int(usuario), operacion_id='rev-' + sufijo)\n"
        "    print('RESULTADO ok')\n"
        "except ErrorServicio as exc:\n"
        "    print(f'RESULTADO error {exc.status}')\n"
        "except DatabaseError:\n"
        "    db.rollback()\n"
        "    print('RESULTADO disparador')\n"
        "finally:\n"
        "    db.close()\n",
        encoding="utf-8",
    )

    def correr_viejo(modo, ticket_row, sufijo=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(WT)
        env["BANCA_PG_PWFILE"] = str(PWFILE)
        env.pop("DATABASE_URL", None)
        proc = subprocess.run(
            [sys.executable, str(runner), modo, str(ticket_row["id"]), ticket_row["serial"],
             str(b["sucursal"]["id"]), str(jose["id"]), sufijo or modo],
            cwd=WT, env=env, capture_output=True, text=True,
        )
        salida = limpiar(proc.stdout + proc.stderr, clave)
        linea = next((ln.strip() for ln in proc.stdout.splitlines() if ln.startswith("RESULTADO")), "")
        return proc.returncode, linea, salida

    codigo, linea, salida = correr_viejo("parcial", reversion)
    consulta = consultar(reversion).json()
    punto(
        "8. El código viejo rechaza el ticket parcial",
        codigo == 0 and linea == "RESULTADO error 409" and consulta["estado"] == "parcial"
        and consulta["importe_a_cobrar"] == "600.00"
        and caja(b["headers"]) == antes_rev - Decimal("600.00"),
        linea or salida[-300:],
    )
    codigo, linea, salida = correr_viejo("forzar", reversion)
    consulta = consultar(reversion).json()
    punto(
        "3 y 8. El disparador impide cerrar el premio completo",
        codigo == 0 and linea == "RESULTADO disparador"
        and consulta["premio_pagado"] == "600.00" and consulta["importe_a_cobrar"] == "600.00"
        and caja(b["headers"]) == antes_rev - Decimal("600.00")
        and dinero(entorno.saldo(b["sucursal"]["id"])) == saldo_banca,
        linea or salida[-300:],
    )
    resto = entorno.c.post("/terminal/tickets/pagar", json={
        "id": reversion["id"], "serial": reversion["serial"], "operacion_id": "pg-rev-2",
    }, headers=b["headers"])
    cuerpo = resto.json()
    punto(
        "8. El código nuevo cobra solo el tramo que faltaba",
        resto.status_code == 200 and cuerpo["estado"] == "pagado"
        and "PREMIO PAGADO: RD$1200.00" in cuerpo["comprobante"]
        and caja(b["headers"]) == antes_rev - Decimal("1200.00"),
        f"estado {cuerpo.get('estado')}",
    )

    real = entorno.sorteo_id("Real Tarde")
    limpio = entorno.vender_ok(b["headers"], [
        {"tipo": "QN", "sorteos": [real], "numeros": "25", "monto": 10},
    ])
    simular(real, 25, 1, 2)
    antes_limpio = caja(b["headers"])
    codigo, linea, salida = correr_viejo("limpio", limpio)
    db = dbmod.nueva_sesion()
    jugada = db.query(Jugada).filter_by(ticket_id=limpio["id"]).one()
    pagada_vieja = bool(jugada.pagada)
    premio_limpio = dinero(db.get(Ticket, limpio["id"]).premio_total)
    estado_limpio = db.get(Ticket, limpio["id"]).estado
    db.close()
    punto(
        "8. Un ganador nunca cobrado sí lo paga el código viejo, una sola vez",
        codigo == 0 and linea == "RESULTADO ok" and estado_limpio == "pagado"
        and pagada_vieja is False and premio_limpio == Decimal("600.00")
        and caja(b["headers"]) == antes_limpio - Decimal("600.00"),
        linea or salida[-300:],
    )
    codigo, linea, salida = correr_viejo("limpio", limpio, "limpio-otra")
    segundo_nuevo = entorno.c.post("/terminal/tickets/pagar", json={
        "id": limpio["id"], "serial": limpio["serial"], "operacion_id": "pg-limpio-nuevo",
    }, headers=b["headers"])
    punto(
        "8. Ese pago viejo no se repite",
        codigo == 0 and linea == "RESULTADO error 409" and segundo_nuevo.status_code == 409
        and caja(b["headers"]) == antes_limpio - Decimal("600.00"),
        linea or salida[-300:],
    )

    red = {"llamadas": 0}

    def prohibido(*args, **kwargs):
        red["llamadas"] += 1
        raise RuntimeError("red prohibida")

    from apps.api import conectate_firmado
    conectate_firmado.descargar_ventana = prohibido
    firmado = _doc(
        [_juego("Anguila 11:00 AM", "g11", (11, 22, 33))],
        [_juego("Haiti Bolet 11:30 AM", "h11", (19, 3, 45))],
        [_juego("Anguila 11:00 AM", "s11", (1, 2, 3))],
        [_juego("Haiti Bolet 11:30 AM", "sh", (4, 5, 6))],
    )
    confirmados = []
    for minuto in (0, 4, 10):
        reloj["ahora"] = datetime(2026, 11, 14, 10, minuto)
        paso = resultados_auto.ciclo(forzar=True, payload=[], firmado=firmado)
        confirmados.append(paso.get("confirmados"))
    reloj["ahora"] = datetime(2026, 11, 14, 10, 12)
    omitido = resultados_auto.ciclo(forzar=False, payload=[], firmado=firmado)
    dbmod.engine().dispose()
    db = dbmod.nueva_sesion()
    filas = {
        fila.sorteo.nombre: (fila.premio1, fila.premio2, fila.premio3, fila.externo, fila.estado)
        for fila in db.query(Resultado)
        if fila.sorteo is not None and fila.sorteo.nombre.startswith(("La Anguila", "Haiti"))
    }
    lecturas = db.query(ObservacionResultado).filter_by(
        sorteo_id=entorno.sorteo_id("La Anguila 11:00 AM")
    ).one().lecturas
    marca = resultados_auto.estado_reloj(db, datetime(2026, 11, 14, 10, 12))
    db.close()
    punto(
        "9. Reloj y lecturas firmadas sobreviven en PostgreSQL",
        confirmados == [0, 0, 2] and omitido.get("omitido") == "otra consulta ya corrió en este intervalo"
        and red["llamadas"] == 0 and lecturas == 3 and marca["reloj"] == "ACTIVO"
        and filas.get("La Anguila 11:00 AM") == (11, 22, 33, "firmado", "liquidado")
        and filas.get("Haiti Bolet 11:30 AM") == (19, 3, 45, "firmado", "liquidado"),
        f"confirmados {confirmados} reloj {marca.get('reloj')} lecturas {lecturas}",
    )

    historico = {
        900001: ("pagado", Decimal("19100.00"), Decimal("10.00")),
        900002: ("ganador", Decimal("600.00"), Decimal("10.00")),
        900003: ("vendido", Decimal("0.00"), Decimal("10.00")),
    }
    tickets, jugadas, saldo = foto_historica()
    premios = {fila[0]: fila[1] for fila in jugadas.values()}
    punto(
        "10. Los tickets históricos conservan importe y estado",
        tickets == historico and antes_hist[0] == historico and despues_recomputar[0] == historico
        and premios == {900001: Decimal("19100.00"), 900002: Decimal("600.00"), 900003: None}
        and all(not fila[3] for fila in jugadas.values())
        and saldo == saldo_viejo == Decimal("5764.00"),
        str(tickets),
    )
    viejo_pagado = {"id": 900001, "serial": "HIST900001"}
    codigo, linea, salida = correr_viejo("historico", viejo_pagado)
    nuevo = entorno.c.post("/terminal/tickets/pagar", json={
        "id": 900001, "serial": "HIST900001", "operacion_id": "pg-historico",
    }, headers=b["headers"])
    tickets, _, saldo = foto_historica()
    punto(
        "10. Un histórico ya pagado no se vuelve a cobrar",
        codigo == 0 and linea == "RESULTADO error 409" and nuevo.status_code == 409
        and tickets[900001][0] == "pagado" and tickets[900001][1] == Decimal("19100.00")
        and saldo == Decimal("5764.00"),
        linea or salida[-300:],
    )
    cabeza = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True,
    )
    punto(
        "El commit histórico sigue siendo 7505f09",
        cabeza.stdout.strip() == "7505f096fd347b0b4bdb70612bfb4054736b89c8",
        cabeza.stdout.strip(),
    )
    client.close()
    print(f"\n{len(fallos)} fallos" if fallos else "\nPostgreSQL aislado: todas las comprobaciones pasaron")
    return 1 if fallos else 0


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception:
        clave = PWFILE.read_text(encoding="ascii").strip() if PWFILE.is_file() else ""
        buf = traceback.format_exc()
        print(limpiar(buf, clave))
        raise SystemExit(1)
    raise SystemExit(codigo)
