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


def test_html_tiene_viewport_fit_cover_y_pwa(entorno):
    html = entorno.c.get("/").text
    assert "viewport-fit=cover" in html
    assert "manifest.webmanifest" in html
    assert 'id="btn-menu"' in html
    assert 'id="nav-fondo"' in html
    # Módulos administrativos clave accesibles
    for sec in (
        "inicio", "usuarios", "ventas-cajeros", "ganadores", "caja",
        "fondos", "entregas", "reportes", "auditoria", "tickets",
    ):
        assert f'data-sec="{sec}"' in html
        assert f'id="sec-{sec}"' in html
