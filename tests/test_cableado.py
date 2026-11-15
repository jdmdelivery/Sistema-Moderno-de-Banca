"""Cableado del panel: ningún botón sin endpoint y ningún endpoint
fantasma. Se cruza el app.js contra las rutas reales de la API y los
id de index.html, como en la auditoría de JDM.
"""
import re
from pathlib import Path

from apps.api.main import app

RAIZ = Path(__file__).resolve().parent.parent
APP_JS = (RAIZ / "apps" / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (RAIZ / "apps" / "web" / "index.html").read_text(encoding="utf-8")


def _rutas_api():
    patrones = []
    for ruta in app.routes:
        path = getattr(ruta, "path", "")
        if path and not path.startswith("/static"):
            patrones.append(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$"))
    return patrones


def _extraer_caminos():
    """Extrae los caminos llamados por api/post/put/del en app.js, recorriendo
    las plantillas `...` con su profundidad de ${...} (admite plantillas y
    comillas anidadas). Las interpolaciones quedan como {x}."""
    caminos = []
    for m in re.finditer(r"(?:api|post|put|del)\(\s*", APP_JS):
        i = m.end()
        if i >= len(APP_JS):
            continue
        comilla = APP_JS[i]
        if comilla in "'\"":
            fin = APP_JS.find(comilla, i + 1)
            if fin > i:
                caminos.append(APP_JS[i + 1:fin])
        elif comilla == "`":
            j, profundidad, buf = i + 1, 0, []
            while j < len(APP_JS):
                ch = APP_JS[j]
                if ch == "$" and j + 1 < len(APP_JS) and APP_JS[j + 1] == "{":
                    profundidad += 1
                    buf.append("{x}")
                    j += 2
                    continue
                if profundidad > 0:
                    if ch == "{":
                        profundidad += 1
                    elif ch == "}":
                        profundidad -= 1
                    j += 1
                    continue
                if ch == "`":
                    break
                buf.append(ch)
                j += 1
            caminos.append("".join(buf))
    return caminos


def test_todos_los_endpoints_del_panel_existen(entorno):
    patrones = _rutas_api()
    faltan = []
    for crudo in _extraer_caminos():
        c = crudo.split("?")[0]
        if not c.startswith("/"):
            continue
        candidatos = {c}
        # Una interpolación pegada a texto (ej. la query dinámica de /cuadres)
        # no es un segmento de ruta: también vale el camino sin ella.
        if re.search(r"[^{/]\{x\}|\{x\}[^}/]", c):
            candidatos.add(c.replace("{x}", ""))
        if not any(p.match(cand) for cand in candidatos for p in patrones):
            faltan.append(crudo)
    assert not faltan, f"El panel llama endpoints que no existen: {faltan}"


def test_todos_los_ids_usados_en_js_existen_en_html():
    usados = set(re.findall(r"#([A-Za-z][\w-]*)", APP_JS))
    en_html = set(re.findall(r'id="([\w-]+)"', INDEX))
    faltan = sorted(u for u in usados if u not in en_html)
    assert not faltan, f"app.js usa id que no están en index.html: {faltan}"


def test_botones_del_html_estan_conectados():
    botones = set(re.findall(r'<button[^>]+id="([\w-]+)"', INDEX))
    sin_conectar = sorted(b for b in botones if f'"#{b}"' not in APP_JS and f"#{b}" not in APP_JS)
    assert not sin_conectar, f"Botones sin conectar en app.js: {sin_conectar}"


def test_onclick_del_html_tienen_funcion_en_js():
    funciones = set(re.findall(r'onclick="(\w+)\(', INDEX))
    faltan = sorted(f for f in funciones if f"function {f}(" not in APP_JS)
    assert not faltan, f"onclick sin función en app.js: {faltan}"


def test_clase_seccion_visible_coincide_en_js_css_y_html():
    """La clase que app.js alterna en las secciones debe ser la misma que
    style.css usa para mostrarlas (display:block) y la que index.html trae
    puesta en la sección inicial. (Fallo real 2026-11-14: el JS alternaba
    «activo» y el CSS/HTML usaban «activa»: el menú marcaba el botón pero
    ninguna sección cambiaba.)"""
    CSS = (RAIZ / "apps" / "web" / "style.css").read_text(encoding="utf-8")
    m = re.search(r'\$\$\("\.seccion"\)\.forEach\(\(s\) => s\.classList\.toggle\("(\w+)"', APP_JS)
    assert m, "app.js no alterna ninguna clase en las secciones"
    clase_js = m.group(1)
    m_css = re.search(r"\.seccion\.(\w+)\s*\{\s*display:\s*block", CSS)
    assert m_css, "style.css no tiene regla .seccion.<clase> con display:block"
    assert m_css.group(1) == clase_js, (
        f"La clase visible no coincide: app.js usa «{clase_js}» y style.css «{m_css.group(1)}»")
    assert f'class="seccion {clase_js}"' in INDEX, (
        "index.html no trae la clase visible puesta en la sección inicial")


def test_el_panel_no_tiene_flujo_de_token_de_terminal():
    """Desde 2026-11-14 la terminal entra con usuario y contraseña (orden
    de Jose: «No quiero token… quiero crear el Usuario y que entre al
    programa»). El panel no debe volver a ofrecer crear terminales con
    token ni mostrar la caja del token: ese flujo costó una activación
    perdida el mismo día."""
    for nombre, texto in (("app.js", APP_JS), ("index.html", INDEX)):
        assert "ter-token" not in texto, f"{nombre} aún referencia la caja del token"
        assert "mostrarToken" not in texto, f"{nombre} aún muestra tokens de terminal"
        assert "guardarTerminal" not in texto, f"{nombre} aún crea terminales con token"
    assert "usuario y la contraseña" in INDEX, (
        "La sección Terminales debe explicar la entrada por usuario y contraseña")


def test_panel_y_estaticos_se_sirven(entorno):
    r = entorno.c.get("/")
    assert r.status_code == 200 and "Sistema de Banca Moderna" in r.text
    assert entorno.c.get("/static/app.js").status_code == 200
    assert entorno.c.get("/static/style.css").status_code == 200
    assert entorno.c.get("/health").json()["ok"] is True
