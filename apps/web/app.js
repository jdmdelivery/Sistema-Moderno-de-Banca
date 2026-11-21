"use strict";
/* Panel del Consorcio — Sistema de Banca Moderna.
   Regla de oro: ningún botón decorativo; cada acción llama a su endpoint
   real y muestra lo que el servidor respondió. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
let TOKEN = localStorage.getItem("lot_token") || "";
let YO = null;
let SUCURSALES = [], SORTEOS = [], TIPOS = [], TERMINALES = [];
let RESULTADO_ACTUAL = null;

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}),
      ...(opts.headers || {}),
    },
  });
  const texto = await r.text();
  let datos;
  try { datos = JSON.parse(texto); } catch { datos = texto; }
  if (!r.ok) throw new Error((datos && datos.detail) || texto || ("Error " + r.status));
  return datos;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const put = (path, body) => api(path, { method: "PUT", body: JSON.stringify(body || {}) });
const del = (path) => api(path, { method: "DELETE" });

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmt(n) { return "$" + Number(n || 0).toLocaleString("es-DO", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function hoyISO() {
  const d = new Date();
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function msg(id, texto, ok = true) {
  const el = $(id);
  el.textContent = texto;
  el.className = "msg " + (ok ? "ok" : "error");
}
function tabla(el, columnas, filas) {
  const destino = typeof el === "string" ? $(el) : el;
  if (!filas.length) { destino.innerHTML = '<p class="nota">Sin datos.</p>'; return; }
  destino.innerHTML = '<div class="tabla-scroll"><table><thead><tr>' + columnas.map((c) => `<th>${esc(c)}</th>`).join("") +
    "</tr></thead><tbody>" + filas.join("") + "</tbody></table></div>";
}
function opciones(lista, valor, texto, extra = "") {
  return extra + lista.map((x) => `<option value="${esc(valor(x))}">${esc(texto(x))}</option>`).join("");
}

/* ------------------------------------------------------------------ sesión */
function pantallaAcceso() {
  document.body.classList.add("sin-sesion");
  document.body.classList.remove("con-sesion");
  cerrarMenuMovil();
  document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
  BLOQUEO_MODAL = 0;
  document.documentElement.classList.remove("modal-abierto");
  document.body.classList.remove("modal-abierto");
  if (!MENU_SCROLL_BLOQUEADO) document.body.style.top = "";
  const login = $("#login");
  if (login) {
    login.style.display = "";
    login.removeAttribute("hidden");
  }
}

function pantallaPanel() {
  document.body.classList.remove("sin-sesion");
  document.body.classList.add("con-sesion");
  const login = $("#login");
  if (login) {
    login.style.display = "none";
    login.setAttribute("hidden", "");
  }
}

function esSuperAdmin() { return !!(YO && YO.rol === "super_admin"); }
function esAdminPanel() { return !!(YO && (YO.rol === "admin" || YO.rol === "super_admin")); }
function adminSucursalRestringido() {
  return !!(YO && YO.rol === "admin" && YO.compat_global === false);
}
/** Secciones de consorcio: solo JDMCASHNOW (Super Admin). */
const SECCIONES_SOLO_SUPER = new Set(["super", "terminales", "sorteos", "resultados", "fuente", "auditoria"]);
function puedeVerSeccion(sec) {
  if (!sec) return false;
  if (SECCIONES_SOLO_SUPER.has(sec)) return esSuperAdmin();
  if (sec === "diseno-ticket") return esAdminPanel();
  return true;
}
function sincronizarCentroVentas(secActiva) {
  const sub = document.querySelector('.nav-sub[data-sub="centro-ventas"]');
  if (!sub) return;
  const enlaces = [...sub.querySelectorAll(".navbtn")];
  let visibles = 0;
  for (const boton of enlaces) {
    const permitido = puedeVerSeccion(boton.dataset.sec);
    boton.hidden = !permitido;
    if (permitido) visibles += 1;
  }
  sub.hidden = visibles === 0;
  const sec = secActiva || (typeof SECCION_ACTIVA !== "undefined" ? SECCION_ACTIVA : "");
  if (!enlaces.some((boton) => boton.dataset.sec === sec && !boton.hidden)) return;
  sub.classList.add("abierto");
  const titulo = sub.querySelector(".nav-sub-titulo");
  if (titulo) titulo.setAttribute("aria-expanded", "true");
}
function etiquetaRol(rol) {
  return ({ super_admin: "Super Admin", admin: "Administrador", supervisor: "Supervisor", operador: "Operador" })[rol] || rol;
}
function nombreSucursalActual() {
  if (!YO || !YO.sucursal_id) return "";
  const s = (typeof SUCURSALES !== "undefined" ? SUCURSALES : []).find((x) => Number(x.id) === Number(YO.sucursal_id));
  return s ? (s.nombre || s.codigo || "") : "";
}
function actualizarEncabezadoContexto() {
  const subMarca = $("#marca-sub");
  const chip = $("#yo-sucursal");
  const side = $("#sidebar-contexto");
  const sucNombre = nombreSucursalActual();
  if (esSuperAdmin()) {
    if (subMarca) subMarca.textContent = "Super Admin · Consorcio";
    if (side) side.textContent = "JDMCASHNOW · Consorcio";
    if (chip) { chip.hidden = true; chip.textContent = ""; }
  } else if (adminSucursalRestringido() || (YO && YO.rol === "admin")) {
    if (subMarca) subMarca.textContent = "Admin de sucursal";
    if (side) side.textContent = (YO && YO.nombre ? YO.nombre : "Administrador") + (sucNombre ? " · " + sucNombre : "");
    if (chip) {
      chip.hidden = !sucNombre;
      chip.textContent = sucNombre || "";
    }
  } else {
    if (subMarca) subMarca.textContent = "Panel del Consorcio";
    if (side) side.textContent = "Administración";
    if (chip) { chip.hidden = true; chip.textContent = ""; }
  }
}
function aplicarVisibilidadRol() {
  $$("[data-solo-super]").forEach((el) => {
    el.hidden = !esSuperAdmin();
  });
  $$("[data-solo-admin]").forEach((el) => {
    el.hidden = !esAdminPanel();
  });
  const grupoConsorcio = document.querySelector('.nav-grupo[data-grupo="consorcio"]');
  if (grupoConsorcio) grupoConsorcio.hidden = !esSuperAdmin();
  const superBtn = $("#nav-super");
  if (superBtn) superBtn.hidden = !esSuperAdmin();
  mostrarFondo(esAdminPanel());
  const formEdicion = $("#suc-form-edicion");
  const formRecarga = $("#suc-form-recarga");
  const puedeGestionSuc = esSuperAdmin() || !!(YO && YO.rol === "admin" && YO.compat_global !== false);
  if (formEdicion) formEdicion.hidden = !puedeGestionSuc;
  if (formRecarga) formRecarga.hidden = !esAdminPanel();
  const notaSuc = $("#suc-alcance-nota");
  if (notaSuc) {
    if (adminSucursalRestringido()) {
      notaSuc.hidden = false;
      notaSuc.textContent = "Panel de su sucursal: solo ve empleados y operaciones de su banca. Crear bancas nuevas es exclusivo de JDMCASHNOW.";
    } else if (esSuperAdmin()) {
      notaSuc.hidden = false;
      notaSuc.textContent = "Super Admin: control total de sucursales, administradores y aprobación de cajeros.";
    } else {
      notaSuc.hidden = true;
    }
  }
  const rolSuper = $("#usu-rol-super");
  if (rolSuper) rolSuper.hidden = !esSuperAdmin();
  const selRol = $("#usu-rol");
  if (selRol && adminSucursalRestringido()) {
    [...selRol.options].forEach((opt) => {
      opt.hidden = !["operador", "supervisor"].includes(opt.value);
    });
    if (!["operador", "supervisor"].includes(selRol.value)) selRol.value = "operador";
  } else if (selRol && !esSuperAdmin()) {
    [...selRol.options].forEach((opt) => {
      opt.hidden = opt.value === "super_admin";
    });
  }
  const notaUsu = $("#usu-alcance-nota");
  if (notaUsu) {
    if (adminSucursalRestringido()) {
      notaUsu.hidden = false;
      notaUsu.textContent = "Los cajeros nuevos quedan PENDIENTES hasta que JDMCASHNOW los apruebe. No puede crear administradores de otras bancas.";
      if (YO.sucursal_id) {
        $("#usu-sucursal").value = String(YO.sucursal_id);
        $("#usu-sucursal").disabled = true;
      }
    } else {
      notaUsu.hidden = true;
      if ($("#usu-sucursal")) $("#usu-sucursal").disabled = false;
    }
  }
  actualizarEncabezadoContexto();
  sincronizarCentroVentas();
  const subLogin = document.querySelector("#login .sub");
  if (subLogin && !TOKEN) subLogin.textContent = "Panel del Consorcio";
  // Desktop: menú abierto; móvil: cerrado.
  sincronizarEstadoMenuInicial();
}

async function entrar() {
  try {
    const r = await post("/auth/login", { usuario: $("#login-usuario").value.trim(), clave: $("#login-clave").value });
    TOKEN = r.token; YO = r.usuario;
    localStorage.setItem("lot_token", TOKEN);
    $("#yo-nombre").textContent = `${YO.nombre} (${etiquetaRol(YO.rol)})`;
    aplicarVisibilidadRol();
    pantallaPanel();
    await cargarCatalogos();
    ir(esSuperAdmin() ? "super" : "inicio");
  } catch (e) { msg("#login-msg", e.message, false); }
}
async function salir() {
  try { await post("/auth/logout"); } catch {}
  TOKEN = ""; YO = null;
  localStorage.removeItem("lot_token");
  pantallaAcceso();
  location.reload();
}
async function restaurarSesion() {
  if (!TOKEN) {
    pantallaAcceso();
    return;
  }
  try {
    YO = await api("/auth/yo");
    $("#yo-nombre").textContent = `${YO.nombre} (${etiquetaRol(YO.rol)})`;
    aplicarVisibilidadRol();
    pantallaPanel();
    await cargarCatalogos();
    ir(esSuperAdmin() ? "super" : "inicio");
  } catch {
    TOKEN = "";
    localStorage.removeItem("lot_token");
    pantallaAcceso();
  }
}

/* --------------------------------------------------------------------- nav */
let GANADORES_RELOJ = null;
let MENU_SCROLL_Y = 0;
let MENU_SCROLL_BLOQUEADO = false;
let MENU_ES_ESCRITORIO = null;
let USUARIOS_ES_MOVIL = null;
let SECCION_ACTIVA = "inicio";

function esEscritorioMenu() {
  return window.matchMedia("(min-width: 901px)").matches;
}
/** Misma frontera que el menú: <901px = teléfono/tablet (tarjetas). */
function esUsuariosMovil() {
  return !esEscritorioMenu();
}

/** Bloquea el scroll del Dashboard detrás del menú móvil (Safari iPhone).
 *  Solo restaura scrollTo cuando realmente se desbloqueó el fondo.
 *  No debe ejecutarse en cada resize (barra URL iOS/Android). */
function bloquearScrollFondo(activo) {
  if (esEscritorioMenu()) {
    if (MENU_SCROLL_BLOQUEADO) {
      document.documentElement.classList.remove("menu-abierto");
      document.body.classList.remove("menu-abierto");
      document.body.style.top = "";
      MENU_SCROLL_BLOQUEADO = false;
    }
    return;
  }
  if (activo) {
    if (MENU_SCROLL_BLOQUEADO) return;
    if (document.body.classList.contains("modal-abierto")) {
      MENU_SCROLL_Y = SCROLL_MODAL_Y;
    } else {
      MENU_SCROLL_Y = window.scrollY || window.pageYOffset || 0;
      document.body.style.top = "-" + MENU_SCROLL_Y + "px";
    }
    document.documentElement.classList.add("menu-abierto");
    document.body.classList.add("menu-abierto");
    MENU_SCROLL_BLOQUEADO = true;
  } else {
    if (!MENU_SCROLL_BLOQUEADO) return;
    document.documentElement.classList.remove("menu-abierto");
    document.body.classList.remove("menu-abierto");
    MENU_SCROLL_BLOQUEADO = false;
    if (BLOQUEO_MODAL > 0) return;
    document.body.style.top = "";
    const y = MENU_SCROLL_Y;
    window.requestAnimationFrame(() => window.scrollTo(0, y));
  }
}

let BLOQUEO_MODAL = 0;
let SCROLL_MODAL_Y = 0;
const HIST_SCROLL = {};

let SCROLL_OBJETIVO = null;
let SCROLL_VIGILAR_HASTA = 0;

function fijarScroll(y) {
  SCROLL_OBJETIVO = y || 0;
  SCROLL_VIGILAR_HASTA = performance.now() + 600;
  window.scrollTo(0, SCROLL_OBJETIVO);
}

window.addEventListener("scroll", () => {
  if (SCROLL_OBJETIVO == null || performance.now() > SCROLL_VIGILAR_HASTA) {
    SCROLL_OBJETIVO = null;
    return;
  }
  if (document.body.classList.contains("modal-abierto") || document.body.classList.contains("menu-abierto")) return;
  if (Math.abs(window.scrollY - SCROLL_OBJETIVO) > 2) window.scrollTo(0, SCROLL_OBJETIVO);
}, { passive: true });

function scrollDePagina() {
  if (document.body.classList.contains("modal-abierto")) return SCROLL_MODAL_Y;
  if (MENU_SCROLL_BLOQUEADO) return MENU_SCROLL_Y;
  return window.scrollY || window.pageYOffset || 0;
}

function adquirirBloqueoModal() {
  SCROLL_OBJETIVO = null;
  BLOQUEO_MODAL += 1;
  if (BLOQUEO_MODAL > 1) return;
  if (!MENU_SCROLL_BLOQUEADO) {
    SCROLL_MODAL_Y = window.scrollY || window.pageYOffset || 0;
    document.body.style.top = "-" + SCROLL_MODAL_Y + "px";
  } else {
    SCROLL_MODAL_Y = MENU_SCROLL_Y;
  }
  document.documentElement.classList.add("modal-abierto");
  document.body.classList.add("modal-abierto");
}

function soltarBloqueoModal() {
  BLOQUEO_MODAL = Math.max(0, BLOQUEO_MODAL - 1);
  if (BLOQUEO_MODAL > 0) return;
  document.documentElement.classList.remove("modal-abierto");
  document.body.classList.remove("modal-abierto");
  if (MENU_SCROLL_BLOQUEADO) return;
  document.body.style.top = "";
  const y = SCROLL_MODAL_Y;
  window.requestAnimationFrame(() => fijarScroll(y));
}

function modalVisible() {
  const lista = document.querySelectorAll(".modal:not([hidden])");
  return lista.length ? lista[lista.length - 1] : null;
}

function abrirModal(el) {
  if (!el || !el.hidden) return;
  adquirirBloqueoModal();
  const prof = (history.state && history.state.prof) || 0;
  history.pushState({
    sec: SECCION_ACTIVA,
    modal: el.id,
    prof: prof + 1,
  }, "", urlHistorial(SECCION_ACTIVA, "ventana-" + el.id));
  el.hidden = false;
  el.querySelectorAll(".modal-cuerpo").forEach((cuerpo) => { cuerpo.scrollTop = 0; });
}

function cerrarModal(el, desdeHistorial) {
  if (!el || el.hidden) return;
  el.hidden = true;
  soltarBloqueoModal();
  if (!desdeHistorial && history.state && history.state.modal === el.id) history.back();
}

function urlHistorial(sec, extra) {
  const base = location.pathname + location.search;
  let hash = "#/" + (sec || "inicio");
  if (extra) hash += "/" + extra;
  return base + hash;
}

function asegurarHistorial() {
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  if (!history.state || history.state.sec == null) {
    history.replaceState({
      sec: SECCION_ACTIVA || "inicio",
      prof: 0,
    }, "", urlHistorial(SECCION_ACTIVA || "inicio"));
  }
}

function casaDelRol() {
  return typeof esSuperAdmin === "function" && esSuperAdmin() ? "super" : "inicio";
}

function actualizarBarraVolver() {
  const btn = $("#btn-volver-pantalla");
  if (!btn) return;
  const enCasa = SECCION_ACTIVA === casaDelRol();
  const detalleTicket = SECCION_ACTIVA === "reporte-tickets" && RTK && RTK.detalle;
  btn.hidden = enCasa && !detalleTicket;
}

function volverPantalla() {
  if (SECCION_ACTIVA === "reporte-tickets" && RTK && RTK.detalle) {
    if (history.state && history.state.detalle) history.back();
    else volverListadoTickets(true);
    return;
  }
  if (history.state && history.state.prof > 0) history.back();
  else ir(casaDelRol(), { desdeHistorial: true, y: HIST_SCROLL[casaDelRol()] || 0 });
}

function alRetroceder(ev) {
  const st = ev.state || {};
  const abierto = modalVisible();
  if (abierto && st.modal !== abierto.id) {
    cerrarModal(abierto, true);
    return;
  }
  if (typeof RTK !== "undefined" && RTK.detalle && !st.detalle) {
    volverListadoTickets(true);
    return;
  }
  if (st.sec && st.sec !== SECCION_ACTIVA) {
    ir(st.sec, { desdeHistorial: true, y: HIST_SCROLL[st.sec] || 0 });
    return;
  }
  actualizarBarraVolver();
}

let TOQUE_Y = 0;
document.addEventListener("touchstart", (ev) => {
  if (ev.touches && ev.touches[0]) TOQUE_Y = ev.touches[0].clientY;
}, { passive: true });
document.addEventListener("touchmove", (ev) => {
  const bloqueado = document.body.classList.contains("modal-abierto") || document.body.classList.contains("menu-abierto");
  if (!bloqueado) return;
  const destino = ev.target && ev.target.closest ? ev.target.closest(".modal-cuerpo, nav.sidebar") : null;
  const y = ev.touches && ev.touches[0] ? ev.touches[0].clientY : TOQUE_Y;
  const dy = y - TOQUE_Y;
  TOQUE_Y = y;
  if (!destino) { ev.preventDefault(); return; }
  const max = destino.scrollHeight - destino.clientHeight;
  if (max <= 1) { ev.preventDefault(); return; }
  if (dy > 0 && destino.scrollTop <= 0) ev.preventDefault();
  else if (dy < 0 && destino.scrollTop >= max - 1) ev.preventDefault();
}, { passive: false });

function sincronizarViewport() {
  const vv = window.visualViewport;
  if (!vv) return;
  document.documentElement.style.setProperty("--vv-alto", Math.round(vv.height) + "px");
}
if (window.visualViewport) {
  visualViewport.addEventListener("resize", sincronizarViewport);
  visualViewport.addEventListener("scroll", sincronizarViewport);
  sincronizarViewport();
}

function setMenuAbierto(abierto) {
  const nav = $("#nav");
  const fondo = $("#nav-fondo");
  const btn = $("#btn-menu");
  if (!nav) return;
  nav.classList.toggle("abierto", !!abierto);
  document.body.classList.toggle("sidebar-colapsado", esEscritorioMenu() && !abierto);
  if (fondo) {
    const showFondo = !!abierto && !esEscritorioMenu();
    fondo.classList.toggle("abierto", showFondo);
    fondo.hidden = !showFondo;
  }
  if (btn) btn.setAttribute("aria-expanded", abierto ? "true" : "false");
  bloquearScrollFondo(!!abierto && !esEscritorioMenu());
}
function cerrarMenuMovil() {
  if (esEscritorioMenu()) return;
  setMenuAbierto(false);
}
function alternarMenuMovil() {
  const nav = $("#nav");
  if (!nav) return;
  setMenuAbierto(!nav.classList.contains("abierto"));
}
function sincronizarEstadoMenuInicial() {
  if (!TOKEN) {
    setMenuAbierto(false);
    MENU_ES_ESCRITORIO = esEscritorioMenu();
    return;
  }
  // Celular: cerrado. Escritorio: abierto.
  MENU_ES_ESCRITORIO = esEscritorioMenu();
  setMenuAbierto(MENU_ES_ESCRITORIO);
}
/** Solo reacciona al cruzar el breakpoint; ignora resize de barra URL al scroll. */
function onResizeMenu() {
  const ahoraEscritorio = esEscritorioMenu();
  const ahoraUsuMovil = esUsuariosMovil();
  if (TOKEN && MENU_ES_ESCRITORIO !== ahoraEscritorio) {
    MENU_ES_ESCRITORIO = ahoraEscritorio;
    sincronizarEstadoMenuInicial();
  } else if (MENU_ES_ESCRITORIO === null) {
    MENU_ES_ESCRITORIO = ahoraEscritorio;
  }
  // Re-pintar Usuarios solo al cruzar móvil↔escritorio (no en cada hide/show de barra URL).
  if (USUARIOS_ES_MOVIL !== ahoraUsuMovil) {
    USUARIOS_ES_MOVIL = ahoraUsuMovil;
    if (TOKEN && SECCION_ACTIVA === "usuarios" && window._usuarios) {
      const y = window.scrollY || window.pageYOffset || 0;
      pintarUsuarios(window._usuarios, esAdminPanel());
      window.requestAnimationFrame(() => window.scrollTo(0, y));
    }
  }
}
function ir(sec, opts) {
  opts = opts || {};
  asegurarHistorial();
  if (!puedeVerSeccion(sec)) {
    sec = esSuperAdmin() ? "super" : "inicio";
  }
  const anterior = SECCION_ACTIVA;
  if (opts.desdeHistorial) {
    if (sec !== anterior) {
      if (GANADORES_RELOJ) {
        clearInterval(GANADORES_RELOJ);
        GANADORES_RELOJ = null;
      }
      cerrarMenuMovil();
      SECCION_ACTIVA = sec;
      $$(".navbtn").forEach((b) => b.classList.toggle("activo", b.dataset.sec === sec));
      sincronizarCentroVentas(sec);
      $$(".seccion").forEach((s) => s.classList.toggle("activo", s.id === "sec-" + sec));
    }
    window.requestAnimationFrame(() => fijarScroll(opts.y || 0));
    actualizarBarraVolver();
    return;
  }
  if (anterior && anterior !== sec) {
    HIST_SCROLL[anterior] = scrollDePagina();
  }
  if (GANADORES_RELOJ) {
    clearInterval(GANADORES_RELOJ);
    GANADORES_RELOJ = null;
  }
  cerrarMenuMovil();
  SECCION_ACTIVA = sec;
  $$(".navbtn").forEach((b) => b.classList.toggle("activo", b.dataset.sec === sec));
  sincronizarCentroVentas(sec);
  $$(".seccion").forEach((s) => s.classList.toggle("activo", s.id === "sec-" + sec));
  const cargar = {
    inicio: cargarInicio, super: cargarSuperAdmin, sucursales: cargarSucursales, terminales: cargarTerminales,
    usuarios: cargarUsuarios, "ventas-cajeros": cargarVentasCajeros,
    "control-cajeros": cargarControlCajeros,
    sorteos: cargarSorteos, tabla: cargarTabla,
    limites: cargarLimites, resultados: cargarResultados, tickets: cargarTicketsLista,
    fuente: cargarFuente, ganadores: cargarGanadores,
    caja: cargarCaja, entregas: cargarEntregas, fondos: cargarFondos, comisiones: cargarComisiones,
    reportes: cargarReportes, "ventas-resumido": cargarVentasResumido,
    "reporte-tickets": cargarReporteTickets,
    auditoria: async () => {},
    "diseno-ticket": cargarDisenoTicket,
  }[sec];
  if (!opts.desdeHistorial && anterior !== sec) {
    const prof = (history.state && history.state.prof) || 0;
    history.pushState({ sec: sec, prof: prof + 1 }, "", urlHistorial(sec));
  }
  const yDestino = opts.desdeHistorial ? (opts.y || 0) : 0;
  const llevar = () => fijarScroll(yDestino);
  if (sec === "ventas-resumido") {
    const visorVentas = document.getElementById("rvr-visor");
    if (visorVentas && !visorVentas.hidden) rvrMarcarVisor(true);
  } else {
    rvrMarcarVisor(false);
  }
  window.requestAnimationFrame(llevar);
  if (cargar) cargar().then(llevar).catch((e) => console.error(e));
  actualizarBarraVolver();
}

/* ----------------------------------------------------------- Super Admin UI */
const SUPER_PERM_CAMPOS = [
  ["puede_crear_cajeros", "Crear cajeros"],
  ["puede_asignar_fondos", "Asignar fondos"],
  ["puede_registrar_entregas", "Registrar entregas"],
  ["puede_ajustar_caja", "Ajustar caja"],
  ["puede_configurar_limites", "Configurar límites"],
  ["puede_anular_tickets", "Anular tickets"],
  ["puede_ver_reportes", "Ver reportes"],
];

async function cargarSuperAdmin() {
  if (!esSuperAdmin()) {
    $("#super-estado").textContent = "Solo JDMCASHNOW (Super Admin) puede ver este panel.";
    return;
  }
  const resumen = await api("/super/resumen");
  const pendientes = await api("/super/cajeros-pendientes");
  const modo = resumen.compat_global
    ? (resumen.compat_global_forzado
      ? "Compat global FORZADO (aislamiento aún no activo)."
      : "Compat global activo (aún no hay aislamiento).")
    : "Aislamiento activo: cada admin solo ve su sucursal.";
  $("#super-estado").textContent =
    `${modo} Cajeros pendientes: ${resumen.cajeros_pendientes_total}. Sucursales: ${resumen.sucursales.length}.`;
  tabla("#super-pendientes",
    ["Nombre", "Usuario", "Sucursal", "Caja", "Acciones"],
    pendientes.map((u) => {
      const suc = SUCURSALES.find((s) => s.id === u.sucursal_id);
      return `<tr><td>${esc(u.nombre)}</td><td>${esc(u.usuario)}</td>
        <td>${esc(suc ? suc.nombre : "—")}</td><td>${fmt(u.saldo_caja)}</td>
        <td><div class="acciones-fila">
          <button class="btn fila primario" data-aprobar="${u.id}">APROBAR</button>
          <button class="btn fila peligro" data-rechazar="${u.id}">RECHAZAR</button>
        </div></td></tr>`;
    }));
  document.querySelectorAll("[data-aprobar]").forEach((b) => {
    b.addEventListener("click", () => aprobarCajeroSuper(b.dataset.aprobar));
  });
  document.querySelectorAll("[data-rechazar]").forEach((b) => {
    b.addEventListener("click", () => rechazarCajeroSuper(b.dataset.rechazar));
  });
  tabla("#super-sucursales",
    ["Código", "Nombre", "Saldo", "Admins", "Cajeros OK", "Pendientes", "Estado"],
    (resumen.sucursales || []).map((s) => {
      const admins = (s.admins || []).map((a) => a.usuario).join(", ") || "—";
      return `<tr><td>${esc(s.codigo)}</td><td>${esc(s.nombre)}</td><td>${fmt(s.saldo_actual)}</td>
        <td>${esc(admins)}</td><td>${s.cajeros_activos}</td><td>${s.cajeros_pendientes}</td>
        <td>${s.activa ? "Activa" : "Inactiva"}</td></tr>`;
    }));
  const sel = $("#super-perm-sucursal");
  if (sel) {
    const prev = sel.value;
    sel.innerHTML = opciones(resumen.sucursales || [], (s) => s.id, (s) => `${s.codigo} — ${s.nombre}`);
    if (prev) sel.value = prev;
  }
}

async function aprobarCajeroSuper(id) {
  try {
    await post(`/super/cajeros/${id}/aprobar`);
    msg("#super-msg", "Cajero aprobado. Ya puede entrar en SUNMI.");
    await cargarSuperAdmin();
  } catch (e) { msg("#super-msg", e.message, false); }
}
async function rechazarCajeroSuper(id) {
  const motivo = prompt("Motivo del rechazo (opcional):") || "";
  if (motivo === null) return;
  try {
    await post(`/super/cajeros/${id}/rechazar`, { motivo: motivo || null });
    msg("#super-msg", "Cajero rechazado.");
    await cargarSuperAdmin();
  } catch (e) { msg("#super-msg", e.message, false); }
}
async function cargarPermisosSuper() {
  const id = $("#super-perm-sucursal").value;
  if (!id) return;
  const p = await api(`/super/permisos-sucursal/${id}`);
  $("#super-permisos").innerHTML = SUPER_PERM_CAMPOS.map(([k, lbl]) =>
    `<label class="check"><input type="checkbox" data-perm="${k}" ${p[k] ? "checked" : ""}> ${esc(lbl)}</label>`
  ).join("");
}
async function guardarPermisosSuper() {
  const id = $("#super-perm-sucursal").value;
  if (!id) return;
  const body = {};
  SUPER_PERM_CAMPOS.forEach(([k]) => {
    const el = document.querySelector(`[data-perm="${k}"]`);
    body[k] = !!(el && el.checked);
  });
  try {
    await put(`/super/permisos-sucursal/${id}`, body);
    msg("#super-perm-msg", "Permisos guardados ✔");
    await cargarSuperAdmin();
  } catch (e) { msg("#super-perm-msg", e.message, false); }
}

async function cargarCatalogos() {
  const base = await Promise.all([
    api("/sucursales"), api("/sorteos"), api("/tipos-jugada"),
  ]);
  SUCURSALES = base[0];
  SORTEOS = base[1];
  TIPOS = base[2];
  try {
    TERMINALES = await api("/terminales");
  } catch {
    TERMINALES = [];
  }
  const suc = (extra) => opciones(SUCURSALES, (s) => s.id, (s) => `${s.codigo} — ${s.nombre}`, extra || "");
  $("#rec-sucursal").innerHTML = suc();
  $("#mov-sucursal").innerHTML = suc();
  $("#tic-sucursal").innerHTML = suc();
  $("#caj-sucursal").innerHTML = suc();
  $("#pen-sucursal").innerHTML = suc();
  const entSucursal = document.querySelector("#ent-sucursal");
  if (entSucursal) entSucursal.innerHTML = suc('<option value="">Según mi permiso</option>');
  $("#rep-sucursal").innerHTML = suc('<option value="">Todas las sucursales</option>');
  $("#usu-sucursal").innerHTML = suc('<option value="">— Sin sucursal —</option>');
  const sor = opciones(SORTEOS, (s) => s.id, (s) => s.nombre);
  const ganSorteo = document.querySelector("#gan-sorteo");
  if (ganSorteo) ganSorteo.innerHTML = opciones(SORTEOS, (s) => s.id, (s) => s.nombre, '<option value="">Todas</option>');
  const ganSucursal = document.querySelector("#gan-sucursal");
  if (ganSucursal) ganSucursal.innerHTML = suc('<option value="">Todas</option>');
  const limLoteria = document.querySelector("#lim-qn-loteria");
  if (limLoteria) {
    const todas = opciones(SORTEOS, (s) => s.id, (s) => s.nombre, '<option value="0">TODAS LAS LOTERÍAS</option>');
    limLoteria.innerHTML = todas;
    $("#lim-pl-loteria").innerHTML = todas;
    $("#lim-tr-loteria").innerHTML = todas;
    $("#lim-sp-loteria1").innerHTML = todas;
    $("#lim-sp-loteria2").innerHTML = todas;
  }
  $("#res-sorteo").innerHTML = sor;
  const tip = opciones(TIPOS, (t) => t.codigo, (t) => `${t.codigo} — ${t.nombre}`);
  $("#tab-tipo").innerHTML = tip;
  $("#caj-terminal").innerHTML = opciones(
    TERMINALES, (t) => t.id, (t) => `${t.sucursal} · Terminal ${t.numero_terminal}`, '<option value="">— Todas / ninguna —</option>');
  actualizarClavesTabla();
  actualizarEncabezadoContexto();
}

/* ------------------------------------------------------------------- inicio */
let INICIO_HOY = null;

function sumarDias(iso, dias) {
  const [anio, mes, dia] = iso.split("-").map(Number);
  const fecha = new Date(Date.UTC(anio, mes - 1, dia));
  fecha.setUTCDate(fecha.getUTCDate() + dias);
  const p = (x) => String(x).padStart(2, "0");
  return `${fecha.getUTCFullYear()}-${p(fecha.getUTCMonth() + 1)}-${p(fecha.getUTCDate())}`;
}

function tarjetasInicio(bloque) {
  const etiquetaPendientes = esSuperAdmin()
    ? "Premios pendientes (alcance)"
    : (esAdminPanel() ? "Premios pendientes sucursal" : "Premios por pagar (míos)");
  // Dashboard RESUMEN: sin tarjeta Comisión (el cálculo sigue en API/perfil).
  const filas = [
    [fmt(bloque.ventas), "Ventas"],
    [bloque.tickets, "Tickets vendidos"],
    [fmt(bloque.premios_pagados), "Premios pagados"],
    [fmt(bloque.premios_pendientes), etiquetaPendientes],
    [fmt(bloque.neto), "Neto"],
  ];
  return filas.map(([n, l]) => `<div class="card"><div class="num">${esc(n)}</div><div class="lbl">${esc(l)}</div></div>`).join("");
}

function marcarChipInicio(tipo) {
  document.querySelectorAll("#sec-inicio .inicio-chips .btn").forEach((b) => {
    b.classList.toggle("activo", !!tipo && b.dataset.rango === tipo);
  });
}

async function cargarInicio(desde, hasta, chip) {
  if (!desde && !hasta && $("#ini-desde").value && $("#ini-hasta").value) {
    desde = $("#ini-desde").value;
    hasta = $("#ini-hasta").value;
  }
  if (desde && hasta && hasta < desde) {
    msg("#inicio-msg", "HASTA no puede ser anterior a DESDE", false);
    return;
  }
  const q = new URLSearchParams();
  if (desde) q.set("desde", desde);
  if (hasta) q.set("hasta", hasta);
  const r = await api("/reportes/inicio" + (q.toString() ? `?${q}` : ""));
  INICIO_HOY = r.hoy;
  $("#ini-desde").value = r.desde;
  $("#ini-hasta").value = r.hasta;
  $("#inicio-periodo").textContent = `${r.desde} → ${r.hasta} · ${r.zona}`;
  // Una sola fila: ledger operativo (prueba si MODO_DESARROLLO, si no reales). No suma ambos.
  const operativo = r.operativo || (r.modo_desarrollo ? r.prueba : r.reales) || r.reales;
  $("#inicio-operativo").innerHTML = tarjetasInicio(operativo);
  if (chip !== undefined) marcarChipInicio(chip || null);
  else if (!desde && !hasta) marcarChipInicio("hoy");
  msg("#inicio-msg", "");
}

function consultarPeriodo(tipo) {
  const hoy = INICIO_HOY || hoyISO();
  const rango = tipo === "ayer"
    ? [sumarDias(hoy, -1), sumarDias(hoy, -1)]
    : tipo === "quince"
      ? [sumarDias(hoy, -14), hoy]
      : [hoy, hoy];
  return cargarInicio(rango[0], rango[1], tipo);
}

/* --------------------------------------------------------------- sucursales */
async function cargarSucursales() {
  await cargarCatalogos();
  tabla("#suc-tabla", ["Código", "Nombre", "Comisión %", "Caja general", "Cajas de cajeras (informativo)", "Activa", "Acciones"],
    SUCURSALES.map((s) => {
      const c = s.consolidado_cajas;
      const info = c
        ? `Prueba ${fmt(c.cajas_prueba)} · Real ${fmt(c.cajas_reales)}`
        : "—";
      return `<tr><td>${esc(s.codigo)}</td><td>${esc(s.nombre)}</td><td>${esc(s.comision_porcentaje)}</td>
      <td>${fmt(s.saldo_actual)}</td><td>${info}</td><td>${s.activa ? "Sí" : "No"}</td>
      <td><button class="btn fila" onclick="editarSucursal(${s.id})">Editar</button></td></tr>`;
    }));
}
function editarSucursal(id) {
  const s = SUCURSALES.find((x) => x.id === id); if (!s) return;
  $("#suc-id").value = s.id; $("#suc-codigo").value = s.codigo; $("#suc-nombre").value = s.nombre;
  $("#suc-direccion").value = s.direccion || ""; $("#suc-telefono").value = s.telefono || "";
  $("#suc-comision").value = s.comision_porcentaje; $("#suc-activa").checked = s.activa;
}
function limpiarSucursal() {
  ["#suc-id", "#suc-codigo", "#suc-nombre", "#suc-direccion", "#suc-telefono"].forEach((i) => $(i).value = "");
  $("#suc-comision").value = 10; $("#suc-activa").checked = true;
}
async function guardarSucursal() {
  const id = $("#suc-id").value;
  const body = {
    codigo: $("#suc-codigo").value.trim(), nombre: $("#suc-nombre").value.trim(),
    direccion: $("#suc-direccion").value.trim() || null, telefono: $("#suc-telefono").value.trim() || null,
    comision_porcentaje: parseFloat($("#suc-comision").value || 0), activa: $("#suc-activa").checked,
  };
  try {
    if (id) await put(`/sucursales/${id}`, body); else await post("/sucursales", body);
    msg("#suc-msg", "Sucursal guardada ✔"); limpiarSucursal(); await cargarSucursales();
  } catch (e) { msg("#suc-msg", e.message, false); }
}
async function recargarSaldo() {
  try {
    const r = await post(`/sucursales/${$("#rec-sucursal").value}/recargar`, {
      monto: parseFloat($("#rec-monto").value || 0), referencia: $("#rec-referencia").value.trim() || null,
    });
    msg("#rec-msg", `Efectivo entregado ✔ Nueva caja: ${fmt(r.saldo_resultante)}`);
    await cargarSucursales();
  } catch (e) { msg("#rec-msg", e.message, false); }
}
async function verMovimientos() {
  const id = $("#mov-sucursal").value;
  const filas = await api(`/sucursales/${id}/movimientos`);
  tabla("#mov-tabla", ["Fecha", "Tipo", "Monto", "Referencia", "Caja resultante"],
    filas.map((m) => `<tr><td>${esc(m.creado_en)}</td><td>${esc(m.tipo)}</td><td>${fmt(m.monto)}</td><td>${esc(m.referencia || "")}</td><td>${fmt(m.saldo_resultante)}</td></tr>`));
}

/* --------------------------------------------------------------- terminales */
async function cargarTerminales() {
  await cargarCatalogos();
  tabla("#ter-tabla", ["Sucursal", "N.º", "Serial", "Activa", "Última conexión", "Acciones"],
    TERMINALES.map((t) => `<tr><td>${esc(t.sucursal)}</td><td>${t.numero_terminal}</td><td>${esc(t.serial_sunmi)}</td>
      <td>${t.activa ? "Sí" : "No"}</td>
      <td>${esc(t.ultima_conexion_en || "—")}</td>
      <td><button class="btn fila" onclick="revocarTerminal(${t.id})">Revocar</button>
      <button class="btn fila" onclick="reactivarTerminal(${t.id})">Reactivar</button></td></tr>`));
}
async function revocarTerminal(id) {
  if (!confirm("¿Revocar esta terminal? Esa sucursal dejará de vender de inmediato.")) return;
  await post(`/terminales/${id}/revocar`); await cargarTerminales();
}
async function reactivarTerminal(id) {
  await post(`/terminales/${id}/reactivar`); await cargarTerminales();
}

/* ----------------------------------------------------------------- usuarios */
function pillEstadoUsuario(u) {
  const e = u.estado || (u.eliminado ? "ELIMINADO" : (u.activo ? "ACTIVO" : "BLOQUEADO"));
  const cls = e === "ACTIVO" ? "activo"
    : (e === "ELIMINADO" ? "eliminado"
      : (e === "PENDIENTE" ? "pendiente" : "bloqueado"));
  return `<span class="pill ${cls}">${esc(e)}</span>`;
}
function estadoUsuarioClave(u) {
  return u.estado || (u.eliminado ? "ELIMINADO" : (u.activo ? "ACTIVO" : "BLOQUEADO"));
}
function inicialesUsuario(nombre) {
  const limpio = String(nombre || "").replace(/[()[\]{}.,;:_/-]+/g, " ").trim();
  const partes = limpio.split(/\s+/).filter((p) => /[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]/.test(p));
  if (!partes.length) return "?";
  const letra = (p) => (p.match(/[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]/) || ["?"])[0];
  if (partes.length === 1) return (letra(partes[0]) + (partes[0].match(/[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]/g) || ["?"])[1] || "").toUpperCase();
  return (letra(partes[0]) + letra(partes[1])).toUpperCase();
}
/** Misma lógica de permisos/acciones; solo cambia la clase visual del botón. */
function htmlAccionesUsuario(u, soyAdmin, clsBtn) {
  let acciones = "";
  if (!u.eliminado) {
    acciones += `<button type="button" class="${clsBtn}" onclick="editarUsuario(${u.id})">EDITAR</button>`;
  }
  if (soyAdmin && !u.eliminado && u.rol !== "super_admin") {
    if (u.activo) {
      acciones += `<button type="button" class="${clsBtn} peligro" onclick="bloquearUsuario(${u.id})">BLOQUEAR</button>`;
    } else {
      acciones += `<button type="button" class="${clsBtn} primario" onclick="desbloquearUsuario(${u.id})">DESBLOQUEAR</button>`;
    }
    acciones += `<button type="button" class="${clsBtn} peligro" onclick="eliminarUsuario(${u.id})">ELIMINAR</button>`;
  }
  return acciones;
}
function tarjetaUsuarioHtml(u, soyAdmin) {
  const suc = SUCURSALES.find((s) => s.id === u.sucursal_id);
  const caja = u.saldo_caja == null ? "—" : fmt(u.saldo_caja);
  const prueba = u.saldo_caja_prueba == null ? "—" : fmt(u.saldo_caja_prueba);
  const estado = estadoUsuarioClave(u);
  const clsEstado = estado === "ACTIVO" ? "activo"
    : (estado === "ELIMINADO" ? "eliminado"
      : (estado === "PENDIENTE" ? "pendiente" : "bloqueado"));
  const acciones = htmlAccionesUsuario(u, soyAdmin, "btn usu-accion");
  return `<article class="usu-card" data-usuario-id="${u.id}">
    <div class="usu-card-top">
      <div class="usu-avatar" aria-hidden="true">${esc(inicialesUsuario(u.nombre))}</div>
      <div class="usu-card-id">
        <div class="usu-card-nombre">${esc(u.nombre)}</div>
        <div class="usu-card-meta">${esc(u.usuario)} · ${esc(etiquetaRol(u.rol))}</div>
      </div>
      <span class="usu-estado ${clsEstado}"><span class="usu-estado-dot"></span>${esc(estado)}</span>
    </div>
    <div class="usu-card-grid">
      <div><span class="k">Sucursal</span><b>${esc(suc ? suc.nombre : "—")}</b></div>
      <div><span class="k">Caja</span><b>${caja}</b></div>
      <div><span class="k">Caja de prueba</span><b>${prueba}</b></div>
    </div>
    <div class="usu-card-acciones">${acciones || '<span class="nota">—</span>'}</div>
  </article>`;
}
function pintarUsuarios(usuarios, soyAdmin) {
  const destino = $("#usu-tabla");
  if (!destino) return;
  USUARIOS_ES_MOVIL = esUsuariosMovil();
  document.body.classList.toggle("usuarios-movil", USUARIOS_ES_MOVIL);
  document.body.classList.toggle("usuarios-escritorio", !USUARIOS_ES_MOVIL);
  if (!usuarios.length) {
    destino.innerHTML = '<p class="nota">Sin datos.</p>';
    return;
  }
  // iPhone/Samsung: SOLO tarjetas en el DOM (evita tabla ancha + scroll jump iOS).
  // Escritorio: SOLO tabla.
  if (USUARIOS_ES_MOVIL) {
    destino.innerHTML = `<div class="usu-lista-movil" data-vista="movil">${usuarios.map((u) => tarjetaUsuarioHtml(u, soyAdmin)).join("")}</div>`;
    return;
  }
  const filas = usuarios.map((u) => {
    const suc = SUCURSALES.find((s) => s.id === u.sucursal_id);
    const caja = u.saldo_caja == null ? "—" : fmt(u.saldo_caja);
    const prueba = u.saldo_caja_prueba == null ? "—" : fmt(u.saldo_caja_prueba);
    const acciones = htmlAccionesUsuario(u, soyAdmin, "btn fila");
    return `<tr><td>${esc(u.nombre)}</td><td>${esc(u.usuario)}</td><td>${esc(etiquetaRol(u.rol))}</td>
      <td>${esc(suc ? suc.nombre : "—")}</td><td>${caja}</td><td>${prueba}</td>
      <td>${pillEstadoUsuario(u)}</td>
      <td><div class="acciones-fila">${acciones || "—"}</div></td></tr>`;
  });
  const columnas = ["Nombre", "Usuario", "Rol", "Sucursal", "Caja", "Caja de prueba", "Estado", "Acciones"];
  destino.innerHTML =
    `<div class="tabla-scroll usu-tabla-escritorio" data-vista="escritorio"><table><thead><tr>` +
    columnas.map((c) => `<th>${esc(c)}</th>`).join("") +
    `</tr></thead><tbody>${filas.join("")}</tbody></table></div>`;
}
async function cargarUsuarios() {
  aplicarVisibilidadRol();
  const filtro = ($("#usu-filtro") && $("#usu-filtro").value) || "";
  const ruta = filtro ? `/usuarios?estado=${encodeURIComponent(filtro)}` : "/usuarios";
  const y = window.scrollY || window.pageYOffset || 0;
  const usuarios = await api(ruta);
  const soyAdmin = esAdminPanel();
  window._usuarios = usuarios;
  pintarUsuarios(usuarios, soyAdmin);
  // Evitar que el re-render de la lista tire el scroll al inicio (Safari iPhone).
  window.requestAnimationFrame(() => window.scrollTo(0, y));
}
function editarUsuario(id) {
  const u = (window._usuarios || []).find((x) => x.id === id); if (!u) return;
  if (u.eliminado) { msg("#usu-msg", "Un usuario eliminado no se puede editar", false); return; }
  const y = window.scrollY || window.pageYOffset || 0;
  $("#usu-id").value = u.id; $("#usu-nombre").value = u.nombre; $("#usu-usuario").value = u.usuario;
  $("#usu-rol").value = u.rol; $("#usu-sucursal").value = u.sucursal_id || "";
  $("#usu-clave").value = ""; $("#usu-activo").checked = u.activo;
  msg("#usu-msg", `Editando ${u.usuario}`);
  // No forzar focus: en iPhone focus() hace scrollIntoView y puede saltar la vista.
  window.requestAnimationFrame(() => window.scrollTo(0, y));
}
function limpiarUsuario() {
  ["#usu-id", "#usu-nombre", "#usu-usuario", "#usu-clave"].forEach((i) => $(i).value = "");
  $("#usu-activo").checked = true;
}
async function guardarUsuario() {
  const id = $("#usu-id").value;
  let sucursalId = $("#usu-sucursal").value ? parseInt($("#usu-sucursal").value) : null;
  let rol = $("#usu-rol").value;
  if (adminSucursalRestringido()) {
    sucursalId = YO.sucursal_id || sucursalId;
    if (!["operador", "supervisor"].includes(rol)) rol = "operador";
  }
  const body = {
    nombre: $("#usu-nombre").value.trim(), usuario: $("#usu-usuario").value.trim(),
    rol, sucursal_id: sucursalId,
    clave: $("#usu-clave").value || null, activo: $("#usu-activo").checked,
  };
  try {
    if (id) await put(`/usuarios/${id}`, body); else await post("/usuarios", body);
    msg("#usu-msg", "Usuario guardado ✔"); limpiarUsuario(); await cargarUsuarios();
  } catch (e) { msg("#usu-msg", e.message, false); }
}
async function bloquearUsuario(id) {
  const u = (window._usuarios || []).find((x) => x.id === id); if (!u) return;
  if (!confirm(`¿BLOQUEAR a ${u.nombre} (${u.usuario})?\nPerderá el acceso de inmediato en SUNMI y en el panel. Su caja y tickets no se modifican.`)) return;
  try {
    await post(`/usuarios/${id}/bloquear`);
    msg("#usu-msg", `${u.usuario} quedó BLOQUEADO.`);
    await cargarUsuarios();
  } catch (e) { msg("#usu-msg", e.message, false); }
}
async function desbloquearUsuario(id) {
  const u = (window._usuarios || []).find((x) => x.id === id); if (!u) return;
  if (u.eliminado) { msg("#usu-msg", "Un usuario eliminado no se puede desbloquear", false); return; }
  if (!confirm(`¿DESBLOQUEAR a ${u.nombre} (${u.usuario})?\nPodrá iniciar sesión de nuevo con sus credenciales.`)) return;
  try {
    await post(`/usuarios/${id}/desbloquear`);
    msg("#usu-msg", `${u.usuario} quedó ACTIVO.`);
    await cargarUsuarios();
  } catch (e) { msg("#usu-msg", e.message, false); }
}
async function eliminarUsuario(id) {
  const u = (window._usuarios || []).find((x) => x.id === id); if (!u) return;
  const suc = SUCURSALES.find((s) => s.id === u.sucursal_id);
  const ok = confirm(
    `¿ESTÁS SEGURO DE QUE DESEAS ELIMINAR ESTE USUARIO?\n\n` +
    `Nombre: ${u.nombre}\nUsuario: ${u.usuario}\nSucursal: ${suc ? suc.nombre : "—"}\n\n` +
    `Si tiene historial financiero se desactivará de forma permanente y se conservarán tickets, pagos y saldos.`
  );
  if (!ok) return;
  const motivo = prompt("Motivo de la eliminación (opcional):", "") || "";
  try {
    const r = await post(`/usuarios/${id}/eliminar`, { confirmar: true, motivo });
    msg("#usu-msg", r.modo === "fisica"
      ? `${u.usuario} eliminado definitivamente.`
      : `${u.usuario} quedó ELIMINADO (historial conservado).`);
    await cargarUsuarios();
  } catch (e) { msg("#usu-msg", e.message, false); }
}

/* ----------------------------------------------------- diseño ticket panel */
function dtConfigDesdeForm() {
  return {
    ancho_px: 384,
    encabezado: {
      mostrar_nombre_banca: true,
      mostrar_codigo: true,
      tamano_nombre: parseInt($("#dt-tam-nombre").value || 26, 10),
      centrado: true,
    },
    qr: {
      posicion: $("#dt-qr-pos").value || "superior",
      tamano_px: parseInt($("#dt-qr-tam").value || 168, 10),
    },
    tipografia: {
      cuerpo: 18,
      jugada: parseInt($("#dt-tam-jugada").value || 22, 10),
      total: parseInt($("#dt-tam-total").value || 22, 10),
      titulo_seccion: 17,
    },
    secciones: {
      qn: !!$("#dt-sec-qn").checked,
      pl: !!$("#dt-sec-pl").checked,
      sp: !!$("#dt-sec-sp").checked,
      tr: !!$("#dt-sec-tr").checked,
    },
    moneda_prefijo: "$ ",
    mensaje_inferior: ($("#dt-mensaje").value || "").trim(),
    mostrar_linea_sistema: false,
  };
}
function dtAplicarConfig(cfg) {
  if (!cfg) return;
  const enc = cfg.encabezado || {};
  const tip = cfg.tipografia || {};
  const qr = cfg.qr || {};
  const sec = cfg.secciones || {};
  if ($("#dt-tam-nombre")) $("#dt-tam-nombre").value = enc.tamano_nombre || 26;
  if ($("#dt-tam-jugada")) $("#dt-tam-jugada").value = tip.jugada || 22;
  if ($("#dt-tam-total")) $("#dt-tam-total").value = tip.total || 22;
  if ($("#dt-qr-tam")) $("#dt-qr-tam").value = qr.tamano_px || 168;
  if ($("#dt-qr-pos")) $("#dt-qr-pos").value = qr.posicion || "superior";
  if ($("#dt-mensaje")) $("#dt-mensaje").value = cfg.mensaje_inferior || "";
  if ($("#dt-sec-qn")) $("#dt-sec-qn").checked = sec.qn !== false;
  if ($("#dt-sec-pl")) $("#dt-sec-pl").checked = sec.pl !== false;
  if ($("#dt-sec-sp")) $("#dt-sec-sp").checked = sec.sp !== false;
  if ($("#dt-sec-tr")) $("#dt-sec-tr").checked = sec.tr !== false;
}
async function cargarDisenoTicket() {
  await cargarCatalogos();
  const sel = $("#dt-sucursal");
  if (!sel) return;
  sel.innerHTML = SUCURSALES.map(
    (s) => `<option value="${s.id}">${esc(s.codigo)} — ${esc(s.nombre)}</option>`
  ).join("");
  if (YO && YO.sucursal_id) sel.value = String(YO.sucursal_id);
  await refrescarDisenoTicket();
}
async function refrescarDisenoTicket() {
  const sid = $("#dt-sucursal") && $("#dt-sucursal").value;
  if (!sid) return;
  try {
    const d = await api("/panel/diseno-ticket?sucursal_id=" + encodeURIComponent(sid));
    dtAplicarConfig(d.config || {});
    if ($("#dt-activo")) $("#dt-activo").checked = d.activo !== false;
    if ($("#dt-tr-nota")) {
      $("#dt-tr-nota").textContent = d.tr_habilitado
        ? "TR (tripleta) está habilitada en el catálogo."
        : "TR no está habilitada en el catálogo: la sección no se imprimirá.";
    }
    msg("#dt-msg", "Diseño cargado.");
    await previewDisenoTicket();
  } catch (e) { msg("#dt-msg", e.message, false); }
}
async function previewDisenoTicket() {
  const sid = $("#dt-sucursal") && $("#dt-sucursal").value;
  const body = { config: dtConfigDesdeForm(), activo: !!($("#dt-activo") && $("#dt-activo").checked) };
  const r = await fetch("/panel/diseno-ticket/preview" + (sid ? ("?sucursal_id=" + encodeURIComponent(sid)) : ""), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}) },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || ("HTTP " + r.status));
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const img = $("#dt-preview");
  if (img) {
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    img.dataset.url = url;
    img.src = url;
  }
}
async function guardarDisenoTicket() {
  const sid = $("#dt-sucursal") && $("#dt-sucursal").value;
  if (!sid) return;
  try {
    await put("/panel/diseno-ticket?sucursal_id=" + encodeURIComponent(sid), {
      config: dtConfigDesdeForm(),
      activo: !!($("#dt-activo") && $("#dt-activo").checked),
    });
    msg("#dt-msg", "Diseño guardado. Las APK nuevas lo usarán sin reinstalarse.");
    await previewDisenoTicket();
  } catch (e) { msg("#dt-msg", e.message, false); }
}

/* ---------------------------------------------------------- ventas cajeros */
let VC_DETALLE_SCROLL = 0;
let VC_DETALLE_ORIGEN = "ventas-cajeros";

function rangoVentasCajeros(tipo) {
  const hoy = hoyISO();
  if (tipo === "ayer") return [sumarDias(hoy, -1), sumarDias(hoy, -1)];
  if (tipo === "semana") return [sumarDias(hoy, -6), hoy];
  if (tipo === "mes") {
    const [y, m] = hoy.split("-");
    return [`${y}-${m}-01`, hoy];
  }
  return [hoy, hoy];
}
/** Tarjeta élite de lista: mismos datos (nombre, tickets, ventas_netas). */
function filaCajeroCompacta(c) {
  const n = Number(c.tickets_vendidos || 0);
  const ticketsTxt = n === 1 ? "1 ticket" : `${n} tickets`;
  return `<article class="vc-card">
    <div class="vc-card-head">
      <div class="vc-card-nombre">${esc(c.nombre)}</div>
    </div>
    <div class="vc-card-body">
      <div class="vc-card-stat">
        <span class="k">Tickets</span>
        <b>${esc(ticketsTxt)}</b>
      </div>
      <div class="vc-card-stat">
        <span class="k">Ventas del ciclo</span>
        <b class="vc-card-monto">${fmt(c.ventas_ciclo != null ? c.ventas_ciclo : c.ventas_netas)}</b>
      </div>
    </div>
    <button type="button" class="btn vc-card-btn" onclick="verDetalleCajero(${c.usuario_id})">VER DETALLE</button>
  </article>`;
}
async function cargarVentasCajeros() {
  await cargarCatalogos();
  const ops = (await api("/usuarios?estado=activos")).filter((u) => u.rol === "operador");
  const bloq = (await api("/usuarios?estado=bloqueados")).filter((u) => u.rol === "operador");
  const cajeros = [...ops, ...bloq];
  $("#vc-cajero").innerHTML = '<option value="">Todos</option>' + cajeros.map(
    (u) => `<option value="${u.id}">${esc(u.nombre)} (${esc(u.usuario)})</option>`
  ).join("");
  $("#vc-sucursal").innerHTML = '<option value="">Todas</option>' + SUCURSALES.map(
    (s) => `<option value="${s.id}">${esc(s.codigo)} — ${esc(s.nombre)}</option>`
  ).join("");
  if (!$("#vc-desde").value || !$("#vc-hasta").value) {
    const [d, h] = rangoVentasCajeros("hoy");
    $("#vc-desde").value = d; $("#vc-hasta").value = h;
  }
  await refrescarVentasCajeros();
}
async function refrescarVentasCajeros() {
  const q = new URLSearchParams();
  if ($("#vc-desde").value) q.set("desde", $("#vc-desde").value);
  if ($("#vc-hasta").value) q.set("hasta", $("#vc-hasta").value);
  if ($("#vc-cajero").value) q.set("usuario_id", $("#vc-cajero").value);
  if ($("#vc-sucursal").value) q.set("sucursal_id", $("#vc-sucursal").value);
  try {
    const datos = await api("/reportes/ventas-cajeros?" + q.toString());
    $("#vc-periodo").textContent = `DESDE ${datos.desde}  HASTA ${datos.hasta} · ${datos.total_cajeros} cajero(s)` +
      (datos.es_prueba ? " · PRUEBA" : "");
    $("#vc-lista").innerHTML = (datos.cajeros || []).length
      ? datos.cajeros.map(filaCajeroCompacta).join("")
      : '<p class="nota">Sin cajeros con estos filtros.</p>';
    msg("#vc-msg", "");
  } catch (e) { msg("#vc-msg", e.message, false); }
}
function seccionActivaId() {
  const sec = document.querySelector("main .seccion.activo");
  return sec ? sec.id.replace(/^sec-/, "") : "ventas-cajeros";
}
function textoVolverDetalleCajero(origen) {
  if (origen === "control-cajeros") return "← VOLVER A CONTROL DE CAJEROS";
  if (origen === "usuarios") return "← VOLVER A USUARIOS";
  return "← VOLVER A USUARIOS";
}
function htmlItemHistorialVc(filas) {
  return filas.map((f) =>
    `<div class="vc-hist-item">
      <div class="vc-hist-top">${f.top}</div>
      ${f.meta ? `<div class="vc-hist-meta">${f.meta}</div>` : ""}
    </div>`
  ).join("");
}
async function verDetalleCajero(id) {
  const modal = $("#vc-modal");
  const cuerpo = $("#vc-modal-cuerpo");
  const btnVolver = $("#vc-modal-volver");
  VC_DETALLE_ORIGEN = seccionActivaId();
  VC_DETALLE_SCROLL = scrollDePagina();
  if (btnVolver) btnVolver.textContent = textoVolverDetalleCajero(VC_DETALLE_ORIGEN);
  $("#vc-modal-titulo").textContent = "Detalle del cajero";
  cuerpo.innerHTML = '<p class="nota">Cargando…</p>';
  abrirModal(modal);
  try {
    const q = new URLSearchParams();
    const desdeDet = (SECCION_ACTIVA === "control-cajeros" ? $("#cc-desde") : $("#vc-desde"))?.value;
    const hastaDet = (SECCION_ACTIVA === "control-cajeros" ? $("#cc-hasta") : $("#vc-hasta"))?.value;
    if (desdeDet) q.set("desde", desdeDet);
    if (hastaDet) q.set("hasta", hastaDet);
    const d = await api(`/reportes/ventas-cajeros/${id}?` + q.toString());
    const r = d.resumen || {};
    $("#vc-modal-titulo").textContent = `${r.nombre || "Cajero"} (${r.usuario || ""})`;
    const ventas = (d.ventas || []).length
      ? htmlItemHistorialVc((d.ventas || []).map((t) => ({
          top: `<b>#${esc(t.id)}</b><span class="vc-hist-estado">${esc(t.estado)}</span><span class="vc-hist-monto">${fmt(t.total)}</span>`,
          meta: `${esc(t.vendido_en || t.fecha)} · vendió este ticket`,
        })))
      : '<p class="nota">Sin ventas en el período.</p>';
    const pagos = (d.premios_pagados || []).length
      ? htmlItemHistorialVc((d.premios_pagados || []).map((p) => ({
          top: `<b>Ticket #${esc(p.ticket_id)}</b><span class="vc-hist-monto">${fmt(p.premio)}</span>`,
          meta: `${esc(p.numeros || "—")} · ${esc(p.pagado_en || "—")} · pagó este cajero · vendió: ${esc(p.vendedor || "—")}`,
        })))
      : '<p class="nota">Sin premios pagados por este cajero en el período.</p>';
    const movs = (d.movimientos || []).length
      ? htmlItemHistorialVc((d.movimientos || []).map((m) => ({
          top: `<b>${esc(m.tipo)}</b><span class="vc-hist-monto">${fmt(m.monto)}</span>`,
          meta: `${esc(m.creado_en || "—")} · ${esc(m.referencia || "")}`,
        })))
      : '<p class="nota">Sin movimientos en el período.</p>';
    const com = d.comision || {};
    const pctVigente = (com.porcentaje_vigente == null || com.porcentaje_vigente === "")
      ? "0" : String(com.porcentaje_vigente);
    const balance = com.comision_pendiente || "0.00";
    const pendiente = Number(balance);
    const puedeCerrar = !!com.puede_cerrar_ciclo;
    const histPagos = (com.historial_pagos || []).length
      ? htmlItemHistorialVc((com.historial_pagos || []).map((p) => ({
          top: `<b>${fmt(p.monto)}</b><span class="vc-hist-estado">PAGO</span><span class="vc-hist-monto">Bal. ${fmt(p.saldo_pendiente)}</span>`,
          meta: `${esc(p.creado_en || "—")} · admin: ${esc(p.administrador || "—")}`,
        })))
      : '<p class="nota">Sin pagos de comisión en este ciclo.</p>';
    const histCierres = (com.historial_cierres || []).length
      ? htmlItemHistorialVc((com.historial_cierres || []).map((cierre) => ({
          top: `<b>CIERRE #${esc(cierre.id)}</b><span class="vc-hist-monto">${fmt(cierre.ventas_ciclo)}</span>`,
          meta: `${esc(cierre.cerrado_en || "—")} · admin: ${esc(cierre.administrador || "—")} · ${esc(cierre.operacion_id || "")}`,
        })))
      : '<p class="nota">Sin cierres de ciclo registrados.</p>';
    const tituloCierre = pendiente > 0 ? "PAGAR COMISIÓN Y CERRAR CICLO" : "CERRAR CICLO";
    const btnCerrar = puedeCerrar
      ? `<button type="button" class="btn vc-btn-cerrar-ciclo" data-cerrar-ciclo-cajera="${esc(r.usuario_id)}" data-cajera-nombre="${esc(r.nombre || "")}" data-pendiente="${esc(balance)}" data-mi-caja="${esc(r.mi_caja)}">${tituloCierre}</button>`
      : `<button type="button" class="btn vc-btn-cerrar-ciclo" disabled title="${esc((com.bloqueos_cierre || []).join(' · ') || 'No se puede cerrar')}">${tituloCierre}</button>`;
    const notaCierre = (com.bloqueos_cierre || []).length
      ? `<p class="vc-comision-periodo-nota">${esc((com.bloqueos_cierre || []).join(" · "))}</p>`
      : "";
    const notaBalance = com.nota_balance
      ? `<p class="vc-comision-periodo-nota">${esc(com.nota_balance)}</p>`
      : "";
    cuerpo.innerHTML = `
      <div class="vc-detalle-hero">
        <div class="vc-detalle-hero-ico" aria-hidden="true">👤</div>
        <div class="vc-detalle-hero-txt">
          <h4>${esc(r.nombre || "Cajero")}</h4>
          <p>${esc(r.sucursal || "—")} · ${esc(r.usuario || "")}</p>
          <div class="vc-detalle-hero-meta">${pillEstadoUsuario(r)} <span>Última operación: ${esc(r.ultima_operacion || "—")}</span></div>
        </div>
      </div>
      <div class="vc-detalle-montos">
        <div class="vc-monto-dest"><span class="k">Ventas del ciclo</span><b class="vc-card-monto">${fmt(r.ventas_ciclo != null ? r.ventas_ciclo : r.ventas_netas)}</b></div>
        <div class="vc-monto-dest"><span class="k">Premios del ciclo</span><b>${fmt(r.premios_pagados)}</b></div>
        <div class="vc-monto-dest"><span class="k">MI CAJA</span><b class="${Number(r.mi_caja) < 0 ? "cc-neg" : "vc-card-monto"}">${fmt(r.mi_caja)}</b></div>
        <div><span class="k">Fondo asignado</span><b>${fmt(r.fondo_asignado)}</b></div>
        <div><span class="k">Entregas</span><b>${fmt(r.entregas)}</b></div>
        <div><span class="k">Tickets vigentes</span><b>${esc(r.tickets_vigentes)}</b></div>
        <div><span class="k">Tickets anulados</span><b>${esc(r.tickets_anulados)}</b></div>
        <div class="vc-monto-pendiente"><span class="k">PREMIOS PENDIENTES</span><b class="vc-pendiente-monto">${fmt(r.premios_pendientes != null ? r.premios_pendientes : (com.premios_pendientes || 0))}</b></div>
      </div>
      <section class="vc-comision-card" aria-label="Comisión ganada">
        <h5>COMISIÓN GANADA</h5>
        <div class="vc-comision-grid vc-comision-grid-simple">
          <div><span class="k">PORCENTAJE VIGENTE</span><b>${esc(pctVigente)}%</b></div>
          <div class="vc-comision-pendiente"><span class="k">BALANCE DE COMISIÓN</span><b class="vc-card-monto">${fmt(balance)}</b></div>
        </div>
        ${notaBalance}
        ${notaCierre}
        <div class="vc-comision-acciones">${btnCerrar}</div>
      </section>
      <p class="vc-detalle-tickets-meta">Tickets del ciclo: ${esc(r.tickets_vendidos)}</p>
      <section class="vc-hist">
        <h5>Historial de pagos de comisión</h5>
        <div class="vc-hist-lista">${histPagos}</div>
      </section>
      <section class="vc-hist">
        <h5>Historial de cierres</h5>
        <div class="vc-hist-lista">${histCierres}</div>
      </section>
      <section class="vc-hist">
        <h5>Tickets vendidos</h5>
        <div class="vc-hist-lista">${ventas}</div>
      </section>
      <section class="vc-hist">
        <h5>Premios que pagó</h5>
        <div class="vc-hist-lista">${pagos}</div>
      </section>
      <section class="vc-hist">
        <h5>Movimientos de caja</h5>
        <div class="vc-hist-lista">${movs}</div>
      </section>`;
    const botonCerrar = cuerpo.querySelector("[data-cerrar-ciclo-cajera]");
    if (botonCerrar && !botonCerrar.disabled) {
      botonCerrar.addEventListener("click", () => cerrarCicloCajeraPerfil(botonCerrar).catch((e) => {
        alert(e.message || String(e));
      }));
    }
  } catch (e) {
    cuerpo.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}
async function refrescarDashboardCajeroTrasCierre(usuarioId) {
  // Actualiza lista + detalle sin recargar la página ni alterar MI CAJA.
  if (typeof refrescarVentasCajeros === "function") {
    await refrescarVentasCajeros();
  }
  await verDetalleCajero(usuarioId);
}
async function cerrarCicloCajeraPerfil(boton) {
  if (!boton || boton.disabled) return;
  const usuarioId = Number(boton.getAttribute("data-cerrar-ciclo-cajera"));
  const nombre = boton.getAttribute("data-cajera-nombre") || "cajera";
  const pendienteTxt = boton.getAttribute("data-pendiente") || "0";
  const pendiente = Number(pendienteTxt);
  const miCaja = boton.getAttribute("data-mi-caja") || "0";
  if (!usuarioId) throw new Error("Cajera no válida");
  const ok = confirm(
    `¿Pagar comisión y cerrar ciclo de ${nombre}?\n\n` +
    `Balance de comisión: ${fmt(pendienteTxt)}\nMI CAJA (no se modifica): ${fmt(miCaja)}\n\n` +
    `Se registrará el pago administrativo, se cerrará el ciclo y el dashboard reiniciará contadores a RD$0.00.\n` +
    `No descuenta MI CAJA, Banco General, fondos ni entregas.`,
  );
  if (!ok) return;
  boton.disabled = true;
  const operacionId = ("cierre-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)).slice(0, 40);
  try {
    const body = { usuario_id: usuarioId, operacion_id: operacionId };
    if (pendiente > 0) body.monto = pendiente;
    const r = await post("/comisiones/cierres", body);
    const nuevo = r.ciclo_nuevo || {};
    const comNueva = r.comision_nueva || {};
    await refrescarDashboardCajeroTrasCierre(usuarioId);
    alert(
      `Ciclo cerrado.\n` +
      `Ventas del ciclo: ${fmt(nuevo.ventas_ciclo || 0)}\n` +
      `Premios del ciclo: ${fmt(nuevo.premios_ciclo || 0)}\n` +
      `Balance de comisión: ${fmt(comNueva.comision_pendiente || 0)}\n` +
      `MI CAJA se mantiene en ${fmt(miCaja)} (sin descuento).`,
    );
  } catch (e) {
    boton.disabled = false;
    throw e;
  }
}
function cerrarDetalleCajero() {
  const modal = $("#vc-modal");
  if (modal) cerrarModal(modal);
  // Cierra overlay sin ir()/recargar: conserva filtros, DOM de lista y scroll.
  const y = VC_DETALLE_SCROLL || 0;
  requestAnimationFrame(() => {
    window.scrollTo(0, y);
    requestAnimationFrame(() => window.scrollTo(0, y));
  });
}
window.verDetalleCajero = verDetalleCajero;
window.cerrarDetalleCajero = cerrarDetalleCajero;
window.eliminarUsuario = eliminarUsuario;

/* ---------------------------------------------------------- control cajeros */
let CC_AJUSTE_EN_CURSO = false;
let CC_DATOS = null;

function rangoControlCajeros(tipo) {
  const hoy = hoyISO();
  if (tipo === "ayer") return [sumarDias(hoy, -1), sumarDias(hoy, -1)];
  if (tipo === "15d") return [sumarDias(hoy, -14), hoy];
  return [hoy, hoy];
}
function fmtRd(n) {
  const v = Number(n || 0);
  const abs = Math.abs(v).toLocaleString("es-DO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (v < 0 ? "-RD$" : "RD$") + abs;
}
function etiquetaEstadoCc(estado) {
  if (estado === "deuda") return '<span class="cc-tag deuda">DEUDA</span>';
  if (estado === "positivo") return '<span class="cc-tag positivo">POSITIVO</span>';
  return '<span class="cc-tag cuadrado">CUADRADO</span>';
}
function filaControlCajero(c) {
  const bal = Number(c.balance_real || 0);
  const clsBal = bal < 0 ? "cc-neg" : (bal > 0 ? "cc-pos" : "cc-cero");
  const filaCls = bal < 0 ? "cc-fila-deuda" : "";
  const accion = bal < 0
    ? `<button type="button" class="btn primario cc-btn-ajustar" data-ajustar="${c.usuario_id}">AJUSTAR</button>
       <button type="button" class="btn cc-btn-ver" data-ver="${c.usuario_id}">VER</button>`
    : `<button type="button" class="btn cc-btn-ver" data-ver="${c.usuario_id}">VER</button>`;
  return `<tr class="${filaCls}">
    <td><b>${esc(c.nombre)}</b><br><span class="cc-meta">${esc(c.usuario)} · ${esc(c.sucursal)}</span><br>${etiquetaEstadoCc(c.estado)}</td>
    <td>${fmtRd(c.ventas)}</td>
    <td>${fmtRd(c.premios_pagados)}</td>
    <td>${fmtRd(c.entregado_admin)}</td>
    <td>${fmtRd(c.neto_periodo)}</td>
    <td>${fmtRd(c.ajustes)}</td>
    <td class="${clsBal}"><b>${fmtRd(c.balance_real)}</b></td>
    <td class="cc-acciones">${accion}</td>
  </tr>`;
}
function tarjetaMovilControl(c) {
  const bal = Number(c.balance_real || 0);
  const clsBal = bal < 0 ? "cc-neg" : (bal > 0 ? "cc-pos" : "cc-cero");
  const accion = bal < 0
    ? `<button type="button" class="btn primario cc-btn-ajustar" data-ajustar="${c.usuario_id}">AJUSTAR</button>
       <button type="button" class="btn cc-btn-ver" data-ver="${c.usuario_id}">VER</button>`
    : `<button type="button" class="btn cc-btn-ver" data-ver="${c.usuario_id}">VER</button>`;
  return `<article class="cc-card${bal < 0 ? " deuda" : ""}">
    <div class="cc-card-head"><b>${esc(c.nombre)}</b>${etiquetaEstadoCc(c.estado)}</div>
    <div class="cc-card-grid">
      <div><span class="k">Ventas</span><b>${fmtRd(c.ventas)}</b></div>
      <div><span class="k">Premios</span><b>${fmtRd(c.premios_pagados)}</b></div>
      <div><span class="k">Entregado</span><b>${fmtRd(c.entregado_admin)}</b></div>
      <div><span class="k">Neto período</span><b>${fmtRd(c.neto_periodo)}</b></div>
      <div><span class="k">Ajustes</span><b>${fmtRd(c.ajustes)}</b></div>
      <div><span class="k">Balance real</span><b class="${clsBal}">${fmtRd(c.balance_real)}</b></div>
    </div>
    <div class="cc-acciones">${accion}</div>
  </article>`;
}
async function cargarControlCajeros() {
  if (!$("#cc-desde").value || !$("#cc-hasta").value) {
    const [d, h] = rangoControlCajeros("hoy");
    $("#cc-desde").value = d;
    $("#cc-hasta").value = h;
  }
  await refrescarControlCajeros();
}
async function refrescarControlCajeros() {
  const q = new URLSearchParams();
  if ($("#cc-desde").value) q.set("desde", $("#cc-desde").value);
  if ($("#cc-hasta").value) q.set("hasta", $("#cc-hasta").value);
  try {
    const datos = await api("/control-cajeros?" + q.toString());
    CC_DATOS = datos;
    const r = datos.resumen || {};
    $("#cc-subtitulo").textContent =
      `${datos.sucursal || "Sucursal"} · ${r.total_cajeros || 0} cajero(s) · ` +
      `Balance total ${fmtRd(r.balance_total)}` +
      (datos.es_prueba ? " · PRUEBA" : "");
    $("#cc-tarjetas").innerHTML = `
      <div class="card"><div class="num">${esc(r.total_cajeros)}</div><div class="lbl">Total cajeros</div></div>
      <div class="card"><div class="num cc-pos">${esc(r.cajeros_positivos)}</div><div class="lbl">Positivos</div></div>
      <div class="card"><div class="num cc-neg">${esc(r.cajeros_negativos)}</div><div class="lbl">Negativos</div></div>
      <div class="card"><div class="num">${fmtRd(r.ventas_totales)}</div><div class="lbl">Ventas del período</div></div>
      <div class="card"><div class="num">${fmtRd(r.premios_pagados)}</div><div class="lbl">Premios del período</div></div>
      <div class="card"><div class="num ${Number(r.balance_total) < 0 ? "cc-neg" : "cc-pos"}">${fmtRd(r.balance_total)}</div><div class="lbl">Balance total (MI CAJA)</div></div>`;
    $("#cc-nota-balance").textContent = datos.nota_balance || "";
    const filas = datos.cajeros || [];
    $("#cc-tbody").innerHTML = filas.length
      ? filas.map(filaControlCajero).join("")
      : '<tr><td colspan="8">Sin cajeros en el alcance.</td></tr>';
    $("#cc-cards-movil").innerHTML = filas.length
      ? filas.map(tarjetaMovilControl).join("")
      : '<p class="nota">Sin cajeros en el alcance.</p>';
    $$(".cc-btn-ver").forEach((b) => b.addEventListener("click", () => verDetalleCajero(Number(b.dataset.ver))));
    $$(".cc-btn-ajustar").forEach((b) => b.addEventListener("click", () => abrirModalAjusteCc(Number(b.dataset.ajustar))));
    const hist = await api("/control-cajeros/ajustes");
    $("#cc-historial").innerHTML = (hist || []).length
      ? `<div class="cc-tabla-wrap"><table class="tabla"><thead><tr>
          <th>Fecha</th><th>Cajero</th><th>Admin</th><th>Anterior</th><th>Ajuste</th><th>Posterior</th><th>Motivo</th><th>Op.</th>
        </tr></thead><tbody>${hist.map((h) => `<tr>
          <td>${esc(h.creado_en || "")}</td>
          <td>${esc(h.cajera)}</td>
          <td>${esc(h.administrador)}</td>
          <td class="cc-neg">${fmtRd(h.balance_anterior)}</td>
          <td>${fmtRd(h.monto)}</td>
          <td>${fmtRd(h.balance_posterior)}</td>
          <td>${esc(h.motivo)}</td>
          <td class="cc-meta">${esc(h.operacion_id)}</td>
        </tr>`).join("")}</tbody></table></div>`
      : '<p class="nota">Sin ajustes registrados.</p>';
    msg("#cc-msg", "");
  } catch (e) {
    msg("#cc-msg", e.message, false);
  }
}
function abrirModalAjusteCc(usuarioId) {
  const c = (CC_DATOS && CC_DATOS.cajeros || []).find((x) => Number(x.usuario_id) === Number(usuarioId));
  if (!c || Number(c.balance_real) >= 0) {
    alert("Solo se ajustan cajeros con balance negativo.");
    return;
  }
  const deuda = Math.abs(Number(c.balance_real));
  $("#cc-modal-titulo").textContent = "AJUSTAR BALANCE DEL CAJERO";
  $("#cc-aj-info").textContent = `Cajero: ${c.nombre} · Sucursal: ${c.sucursal}`;
  $("#cc-aj-balance").value = fmtRd(c.balance_real);
  $("#cc-aj-monto").value = deuda.toFixed(2);
  $("#cc-aj-motivo").value = "Ajuste de banca negativa.";
  $("#cc-aj-usuario-id").value = String(c.usuario_id);
  $("#cc-aj-balance-visto").value = String(c.balance_real);
  $("#cc-aj-operacion").value = ("aj-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)).slice(0, 40);
  $("#cc-aj-msg").textContent = "";
  actualizarPreviewAjusteCc();
  abrirModal($("#cc-modal"));
  CC_AJUSTE_EN_CURSO = false;
  const btn = $("#cc-aj-aplicar");
  if (btn) btn.disabled = false;
}
function actualizarPreviewAjusteCc() {
  const bal = Number($("#cc-aj-balance-visto").value || 0);
  const monto = Number($("#cc-aj-monto").value || 0);
  const nuevo = bal + monto;
  $("#cc-aj-nuevo").value = fmtRd(nuevo);
  const deuda = Math.abs(Math.min(bal, 0));
  if (!(monto > 0) || monto > deuda + 0.009) {
    msg("#cc-aj-msg", monto > deuda ? "El ajuste no puede superar la deuda vigente." : "Indique un monto mayor que cero.", false);
  } else {
    msg("#cc-aj-msg", "");
  }
}
function cerrarModalAjusteCc() {
  const modal = $("#cc-modal");
  if (modal) cerrarModal(modal);
}
async function aplicarAjusteCc() {
  if (CC_AJUSTE_EN_CURSO) return;
  const usuarioId = Number($("#cc-aj-usuario-id").value);
  const monto = Number($("#cc-aj-monto").value);
  const motivo = ($("#cc-aj-motivo").value || "").trim();
  const balanceVisto = Number($("#cc-aj-balance-visto").value);
  const operacionId = $("#cc-aj-operacion").value;
  const deuda = Math.abs(Math.min(balanceVisto, 0));
  if (!(monto > 0) || monto > deuda + 0.009) {
    msg("#cc-aj-msg", "Monto inválido para la deuda vigente.", false);
    return;
  }
  if (motivo.length < 3) {
    msg("#cc-aj-msg", "Indique el motivo del ajuste.", false);
    return;
  }
  const ok = confirm(
    `¿Confirmar ajuste contable?\n\n` +
    `Balance actual: ${fmtRd(balanceVisto)}\n` +
    `Monto del ajuste: ${fmtRd(monto)}\n` +
    `Nuevo balance: ${fmtRd(balanceVisto + monto)}\n\n` +
    `No entrega efectivo físico ni toca el Banco General.`,
  );
  if (!ok) return;
  CC_AJUSTE_EN_CURSO = true;
  const btn = $("#cc-aj-aplicar");
  if (btn) btn.disabled = true;
  try {
    await post("/control-cajeros/ajuste", {
      usuario_id: usuarioId,
      monto,
      motivo,
      operacion_id: operacionId,
      balance_visto: balanceVisto,
    });
    cerrarModalAjusteCc();
    await refrescarControlCajeros();
    msg("#cc-msg", "Ajuste aplicado. Tabla y tarjetas actualizadas.");
  } catch (e) {
    msg("#cc-aj-msg", e.message, false);
    CC_AJUSTE_EN_CURSO = false;
    if (btn) btn.disabled = false;
  }
}
window.abrirModalAjusteCc = abrirModalAjusteCc;
window.cerrarModalAjusteCc = cerrarModalAjusteCc;

/* ------------------------------------------------------------------ sorteos */
async function cargarSorteos() {
  await cargarCatalogos();
  tabla("#sor-tabla", ["Nombre", "Sorteo", "Cierre", "Días", "Orden", "Activo", "Acciones"],
    SORTEOS.map((s) => `<tr><td>${esc(s.nombre)}</td><td>${esc(s.hora_sorteo)}</td><td>${esc(s.hora_cierre)}</td>
      <td>${esc(s.dias_activos.join(","))}</td><td>${s.orden}</td><td>${s.activo ? "Sí" : "No"}</td>
      <td><button class="btn fila" onclick="editarSorteo(${s.id})">Editar</button></td></tr>`));
}
function editarSorteo(id) {
  const s = SORTEOS.find((x) => x.id === id); if (!s) return;
  $("#sor-id").value = s.id; $("#sor-nombre").value = s.nombre;
  $("#sor-hora-sorteo").value = s.hora_sorteo; $("#sor-hora-cierre").value = s.hora_cierre;
  $("#sor-orden").value = s.orden; $("#sor-activo").checked = s.activo;
  $$('input[name="sor-dia"]').forEach((c) => c.checked = s.dias_activos.includes(parseInt(c.value)));
}
function limpiarSorteo() {
  ["#sor-id", "#sor-nombre", "#sor-hora-sorteo", "#sor-hora-cierre"].forEach((i) => $(i).value = "");
  $("#sor-orden").value = 100; $("#sor-activo").checked = true;
  $$('input[name="sor-dia"]').forEach((c) => c.checked = true);
}
async function guardarSorteo() {
  const id = $("#sor-id").value;
  const dias = [...$$('input[name="sor-dia"]:checked')].map((c) => parseInt(c.value));
  const body = {
    nombre: $("#sor-nombre").value.trim(), hora_sorteo: $("#sor-hora-sorteo").value.trim(),
    hora_cierre: $("#sor-hora-cierre").value.trim(), dias_activos: dias,
    orden: parseInt($("#sor-orden").value || 100), activo: $("#sor-activo").checked,
  };
  try {
    if (id) await put(`/sorteos/${id}`, body); else await post("/sorteos", body);
    msg("#sor-msg", "Sorteo guardado ✔"); limpiarSorteo(); await cargarSorteos();
  } catch (e) { msg("#sor-msg", e.message, false); }
}


/* ------------------------------------------------------------ tabla de pagos */
const CLAVES_POR_TIPO = { QN: ["1ro", "2do", "3ro"], PL: ["1-2", "1-3", "2-3"], SP: ["sp"], TR: ["tr"] };
function actualizarClavesTabla() {
  const tipo = $("#tab-tipo").value || "QN";
  $("#tab-clave").innerHTML = (CLAVES_POR_TIPO[tipo] || []).map((c) => `<option value="${c}">${c}</option>`).join("");
}
async function cargarTabla() {
  const filas = await api("/tabla-pagos");
  tabla("#tab-tabla", ["Tipo", "Posición", "Factor", "Desde", "Hasta"],
    filas.map((f) => `<tr><td>${esc(f.tipo)}</td><td>${esc(f.clave)}</td><td>×${esc(f.factor)}</td>
      <td>${esc(f.vigente_desde)}</td><td>${esc(f.vigente_hasta || "— vigente —")}</td></tr>`));
  if (!$("#tab-desde").value) $("#tab-desde").value = hoyISO();
}
async function guardarFactor() {
  try {
    await post("/tabla-pagos", {
      tipo: $("#tab-tipo").value, clave: $("#tab-clave").value,
      factor: parseFloat($("#tab-factor").value || 0), vigente_desde: $("#tab-desde").value,
    });
    msg("#tab-msg", "Factor guardado ✔ Aplica a las ventas desde esa fecha; los tickets ya vendidos no cambian.");
    await cargarTabla();
  } catch (e) { msg("#tab-msg", e.message, false); }
}

/* ------------------------------------------------------------------ límites */
let LIMITE_CAJERAS = [];
let LIMITE_EDICION = null;
function numeros00a99(extra) {
  let html = extra || "";
  for (let n = 0; n < 100; n++) html += `<option value="${String(n).padStart(2, "0")}">${String(n).padStart(2, "0")}</option>`;
  return html;
}
async function cargarLimites() {
  if (!$("#lim-qn-numero").options.length) {
    $("#lim-qn-numero").innerHTML = numeros00a99('<option value="*">TODOS LOS NÚMEROS</option>');
    $("#lim-pl-a").innerHTML = numeros00a99();
    $("#lim-pl-b").innerHTML = numeros00a99();
    $("#lim-sp-a").innerHTML = numeros00a99();
    $("#lim-sp-b").innerHTML = numeros00a99();
    $("#lim-tr-a").innerHTML = numeros00a99();
    $("#lim-tr-b").innerHTML = numeros00a99();
    $("#lim-tr-c").innerHTML = numeros00a99();
  }
  const elegido = $("#lim-sucursal").value;
  $("#lim-sucursal").innerHTML = opciones(SUCURSALES, (s) => s.id, (s) => `${s.codigo} — ${s.nombre}`);
  if (elegido) $("#lim-sucursal").value = elegido;
  LIMITE_CAJERAS = (await api("/usuarios")).filter((u) => u.rol === "operador");
  pintarCajerasLimite();
  await pintarLimites();
}
function pintarCajerasLimite() {
  const lista = LIMITE_CAJERAS.filter((u) => String(u.sucursal_id) === String($("#lim-sucursal").value));
  const elegido = $("#lim-cajera").value;
  $("#lim-cajera").innerHTML = lista.length
    ? opciones(lista, (u) => u.id, (u) => `${u.nombre} (${u.usuario})`)
    : '<option value="">No hay cajeras en esta sucursal</option>';
  if (elegido) $("#lim-cajera").value = elegido;
}
async function pintarLimites() {
  const suc = $("#lim-sucursal").value;
  const cajera = $("#lim-cajera").value;
  const q = new URLSearchParams();
  if (suc) q.set("sucursal_id", suc);
  if (cajera) q.set("usuario_id", cajera);
  const filas = await api("/limites-cajera?" + q.toString());
  tabla("#lim-tabla", ["Cajera", "Tipo", "Lotería", "Número", "Máximo del día", "Acciones"],
    filas.map((l) => `<tr><td>${esc(l.cajera)}</td><td>${esc(l.tipo)}</td><td>${esc(l.sorteo)}</td>
      <td>${esc(l.numero)}</td><td>${fmt(l.monto_max_acumulado)}</td>
      <td><button class="btn fila" data-editar-limite="${l.id}">Editar</button>
      <button class="btn fila" data-borrar-limite="${l.id}">Eliminar</button></td></tr>`));
  filas.forEach((l) => { window["limite" + l.id] = l; });
  document.querySelectorAll("[data-editar-limite]").forEach((b) => b.addEventListener("click", () => editarLimite(window["limite" + b.dataset.editarLimite])));
  document.querySelectorAll("[data-borrar-limite]").forEach((b) => b.addEventListener("click", () => borrarLimiteCajera(b.dataset.borrarLimite)));
}
function editarLimite(l) {
  LIMITE_EDICION = l.id;
  $("#lim-cajera").value = String(l.usuario_id);
  const partes = String(l.clave_numero || "").split("-");
  if (l.tipo === "PL") {
    $("#lim-pl-loteria").value = String(l.sorteo_id);
    $("#lim-pl-monto").value = l.monto_max_acumulado;
    if (l.clave_numero === "*") $("#lim-pl-modo").value = "*";
    else {
      $("#lim-pl-modo").value = "uno";
      $("#lim-pl-a").value = partes[0];
      $("#lim-pl-b").value = partes[1] || partes[0];
    }
  } else if (l.tipo === "SP") {
    $("#lim-sp-loteria1").value = String(l.sorteo_id || 0);
    $("#lim-sp-loteria2").value = String(l.sorteo2_id || 0);
    $("#lim-sp-monto").value = l.monto_max_acumulado;
    if (l.clave_numero === "*") $("#lim-sp-modo").value = "*";
    else {
      $("#lim-sp-modo").value = "uno";
      $("#lim-sp-a").value = partes[0];
      $("#lim-sp-b").value = partes[1] || partes[0];
    }
  } else if (l.tipo === "TR") {
    $("#lim-tr-loteria").value = String(l.sorteo_id);
    $("#lim-tr-monto").value = l.monto_max_acumulado;
    if (l.clave_numero === "*") $("#lim-tr-modo").value = "*";
    else {
      $("#lim-tr-modo").value = "uno";
      $("#lim-tr-a").value = partes[0];
      $("#lim-tr-b").value = partes[1] || partes[0];
      $("#lim-tr-c").value = partes[2] || partes[0];
    }
  } else {
    $("#lim-qn-loteria").value = String(l.sorteo_id);
    $("#lim-qn-numero").value = l.clave_numero;
    $("#lim-qn-monto").value = l.monto_max_acumulado;
  }
  msg("#lim-msg", "Editando el límite. Guarde para reemplazarlo.", true);
}
async function guardarLimiteCajera(tipo) {
  const cajera = $("#lim-cajera").value;
  if (!cajera) throw new Error("Seleccione una cajera");
  const cuerpo = { usuario_id: Number(cajera), tipo, id: LIMITE_EDICION, sorteo2_id: 0 };
  if (tipo === "QN") {
    cuerpo.sorteo_id = Number($("#lim-qn-loteria").value);
    cuerpo.numeros = $("#lim-qn-numero").value;
    cuerpo.monto_max_acumulado = Number($("#lim-qn-monto").value);
  } else if (tipo === "PL") {
    cuerpo.sorteo_id = Number($("#lim-pl-loteria").value);
    cuerpo.numeros = $("#lim-pl-modo").value === "*" ? "*" : `${$("#lim-pl-a").value}-${$("#lim-pl-b").value}`;
    cuerpo.monto_max_acumulado = Number($("#lim-pl-monto").value);
  } else if (tipo === "SP") {
    cuerpo.sorteo_id = Number($("#lim-sp-loteria1").value);
    cuerpo.sorteo2_id = Number($("#lim-sp-loteria2").value);
    if (cuerpo.sorteo_id && cuerpo.sorteo2_id && cuerpo.sorteo_id === cuerpo.sorteo2_id) {
      throw new Error("El Súper Palé requiere dos loterías diferentes");
    }
    if ((cuerpo.sorteo_id === 0) !== (cuerpo.sorteo2_id === 0)) {
      throw new Error("Para SP elija dos loterías, o TODAS en ambas");
    }
    cuerpo.numeros = $("#lim-sp-modo").value === "*" ? "*" : `${$("#lim-sp-a").value}-${$("#lim-sp-b").value}`;
    cuerpo.monto_max_acumulado = Number($("#lim-sp-monto").value);
  } else if (tipo === "TR") {
    cuerpo.sorteo_id = Number($("#lim-tr-loteria").value);
    cuerpo.numeros = $("#lim-tr-modo").value === "*"
      ? "*"
      : `${$("#lim-tr-a").value}-${$("#lim-tr-b").value}-${$("#lim-tr-c").value}`;
    cuerpo.monto_max_acumulado = Number($("#lim-tr-monto").value);
  } else {
    throw new Error("Tipo de límite no válido");
  }
  if (!cuerpo.monto_max_acumulado || cuerpo.monto_max_acumulado <= 0) throw new Error("Indique el monto máximo");
  await post("/limites-cajera", cuerpo);
  LIMITE_EDICION = null;
  msg("#lim-msg", "Límite guardado. Cada combinación conserva su propio máximo del día.", true);
  await pintarLimites();
}
async function borrarLimiteCajera(id) {
  if (!confirm("¿Eliminar este límite?")) return;
  await del(`/limites-cajera/${id}`);
  if (LIMITE_EDICION === Number(id)) LIMITE_EDICION = null;
  await pintarLimites();
}

/* --------------------------------------------------------------- resultados */
async function cargarResultados() {
  if (!$("#res-fecha").value) $("#res-fecha").value = hoyISO();
  await Promise.all([cargarResultadosDia(), cargarImportaciones()]);
}
async function cargarResultadosDia() {
  const fecha = $("#res-fecha").value || hoyISO();
  const filas = await api(`/resultados?fecha=${fecha}`);
  tabla("#res-dia-tabla", ["Sorteo", "1.º", "2.º", "3.º", "Estado", "Fuente"],
    filas.map((r) => `<tr><td>${esc(r.sorteo)}</td><td>${esc(r.premio1)}</td><td>${esc(r.premio2)}</td>
      <td>${esc(r.premio3)}</td><td><span class="pill ${esc(r.estado)}">${esc(r.estado)}</span></td><td>${esc(r.fuente)}</td></tr>`));
}
async function cargarImportaciones() {
  const filas = await api("/importaciones");
  tabla("#imp-tabla", ["Hora", "Fecha objetivo", "OK", "HTTP", "Propuestos", "Detalle"],
    filas.map((i) => `<tr><td>${esc(i.creado_en)}</td><td>${esc(i.fecha_objetivo)}</td><td>${i.ok ? "Sí" : "No"}</td>
      <td>${esc(i.estado_http ?? "—")}</td><td>${i.encontrados}</td><td>${esc(i.detalle || "")}</td></tr>`));
}
async function buscarResultado() {
  const fecha = $("#res-fecha").value || hoyISO();
  const sid = $("#res-sorteo").value;
  const filas = await api(`/resultados?fecha=${fecha}&sorteo_id=${sid}`);
  RESULTADO_ACTUAL = filas[0] || null;
  const caja = $("#res-estado");
  if (!RESULTADO_ACTUAL) {
    caja.className = "estado-box";
    caja.textContent = "Este sorteo no tiene resultado registrado para esa fecha. Digite los números y GUARDE LA PROPUESTA.";
    return;
  }
  const r = RESULTADO_ACTUAL;
  $("#res-p1").value = r.premio1; $("#res-p2").value = r.premio2; $("#res-p3").value = r.premio3;
  caja.className = "estado-box" + (r.estado === "liquidado" ? " ganador" : "");
  caja.textContent = `${r.leyenda ? r.leyenda + " · " : ""}${r.sorteo} · ${r.fecha} → ${r.premio1} - ${r.premio2} - ${r.premio3} · Estado: ${r.estado.toUpperCase()} · Fuente: ${r.fuente}` +
    (r.liquidado_en ? ` · Liquidado: ${r.liquidado_en}` : "");
}
async function guardarResultado() {
  try {
    const r = await post("/resultados", {
      sorteo_id: parseInt($("#res-sorteo").value), fecha: $("#res-fecha").value || hoyISO(),
      premio1: parseInt($("#res-p1").value), premio2: parseInt($("#res-p2").value), premio3: parseInt($("#res-p3").value),
      simulado: $("#res-simulado").checked,
    });
    RESULTADO_ACTUAL = r;
    msg("#res-msg", r.leyenda
      ? `${r.leyenda} ✔ ${r.sorteo}: ${r.premio1}-${r.premio2}-${r.premio3}. Tickets de prueba: ${r.tickets_prueba}`
      : `Propuesta guardada ✔ ${r.sorteo}: ${r.premio1}-${r.premio2}-${r.premio3} (sin liquidar todavía)`);
    await buscarResultado(); await cargarResultadosDia();
  } catch (e) { msg("#res-msg", e.message, false); }
}
async function confirmarResultado() {
  if (!RESULTADO_ACTUAL) { msg("#res-msg", "Primero BUSQUE o GUARDE un resultado", false); return; }
  if (!confirm("¿Confirmar y LIQUIDAR? El motor marcará los tickets ganadores con este resultado.")) return;
  try {
    const r = await post(`/resultados/${RESULTADO_ACTUAL.id}/confirmar`);
    RESULTADO_ACTUAL = r;
    msg("#res-msg", `Liquidado ✔ Tickets afectados: ${r.tickets_afectados}`);
    await buscarResultado(); await cargarResultadosDia();
  } catch (e) { msg("#res-msg", e.message, false); }
}
async function revertirResultado() {
  if (!RESULTADO_ACTUAL) { msg("#res-msg", "Primero BUSQUE un resultado liquidado", false); return; }
  if (!confirm("¿Revertir la liquidación? Los tickets volverán a estar sin evaluar (solo si ninguno fue pagado).")) return;
  try {
    const r = await post(`/resultados/${RESULTADO_ACTUAL.id}/revertir`);
    RESULTADO_ACTUAL = r;
    msg("#res-msg", `Liquidación revertida ✔ Tickets afectados: ${r.tickets_afectados}. El resultado quedó PROPUESTO para corregirlo.`);
    await buscarResultado(); await cargarResultadosDia();
  } catch (e) { msg("#res-msg", e.message, false); }
}
async function importarConectate() {
  try {
    msg("#res-msg", "Importando desde Conectate...");
    const r = await post("/resultados/importar", { fecha: $("#res-fecha").value || hoyISO() });
    msg("#res-msg", r.motivo, r.ok);
    await cargarResultadosDia(); await cargarImportaciones();
  } catch (e) { msg("#res-msg", e.message, false); }
}

/* ------------------------------------------------------------------ tickets */
function llaveTicket() {
  return { id: parseInt($("#tic-id").value || 0), serial: $("#tic-serial").value.trim() };
}
function pintarTicket(d) {
  const caja = $("#tic-resultado");
  caja.className = "estado-box" + (d.estado === "ganador" ? " ganador" : "") + (d.estado === "anulado" || d.estado === "no_ganador" ? " error" : "");
  const jugadas = (d.jugadas || []).map((j) =>
    `• ${esc(j.tipo_nombre)} ${esc(j.numeros)} → ${esc(j.loterias.join(" + "))} · ${fmt(j.monto)}` +
    (j.evaluada ? ` · premio ${fmt(j.premio || 0)}` : " · sin evaluar")).join("\n");
  let extra = "";
  if (d.estado === "anulado") {
    extra = `\nAnulado: ${d.anulado_en || "—"} · Por: ${d.anulado_por || "—"} · Motivo: ${d.anulado_motivo || "—"}`;
  } else if (d.mensaje_anular) {
    extra = `\n${d.mensaje_anular}`;
  } else if (d.puede_anular_cajera) {
    extra = `\nCajera puede anular · quedan ${d.segundos_para_anular || 0}s`;
  }
  caja.textContent =
    `Ticket ${d.id} · Serial ${d.serial} · ${d.banca} (${d.banca_codigo})\n` +
    `Vendido: ${d.fecha_hora} · Total: ${fmt(d.total)}\n${jugadas}\n` +
    `Cajero: ${d.cajero || "—"} · Sucursal: ${d.banca || "—"}\n` +
    `Estado: ${String(d.estado).toUpperCase()} · Premio: ${fmt(d.premio_total)}\n${d.mensaje || ""}${extra}`;
}
async function consultarTicket() {
  try {
    const d = await post("/panel/tickets/consultar", llaveTicket());
    pintarTicket(d); msg("#tic-msg", "Consulta lista ✔");
  } catch (e) { msg("#tic-msg", e.message, false); }
}
async function pagarTicketPanel() {
  try {
    const consulta = await post("/panel/tickets/consultar", llaveTicket());
    const premio = Number(consulta.premio_pendiente || consulta.importe_a_cobrar || 0);
    const miCaja = Number(consulta.mi_caja || 0);
    const excede = !!consulta.premio_excede_mi_caja || (premio > miCaja);
    const despues = consulta.mi_caja_despues_si_paga != null
      ? Number(consulta.mi_caja_despues_si_paga)
      : (miCaja - premio);
    let texto =
      `¿Confirmar pago de ${fmt(premio)}?\n` +
      `MI CAJA actual: ${fmt(miCaja)}\n`;
    if (excede) {
      texto +=
        `\nEl premio supera MI CAJA.\n` +
        `Si continúa, MI CAJA quedará en ${fmt(despues)} (deuda contable).\n` +
        `No inventa efectivo físico ni genera ajuste automático.\n\n` +
        `¿Confirma el pago de todas formas?`;
    } else {
      texto += `\n¿Registrar el pago?`;
    }
    if (!confirm(texto)) return;
    const d = await post("/panel/tickets/pagar", {
      ...llaveTicket(),
      sucursal_id: parseInt($("#tic-sucursal").value),
      confirmar_caja_negativa: excede ? true : false,
    });
    const cajaTxt = d.mi_caja != null ? ` · MI CAJA ${fmt(d.mi_caja)}` : "";
    pintarTicket(d);
    msg("#tic-msg", `Ticket PAGADO ✔ ${fmt(d.premio_total || premio)}${cajaTxt}`);
  } catch (e) { msg("#tic-msg", e.message, false); }
}
async function anularTicketPanel() {
  const motivo = ($("#tic-motivo").value || "").trim();
  if (!motivo) {
    msg("#tic-msg", "Indique el motivo de la anulación.", false);
    return;
  }
  if (!confirm("¿Anular este ticket como administrador? El efectivo se devuelve al cliente y sale de la caja de la banca vendedora. Queda registrado quién anuló, cuándo y el motivo.")) return;
  try {
    const d = await post("/panel/tickets/anular", { ...llaveTicket(), motivo });
    pintarTicket(d); msg("#tic-msg", "Ticket ANULADO ✔ El efectivo salió de la caja de la banca vendedora.");
    await pintarListaTickets().catch(() => {});
  } catch (e) { msg("#tic-msg", e.message, false); }
}

/* -------------------------------------------------------- lista tickets admin */
let TIC_PAGINA = 1;
let TIC_CAJERAS = [];

function rangoTickets(tipo) {
  const hoy = hoyISO();
  if (tipo === "ayer") return [sumarDias(hoy, -1), sumarDias(hoy, -1)];
  if (tipo === "semana") {
    const d = new Date(hoy + "T12:00:00");
    const dia = (d.getDay() + 6) % 7;
    d.setDate(d.getDate() - dia);
    const desde = d.toISOString().slice(0, 10);
    return [desde, hoy];
  }
  if (tipo === "mes") return [hoy.slice(0, 8) + "01", hoy];
  return [hoy, hoy];
}

async function cargarTicketsLista() {
  const hoy = hoyISO();
  if (!$("#tic-lista-desde").value) $("#tic-lista-desde").value = hoy;
  if (!$("#tic-lista-hasta").value) $("#tic-lista-hasta").value = hoy;
  $("#tic-lista-sucursal").innerHTML =
    '<option value="">Todas</option>' +
    opciones(SUCURSALES, (s) => s.id, (s) => `${s.codigo} — ${s.nombre}`);
  TIC_CAJERAS = (await api("/usuarios")).filter((u) => u.rol === "operador");
  $("#tic-lista-cajera").innerHTML =
    '<option value="">Todas</option>' +
    opciones(TIC_CAJERAS, (u) => u.id, (u) => `${u.nombre} (${u.usuario})`);
  TIC_PAGINA = 1;
  await pintarListaTickets();
}

async function pintarListaTickets() {
  const qs = new URLSearchParams();
  const id = ($("#tic-lista-id").value || "").trim();
  if (id) qs.set("ticket_id", id);
  else {
    if ($("#tic-lista-desde").value) qs.set("desde", $("#tic-lista-desde").value);
    if ($("#tic-lista-hasta").value) qs.set("hasta", $("#tic-lista-hasta").value);
  }
  if ($("#tic-lista-sucursal").value) qs.set("sucursal_id", $("#tic-lista-sucursal").value);
  if ($("#tic-lista-cajera").value) qs.set("usuario_id", $("#tic-lista-cajera").value);
  if ($("#tic-lista-estado").value) qs.set("estado", $("#tic-lista-estado").value);
  qs.set("pagina", String(TIC_PAGINA));
  qs.set("por_pagina", "30");
  try {
    const datos = await api(`/panel/tickets?${qs.toString()}`);
    $("#tic-lista-meta").textContent =
      `${datos.total || 0} ticket(s) · página ${datos.pagina}/${datos.paginas}` +
      (datos.modo_desarrollo ? " · PRUEBA" : "");
    const filas = datos.tickets || [];
    if (!filas.length) {
      $("#tic-lista").innerHTML = '<p class="nota">No hay tickets con esos filtros.</p>';
    } else {
      $("#tic-lista").innerHTML = filas.map((t) => {
        const lot = (t.loterias || []).join(", ") || "—";
        const anular = t.puede_anular
          ? `<button type="button" class="btn peligro" data-tic-anular="${t.id}" data-tic-serial="${esc(t.serial)}">ELIMINAR / ANULAR</button>`
          : "";
        return `<article class="tic-card">
          <div class="tic-cab">
            <h4>#${esc(t.id)} · ${esc(t.serial)}</h4>
            <span class="estado-pill">${esc(String(t.estado).toUpperCase())}${t.es_prueba ? " · PRUEBA" : ""}</span>
          </div>
          <div class="meta">${esc(t.vendido_en || t.fecha || "—")} · ${esc(t.cajera)} (${esc(t.cajera_usuario)}) · ${esc(t.sucursal)}</div>
          <div class="meta">Loterías: ${esc(lot)}</div>
          <div class="montos"><div>Total <b>${fmt(t.total)}</b></div><div>Premio <b>${fmt(t.premio_total)}</b></div></div>
          <div class="tic-acciones">
            <button type="button" class="btn primario" data-tic-ver="${t.id}">VER TICKET</button>
            ${anular}
          </div>
        </article>`;
      }).join("");
    }
    const pag = $("#tic-paginacion");
    pag.innerHTML = "";
    if ((datos.paginas || 1) > 1) {
      if (datos.pagina > 1) {
        pag.innerHTML += `<button type="button" class="btn" data-tic-pag="${datos.pagina - 1}">Anterior</button>`;
      }
      if (datos.pagina < datos.paginas) {
        pag.innerHTML += `<button type="button" class="btn" data-tic-pag="${datos.pagina + 1}">Siguiente</button>`;
      }
    }
    document.querySelectorAll("[data-tic-ver]").forEach((b) => {
      b.addEventListener("click", () => verTicketDetalle(parseInt(b.dataset.ticVer, 10)));
    });
    document.querySelectorAll("[data-tic-anular]").forEach((b) => {
      b.addEventListener("click", () => anularTicketLista(b));
    });
    document.querySelectorAll("[data-tic-pag]").forEach((b) => {
      b.addEventListener("click", () => {
        TIC_PAGINA = parseInt(b.dataset.ticPag, 10);
        pintarListaTickets().catch((e) => msg("#tic-lista-msg", e.message, false));
      });
    });
    msg("#tic-lista-msg", "Lista actualizada ✔");
  } catch (e) {
    msg("#tic-lista-msg", e.message, false);
  }
}

async function verTicketDetalle(id) {
  try {
    const d = await api(`/panel/tickets/${id}`);
    $("#tic-id").value = d.id;
    $("#tic-serial").value = d.serial;
    pintarTicket(d);
    const jugadas = (d.jugadas || []).map((j) =>
      `<li><b>${esc(j.tipo_nombre)}</b> ${esc(j.numeros)} → ${esc((j.loterias || []).join(" + "))} · ${fmt(j.monto)}` +
      (j.evaluada ? ` · premio ${fmt(j.premio || 0)}${j.pagada ? " (pagado)" : ""}` : " · sin evaluar") +
      `</li>`).join("");
    $("#tic-modal-titulo").textContent = `Ticket #${d.id} · ${d.serial}`;
    $("#tic-modal-cuerpo").innerHTML = `
      <p class="meta">${esc(d.fecha_hora || "—")} · ${esc(d.cajero || "—")} · ${esc(d.banca || "—")}</p>
      <p><b>Estado:</b> ${esc(String(d.estado).toUpperCase())} · <b>Total:</b> ${fmt(d.total)} · <b>Premio:</b> ${fmt(d.premio_total)}</p>
      ${d.es_prueba ? '<p class="nota">Ticket de PRUEBA</p>' : ""}
      <h4>Jugadas</h4><ul class="tic-jugadas">${jugadas || "<li>Sin jugadas</li>"}</ul>
      ${d.estado === "anulado" ? `<p class="nota">Anulado: ${esc(d.anulado_en || "—")} · ${esc(d.anulado_por || "—")} · ${esc(d.anulado_motivo || "—")}</p>` : ""}
      ${d.pago ? `<p class="nota">Pago: ${esc(d.pago.fecha_hora || "—")} · ${esc(d.pago.sucursal || "—")} · cajero ${esc(d.pago.cajero || "—")}</p>` : ""}`;
    abrirModal($("#tic-modal"));
    const btn = $("#tic-modal-anular");
    const puede = !!(d.puede_anular_admin || (d.anulacion_admin && d.anulacion_admin.puede_anular));
    btn.hidden = !puede;
    btn.dataset.ticAnular = String(d.id);
    btn.dataset.ticSerial = d.serial;
    btn.onclick = () => abrirModalAnular(d.id, d.serial);
  } catch (e) {
    msg("#tic-lista-msg", e.message, false);
  }
}

let TIC_ANULAR = null;

async function abrirModalAnular(id, serial) {
  try {
    const info = await api(`/panel/tickets/${id}/anulacion`);
    const det = await api(`/panel/tickets/${id}`);
    TIC_ANULAR = { id, serial: serial || det.serial, info, det };
    const lot = (info.loterias || []).join(", ") || "—";
    const cerrados = (info.sorteos_cerrados || []).join(", ") || "Ninguno (abiertos)";
    $("#tic-anular-resumen").innerHTML =
      `<b>Ticket #${esc(id)}</b> · ${esc(det.serial)}<br>` +
      `Cajera: ${esc(info.cajera)} (${esc(info.cajera_usuario)}) · Sucursal: ${esc(info.sucursal)}<br>` +
      `Importe: <b>${fmt(info.total)}</b> · Estado: ${esc(String(info.estado).toUpperCase())}<br>` +
      `Loterías: ${esc(lot)}<br>` +
      `Sorteos cerrados: ${esc(cerrados)}<br>` +
      `Premios pendientes: <b>${fmt(info.premios_pendientes_total)}</b>` +
      (info.tiene_premios_pagados ? " · <b>TIENE PREMIOS PAGADOS</b>" : "");
    const avisos = (info.advertencias || []).map((a) => `<p>${esc(a)}</p>`).join("");
    $("#tic-anular-avisos").innerHTML = avisos || "<p>Sin advertencias especiales.</p>";
    $("#tic-anular-motivo").value = "";
    msg("#tic-anular-msg", "");
    $("#tic-anular-confirmar").disabled = !info.puede_anular;
    abrirModal($("#tic-anular-modal"));
  } catch (e) {
    msg("#tic-lista-msg", e.message, false);
  }
}

async function anularTicketLista(boton) {
  await abrirModalAnular(boton.dataset.ticAnular, boton.dataset.ticSerial);
}

async function confirmarAnulacionAdmin() {
  if (!TIC_ANULAR) return;
  const texto = ($("#tic-anular-motivo").value || "").trim();
  if (!texto) {
    msg("#tic-anular-msg", "Indique el motivo de la anulación.", false);
    return;
  }
  if (!TIC_ANULAR.info.puede_anular) {
    msg("#tic-anular-msg", "Este ticket no se puede anular directamente.", false);
    return;
  }
  try {
    const d = await post("/panel/tickets/anular", {
      id: parseInt(TIC_ANULAR.id, 10),
      serial: TIC_ANULAR.serial,
      motivo: texto,
    });
    $("#tic-motivo").value = texto;
    $("#tic-id").value = d.id;
    $("#tic-serial").value = d.serial;
    pintarTicket(d);
    cerrarModal($("#tic-anular-modal"), true);
    cerrarModal($("#tic-modal"), true);
    TIC_ANULAR = null;
    if (history.state && (history.state.modal === "tic-anular-modal" || history.state.modal === "tic-modal")) {
      history.go(-2);
    }
    msg("#tic-lista-msg", `Ticket #${d.id} ANULADO ✔`);
    if (typeof cargarDashboard === "function") {
      try { await cargarDashboard(); } catch (_) { /* opcional */ }
    }
    await pintarListaTickets();
  } catch (e) {
    msg("#tic-anular-msg", e.message, false);
  }
}

/* --------------------------------------------------------------------- caja */
async function cargarCaja() {
  if (!$("#caj-fecha").value) $("#caj-fecha").value = hoyISO();
  if (!$("#cua-fecha").value) $("#cua-fecha").value = hoyISO();
  await listarCaja(); await cargarCuadres();
}
function cajaBody() {
  return {
    sucursal_id: parseInt($("#caj-sucursal").value),
    terminal_id: $("#caj-terminal").value ? parseInt($("#caj-terminal").value) : null,
    monto: parseFloat($("#caj-monto").value || 0), concepto: $("#caj-concepto").value.trim() || null,
  };
}
async function recibirEfectivo() {
  try {
    const r = await post("/panel/caja/recibir", cajaBody());
    msg("#caj-msg", `Efectivo recibido ✔ ${fmt(r.monto)}`); await listarCaja();
  } catch (e) { msg("#caj-msg", e.message, false); }
}
async function registrarGasto() {
  try {
    const r = await post("/panel/caja/gasto", cajaBody());
    msg("#caj-msg", `Gasto registrado ✔ ${fmt(r.monto)}`); await listarCaja();
  } catch (e) { msg("#caj-msg", e.message, false); }
}
async function listarCaja() {
  const fecha = $("#caj-fecha").value || hoyISO();
  const suc = $("#caj-sucursal").value;
  const filas = await api(`/caja/transacciones?fecha=${fecha}${suc ? `&sucursal_id=${suc}` : ""}`);
  tabla("#caj-tabla", ["Hora", "Tipo", "Monto", "Concepto"],
    filas.map((t) => `<tr><td>${esc(t.creado_en)}</td><td>${esc(t.tipo)}</td><td>${fmt(t.monto)}</td><td>${esc(t.concepto || "")}</td></tr>`));
}
async function entregarCuadre() {
  try {
    const r = await post("/panel/caja/cuadre", {
      sucursal_id: parseInt($("#caj-sucursal").value),
      terminal_id: $("#caj-terminal").value ? parseInt($("#caj-terminal").value) : null,
      fecha: $("#cua-fecha").value || hoyISO(),
      efectivo_contado: $("#cua-contado").value ? parseFloat($("#cua-contado").value) : null,
    });
    const caja = $("#cua-resultado");
    caja.className = "estado-box ganador";
    caja.textContent =
      `CUADRE ${r.fecha}\nVentas: ${fmt(r.ventas_total)} · Premios pagados: ${fmt(r.premios_pagados_total)} · ` +
      `Gastos: ${fmt(r.gastos_total)} · Efectivo recibido: ${fmt(r.efectivo_recibido_total)}\n` +
      `TOTAL A ENTREGAR: ${fmt(r.total_a_entregar)}` +
      (r.efectivo_contado !== null ? ` · Contado: ${fmt(r.efectivo_contado)} · Diferencia: ${fmt(r.diferencia)}` : "");
    await cargarCuadres();
  } catch (e) { msg("#caj-msg", e.message, false); }
}
async function cargarCuadres() {
  const suc = $("#caj-sucursal").value;
  const filas = await api(`/cuadres${suc ? `?sucursal_id=${suc}` : ""}`);
  tabla("#cua-tabla", ["Fecha", "Ventas", "Premios", "Gastos", "Recibido", "A entregar", "Diferencia"],
    filas.map((c) => `<tr><td>${esc(c.fecha)}</td><td>${fmt(c.ventas_total)}</td><td>${fmt(c.premios_pagados_total)}</td>
      <td>${fmt(c.gastos_total)}</td><td>${fmt(c.efectivo_recibido_total)}</td><td>${fmt(c.total_a_entregar)}</td>
      <td>${c.diferencia === null ? "—" : fmt(c.diferencia)}</td></tr>`));
}

function filaEntrega(e) {
  const recibir = e.recepcion === "RECIBIDA"
    ? "RECIBIDA"
    : `<button class="btn" data-recibir="${esc(e.id)}">RECIBIR</button>`;
  return `<tr><td>${esc(e.cajera)}</td><td>${esc(e.sucursal)}</td><td>${esc(e.fecha_hora)}</td>
    <td>${fmt(e.monto)}</td><td>${fmt(e.saldo_anterior)}</td><td>${fmt(e.saldo_restante)}</td>
    <td>${esc(e.numero)}</td><td>${esc(e.estado)}</td><td>${recibir}</td></tr>`;
}
async function cargarEntregas() {
  const suc = $("#ent-sucursal").value;
  const datos = await api(`/entregas${suc ? `?sucursal_id=${suc}` : ""}`);
  const columnas = ["Cajera", "Sucursal", "Fecha y hora", "Monto", "Saldo anterior", "Saldo restante", "Número", "Estado", "Recepción"];
  tabla("#ent-reales", columnas, (datos.reales || []).map(filaEntrega));
  tabla("#ent-prueba", columnas, (datos.prueba || []).map(filaEntrega));
  document.querySelectorAll("[data-recibir]").forEach((boton) => {
    boton.addEventListener("click", () => recibirEntrega(boton.dataset.recibir));
  });
}
async function recibirEntrega(id) {
  try {
    await post(`/entregas/${id}/recibir`, {});
    msg("#ent-msg", "Recepción física registrada. El dinero no se descontó otra vez.", true);
    await cargarEntregas();
  } catch (e) { msg("#ent-msg", e.message, false); }
}

/* ---------------------------------------------------- asignar fondo a cajera */
let FONDO_CAJERAS = [];
let FONDO_OPERACION = "";

function mostrarFondo(visible) {
  for (const sec of ["fondos", "comisiones"]) {
    const boton = document.querySelector(`.navbtn[data-sec="${sec}"]`);
    if (boton) boton.hidden = !visible;
  }
  const superBtn = $("#nav-super");
  if (superBtn && !visible && !esSuperAdmin()) superBtn.hidden = true;
}
function nuevaOperacionFondo() {
  FONDO_OPERACION = ("fondo-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10)).slice(0, 40);
}
async function cargarFondos() {
  if (!FONDO_OPERACION) nuevaOperacionFondo();
  const suc = opciones(SUCURSALES, (s) => s.id, (s) => `${s.codigo} — ${s.nombre}`);
  const elegido = $("#fon-sucursal").value;
  $("#fon-sucursal").innerHTML = suc;
  if (elegido) $("#fon-sucursal").value = elegido;
  FONDO_CAJERAS = (await api("/usuarios")).filter((u) => u.rol === "operador");
  pintarCajerasFondo();
  await pintarHistorialFondos();
}
function pintarCajerasFondo() {
  const sucursal = $("#fon-sucursal").value;
  const lista = FONDO_CAJERAS.filter((u) => String(u.sucursal_id) === String(sucursal));
  const elegido = $("#fon-cajera").value;
  $("#fon-cajera").innerHTML = lista.length
    ? opciones(lista, (u) => u.id, (u) => `${u.nombre} (${u.usuario})`)
    : '<option value="">No hay cajeras en esta sucursal</option>';
  if (elegido) $("#fon-cajera").value = elegido;
  pintarCajaFondo();
}
function pintarCajaFondo() {
  const cajera = FONDO_CAJERAS.find((u) => String(u.id) === $("#fon-cajera").value);
  const sucursal = SUCURSALES.find((s) => String(s.id) === $("#fon-sucursal").value);
  if (!cajera) {
    $("#fon-caja").textContent = "Seleccione una cajera para ver MI CAJA.";
    return;
  }
  const miCaja = window.MODO_DESARROLLO ? cajera.saldo_caja_prueba : cajera.saldo_caja;
  const general = sucursal ? sucursal.saldo_actual : "0";
  $("#fon-caja").textContent =
    `MI CAJA: ${fmt(miCaja)} · Caja real: ${fmt(cajera.saldo_caja)} · Caja de prueba: ${fmt(cajera.saldo_caja_prueba)} · Caja general: ${fmt(general)}`;
}
async function asignarFondo() {
  const boton = $("#btn-fondo");
  if (boton.disabled) return;
  const cajera = $("#fon-cajera").value;
  const monto = $("#fon-monto").value;
  if (!cajera) throw new Error("Seleccione una cajera");
  if (!monto || Number(monto) <= 0) throw new Error("El fondo debe ser mayor que cero");
  boton.disabled = true;
  try {
    const r = await post("/fondos", {
      sucursal_id: Number($("#fon-sucursal").value),
      usuario_id: Number(cajera),
      monto: Number(monto),
      tipo: $("#fon-tipo").value,
      operacion_id: FONDO_OPERACION,
      motivo: $("#fon-motivo").value.trim() || null,
    });
    nuevaOperacionFondo();
    $("#fon-monto").value = "";
    msg("#fon-msg", `${r.etiqueta}: ${r.origen} de ${fmt(r.monto)}. MI CAJA queda en ${fmt(r.mi_caja)}.`, true);
    await cargarCatalogos();
    await cargarFondos();
  } finally {
    boton.disabled = false;
  }
}
async function pintarHistorialFondos() {
  const suc = $("#fon-sucursal").value;
  const filas = await api(`/fondos${suc ? `?sucursal_id=${suc}` : ""}`);
  tabla("#fon-tabla",
    ["Fecha y hora", "Cajera", "Sucursal", "Origen", "Monto", "Motivo", "Administrador", "Operación", "Cajón resultante", "Caja general"],
    filas.map((f) => `<tr><td>${esc(f.creado_en)}</td><td>${esc(f.cajera)}</td><td>${esc(f.sucursal)}</td>
      <td>${esc(f.etiqueta)} — ${esc(f.origen)}</td><td>${fmt(f.monto)}</td><td>${esc(f.motivo || "—")}</td>
      <td>${esc(f.administrador)}</td><td>${esc(f.operacion_id)}</td>
      <td>${fmt(f.saldo_cajera_resultante)}</td><td>${fmt(f.saldo_general_resultante)}</td></tr>`));
}

/* --------------------------------------------------------- comisiones */
let COMISION_CAJERAS = [];
let COMISION_OPERACION = "";
async function cargarComisiones() {
  if (!COMISION_OPERACION) {
    COMISION_OPERACION = ("liq-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)).slice(0, 40);
  }
  const hoy = hoyISO();
  if (!$("#com-desde").value) { $("#com-desde").value = hoy; $("#com-hasta").value = hoy; }
  const elegido = $("#com-sucursal").value;
  $("#com-sucursal").innerHTML = opciones(SUCURSALES, (s) => s.id, (s) => `${s.codigo} — ${s.nombre}`);
  if (elegido) $("#com-sucursal").value = elegido;
  COMISION_CAJERAS = (await api("/usuarios")).filter((u) => u.rol === "operador");
  pintarCajerasComision();
  await pintarHistorialComision();
  await pintarLiquidaciones();
}
function pintarCajerasComision() {
  const sucursal = $("#com-sucursal").value;
  const lista = COMISION_CAJERAS.filter((u) => String(u.sucursal_id) === String(sucursal));
  const elegido = $("#com-cajera").value;
  $("#com-cajera").innerHTML = lista.length
    ? opciones(lista, (u) => u.id, (u) => `${u.nombre} (${u.usuario})`)
    : '<option value="">No hay cajeras en esta sucursal</option>';
  if (elegido) $("#com-cajera").value = elegido;
}
async function previewComisionCiclo() {
  const cajera = $("#com-cajera").value;
  const porcentaje = $("#com-porcentaje").value;
  if (!cajera) throw new Error("Seleccione una cajera");
  if (porcentaje === "" || Number(porcentaje) < 0 || Number(porcentaje) > 100) {
    throw new Error("El porcentaje debe estar entre 0 y 100");
  }
  const p = await api(
    `/comisiones/preview-aplicar-ciclo?usuario_id=${Number(cajera)}&porcentaje=${Number(porcentaje)}`,
  );
  const box = $("#com-preview");
  if (box) {
    box.hidden = false;
    box.innerHTML =
      `<b>Vista previa — ${esc(p.cajera)} (${esc(p.usuario)})</b><br>`
      + `Porcentaje: ${esc(p.porcentaje_propuesto)}% · Desde: ${esc(p.aplicar_desde)}<br>`
      + `Ventas válidas ciclo: ${fmt(p.ventas_validas)}`
      + ` · Sin % al vender: ${fmt(p.ventas_sin_porcentaje)}<br>`
      + `Balance actual: ${fmt(p.balance_actual)}`
      + ` → Balance proyectado: <b>${fmt(p.balance_proyectado)}</b>`
      + ` (pagado: ${fmt(p.comision_pagada)})`
      + (p.ya_aplicado_mismo_pct ? `<br><i>Este % ya cubre el inicio del ciclo (idempotente).</i>` : "");
  }
  return p;
}

async function guardarComision() {
  const cajera = $("#com-cajera").value;
  const porcentaje = $("#com-porcentaje").value;
  const aplicarCiclo = !!$("#com-aplicar-ciclo")?.checked;
  if (!cajera) throw new Error("Seleccione una cajera");
  if (porcentaje === "" || Number(porcentaje) < 0 || Number(porcentaje) > 100) {
    throw new Error("El porcentaje debe estar entre 0 y 100");
  }
  if (aplicarCiclo) {
    const p = await previewComisionCiclo();
    const ok = confirm(
      `¿Autoriza aplicar ${p.porcentaje_propuesto}% desde el INICIO DEL CICLO ABIERTO?\n\n`
      + `Cajera: ${p.cajera} (${p.usuario})\n`
      + `Ventas válidas: ${fmt(p.ventas_validas)}\n`
      + `Balance actual: ${fmt(p.balance_actual)}\n`
      + `Balance proyectado: ${fmt(p.balance_proyectado)}\n`
      + `Pagos del ciclo: ${fmt(p.comision_pagada)}\n\n`
      + `No borra ventas ni historiales. No modifica MI CAJA ni Banco General.`,
    );
    if (!ok) return;
  }
  const r = await post("/comisiones", {
    usuario_id: Number(cajera),
    porcentaje: Number(porcentaje),
    aplicar_desde_inicio_ciclo: aplicarCiclo,
  });
  msg("#com-msg", `Porcentaje de ${r.cajera}: ${r.porcentaje}% (desde ${r.vigente_desde})`, true);
  if ($("#com-aplicar-ciclo")) $("#com-aplicar-ciclo").checked = false;
  await pintarHistorialComision();
}
async function pintarHistorialComision() {
  const suc = $("#com-sucursal").value;
  const filas = await api(`/comisiones${suc ? `?sucursal_id=${suc}` : ""}`);
  tabla("#com-historial",
    ["Fecha y hora", "Cajera", "Anterior", "Nuevo", "Vigente desde", "Administrador"],
    filas.map((f) => `<tr><td>${esc(f.creado_en)}</td><td>${esc(f.cajera)}</td>
      <td>${f.porcentaje_anterior == null ? "—" : esc(f.porcentaje_anterior) + "%"}</td>
      <td>${esc(f.porcentaje)}%</td><td>${esc(f.vigente_desde)}</td><td>${esc(f.administrador)}</td></tr>`));
}
function bloqueComision(bloque) {
  if (!bloque) return "—";
  const partes = (bloque.desglose || []).map((d) => `${d.porcentaje}% sobre ${fmt(d.ventas)} = ${fmt(d.comision)}`);
  return `Ventas ${fmt(bloque.ventas_validas)} · Comisión ${fmt(bloque.comision)}` +
    (partes.length > 1 ? ` · ${partes.join(" · ")}` : "");
}
async function verComisiones() {
  const suc = $("#com-sucursal").value;
  const cajera = $("#com-cajera").value;
  const q = new URLSearchParams({ desde: $("#com-desde").value, hasta: $("#com-hasta").value });
  if (suc) q.set("sucursal_id", suc);
  if (cajera) q.set("usuario_id", cajera);
  const datos = await api("/comisiones/resumen?" + q.toString());
  tabla("#com-resumen",
    ["Cajera", "Sucursal", "Porcentaje actual", "Ventas y comisión", "Prueba", "Liquidación"],
    datos.cajeras.map((c) => `<tr><td>${esc(c.cajera)}</td><td>${esc(c.sucursal)}</td>
      <td>${esc(c.porcentaje_actual)}%</td><td>${esc(bloqueComision(c.real))}</td>
      <td>${esc(bloqueComision(c.prueba))}</td>
      <td>${c.liquidacion ? esc(c.liquidacion.estado.toUpperCase()) + " " + fmt(c.liquidacion.importe) : "—"}</td></tr>`));
  msg("#com-res-msg", "Comisiones del período listas", true);
}
async function liquidarComision() {
  const cajera = $("#com-cajera").value;
  if (!cajera) throw new Error("Seleccione una cajera");
  const r = await post("/comisiones/liquidaciones", {
    usuario_id: Number(cajera),
    desde: $("#com-desde").value,
    hasta: $("#com-hasta").value,
    operacion_id: COMISION_OPERACION,
  });
  COMISION_OPERACION = ("liq-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)).slice(0, 40);
  msg("#com-res-msg", `Liquidación ${r.estado.toUpperCase()} por ${fmt(r.importe)}. No se descontó ninguna caja.`, true);
  await pintarLiquidaciones();
  await verComisiones();
}
async function pintarLiquidaciones() {
  const suc = $("#com-sucursal").value;
  const filas = await api(`/comisiones/liquidaciones${suc ? `?sucursal_id=${suc}` : ""}`);
  tabla("#com-liquidaciones",
    ["Período", "Cajera", "Importe", "Estado", "Responsable", "Fecha de pago", ""],
    filas.map((f) => `<tr><td>${esc(f.desde)} a ${esc(f.hasta)}</td><td>${esc(f.cajera)}</td>
      <td>${fmt(f.importe)}</td><td>${esc(f.estado.toUpperCase())}</td><td>${esc(f.responsable || "—")}</td>
      <td>${esc(f.pagada_en || "—")}</td>
      <td>${f.estado === "pendiente" ? `<button class="btn fila" data-pagar-comision="${f.id}">MARCAR PAGADA</button>` : ""}</td></tr>`));
  document.querySelectorAll("[data-pagar-comision]").forEach((boton) => {
    boton.addEventListener("click", () => pagarComision(boton.dataset.pagarComision));
  });
}
async function pagarComision(id) {
  const r = await post(`/comisiones/liquidaciones/${id}/pagar`, {});
  msg("#com-res-msg", `Comisión PAGADA por ${fmt(r.importe)}. MI CAJA y la caja general no cambiaron.`, true);
  await pintarLiquidaciones();
}

/* ----------------------------------------------------------------- reportes */
async function cargarReportes() {
  const hoy = hoyISO();
  if (!$("#rep-desde").value) { $("#rep-desde").value = hoy; $("#rep-hasta").value = hoy; }
  if (!$("#pen-desde").value) { $("#pen-desde").value = hoy; $("#pen-hasta").value = hoy; }
  if (!$("#ven-desde").value) { $("#ven-desde").value = hoy; $("#ven-hasta").value = hoy; }
  const usuarios = await api("/usuarios");
  $("#ven-usuario").innerHTML = opciones(usuarios, (u) => u.id,
    (u) => `${u.nombre} (${u.usuario})`, '<option value="">Todos los usuarios</option>');
}
async function verVentas() {
  try {
    const usu = $("#ven-usuario").value;
    const r = await api(`/reportes/ventas?desde=${$("#ven-desde").value}&hasta=${$("#ven-hasta").value}${usu ? `&usuario_id=${usu}` : ""}`);
    $("#ven-salida").innerHTML =
      `<p class="nota">Tickets: <b>${r.total_tickets}</b> · Total vendido: <b>${fmt(r.total_vendido)}</b> · Premios: <b>${fmt(r.total_premios)}</b></p>`;
    tabla("#ven-tabla", ["Ticket", "Serial", "Banca", "Operador", "Fecha", "Total", "Estado", "Premio"],
      r.tickets.map((t) => `<tr><td>${t.id}</td><td>${esc(t.serial)}</td><td>${esc(t.banca)}</td>
        <td>${esc(t.operador)} (${esc(t.operador_usuario)})</td><td>${esc(t.vendido_en || t.fecha)}</td>
        <td>${fmt(t.total)}</td><td><span class="pill ${esc(t.estado)}">${esc(t.estado)}</span></td><td>${fmt(t.premio_total)}</td></tr>`));
    msg("#ven-msg", "Ventas listas ✔");
  } catch (e) { msg("#ven-msg", e.message, false); }
}
function tablaTickets(contenedor, tickets) {
  tabla(contenedor, ["Ticket", "Serial", "Banca", "Fecha", "Total", "Estado", "Premio"],
    tickets.map((t) => `<tr><td>${t.id}</td><td>${esc(t.serial)}</td><td>${esc(t.banca)}</td><td>${esc(t.fecha)}</td>
      <td>${fmt(t.total)}</td><td><span class="pill ${esc(t.estado)}">${esc(t.estado)}</span></td><td>${fmt(t.premio_total)}</td></tr>`));
}
async function verResumen() {
  try {
    const suc = $("#rep-sucursal").value;
    const r = await api(`/reportes/resumen?desde=${$("#rep-desde").value}&hasta=${$("#rep-hasta").value}&vista=${$("#rep-vista").value}${suc ? `&sucursal_id=${suc}` : ""}`);
    if (r.vista === "final") {
      $("#rep-salida").innerHTML = `<div class="cards">
        <div class="card"><div class="num">${fmt(r.ventas)}</div><div class="lbl">Ventas</div></div>
        <div class="card"><div class="num">${r.total_tickets}</div><div class="lbl">Tickets</div></div>
        <div class="card"><div class="num">${fmt(r.premios_pagados)}</div><div class="lbl">Premios pagados</div></div>
        <div class="card"><div class="num">${fmt(r.premios_pendientes)}</div><div class="lbl">Premios por pagar</div></div>
        <div class="card"><div class="num">${fmt(r.neto)}</div><div class="lbl">Neto</div></div>
        <div class="card"><div class="num">${fmt(r.comision_total)}</div><div class="lbl">Comisión bancas</div></div>
        <div class="card"><div class="num">${r.anulados_cantidad} · ${fmt(r.anulados_monto)}</div><div class="lbl">Anulados</div></div>
      </div>`;
    } else if (r.vista === "por_loteria") {
      tabla("#rep-salida", ["Sorteo", "Jugadas", "Ventas", "Premios"],
        r.filas.map((f) => `<tr><td>${esc(f.sorteo)}</td><td>${f.jugadas}</td><td>${fmt(f.ventas)}</td><td>${fmt(f.premios)}</td></tr>`));
    } else {
      tablaTickets("#rep-salida", r.tickets || []);
    }
    msg("#rep-msg", "Reporte listo ✔");
  } catch (e) { msg("#rep-msg", e.message, false); }
}
async function verPendientes() {
  try {
    const r = await api(`/reportes/pendientes?desde=${$("#pen-desde").value}&hasta=${$("#pen-hasta").value}&sucursal_id=${$("#pen-sucursal").value}`);
    let html = `<p class="nota">Pendientes de pago: <b>${fmt(r.monto_pendiente)}</b> · Pagados en otra sucursal: <b>${fmt(r.pagado_en_otra_monto)}</b> · Total pagado: <b>${fmt(r.total_pagado)}</b></p>`;
    $("#pen-salida").innerHTML = html;
    tablaTickets("#pen-salida", r.pendientes);
    msg("#pen-msg", "Pendientes listos ✔");
  } catch (e) { msg("#pen-msg", e.message, false); }
}
async function verPendientesTexto() {
  try {
    const t = await api(`/reportes/pendientes?desde=${$("#pen-desde").value}&hasta=${$("#pen-hasta").value}&sucursal_id=${$("#pen-sucursal").value}&formato=texto`);
    const pre = $("#pen-texto");
    pre.style.display = "block";
    pre.textContent = t;
    msg("#pen-msg", "Formato impreso listo ✔ (el mismo que sale por la térmica)");
  } catch (e) { msg("#pen-msg", e.message, false); }
}
function imprimirPendientes() {
  const texto = $("#pen-texto").textContent;
  if (!texto) { msg("#pen-msg", "Primero genere el FORMATO IMPRESO", false); return; }
  const w = window.open("", "_blank");
  w.document.write(`<pre style="font-family:monospace">${esc(texto)}</pre>`);
  w.document.close(); w.print();
}

/* ----------------------------------------- reporte ventas resumido (Lotería) */
const RVR = {
  filtros: null,
  datos: null,
  mostrarCajeros: false,
  consulta: 0,
  pagina: 1,
  porPagina: 12,
  zoom: 100,
  buscar: "",
};

function rvrFecha(iso) {
  const p = String(iso || "").split("-");
  return p.length === 3 ? `${p[2]}/${p[1]}/${p[0]}` : esc(iso || "");
}
function rvrMonto(v) {
  const n = Number(v);
  const txt = fmt(v);
  if (!Number.isFinite(n) || n >= 0) return esc(txt);
  return `<span class="rvr-neg">${esc(txt)}</span>`;
}

function rvrCeldasLoteria(bloque) {
  return `<td>${rvrMonto(bloque.venta)}</td><td>${rvrMonto(bloque.comision)}</td>
    <td>${rvrMonto(bloque.neto)}</td><td>${rvrMonto(bloque.premios)}</td>
    <td>${rvrMonto(bloque.resultado)}</td>`;
}

function rvrCeldasRecargas(bloque, resultadoTotal) {
  // Sección visual LotoBet (siempre visible). Sin producto real → 0.00.
  const rec = bloque || { venta: "0", comision: "0", neto: "0" };
  return `<td>${rvrMonto(rec.venta)}</td><td>${rvrMonto(rec.comision)}</td>
    <td>${rvrMonto(rec.neto)}</td><td>${rvrMonto(resultadoTotal)}</td>`;
}

function rvrFilasPlanas(datos) {
  const filas = [];
  for (const g of (datos.grupos || [])) {
    filas.push({ tipo: "grupo", grupo: g });
    for (const b of (g.bancas || [])) {
      filas.push({ tipo: "banca", banca: b, grupo: g });
      if (RVR.mostrarCajeros) {
        for (const cajero of (b.cajeros || [])) filas.push({ tipo: "cajero", cajero, banca: b });
        if ((b.cajeros || []).length) {
          filas.push({ tipo: "comision_cajeras", monto: b.total_comision_cajeras, banca: b });
        }
      }
    }
    filas.push({ tipo: "subtotal", grupo: g });
  }
  filas.push({ tipo: "total", total: datos.total });
  filas.push({ tipo: "total_bancas", total: datos.total });
  filas.push({ tipo: "promedio", total: datos.total });
  return filas;
}

function rvrCoincideBusqueda(fila, q) {
  if (!q) return true;
  const t = q.toLowerCase();
  if (fila.tipo === "grupo") return (fila.grupo.grupo_nombre || "").toLowerCase().includes(t);
  if (fila.tipo === "cajero" || fila.tipo === "banca") {
    const b = fila.banca;
    return `${b.banca} ${b.codigo} ${fila.cajero?.nombre || ""}`.toLowerCase().includes(t);
  }
  if (fila.tipo === "subtotal") return "sub-total".includes(t) || "subtotal".includes(t) || (fila.grupo.grupo_nombre || "").toLowerCase().includes(t);
  if (fila.tipo === "total" || fila.tipo === "total_bancas" || fila.tipo === "promedio") {
    return "total".includes(t) || "promedio".includes(t) || "bancas".includes(t);
  }
  return true;
}

function rvrEscaparRe(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function rvrResaltar(html, q) {
  if (!q) return html;
  try {
    const re = new RegExp("(" + rvrEscaparRe(q) + ")", "gi");
    return html.replace(re, '<mark class="rvr-mark">$1</mark>');
  } catch {
    return html;
  }
}

function rvrHtmlDocumento(datos, filas, buscar) {
  // Recargas siempre visible (LotoBet). Valores 0.00 hasta existir el producto.
  const colSpan = 10;
  const vacioRec = { venta: "0.00", comision: "0.00", neto: "0.00" };
  let cuerpo = "";
  for (const f of filas) {
    if (f.tipo === "grupo") {
      const n = (f.grupo.bancas || []).length || (f.grupo.subtotal && f.grupo.subtotal.bancas) || 0;
      cuerpo += `<tr class="grupo"><td class="izq" colspan="${colSpan}">Grupo: ${esc(f.grupo.grupo_nombre)}&nbsp;&nbsp;&nbsp;Total de Bancas: (${n})</td></tr>`;
    } else if (f.tipo === "banca") {
      const b = f.banca;
      cuerpo += `<tr class="banca">
        <td class="izq">${esc(b.codigo)} ${esc(b.banca)}</td>
        ${rvrCeldasLoteria(b.loteria)}
        ${rvrCeldasRecargas(b.recargas || vacioRec, b.resultado_total)}
      </tr>`;
    } else if (f.tipo === "cajero") {
      const c = f.cajero;
      cuerpo += `<tr class="banca">
        <td class="izq">&nbsp;&nbsp;Cajero: ${esc(c.nombre)}</td>
        <td>${rvrMonto(c.venta)}</td>
        <td>${rvrMonto(c.comision)}</td>
        <td>${rvrMonto(c.neto)}</td>
        <td>${rvrMonto(c.premios)}</td>
        <td>${rvrMonto(c.resultado)}</td>
        <td></td><td></td><td></td><td></td>
      </tr>`;
    } else if (f.tipo === "comision_cajeras") {
      cuerpo += `<tr class="banca">
        <td class="izq">&nbsp;&nbsp;Total comisión de cajeras</td>
        <td></td>
        <td>${rvrMonto(f.monto)}</td>
        <td></td><td></td><td></td><td></td><td></td><td></td><td></td>
      </tr>`;
    } else if (f.tipo === "subtotal") {
      const s = f.grupo.subtotal;
      cuerpo += `<tr class="bloque-totales">
        <td class="izq">Sub-Total</td>
        ${rvrCeldasLoteria(s.loteria)}
        ${rvrCeldasRecargas(s.recargas || vacioRec, s.resultado_total)}
      </tr>`;
    } else if (f.tipo === "total") {
      const t = f.total;
      cuerpo += `<tr class="bloque-totales">
        <td class="izq">Total</td>
        ${rvrCeldasLoteria(t.loteria)}
        ${rvrCeldasRecargas(t.recargas || vacioRec, t.resultado_total)}
      </tr>`;
    } else if (f.tipo === "total_bancas") {
      cuerpo += `<tr class="bloque-totales"><td class="izq" colspan="${colSpan}">Total de Bancas: (${f.total.bancas})</td></tr>`;
    } else if (f.tipo === "promedio") {
      cuerpo += `<tr class="bloque-totales"><td class="izq" colspan="${colSpan}">Promedio de Ventas por Banca: (${esc(fmt(f.total.promedio_venta))})</td></tr>`;
    }
  }
  if (!filas.length) {
    cuerpo = `<tr><td class="rvr-vacio" colspan="${colSpan}">Sin bancas para los filtros seleccionados.</td></tr>`;
  }
  const html = `
    <div class="rvr-doc-cab">
      <div class="emp">${esc(datos.empresa || "BANCA MODERNA")}</div>
      <div class="hora">Fecha/Hora ${esc(datos.impreso || "")}</div>
      <div class="tit">Resumen de Ventas</div>
      <div class="meta">Desde ${rvrFecha(datos.desde)} al ${rvrFecha(datos.hasta)}</div>
    </div>
    <table class="rvr-tabla">
      <thead>
        <tr>
          <th class="izq" rowspan="2">Banca</th>
          <th colspan="5" class="sec-lot">LOTERÍA</th>
          <th colspan="3" class="sec-rec">RECARGAS</th>
          <th class="sec-total" rowspan="2">Resultado Total</th>
        </tr>
        <tr>
          <th>Venta</th><th>Comisión</th><th>Neto</th><th>Premios</th><th>Resultado</th>
          <th>Venta</th><th>Comisión</th><th>Neto</th>
        </tr>
      </thead>
      <tbody>${cuerpo}</tbody>
    </table>`;
  return rvrResaltar(html, buscar || "");
}

function renderVentasResumido() {
  const hoja = $("#rvr-hoja");
  const visor = $("#rvr-visor");
  if (!hoja || !visor || !RVR.datos) return;
  visor.hidden = false;
  rvrMarcarVisor(true);
  const d = RVR.datos;
  const planas = rvrFilasPlanas(d).filter((f) => rvrCoincideBusqueda(f, RVR.buscar));
  const cuerpo = planas.filter((f) => ["grupo", "banca", "cajero", "comision_cajeras", "subtotal"].includes(f.tipo));
  const cierre = planas.filter((f) => ["total", "total_bancas", "promedio"].includes(f.tipo));
  const totalPag = Math.max(1, Math.ceil(Math.max(cuerpo.length, 1) / RVR.porPagina));
  if (RVR.pagina > totalPag) RVR.pagina = totalPag;
  if (RVR.pagina < 1) RVR.pagina = 1;
  const ini = (RVR.pagina - 1) * RVR.porPagina;
  let paginaFilas = cuerpo.slice(ini, ini + RVR.porPagina);
  if (RVR.pagina === totalPag) paginaFilas = paginaFilas.concat(cierre);
  hoja.innerHTML = rvrHtmlDocumento(d, paginaFilas, RVR.buscar);
  hoja.dataset.zoom = String(RVR.zoom);
  const pagEl = $("#rvr-pagina");
  if (pagEl) pagEl.textContent = `${RVR.pagina} / ${totalPag}`;
  const prev = $("#btn-rvr-prev");
  const next = $("#btn-rvr-next");
  if (prev) prev.disabled = RVR.pagina <= 1;
  if (next) next.disabled = RVR.pagina >= totalPag;
}

function rvrParametros() {
  const q = new URLSearchParams();
  q.set("desde", $("#rvr-desde").value);
  q.set("hasta", $("#rvr-hasta").value);
  const banca = $("#rvr-banca").value;
  const grupo = $("#rvr-grupo").value;
  const ruta = $("#rvr-ruta").value;
  if (banca) q.set("sucursal_id", banca);
  if (grupo) q.set("grupo_id", grupo);
  if (ruta) q.set("ruta_id", ruta);
  return q;
}

function rvrPoblarSelects() {
  const f = RVR.filtros || { grupos: [], bancas: [], rutas: [] };
  const gSel = $("#rvr-grupo");
  const bSel = $("#rvr-banca");
  const rSel = $("#rvr-ruta");
  if (!gSel || !bSel || !rSel) return;
  const gid = gSel.value;
  gSel.innerHTML = '<option value="">TODOS LOS GRUPOS</option>' +
    (f.grupos || []).map((g) => `<option value="${esc(g.id)}">${esc(g.nombre)}</option>`).join("");
  if (gid) gSel.value = gid;
  const grupoActivo = gSel.value;
  const bancas = (f.bancas || []).filter((b) => !grupoActivo || b.grupo_id === grupoActivo);
  const bid = bSel.value;
  bSel.innerHTML = '<option value="">TODAS LAS BANCAS</option>' +
    bancas.map((b) => `<option value="${b.id}">${esc(b.codigo)} — ${esc(b.nombre)}</option>`).join("");
  if (bid && [...bSel.options].some((o) => o.value === bid)) bSel.value = bid;
  const rutas = f.rutas || [];
  rSel.innerHTML = '<option value="">TODAS LAS RUTAS</option>' +
    rutas.map((r) => `<option value="${esc(r.id)}">${esc(r.nombre)}</option>`).join("");
  const wrap = $("#rvr-ruta-wrap");
  if (wrap) wrap.style.display = rutas.length ? "" : "";
}

function rvrPintarFechas() {
  for (const id of ["rvr-desde", "rvr-hasta"]) {
    const input = document.getElementById(id);
    const vista = document.getElementById(id + "-vista");
    if (!input || !vista) continue;
    vista.textContent = input.value ? rvrFecha(input.value) : "DD/MM/AAAA";
  }
}

async function cargarVentasResumido() {
  const hoy = hoyISO();
  if ($("#rvr-desde") && !$("#rvr-desde").value) $("#rvr-desde").value = hoy;
  if ($("#rvr-hasta") && !$("#rvr-hasta").value) $("#rvr-hasta").value = hoy;
  rvrPintarFechas();
  try {
    RVR.filtros = await api("/reportes/ventas-resumido/filtros");
    rvrPoblarSelects();
    msg("#rvr-msg", "Filtros listos. Pulse VER para consultar.", true);
  } catch (e) {
    msg("#rvr-msg", e.message, false);
  }
}

async function verVentasResumido(mostrarCajeros = RVR.mostrarCajeros) {
  const consulta = ++RVR.consulta;
  try {
    const q = rvrParametros();
    const datos = await api("/reportes/ventas-resumido?" + q.toString());
    if (consulta !== RVR.consulta) return;
    RVR.datos = datos;
    RVR.mostrarCajeros = mostrarCajeros;
    RVR.pagina = 1;
    renderVentasResumido();
    msg("#rvr-msg", `Reporte listo · ${RVR.datos.total.bancas} banca(s)`, true);
  } catch (e) {
    if (consulta !== RVR.consulta) return;
    msg("#rvr-msg", e.message, false);
  }
}

async function rvrObtenerPdf() {
  if (!$("#rvr-desde").value || !$("#rvr-hasta").value) {
    msg("#rvr-msg", "Indique el rango de fechas", false);
    return null;
  }
  const q = rvrParametros();
  if (RVR.mostrarCajeros) q.set("desglose", "cajeros");
  const r = await fetch("/reportes/ventas-resumido.pdf?" + q.toString(), {
    headers: TOKEN ? { Authorization: "Bearer " + TOKEN } : {},
  });
  if (!r.ok) {
    let detalle = "No se pudo generar el PDF";
    try {
      const j = await r.json();
      detalle = (j && j.detail) || detalle;
    } catch { /* el cuerpo no era JSON */ }
    throw new Error(typeof detalle === "string" ? detalle : "No se pudo generar el PDF");
  }
  const blob = await r.blob();
  if (!blob || !blob.size) throw new Error("El PDF llegó vacío");
  return blob;
}

function rvrNombrePdf() {
  const desde = $("#rvr-desde").value || "desde";
  const hasta = $("#rvr-hasta").value || "hasta";
  return `Resumen-de-Ventas-${desde}-al-${hasta}.pdf`;
}

async function descargarPdfVentasResumido() {
  try {
    const blob = await rvrObtenerPdf();
    if (!blob) return;
    const url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = rvrNombrePdf();
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    msg("#rvr-msg", "PDF A4 horizontal descargado. No usa la impresora de Windows.", true);
  } catch (e) {
    msg("#rvr-msg", e.message, false);
  }
}

async function imprimirVentasResumido() {
  try {
    const blob = await rvrObtenerPdf();
    if (!blob) return;
    const url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
    const w = window.open(url, "_blank");
    if (!w) {
      msg("#rvr-msg", "El navegador bloqueó la ventana. Use DESCARGAR PDF: el archivo ya es A4 horizontal.", false);
      return;
    }
    const lanzar = () => {
      try { w.focus(); w.print(); } catch { /* el visor PDF imprime cuando termina de abrir */ }
    };
    setTimeout(lanzar, 700);
    msg("#rvr-msg", "Documento A4 horizontal, sin el panel. La hoja del PDF no depende de la impresora térmica.", true);
  } catch (e) {
    msg("#rvr-msg", e.message, false);
  }
}

function rvrPrepararImpresionPanel() {
  if (!RVR.datos || !$("#rvr-hoja")) return;
  const planas = rvrFilasPlanas(RVR.datos);
  $("#rvr-hoja").innerHTML = rvrHtmlDocumento(RVR.datos, planas, "");
  $("#rvr-hoja").dataset.zoom = "100";
}

function rvrEsMovil() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function rvrMarcarVisor(abierto) {
  const on = !!abierto && rvrEsMovil();
  const sec = document.getElementById("sec-ventas-resumido");
  if (sec) sec.classList.toggle("rvr-movil-abierto", on);
  document.documentElement.classList.toggle("rvr-movil-abierto", on);
  document.body.classList.toggle("rvr-movil-abierto", on);
}

function volverFiltrosVentasResumido() {
  const visor = $("#rvr-visor");
  if (visor) visor.hidden = true;
  rvrMarcarVisor(false);
  const filtros = document.getElementById("rvr-filtros");
  if (filtros) filtros.scrollIntoView({ block: "start" });
}

function regresarVentasResumido() {
  volverFiltrosVentasResumido();
  RVR.datos = null;
  ir("reportes");
}

/* ---------------------------------------------- reporte de tickets (consulta) */
const RTK = {
  cajeros: [],
  filtros: null,
  datos: null,
  consulta: null,
  detalle: null,
  reciboUrl: "",
  vista: null,
  pagina: 1,
  porPagina: 12,
  zoom: 100,
  buscar: "",
};

function rtkPintarFechas() {
  for (const id of ["rtk-desde", "rtk-hasta"]) {
    const input = document.getElementById(id);
    const vista = document.getElementById(id + "-vista");
    if (!input || !vista) continue;
    vista.textContent = input.value ? rvrFecha(input.value) : "DD/MM/AAAA";
  }
}

function rtkCuando(iso) {
  const texto = String(iso || "").trim();
  if (!texto) return "";
  const [fecha, hora] = texto.split(" ");
  const p = fecha.split("-");
  const hm = (hora || "").slice(0, 5);
  if (p.length === 3) return `${p[2]}/${p[1]}/${p[0]}${hm ? " " + hm : ""}`;
  return texto;
}

function rtkEstado(valor) {
  return String(valor || "todos").replaceAll("_", " ").toUpperCase();
}

function rtkPoblarSelects() {
  const f = RTK.filtros || { grupos: [], bancas: [], rutas: [] };
  const gSel = $("#rtk-grupo");
  const bSel = $("#rtk-banca");
  const rSel = $("#rtk-ruta");
  const lSel = $("#rtk-loteria");
  if (!gSel || !bSel || !rSel || !lSel) return;
  const gid = gSel.value;
  gSel.innerHTML = '<option value="">TODOS LOS GRUPOS</option>' +
    (f.grupos || []).map((g) => `<option value="${esc(g.id)}">${esc(g.nombre)}</option>`).join("");
  if (gid) gSel.value = gid;
  const grupoActivo = gSel.value;
  const bancas = (f.bancas || []).filter((b) => !grupoActivo || b.grupo_id === grupoActivo);
  const bid = bSel.value;
  bSel.innerHTML = '<option value="">TODAS LAS BANCAS</option>' +
    bancas.map((b) => `<option value="${b.id}">${esc(b.codigo)} — ${esc(b.nombre)}</option>`).join("");
  if (bid && [...bSel.options].some((o) => o.value === bid)) bSel.value = bid;
  const rid = rSel.value;
  rSel.innerHTML = '<option value="">TODAS LAS RUTAS</option>' +
    (f.rutas || []).map((r) => `<option value="${esc(r.id)}">${esc(r.nombre)}</option>`).join("");
  if (rid) rSel.value = rid;
  const lid = lSel.value;
  lSel.innerHTML = '<option value="">TODAS LAS LOTERÍAS</option>' +
    opciones(SORTEOS, (s) => s.id, (s) => s.nombre);
  if (lid && [...lSel.options].some((o) => o.value === lid)) lSel.value = lid;
  rtkPoblarCajeros();
}

function rtkPoblarCajeros() {
  const banca = $("#rtk-banca") ? $("#rtk-banca").value : "";
  const previo = $("#rtk-cajero") ? $("#rtk-cajero").value : "";
  const lista = RTK.cajeros.filter((u) => !banca || String(u.sucursal_id) === String(banca));
  $("#rtk-cajero").innerHTML =
    '<option value="">TODOS LOS CAJEROS</option>' +
    opciones(lista, (u) => u.id, (u) => `${u.nombre} (${u.usuario})`);
  if ([...$("#rtk-cajero").options].some((o) => o.value === previo)) $("#rtk-cajero").value = previo;
}

function rtkFiltrosFormulario() {
  return {
    desde: $("#rtk-desde").value,
    hasta: $("#rtk-hasta").value,
    hora_desde: $("#rtk-hora-desde").value || "00:00",
    hora_hasta: $("#rtk-hora-hasta").value || "23:59",
    grupo_id: $("#rtk-grupo").value,
    sucursal_id: $("#rtk-banca").value,
    sorteo_id: $("#rtk-loteria").value,
    estado: $("#rtk-estado").value,
    ruta_id: $("#rtk-ruta").value,
    orden: $("#rtk-orden").value || "numero",
    usuario_id: $("#rtk-cajero").value,
    ticket_id: ($("#rtk-numero").value || "").trim(),
  };
}

function rtkParametros(filtros) {
  const f = filtros || rtkFiltrosFormulario();
  const q = new URLSearchParams();
  q.set("desde", f.desde || "");
  q.set("hasta", f.hasta || "");
  q.set("hora_desde", f.hora_desde || "00:00");
  q.set("hora_hasta", f.hora_hasta || "23:59");
  q.set("orden", f.orden || "numero");
  if (f.grupo_id) q.set("grupo_id", f.grupo_id);
  if (f.sucursal_id) q.set("sucursal_id", f.sucursal_id);
  if (f.sorteo_id) q.set("sorteo_id", f.sorteo_id);
  if (f.usuario_id) q.set("usuario_id", f.usuario_id);
  if (f.estado) q.set("estado", f.estado);
  if (f.ruta_id) q.set("ruta_id", f.ruta_id);
  if (f.ticket_id) q.set("ticket_id", f.ticket_id);
  return q;
}

function rtkFilasVisibles() {
  const todas = (RTK.datos && RTK.datos.tickets) || [];
  const q = (RTK.buscar || "").trim().toLowerCase();
  if (!q) return todas;
  return todas.filter((t) => {
    const txt = [
      t.id, t.serial, t.sucursal, t.sucursal_codigo, t.cajera, t.cajera_usuario,
      t.cajera ? "" : "Cajero sin registrar",
      t.estado, t.etiqueta_estado, t.usuario_pago, t.usuario_anulo,
    ].join(" ").toLowerCase();
    return txt.includes(q);
  });
}

function rtkLineasPagina(filas, agrupar) {
  const paginas = Math.max(1, Math.ceil(Math.max(filas.length, 1) / RTK.porPagina));
  if (RTK.pagina > paginas) RTK.pagina = paginas;
  if (RTK.pagina < 1) RTK.pagina = 1;
  const ini = (RTK.pagina - 1) * RTK.porPagina;
  const slice = filas.slice(ini, ini + RTK.porPagina);
  const lineas = [];
  let previo = null;
  for (const t of slice) {
    if (agrupar && t.estado !== previo) {
      const n = filas.filter((x) => x.estado === t.estado).length;
      lineas.push({ tipo: "grupo", etiqueta: t.etiqueta_estado || t.estado, n });
      previo = t.estado;
    }
    lineas.push({ tipo: "ticket", t });
  }
  return { lineas, paginas };
}

function rtkHtmlDocumento(datos, filas, resumen, conDetalle) {
  const f = (datos && datos.filtros) || {};
  const numero = f.ticket_id ? ` · N.º ${esc(f.ticket_id)}` : "";
  const detalle = conDetalle !== false;
  const agrupar = !!(datos && datos.agrupar_estado);
  const pack = detalle
    ? rtkLineasPagina(filas, agrupar)
    : { lineas: rtkLineasCompletas(filas, agrupar), paginas: 1 };
  const cuerpo = pack.lineas.map((linea) => {
    if (linea.tipo === "grupo") {
      const sufijo = linea.n === 1 ? "ticket" : "tickets";
      return `<tr class="grupo"><td class="izq" colspan="9">${esc(linea.etiqueta)} · ${linea.n} ${sufijo}</td></tr>`;
    }
    const t = linea.t;
    const ganado = Number(t.premio_total || 0) > 0 ? fmt(t.premio_total) : "";
    const vendedor = String(t.cajera || "").trim() || "Cajero sin registrar";
    const numeroCelda = detalle
      ? `<button type="button" class="rtk-num" data-rtk-ver="${esc(t.id)}">${esc(t.id)}</button>`
      : esc(t.id);
    return `<tr>
      <td class="izq"><div>${esc(t.sucursal_codigo)} ${esc(t.sucursal)}</div><div class="rtk-vendedor">${esc(vendedor)}</div></td>
      <td class="corto">${esc(rtkCuando(t.vendido_en))}</td>
      <td class="corto">${numeroCelda}</td>
      <td>${esc(fmt(t.total))}</td>
      <td>${ganado ? esc(ganado) : ""}</td>
      <td class="izq">${esc(t.usuario_pago || "")}</td>
      <td class="corto">${esc(rtkCuando(t.fecha_pago))}</td>
      <td class="izq">${esc(t.usuario_anulo || "")}</td>
      <td class="corto">${esc(rtkCuando(t.fecha_anulacion))}</td>
    </tr>`;
  }).join("");
  const n = resumen ? resumen.n : filas.length;
  const suma = resumen ? resumen.suma : filas.reduce((acc, t) => acc + Number(t.total || 0), 0);
  const premio = resumen ? resumen.premio : filas.reduce((acc, t) => acc + Number(t.premio_total || 0), 0);
  return `<div class="rvr-doc-cab">
      <div class="emp">${esc(datos.empresa || "BANCA MODERNA")}</div>
      <div class="hora">Fecha/Hora ${esc(datos.impreso || "")}</div>
      <div class="tit">Resumen de Tickets</div>
      <div class="meta">Desde ${rvrFecha(datos.desde)} ${esc(f.hora_desde || "00:00")} al ${rvrFecha(datos.hasta)} ${esc(f.hora_hasta || "23:59")}</div>
      <div class="meta">Grupo: ${esc(f.grupo || "TODOS LOS GRUPOS")} · Banca: ${esc(f.banca || "TODAS LAS BANCAS")} · Lotería: ${esc(f.loteria || "TODAS LAS LOTERÍAS")} · Estado: ${esc(rtkEstado(f.estado))}</div>
      <div class="meta">Ruta: ${esc(f.ruta || "TODAS LAS RUTAS")} · Cajero: ${esc(f.cajero || "TODOS LOS CAJEROS")} · Orden: ${esc(f.orden || "numero")}${numero}</div>
    </div>
    <table class="rvr-tabla">
      <thead><tr>
        <th class="izq">Banca</th><th class="corto">Fecha y hora</th><th class="corto">N.º</th>
        <th>Total apostado</th><th>Total ganado</th><th class="izq">Usuario que pagó</th>
        <th class="corto">Fecha de pago</th><th class="izq">Usuario que anuló</th><th class="corto">Fecha de anulación</th>
      </tr></thead>
      <tbody>
        ${cuerpo || `<tr><td class="izq" colspan="9">No hay tickets con esos filtros.</td></tr>`}
        <tr class="bloque-totales">
          <td class="izq">Total</td>
          <td></td>
          <td class="corto">${n} ticket(s)</td>
          <td>${esc(fmt(suma))}</td>
          <td>${Number(premio) > 0 ? esc(fmt(premio)) : ""}</td>
          <td colspan="4"></td>
        </tr>
      </tbody>
    </table>`;
}

function rtkLineasCompletas(filas, agrupar) {
  const lineas = [];
  let previo = null;
  for (const t of filas) {
    if (agrupar && t.estado !== previo) {
      const n = filas.filter((x) => x.estado === t.estado).length;
      lineas.push({ tipo: "grupo", etiqueta: t.etiqueta_estado || t.estado, n });
      previo = t.estado;
    }
    lineas.push({ tipo: "ticket", t });
  }
  return lineas;
}

function rtkScroll() {
  return document.querySelector("#sec-reporte-tickets .rvr-scroll");
}

function rtkRaizScroll() {
  return document.scrollingElement || document.documentElement;
}

function rtkMarcarDetalle(activo) {
  const btn = $("#btn-rtk-volver");
  if (btn) btn.hidden = !activo;
  const hoja = $("#rtk-hoja");
  if (hoja) hoja.classList.toggle("rtk-detalle", !!activo);
}

function rtkTituloGrupo(sorteos) {
  const partes = (sorteos || []).map((s) => {
    const nombre = String(s.nombre || "").trim();
    const horario = String(s.horario || "").trim();
    if (horario && !nombre.toLowerCase().includes(horario.toLowerCase())) {
      return `${nombre} · ${horario}`.replace(/^ · | · $/g, "");
    }
    return nombre;
  }).filter(Boolean);
  return partes.join(" + ") || "Sin lotería";
}

function rtkHtmlDetalle(d) {
  const grupos = (d.grupos || []).map((g) => {
    const titulo = rtkTituloGrupo(g.sorteos);
    const filas = (g.jugadas || []).map((j) => {
      const ganado = j.premio != null ? fmt(j.premio) : "";
      return `<tr>
        <td class="izq">${esc(j.tipo_nombre)} ${esc(j.numeros)}</td>
        <td>${esc(fmt(j.monto))}</td>
        <td>${ganado ? esc(ganado) : ""}</td>
      </tr>`;
    }).join("");
    return `<tr class="grupo"><td class="izq" colspan="3">${esc(titulo)}</td></tr>${filas}`;
  }).join("");
  const pagosCab = (d.pagos || []).map((p) =>
    `${p.usuario || ""}${p.fecha ? " el " + rtkCuando(p.fecha) : ""}`.trim()).filter(Boolean);
  const pago = pagosCab.length ? `<div class="meta">Pagado por ${esc(pagosCab.join(" · "))}</div>` : "";
  const anulado = d.fecha_anulacion
    ? `<div class="meta">Anulado por ${esc(d.usuario_anulo || "")} el ${esc(rtkCuando(d.fecha_anulacion))}</div>`
    : "";
  const historial = (d.pagos || []).map((p) => `<tr>
      <td class="izq">${esc(p.usuario || "")}</td>
      <td class="corto">${esc(rtkCuando(p.fecha))}</td>
      <td>${esc(fmt(p.monto))}</td>
    </tr>`).join("") || `<tr><td class="izq" colspan="3">Sin pagos</td></tr>`;
  return `<div class="rvr-doc-cab">
      <div class="emp">${esc(d.empresa || "BANCA MODERNA")}</div>
      <div class="tit">Ticket #${esc(d.id)}</div>
      <div class="meta">${esc(d.banca_codigo || "")} ${esc(d.banca_nombre || d.banca || "")}</div>
      <div class="meta">Fecha y hora ${esc(rtkCuando(d.fecha_hora))}</div>
      <div class="meta">Estado: ${esc(d.etiqueta_estado || rtkEstado(d.estado))}</div>
      ${pago}${anulado}
    </div>
    <table class="rvr-tabla">
      <thead><tr>
        <th class="izq">Tipo y número</th><th>Apostado</th><th>Ganado</th>
      </tr></thead>
      <tbody>
        ${grupos || `<tr><td class="izq" colspan="3">Sin jugadas</td></tr>`}
      </tbody>
    </table>
    <table class="rvr-tabla rtk-cierre">
      <tbody>
        <tr class="bloque-totales"><td class="izq">Total apostado</td><td class="rtk-monto">${esc(fmt(d.total))}</td></tr>
        <tr class="bloque-totales"><td class="izq">Premio ganado</td><td class="rtk-monto">${esc(fmt(d.premio_ganado))}</td></tr>
        <tr class="bloque-totales"><td class="izq">Monto pagado</td><td class="rtk-monto">${esc(fmt(d.importe_pagado))}</td></tr>
        <tr class="bloque-totales"><td class="izq">Saldo pendiente</td><td class="rtk-monto">${esc(fmt(d.importe_pendiente))}</td></tr>
      </tbody>
    </table>
    <div class="rvr-doc-cab" style="margin-top:12px">
      <div class="tit">Historial de pagos</div>
    </div>
    <table class="rvr-tabla">
      <thead><tr><th class="izq">Usuario</th><th class="corto">Fecha</th><th>Monto</th></tr></thead>
      <tbody>${historial}</tbody>
    </table>`;
}

function renderReporteTickets() {
  const hoja = $("#rtk-hoja");
  if (!hoja || !RTK.datos) return;
  RTK.detalle = null;
  rtkMarcarDetalle(false);
  const filas = rtkFilasVisibles();
  const suma = filas.reduce((n, t) => n + Number(t.total || 0), 0);
  const premio = filas.reduce((n, t) => n + Number(t.premio_total || 0), 0);
  const pack = rtkLineasPagina(filas, !!RTK.datos.agrupar_estado);
  hoja.innerHTML = rtkHtmlDocumento(RTK.datos, filas, { n: filas.length, suma, premio }, true);
  hoja.dataset.zoom = String(RTK.zoom);
  const pag = $("#rtk-pagina");
  if (pag) pag.textContent = `${RTK.pagina} / ${pack.paginas}`;
  const prev = $("#btn-rtk-prev");
  const next = $("#btn-rtk-next");
  if (prev) prev.disabled = RTK.pagina <= 1;
  if (next) next.disabled = RTK.pagina >= pack.paginas;
}

function pintarDetalleReporteTicket() {
  const hoja = $("#rtk-hoja");
  if (!hoja || !RTK.detalle) return;
  const src = RTK.reciboUrl || "";
  hoja.innerHTML = `<div class="rtk-recibo"><img alt="Recibo del ticket ${esc(RTK.detalle.id)}" src="${src}"></div>`;
  hoja.dataset.zoom = String(RTK.zoom);
  rtkMarcarDetalle(true);
  const pag = $("#rtk-pagina");
  if (pag) pag.textContent = `Ticket #${RTK.detalle.id}`;
  const prev = $("#btn-rtk-prev");
  const next = $("#btn-rtk-next");
  if (prev) prev.disabled = true;
  if (next) next.disabled = true;
}

function rtkPrepararImpresion() {
  if (!$("#rtk-hoja")) return;
  if (RTK.detalle) {
    pintarDetalleReporteTicket();
    $("#rtk-hoja").dataset.zoom = "100";
    return;
  }
  if (!RTK.datos) return;
  const filas = RTK.datos.tickets || [];
  const suma = filas.reduce((n, t) => n + Number(t.total || 0), 0);
  const premio = filas.reduce((n, t) => n + Number(t.premio_total || 0), 0);
  $("#rtk-hoja").innerHTML = rtkHtmlDocumento(RTK.datos, filas, { n: filas.length, suma, premio }, false);
  $("#rtk-hoja").dataset.zoom = "100";
}

async function cargarReporteTickets() {
  const hoy = hoyISO();
  if ($("#rtk-desde") && !$("#rtk-desde").value) $("#rtk-desde").value = hoy;
  if ($("#rtk-hasta") && !$("#rtk-hasta").value) $("#rtk-hasta").value = hoy;
  if ($("#rtk-hora-desde") && !$("#rtk-hora-desde").value) $("#rtk-hora-desde").value = "00:00";
  if ($("#rtk-hora-hasta") && !$("#rtk-hora-hasta").value) $("#rtk-hora-hasta").value = "23:59";
  rtkPintarFechas();
  try {
    RTK.filtros = await api("/reportes/ventas-resumido/filtros");
    if (!SORTEOS.length) SORTEOS = await api("/sorteos");
    RTK.cajeros = (await api("/usuarios")).filter((u) => u.rol === "operador");
    rtkPoblarSelects();
    if (!RTK.datos) msg("#rtk-msg", "Filtros listos. Pulse VER para consultar.", true);
  } catch (e) {
    msg("#rtk-msg", e.message, false);
  }
}

async function verReporteTickets() {
  const f = rtkFiltrosFormulario();
  if (!f.desde || !f.hasta) {
    msg("#rtk-msg", "Indique el rango de fechas", false);
    return;
  }
  if (f.ticket_id && !/^\d+$/.test(f.ticket_id)) {
    msg("#rtk-msg", "El número de ticket no es válido", false);
    return;
  }
  if (f.hora_hasta < f.hora_desde) {
    msg("#rtk-msg", "La hora hasta no puede ser anterior a la hora desde", false);
    return;
  }
  try {
    RTK.datos = await api("/reportes/tickets?" + rtkParametros(f).toString());
    RTK.consulta = f;
    RTK.detalle = null;
    RTK.vista = null;
    RTK.pagina = 1;
    $("#rtk-visor").hidden = false;
    renderReporteTickets();
    const n = RTK.datos.total || 0;
    const aviso = RTK.datos.recorte ? " · se muestran los 5.000 más recientes" : "";
    const rango = `${rvrFecha(RTK.datos.desde)} ${f.hora_desde} al ${rvrFecha(RTK.datos.hasta)} ${f.hora_hasta}`;
    msg("#rtk-msg", `Reporte listo · ${n} ticket(s) · ${rango}${aviso}`, true);
  } catch (e) {
    msg("#rtk-msg", e.message, false);
  }
}

async function rtkObtenerPdf() {
  const ruta = RTK.detalle
    ? `/reportes/tickets/${RTK.detalle.id}/recibo.pdf`
    : (RTK.consulta ? "/reportes/tickets.pdf?" + rtkParametros(RTK.consulta).toString() : "");
  if (!ruta) {
    msg("#rtk-msg", "Pulse VER para consultar antes de imprimir o descargar.", false);
    return null;
  }
  const r = await fetch(ruta, {
    headers: TOKEN ? { Authorization: "Bearer " + TOKEN } : {},
  });
  if (!r.ok) {
    let detalle = "No se pudo generar el PDF";
    try {
      const j = await r.json();
      detalle = (j && j.detail) || detalle;
    } catch { /* el cuerpo no era JSON */ }
    throw new Error(typeof detalle === "string" ? detalle : "No se pudo generar el PDF");
  }
  const blob = await r.blob();
  if (!blob || !blob.size) throw new Error("El PDF llegó vacío");
  return blob;
}

function rtkNombrePdf() {
  if (RTK.detalle) return `Recibo-${RTK.detalle.id}.pdf`;
  const f = RTK.consulta || {};
  return `Reporte-de-Tickets-${f.desde || "desde"}-al-${f.hasta || "hasta"}.pdf`;
}

async function descargarPdfReporteTickets() {
  try {
    const blob = await rtkObtenerPdf();
    if (!blob) return;
    const url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = rtkNombrePdf();
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    msg("#rtk-msg", RTK.detalle
      ? `PDF del ticket #${RTK.detalle.id} descargado.`
      : "PDF A4 horizontal descargado con el último reporte consultado.", true);
  } catch (e) {
    msg("#rtk-msg", e.message, false);
  }
}

async function imprimirReporteTickets() {
  try {
    const blob = await rtkObtenerPdf();
    if (!blob) return;
    const url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
    const w = window.open(url, "_blank");
    if (!w) {
      msg("#rtk-msg", "El navegador bloqueó la ventana. Use DESCARGAR PDF: el archivo ya es A4 horizontal.", false);
      return;
    }
    setTimeout(() => { try { w.focus(); w.print(); } catch { /* el visor imprime al abrir */ } }, 700);
    msg("#rtk-msg", RTK.detalle
      ? `Impresión del ticket #${RTK.detalle.id}.`
      : "Impresión del último reporte consultado, en A4 horizontal.", true);
  } catch (e) {
    msg("#rtk-msg", e.message, false);
  }
}

function regresarReporteTickets() {
  RTK.detalle = null;
  if (RTK.reciboUrl) {
    URL.revokeObjectURL(RTK.reciboUrl);
    RTK.reciboUrl = "";
  }
  RTK.vista = null;
  $("#rtk-visor").hidden = true;
  ir("reportes");
}

function volverListadoTickets(desdeHistorial) {
  if (!RTK.datos) return;
  const vista = RTK.vista || {};
  RTK.detalle = null;
  if (RTK.reciboUrl) {
    URL.revokeObjectURL(RTK.reciboUrl);
    RTK.reciboUrl = "";
  }
  RTK.pagina = vista.pagina || RTK.pagina;
  RTK.buscar = vista.buscar || "";
  if ($("#rtk-buscar")) $("#rtk-buscar").value = RTK.buscar;
  renderReporteTickets();
  const scroll = rtkScroll();
  if (scroll) {
    scroll.scrollTop = vista.scrollTop || 0;
    scroll.scrollLeft = vista.scrollLeft || 0;
  }
  const raiz = rtkRaizScroll();
  if (raiz) raiz.scrollTop = vista.paginaTop || 0;
  RTK.vista = null;
  actualizarBarraVolver();
  if (!desdeHistorial && history.state && history.state.detalle) history.back();
}

async function verDetalleReporteTicket(id) {
  try {
    if (!RTK.detalle) {
      const scroll = rtkScroll();
      const raiz = rtkRaizScroll();
      RTK.vista = {
        pagina: RTK.pagina,
        buscar: RTK.buscar,
        scrollTop: scroll ? scroll.scrollTop : 0,
        scrollLeft: scroll ? scroll.scrollLeft : 0,
        paginaTop: raiz ? raiz.scrollTop : 0,
      };
    }
    const detalle = await api(`/reportes/tickets/${id}`);
    const respuesta = await fetch(`/reportes/tickets/${id}/imagen`, {
      headers: TOKEN ? { Authorization: "Bearer " + TOKEN } : {},
    });
    if (!respuesta.ok) throw new Error("No se pudo abrir el recibo");
    const blob = await respuesta.blob();
    if (!blob || !blob.size) throw new Error("El recibo llegó vacío");
    if (RTK.reciboUrl) URL.revokeObjectURL(RTK.reciboUrl);
    RTK.reciboUrl = URL.createObjectURL(blob);
    RTK.detalle = detalle;
    pintarDetalleReporteTicket();
    const scroll = rtkScroll();
    if (scroll) {
      scroll.scrollTop = 0;
      scroll.scrollLeft = 0;
    }
    msg("#rtk-msg", `Recibo del ticket #${RTK.detalle.id}.`, true);
    if (!(history.state && history.state.detalle)) {
      const prof = (history.state && history.state.prof) || 0;
      history.pushState({
        sec: "reporte-tickets",
        detalle: RTK.detalle.id,
        prof: prof + 1,
      }, "", urlHistorial("reporte-tickets", "ticket-" + RTK.detalle.id));
    }
    actualizarBarraVolver();
  } catch (e) {
    msg("#rtk-msg", e.message, false);
  }
}

/* ---------------------------------------------------------------- auditoría */
async function verAuditoria() {
  const ent = $("#aud-entidad").value.trim(), acc = $("#aud-accion").value.trim();
  const filas = await api(`/auditoria?limite=200${ent ? `&entidad=${encodeURIComponent(ent)}` : ""}${acc ? `&accion=${encodeURIComponent(acc)}` : ""}`);
  tabla("#aud-tabla", ["Hora", "Entidad", "ID", "Acción", "Usuario", "Detalle"],
    filas.map((a) => `<tr><td>${esc(a.creado_en)}</td><td>${esc(a.entidad)}</td><td>${esc(a.entidad_id)}</td>
      <td>${esc(a.accion)}</td><td>${esc(a.usuario_id ?? "—")}</td><td>${esc(JSON.stringify(a.detalle))}</td></tr>`));
}

/* ------------------------------------------------------------------- eventos */
async function marcarDesarrollo() {
  try {
    const salud = await fetch("/health").then((r) => r.json());
    window.MODO_DESARROLLO = !!salud.modo_desarrollo;
  } catch {}
}

document.addEventListener("DOMContentLoaded", () => {
  marcarDesarrollo();
  MENU_ES_ESCRITORIO = esEscritorioMenu();
  USUARIOS_ES_MOVIL = esUsuariosMovil();
  document.body.classList.toggle("usuarios-movil", USUARIOS_ES_MOVIL);
  document.body.classList.toggle("usuarios-escritorio", !USUARIOS_ES_MOVIL);
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  $("#ini-hoy").addEventListener("click", () => consultarPeriodo("hoy").catch((e) => msg("#inicio-msg", e.message, false)));
  $("#ini-ayer").addEventListener("click", () => consultarPeriodo("ayer").catch((e) => msg("#inicio-msg", e.message, false)));
  $("#ini-quince").addEventListener("click", () => consultarPeriodo("quince").catch((e) => msg("#inicio-msg", e.message, false)));
  $("#ini-consultar").addEventListener("click", () => cargarInicio($("#ini-desde").value, $("#ini-hasta").value, null).catch((e) => msg("#inicio-msg", e.message, false)));
  $("#btn-login").addEventListener("click", entrar);
  $("#login-clave").addEventListener("keydown", (e) => { if (e.key === "Enter") entrar(); });
  $("#btn-salir").addEventListener("click", salir);
  $("#btn-menu").addEventListener("click", alternarMenuMovil);
  $("#nav-fondo").addEventListener("click", cerrarMenuMovil);
  $$(".navbtn").forEach((b) => b.addEventListener("click", () => ir(b.dataset.sec)));
  $$(".nav-grupo-titulo").forEach((b) => b.addEventListener("click", () => {
    const grupo = b.closest(".nav-grupo");
    if (!grupo) return;
    const abierto = !grupo.classList.contains("abierto");
    grupo.classList.toggle("abierto", abierto);
    b.setAttribute("aria-expanded", abierto ? "true" : "false");
  }));
  $$(".nav-sub-titulo").forEach((b) => b.addEventListener("click", () => {
    const sub = b.closest(".nav-sub");
    if (!sub) return;
    const abierto = !sub.classList.contains("abierto");
    sub.classList.toggle("abierto", abierto);
    b.setAttribute("aria-expanded", abierto ? "true" : "false");
  }));
  window.addEventListener("resize", onResizeMenu);
  // Safari iPhone: la barra URL dispara visualViewport; no debe resetear scroll ni menú.
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", () => {});
  }
  if ($("#btn-super-refrescar")) $("#btn-super-refrescar").addEventListener("click", () => cargarSuperAdmin().catch((e) => msg("#super-msg", e.message, false)));
  if ($("#btn-super-perm-cargar")) $("#btn-super-perm-cargar").addEventListener("click", () => cargarPermisosSuper().catch((e) => msg("#super-perm-msg", e.message, false)));
  if ($("#btn-super-perm-guardar")) $("#btn-super-perm-guardar").addEventListener("click", () => guardarPermisosSuper().catch((e) => msg("#super-perm-msg", e.message, false)));
  $("#btn-suc-guardar").addEventListener("click", guardarSucursal);
  $("#btn-suc-limpiar").addEventListener("click", limpiarSucursal);
  $("#btn-recargar").addEventListener("click", recargarSaldo);
  $("#btn-movimientos").addEventListener("click", () => verMovimientos().catch((e) => alert(e.message)));
  $("#btn-usu-guardar").addEventListener("click", guardarUsuario);
  $("#btn-usu-limpiar").addEventListener("click", limpiarUsuario);
  if ($("#btn-usu-filtrar")) $("#btn-usu-filtrar").addEventListener("click", () => cargarUsuarios().catch((e) => msg("#usu-msg", e.message, false)));
  if ($("#usu-filtro")) $("#usu-filtro").addEventListener("change", () => cargarUsuarios().catch((e) => msg("#usu-msg", e.message, false)));
  if ($("#btn-vc-ver")) $("#btn-vc-ver").addEventListener("click", () => refrescarVentasCajeros());
  if ($("#vc-chips")) {
    $$("#vc-chips .btn").forEach((b) => b.addEventListener("click", () => {
      const [d, h] = rangoVentasCajeros(b.dataset.rango);
      $("#vc-desde").value = d; $("#vc-hasta").value = h;
      $$("#vc-chips .btn").forEach((x) => x.classList.toggle("activo", x === b));
      refrescarVentasCajeros();
    }));
  }
  if ($("#btn-cc-actualizar")) $("#btn-cc-actualizar").addEventListener("click", () => refrescarControlCajeros());
  if ($("#cc-chips")) {
    $$("#cc-chips .btn").forEach((b) => b.addEventListener("click", () => {
      const [d, h] = rangoControlCajeros(b.dataset.rango);
      $("#cc-desde").value = d; $("#cc-hasta").value = h;
      $$("#cc-chips .btn").forEach((x) => x.classList.toggle("activo", x === b));
      refrescarControlCajeros();
    }));
  }
  if ($("#cc-aj-monto")) $("#cc-aj-monto").addEventListener("input", actualizarPreviewAjusteCc);
  if ($("#cc-aj-aplicar")) $("#cc-aj-aplicar").addEventListener("click", () => aplicarAjusteCc().catch((e) => msg("#cc-aj-msg", e.message, false)));
  if ($("#cc-aj-cancelar")) $("#cc-aj-cancelar").addEventListener("click", cerrarModalAjusteCc);
  if ($("#cc-modal-cerrar")) $("#cc-modal-cerrar").addEventListener("click", cerrarModalAjusteCc);
  if ($("#cc-modal")) $("#cc-modal").addEventListener("click", (e) => { if (e.target === $("#cc-modal")) cerrarModalAjusteCc(); });
  if ($("#vc-modal-cerrar")) $("#vc-modal-cerrar").addEventListener("click", cerrarDetalleCajero);
  if ($("#vc-modal-volver")) $("#vc-modal-volver").addEventListener("click", cerrarDetalleCajero);
  if ($("#vc-modal")) $("#vc-modal").addEventListener("click", (e) => { if (e.target === $("#vc-modal")) cerrarDetalleCajero(); });
  if ($("#btn-dt-cargar")) $("#btn-dt-cargar").addEventListener("click", () => refrescarDisenoTicket().catch((e) => msg("#dt-msg", e.message, false)));
  if ($("#btn-dt-preview")) $("#btn-dt-preview").addEventListener("click", () => previewDisenoTicket().catch((e) => msg("#dt-msg", e.message, false)));
  if ($("#btn-dt-guardar")) $("#btn-dt-guardar").addEventListener("click", () => guardarDisenoTicket());
  if ($("#dt-sucursal")) $("#dt-sucursal").addEventListener("change", () => refrescarDisenoTicket().catch((e) => msg("#dt-msg", e.message, false)));
  $("#btn-sor-guardar").addEventListener("click", guardarSorteo);
  $("#btn-sor-limpiar").addEventListener("click", limpiarSorteo);
  $("#tab-tipo").addEventListener("change", actualizarClavesTabla);
  $("#btn-tab-guardar").addEventListener("click", guardarFactor);
  $("#lim-sucursal").addEventListener("change", () => { pintarCajerasLimite(); pintarLimites().catch(() => {}); });
  $("#lim-cajera").addEventListener("change", () => pintarLimites().catch(() => {}));
  $("#btn-lim-qn").addEventListener("click", () => guardarLimiteCajera("QN").catch((e) => msg("#lim-msg", e.message, false)));
  $("#btn-lim-pl").addEventListener("click", () => guardarLimiteCajera("PL").catch((e) => msg("#lim-msg", e.message, false)));
  $("#btn-lim-sp").addEventListener("click", () => guardarLimiteCajera("SP").catch((e) => msg("#lim-msg", e.message, false)));
  $("#btn-lim-tr").addEventListener("click", () => guardarLimiteCajera("TR").catch((e) => msg("#lim-msg", e.message, false)));
  $("#btn-res-buscar").addEventListener("click", () => buscarResultado().catch((e) => msg("#res-msg", e.message, false)));
  $("#btn-res-guardar").addEventListener("click", guardarResultado);
  $("#btn-res-confirmar").addEventListener("click", confirmarResultado);
  $("#btn-res-revertir").addEventListener("click", revertirResultado);
  $("#btn-res-importar").addEventListener("click", importarConectate);
  $("#res-fecha").addEventListener("change", () => { cargarResultadosDia().catch(() => {}); });
  $("#btn-tic-consultar").addEventListener("click", consultarTicket);
  $("#btn-tic-pagar").addEventListener("click", pagarTicketPanel);
  $("#btn-tic-anular").addEventListener("click", anularTicketPanel);
  $("#btn-tic-lista")?.addEventListener("click", () => {
    TIC_PAGINA = 1;
    pintarListaTickets().catch((e) => msg("#tic-lista-msg", e.message, false));
  });
  document.querySelectorAll("[data-tic-rango]").forEach((b) => {
    b.addEventListener("click", () => {
      const [d, h] = rangoTickets(b.dataset.ticRango);
      $("#tic-lista-desde").value = d;
      $("#tic-lista-hasta").value = h;
      $("#tic-lista-id").value = "";
      TIC_PAGINA = 1;
      pintarListaTickets().catch((e) => msg("#tic-lista-msg", e.message, false));
    });
  });
  $("#tic-modal-cerrar")?.addEventListener("click", () => cerrarModal($("#tic-modal")));
  $("#tic-modal")?.addEventListener("click", (ev) => {
    if (ev.target === $("#tic-modal")) cerrarModal($("#tic-modal"));
  });
  const cerrarAnular = () => { TIC_ANULAR = null; cerrarModal($("#tic-anular-modal")); };
  $("#tic-anular-cancelar")?.addEventListener("click", cerrarAnular);
  $("#tic-anular-cancelar-2")?.addEventListener("click", cerrarAnular);
  $("#tic-anular-confirmar")?.addEventListener("click", () => {
    confirmarAnulacionAdmin().catch((e) => msg("#tic-anular-msg", e.message, false));
  });
  $("#tic-anular-modal")?.addEventListener("click", (ev) => {
    if (ev.target === $("#tic-anular-modal")) cerrarAnular();
  });
  $("#btn-caj-recibir").addEventListener("click", recibirEfectivo);
  $("#btn-caj-gasto").addEventListener("click", registrarGasto);
  $("#btn-caj-listar").addEventListener("click", () => listarCaja().catch((e) => msg("#caj-msg", e.message, false)));
  $("#btn-caj-cuadre").addEventListener("click", entregarCuadre);
  $("#btn-ent-ver").addEventListener("click", () => cargarEntregas().catch((e) => msg("#ent-msg", e.message, false)));
  $("#fon-sucursal").addEventListener("change", pintarCajerasFondo);
  $("#fon-cajera").addEventListener("change", pintarCajaFondo);
  $("#btn-fondo").addEventListener("click", () => asignarFondo().catch((e) => msg("#fon-msg", e.message, false)));
  $("#com-sucursal").addEventListener("change", pintarCajerasComision);
  $("#btn-comision").addEventListener("click", () => guardarComision().catch((e) => msg("#com-msg", e.message, false)));
  const btnPrev = $("#btn-com-preview");
  if (btnPrev) {
    btnPrev.addEventListener("click", () => previewComisionCiclo().catch((e) => msg("#com-msg", e.message, false)));
  }
  $("#btn-com-ver").addEventListener("click", () => verComisiones().catch((e) => msg("#com-res-msg", e.message, false)));
  $("#btn-com-liquidar").addEventListener("click", () => liquidarComision().catch((e) => msg("#com-res-msg", e.message, false)));
  $("#caj-sucursal").addEventListener("change", () => { cargarCuadres().catch(() => {}); });
  $("#btn-rep-ver").addEventListener("click", verResumen);
  $("#btn-ven-ver").addEventListener("click", verVentas);
  $("#btn-pen-ver").addEventListener("click", verPendientes);
  $("#btn-pen-texto").addEventListener("click", verPendientesTexto);
  $("#btn-pen-imprimir").addEventListener("click", imprimirPendientes);
  if ($("#btn-rvr-ver")) $("#btn-rvr-ver").addEventListener("click", () => verVentasResumido(false));
  if ($("#btn-rvr-cajeros")) $("#btn-rvr-cajeros").addEventListener("click", () => verVentasResumido(true));
  if ($("#btn-rvr-todos")) $("#btn-rvr-todos").addEventListener("click", () => {
    if ($("#rvr-banca")) $("#rvr-banca").value = "";
    return verVentasResumido(true);
  });
  if ($("#btn-rvr-imprimir")) $("#btn-rvr-imprimir").addEventListener("click", imprimirVentasResumido);
  if ($("#btn-rvr-print2")) $("#btn-rvr-print2").addEventListener("click", imprimirVentasResumido);
  if ($("#btn-rvr-pdf")) $("#btn-rvr-pdf").addEventListener("click", descargarPdfVentasResumido);
  window.addEventListener("beforeprint", rvrPrepararImpresionPanel);
  window.addEventListener("afterprint", () => { if (RVR.datos) renderVentasResumido(); });
  if ($("#btn-rvr-regresar")) $("#btn-rvr-regresar").addEventListener("click", regresarVentasResumido);
  if ($("#btn-rvr-visor-regresar")) $("#btn-rvr-visor-regresar").addEventListener("click", volverFiltrosVentasResumido);
  window.addEventListener("resize", () => {
    const visor = document.getElementById("rvr-visor");
    if (visor && !visor.hidden) rvrMarcarVisor(true);
  });
  if ($("#btn-rvr-actualizar")) $("#btn-rvr-actualizar").addEventListener("click", () => verVentasResumido());
  if ($("#btn-rvr-prev")) $("#btn-rvr-prev").addEventListener("click", () => { RVR.pagina -= 1; renderVentasResumido(); });
  if ($("#btn-rvr-next")) $("#btn-rvr-next").addEventListener("click", () => { RVR.pagina += 1; renderVentasResumido(); });
  if ($("#rvr-zoom")) $("#rvr-zoom").addEventListener("change", (e) => {
    RVR.zoom = Number(e.target.value) || 100;
    if ($("#rvr-hoja")) $("#rvr-hoja").dataset.zoom = String(RVR.zoom);
  });
  for (const id of ["rvr-desde", "rvr-hasta"]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", rvrPintarFechas);
  }
  if ($("#rvr-buscar")) $("#rvr-buscar").addEventListener("input", (e) => {
    RVR.buscar = (e.target.value || "").trim();
    RVR.pagina = 1;
    renderVentasResumido();
  });
  if ($("#btn-rtk-ver")) $("#btn-rtk-ver").addEventListener("click", () => verReporteTickets());
  if ($("#btn-rtk-imprimir")) $("#btn-rtk-imprimir").addEventListener("click", imprimirReporteTickets);
  if ($("#btn-rtk-print2")) $("#btn-rtk-print2").addEventListener("click", imprimirReporteTickets);
  if ($("#btn-rtk-pdf")) $("#btn-rtk-pdf").addEventListener("click", descargarPdfReporteTickets);
  if ($("#btn-rtk-regresar")) $("#btn-rtk-regresar").addEventListener("click", regresarReporteTickets);
  if ($("#btn-rtk-volver")) $("#btn-rtk-volver").addEventListener("click", () => {
    if (history.state && history.state.detalle) history.back();
    else volverListadoTickets(true);
  });
  if ($("#btn-volver-pantalla")) $("#btn-volver-pantalla").addEventListener("click", volverPantalla);
  window.addEventListener("popstate", alRetroceder);
  asegurarHistorial();
  if ($("#btn-rtk-actualizar")) $("#btn-rtk-actualizar").addEventListener("click", () => {
    if (RTK.detalle) verDetalleReporteTicket(RTK.detalle.id);
    else verReporteTickets();
  });
  if ($("#btn-rtk-prev")) $("#btn-rtk-prev").addEventListener("click", () => {
    if (RTK.detalle) return;
    RTK.pagina -= 1;
    renderReporteTickets();
  });
  if ($("#btn-rtk-next")) $("#btn-rtk-next").addEventListener("click", () => {
    if (RTK.detalle) return;
    RTK.pagina += 1;
    renderReporteTickets();
  });
  if ($("#rtk-zoom")) $("#rtk-zoom").addEventListener("change", (e) => {
    RTK.zoom = Number(e.target.value) || 100;
    if ($("#rtk-hoja")) $("#rtk-hoja").dataset.zoom = String(RTK.zoom);
  });
  if ($("#rtk-buscar")) $("#rtk-buscar").addEventListener("input", (e) => {
    if (RTK.detalle) return;
    RTK.buscar = (e.target.value || "").trim();
    RTK.pagina = 1;
    renderReporteTickets();
  });
  if ($("#rtk-banca")) $("#rtk-banca").addEventListener("change", rtkPoblarCajeros);
  if ($("#rtk-grupo")) $("#rtk-grupo").addEventListener("change", rtkPoblarSelects);
  for (const id of ["rtk-desde", "rtk-hasta"]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", rtkPintarFechas);
  }
  const hojaTickets = $("#rtk-hoja");
  if (hojaTickets) hojaTickets.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-rtk-ver]");
    if (!btn) return;
    verDetalleReporteTicket(btn.dataset.rtkVer);
  });
  window.addEventListener("beforeprint", rtkPrepararImpresion);
  window.addEventListener("afterprint", () => {
    if (RTK.detalle) pintarDetalleReporteTicket();
    else if (RTK.datos) renderReporteTickets();
  });
  if ($("#rvr-grupo")) $("#rvr-grupo").addEventListener("change", () => rvrPoblarSelects());
  $("#btn-aud-ver").addEventListener("click", () => verAuditoria().catch((e) => alert(e.message)));
  $("#btn-fuente").addEventListener("click", () => consultarFuente().catch((e) => msg("#fuente-msg", e.message, false)));
  $("#btn-gan").addEventListener("click", () => cargarGanadores().catch((e) => msg("#gan-msg", e.message, false)));
  ["#gan-fecha", "#gan-sorteo", "#gan-sucursal", "#gan-cajera", "#gan-estado"].forEach((sel) => {
    const el = $(sel);
    if (el) el.addEventListener("change", () => refrescarGanadores().catch((e) => msg("#gan-msg", e.message, false)));
  });
  $("#gan-modal-cerrar").addEventListener("click", cerrarModalGanador);
  $("#gan-modal").addEventListener("click", (e) => { if (e.target === $("#gan-modal")) cerrarModalGanador(); });
  restaurarSesion();
});

function filaEstadoFuente(clave, valor) {
  return `<div class="fila-estado"><span class="k">${esc(clave)}</span><span class="v">${esc(valor)}</span></div>`;
}

async function cargarFuente() {
  const datos = await api("/fuente-resultados");
  const trabajador = datos.trabajador || {};
  const fuenteNombre = datos.nombre_fuente || (datos.fuente === "conectate" ? "Conéctate.com" : (datos.fuente || "—"));
  const reloj = trabajador.reloj || (trabajador.activo ? "ACTIVO" : "DETENIDO");
  const ultimaConsulta = trabajador.ultima_ejecucion || trabajador.ultimo_intento || "—";
  const ultimaOk = trabajador.ultima_consulta_ok || trabajador.ultimo_ok || "—";
  const ultimoDetalle = trabajador.ultimo_detalle || datos.ultimo_resultado || "—";
  const error = trabajador.ultimo_error || "ninguno";
  const conectados = (datos.sorteos || []).filter((s) => s.conectada).length;
  const total = (datos.sorteos || []).length;
  $("#fuente-estado").innerHTML = [
    filaEstadoFuente("Fuente", fuenteNombre),
    filaEstadoFuente("Estado de conexión", `${conectados}/${total} sorteos con fuente`),
    filaEstadoFuente("Trabajador automático", reloj),
    filaEstadoFuente("Última consulta", ultimaConsulta),
    filaEstadoFuente("Última verificación correcta", ultimaOk),
    filaEstadoFuente("Último resultado recibido", ultimoDetalle),
    filaEstadoFuente("Intervalo", `${datos.intervalo_segundos || "—"} s`),
    filaEstadoFuente("Errores", error),
  ].join("");
  tabla("#fuente-tabla",
    ["Sorteo", "Hora", "Conexión", "Motivo"],
    (datos.sorteos || []).map((s) => `<tr><td>${esc(s.sorteo)}</td><td>${esc(s.hora || s.hora_fuente || "—")}</td>
      <td>${s.conectada ? "Conectada" : "Sin conexión"}</td><td>${esc(s.motivo || "")}</td></tr>`));
}

async function consultarFuente() {
  msg("#fuente-msg", "Consultando Conéctate.com...");
  const r = await post("/fuente-resultados/sincronizar", {});
  const resumen = r.ok
    ? `Encontrados: ${r.encontrados || 0} · Confirmados: ${r.confirmados || 0}`
    : (r.motivo || "La fuente falló");
  msg("#fuente-msg", resumen, !!r.ok);
  await cargarFuente();
}

function pillPago(estado) {
  const clave = estado === "PAGADO" ? "pagado" : (estado === "PARCIALMENTE PAGADO" ? "parcial" : "pendiente");
  return `<span class="pill ${clave}">${esc(estado || "PENDIENTE")}</span>`;
}

function tarjetaGanador(t) {
  const prueba = t.no_oficial || t.leyenda;
  return `<article class="gan-card${prueba ? " prueba" : ""}">
    <div class="gan-card-top">
      <div>
        <h4>Ticket #${esc(t.id)}</h4>
        <div class="meta">Serial ${esc(t.serial || "—")} · ${esc(t.fecha || "—")}</div>
      </div>
      ${pillPago(t.estado_pago || (t.estado === "pagado" ? "PAGADO" : "PENDIENTE"))}
    </div>
    ${prueba ? `<div class="aviso">${esc(t.leyenda || "PRUEBA — NO OFICIAL")}</div>` : ""}
    <div class="meta">Vendió: <b>${esc(t.cajero || "—")}</b><br>Sucursal: <b>${esc(t.banca || "—")}</b><br>
      Lotería(s): <b>${esc(t.loterias || "—")}</b></div>
    <div class="montos">
      <div>Premio total<br><b>${fmt(t.premio)}</b></div>
      <div>Pagado<br><b>${fmt(t.importe_pagado || 0)}</b></div>
      <div>Pendiente<br><b>${fmt(t.importe_pendiente == null ? t.premio : t.importe_pendiente)}</b></div>
      <div>Pagó<br><b>${esc(t.cajero_pago || "—")}</b></div>
    </div>
    <div class="meta">${t.pagado_en ? "Pago: " + esc(t.pagado_en) : "Sin pago confirmado"}</div>
    <button type="button" class="btn primario" onclick="verTicketGanador(${t.id})">VER TICKET</button>
  </article>`;
}

async function pintarCajerasGanadores() {
  const sel = $("#gan-cajera");
  if (!sel) return;
  const actual = sel.value;
  try {
    const usuarios = await api("/usuarios");
    const cajeras = usuarios.filter((u) => u.rol === "operador");
    sel.innerHTML = '<option value="">Todas</option>' + cajeras.map(
      (u) => `<option value="${u.id}">${esc(u.nombre)} (${esc(u.usuario)})</option>`
    ).join("");
    if (actual) sel.value = actual;
  } catch {}
}

async function cargarGanadores() {
  await cargarCatalogos();
  await pintarCajerasGanadores();
  if (!$("#gan-fecha").value) $("#gan-fecha").value = hoyISO();
  if (GANADORES_RELOJ) clearInterval(GANADORES_RELOJ);
  GANADORES_RELOJ = setInterval(() => refrescarGanadores().catch(() => {}), 15000);
  await refrescarGanadores();
}

async function refrescarGanadores() {
  const q = new URLSearchParams();
  if ($("#gan-fecha").value) q.set("fecha", $("#gan-fecha").value);
  if ($("#gan-sorteo").value) q.set("sorteo_id", $("#gan-sorteo").value);
  if ($("#gan-sucursal").value) q.set("sucursal_id", $("#gan-sucursal").value);
  if ($("#gan-cajera") && $("#gan-cajera").value) q.set("usuario_id", $("#gan-cajera").value);
  if ($("#gan-estado").value) q.set("estado", $("#gan-estado").value);
  const datos = await api("/ganadores?" + q.toString());
  $("#gan-totales").innerHTML =
    `<div class="card"><div class="num">${esc(datos.total_tickets)}</div><div class="lbl">Tickets ganadores</div></div>` +
    `<div class="card"><div class="num">${fmt(datos.total_premios)}</div><div class="lbl">Premio total</div></div>` +
    `<div class="card"><div class="num">${fmt(datos.premios_pagados)}</div><div class="lbl">Pagado</div></div>` +
    `<div class="card"><div class="num">${fmt(datos.premios_pendientes)}</div><div class="lbl">Pendiente</div></div>`;
  const prueba = datos.prueba || [];
  const aviso = $("#gan-prueba");
  if (aviso) {
    aviso.textContent = prueba.length
      ? `PRUEBA — NO OFICIAL: ${prueba.length} ticket(s). Estos premios no salen de la caja real.`
      : "";
  }
  $("#gan-lista").innerHTML = (datos.tickets || []).length
    ? datos.tickets.map(tarjetaGanador).join("")
    : '<p class="nota">Sin ganadores con estos filtros.</p>';
  const cajaPrueba = $("#gan-prueba-lista");
  if (cajaPrueba) {
    cajaPrueba.innerHTML = prueba.length ? prueba.map(tarjetaGanador).join("") : "";
  }
}

async function verTicketGanador(id) {
  const modal = $("#gan-modal");
  const cuerpo = $("#gan-modal-cuerpo");
  $("#gan-modal-titulo").textContent = `Ticket #${id}`;
  cuerpo.innerHTML = '<p class="nota">Cargando…</p>';
  abrirModal(modal);
  try {
    const d = await api(`/ganadores/${id}`);
    const grupos = (d.grupos || []).map((g) => {
      const jugadas = (g.jugadas || []).map((j) => {
        const lots = (j.loterias && j.loterias.length) ? j.loterias.join(" · ") : g.loteria;
        return `<div class="gan-jugada">
          <b>${esc(j.tipo_nombre)}</b> · ${esc(j.numeros)} · ${pillPago(j.estado_premio)}<br>
          Lotería: ${esc(lots)}<br>
          Apostado ${fmt(j.monto)} · Premio ${fmt(j.premio)}
          ${j.pagado_por ? `<br>Pagó: ${esc(j.pagado_por)}${j.pagado_en ? " · " + esc(j.pagado_en) : ""}` : ""}
        </div>`;
      }).join("");
      return `<div class="gan-grupo">
        <h5>${esc(g.loteria)}</h5>
        <div class="meta">Sorteo ${esc(g.fecha || "—")} ${esc(g.hora_sorteo || "")}
          ${g.resultado_oficial ? ` · Oficial ${esc(g.resultado_oficial)}` : ""}</div>
        ${jugadas || '<p class="nota">Sin jugadas ganadoras en esta lotería.</p>'}
      </div>`;
    }).join("");
    cuerpo.innerHTML = `
      ${d.leyenda ? `<div class="aviso">${esc(d.leyenda)}</div>` : ""}
      <div class="meta" style="margin:8px 0 12px">
        Vendió: <b>${esc(d.cajero || "—")}</b> · Sucursal: <b>${esc(d.banca || "—")}</b><br>
        ${pillPago(d.estado_pago)} · Premio ${fmt(d.premio_total)} · Pagado ${fmt(d.importe_pagado)} · Pendiente ${fmt(d.importe_pendiente)}
        ${d.cajero_pago ? `<br>Pagó: <b>${esc(d.cajero_pago)}</b>${d.pagado_en ? " · " + esc(d.pagado_en) : ""}` : ""}
      </div>
      ${grupos || '<p class="nota">Sin jugadas ganadoras.</p>'}`;
  } catch (e) {
    cuerpo.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

function cerrarModalGanador() {
  const modal = $("#gan-modal");
  if (modal) cerrarModal(modal);
}

window.verTicketGanador = verTicketGanador;
window.cerrarModalGanador = cerrarModalGanador;
