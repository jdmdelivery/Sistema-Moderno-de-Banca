"""Panel móvil: menú, safe-area, sin overflow de página y módulos accesibles."""


def test_css_iphone_sin_overflow_y_safe_area(entorno):
    css = entorno.c.get("/static/style.css").text
    assert "overflow-x:hidden" in css or "overflow-x: hidden" in css
    assert "safe-area-inset" in css
    assert "100dvh" in css or "env(safe-area-inset-top)" in css
    assert "minmax(0,1fr)" in css or "minmax(0, 1fr)" in css


def test_css_menu_movil_bloquea_scroll_del_dashboard(entorno):
    css = entorno.c.get("/static/style.css").text
    assert "body.menu-abierto" in css
    assert "overscroll-behavior:contain" in css or "overscroll-behavior: contain" in css
    assert "overscroll-behavior:none" in css or "overscroll-behavior: none" in css
    assert "isolation:isolate" in css or "isolation: isolate" in css
    js = entorno.c.get("/static/app.js").text
    assert "bloquearScrollFondo" in js
    assert "menu-abierto" in js
    assert "MENU_SCROLL_Y" in js
    assert "MENU_SCROLL_BLOQUEADO" in js
    assert "onResizeMenu" in js
    # No re-sincronizar menú en cada resize (barra URL móvil provocaba scrollTo(0)).
    assert "sincronizarEstadoMenuInicial();" not in js.split("window.addEventListener(\"resize\"")[1][:120]
    assert "onResizeMenu" in js.split("window.addEventListener(\"resize\"")[1][:80]


def test_html_tiene_viewport_fit_cover_y_pwa(entorno):
    html = entorno.c.get("/").text
    assert "viewport-fit=cover" in html
    assert "manifest.webmanifest" in html
    assert 'id="btn-menu"' in html
    assert 'id="nav-fondo"' in html
    assert 'class="sin-sesion"' in html or "class='sin-sesion'" in html
    # Módulos administrativos clave accesibles
    for sec in (
        "inicio", "usuarios", "ventas-cajeros", "ganadores", "caja",
        "fondos", "entregas", "reportes", "auditoria", "tickets",
    ):
        assert f'data-sec="{sec}"' in html
        assert f'id="sec-{sec}"' in html


def test_login_sin_sesion_oculta_panel(entorno):
    css = entorno.c.get("/static/style.css").text
    js = entorno.c.get("/static/app.js").text
    assert "body.sin-sesion" in css
    assert "body.con-sesion" in css
    assert "z-index:100" in css or "z-index: 100" in css
    assert "pantallaAcceso" in js
    assert "pantallaPanel" in js
    # El overlay de acceso usa fondo opaco, no un velo sobre el Dashboard.
    assert "login-overlay" in css
    assert "background:var(--fondo)" in css or "background: var(--fondo)" in css


def test_dashboard_movil_calendarios_visibles_y_chips(entorno):
    html = entorno.c.get("/").text
    css = entorno.c.get("/static/style.css").text
    js = entorno.c.get("/static/app.js").text
    assert 'id="ini-hoy"' in html and 'id="ini-ayer"' in html and 'id="ini-quince"' in html
    assert 'id="ini-desde"' in html and 'id="ini-hasta"' in html and 'id="ini-consultar"' in html
    # DESDE/HASTA/CONSULTAR visibles también en móvil (ya no solo-escritorio).
    inicio = html.split('id="sec-inicio"')[1].split("</section>")[0]
    assert 'class="inicio-rango"' in inicio or "inicio-rango" in inicio
    assert 'id="ini-desde"' in inicio and "solo-escritorio" not in inicio.split('id="ini-desde"')[0][-80:]
    assert ".solo-escritorio{display:none" in css.replace(" ", "")
    assert "inicio-chips" in css
    assert "inicio-rango" in css
    assert "consultarPeriodo" in js
    assert "HASTA no puede ser anterior a DESDE" in js
    # Dashboard unificado: una sola sección operativa (sin Reales / Separados).
    assert '<h3>PRUEBA</h3>' not in html
    assert "Separados de reales" not in html
    assert '<h3>Reales</h3>' not in inicio
    assert 'id="inicio-operativo"' in html
    assert 'data-bloque="operativo"' in html
    assert "MODO DESARROLLO" not in inicio


def test_usuarios_tarjetas_movil_y_tabla_escritorio(entorno):
    html = entorno.c.get("/").text
    css = entorno.c.get("/static/style.css").text
    js = entorno.c.get("/static/app.js").text
    sw = entorno.c.get("/sw.js").text
    assert 'id="sec-usuarios"' in html
    assert "usu-hero" in html
    assert "ticket-img-local-1" in html  # cache-bust CSS/JS
    assert "tarjetaUsuarioHtml" in js
    assert "pintarUsuarios" in js and "esUsuariosMovil" in js
    assert "usu-lista-movil" in js and "usu-tabla-escritorio" in js
    assert "htmlAccionesUsuario" in js
    assert "editarUsuario(" in js and "bloquearUsuario(" in js
    assert "desbloquearUsuario(" in js and "eliminarUsuario(" in js
    # En móvil solo se montan tarjetas (sin tabla en el DOM).
    assert 'data-vista="movil"' in js
    assert 'data-vista="escritorio"' in js
    # Sin IDs duplicados de formulario; acciones reutilizan handlers globales.
    assert js.count('id="usu-id"') == 0
    assert "usu-lista-movil" in css and "usu-card" in css
    compact = css.replace(" ", "").replace("\r", "")
    # Mobile-first: tarjetas visibles por defecto; tabla solo ≥901px.
    assert ".usu-lista-movil{display:flex" in compact
    assert ".usu-tabla-escritorio{display:none!important}" in compact
    assert "@media(min-width:901px)" in compact
    assert "banca-admin-shell-v5-ticket-img-local" in sw


def test_fuente_resultados_es_conectate(entorno):
    html = entorno.c.get("/").text
    js = entorno.c.get("/static/app.js").text
    assert "Fuente: Conéctate.com" in html
    assert "Consultando Conéctate.com" in js
    assert "Consultando RDLotto" not in js
    assert "La fuente es RDLotto" not in html
    r = entorno.c.get("/fuente-resultados", headers=entorno.admin)
    assert r.status_code == 200
    datos = r.json()
    assert datos["fuente"] == "conectate"
    assert datos["nombre_fuente"] == "Conéctate.com"
    assert "conectate.com" in (datos.get("url") or "").lower()
    assert datos["trabajador"]["fuente"] == "conectate"
