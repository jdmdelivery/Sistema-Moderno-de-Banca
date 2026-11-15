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
async function entrar() {
  try {
    const r = await post("/auth/login", { usuario: $("#login-usuario").value.trim(), clave: $("#login-clave").value });
    TOKEN = r.token; YO = r.usuario;
    localStorage.setItem("lot_token", TOKEN);
    $("#login").style.display = "none";
    $("#yo-nombre").textContent = `${YO.nombre} (${YO.rol})`;
    mostrarFondo(YO.rol === "admin");
    await cargarCatalogos();
    ir("inicio");
  } catch (e) { msg("#login-msg", e.message, false); }
}
async function salir() {
  try { await post("/auth/logout"); } catch {}
  TOKEN = ""; YO = null;
  localStorage.removeItem("lot_token");
  location.reload();
}
async function restaurarSesion() {
  if (!TOKEN) return;
  try {
    YO = await api("/auth/yo");
    $("#login").style.display = "none";
    $("#yo-nombre").textContent = `${YO.nombre} (${YO.rol})`;
    mostrarFondo(YO.rol === "admin");
    await cargarCatalogos();
    ir("inicio");
  } catch { TOKEN = ""; localStorage.removeItem("lot_token"); }
}

/* --------------------------------------------------------------------- nav */
let GANADORES_RELOJ = null;
function cerrarMenuMovil() {
  const nav = $("#nav");
  const fondo = $("#nav-fondo");
  const btn = $("#btn-menu");
  if (!nav) return;
  nav.classList.remove("abierto");
  if (fondo) { fondo.classList.remove("abierto"); fondo.hidden = true; }
  if (btn) btn.setAttribute("aria-expanded", "false");
}
function alternarMenuMovil() {
  const nav = $("#nav");
  const fondo = $("#nav-fondo");
  const btn = $("#btn-menu");
  const abierto = !nav.classList.contains("abierto");
  nav.classList.toggle("abierto", abierto);
  if (fondo) { fondo.classList.toggle("abierto", abierto); fondo.hidden = !abierto; }
  if (btn) btn.setAttribute("aria-expanded", abierto ? "true" : "false");
}
function ir(sec) {
  if (GANADORES_RELOJ) {
    clearInterval(GANADORES_RELOJ);
    GANADORES_RELOJ = null;
  }
  cerrarMenuMovil();
  $$(".navbtn").forEach((b) => b.classList.toggle("activo", b.dataset.sec === sec));
  $$(".seccion").forEach((s) => s.classList.toggle("activo", s.id === "sec-" + sec));
  const cargar = {
    inicio: cargarInicio, sucursales: cargarSucursales, terminales: cargarTerminales,
    usuarios: cargarUsuarios, sorteos: cargarSorteos, tabla: cargarTabla,
    limites: cargarLimites, resultados: cargarResultados, tickets: async () => {},
    fuente: cargarFuente, ganadores: cargarGanadores,
    caja: cargarCaja, entregas: cargarEntregas, fondos: cargarFondos, comisiones: cargarComisiones,
    reportes: cargarReportes, auditoria: async () => {},
  }[sec];
  if (cargar) cargar().catch((e) => console.error(e));
}

async function cargarCatalogos() {
  [SUCURSALES, SORTEOS, TIPOS, TERMINALES] = await Promise.all([
    api("/sucursales"), api("/sorteos"), api("/tipos-jugada"), api("/terminales"),
  ]);
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
  }
  $("#res-sorteo").innerHTML = sor;
  const tip = opciones(TIPOS, (t) => t.codigo, (t) => `${t.codigo} — ${t.nombre}`);
  $("#tab-tipo").innerHTML = tip;
  $("#caj-terminal").innerHTML = opciones(
    TERMINALES, (t) => t.id, (t) => `${t.sucursal} · Terminal ${t.numero_terminal}`, '<option value="">— Todas / ninguna —</option>');
  actualizarClavesTabla();
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
  const filas = [
    [fmt(bloque.ventas), "Ventas"],
    [bloque.tickets, "Tickets vendidos"],
    [fmt(bloque.premios_pagados), "Premios pagados"],
    [fmt(bloque.premios_pendientes), "Premios por pagar"],
    [fmt(bloque.neto), "Neto (ventas − premios pagados)"],
    [fmt(bloque.comision), "Comisión"],
  ];
  return filas.map(([n, l]) => `<div class="card"><div class="num">${esc(n)}</div><div class="lbl">${esc(l)}</div></div>`).join("");
}

async function cargarInicio(desde, hasta) {
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
  $("#inicio-periodo").textContent = `DESDE ${r.desde}  HASTA ${r.hasta}  ·  ${r.zona}`;
  $("#inicio-reales").innerHTML = tarjetasInicio(r.reales);
  $("#inicio-prueba").innerHTML = tarjetasInicio(r.prueba);
  msg("#inicio-msg", "");
}

function consultarPeriodo(tipo) {
  const hoy = INICIO_HOY || hoyISO();
  const rango = tipo === "ayer"
    ? [sumarDias(hoy, -1), sumarDias(hoy, -1)]
    : tipo === "quince"
      ? [sumarDias(hoy, -14), hoy]
      : [hoy, hoy];
  return cargarInicio(rango[0], rango[1]);
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
async function cargarUsuarios() {
  const usuarios = await api("/usuarios");
  const soyAdmin = YO && YO.rol === "admin";
  tabla("#usu-tabla", ["Nombre", "Usuario", "Rol", "Sucursal", "Caja", "Caja de prueba", "Estado", "Acciones"],
    usuarios.map((u) => {
      const suc = SUCURSALES.find((s) => s.id === u.sucursal_id);
      const caja = u.saldo_caja == null ? "—" : fmt(u.saldo_caja);
      const prueba = u.saldo_caja_prueba == null ? "—" : fmt(u.saldo_caja_prueba);
      const estado = u.activo
        ? '<span class="pill activo">ACTIVO</span>'
        : '<span class="pill bloqueado">BLOQUEADO</span>';
      let acciones = `<button class="btn fila" onclick="editarUsuario(${u.id})">EDITAR</button>`;
      if (soyAdmin) {
        if (u.activo) {
          acciones += ` <button class="btn fila peligro" onclick="bloquearUsuario(${u.id})">BLOQUEAR</button>`;
        } else {
          acciones += ` <button class="btn fila primario" onclick="desbloquearUsuario(${u.id})">DESBLOQUEAR</button>`;
        }
      }
      return `<tr><td>${esc(u.nombre)}</td><td>${esc(u.usuario)}</td><td>${esc(u.rol)}</td>
        <td>${esc(suc ? suc.nombre : "—")}</td><td>${caja}</td><td>${prueba}</td>
        <td>${estado}</td>
        <td><div class="acciones-fila">${acciones}</div></td></tr>`;
    }));
  window._usuarios = usuarios;
}
function editarUsuario(id) {
  const u = (window._usuarios || []).find((x) => x.id === id); if (!u) return;
  $("#usu-id").value = u.id; $("#usu-nombre").value = u.nombre; $("#usu-usuario").value = u.usuario;
  $("#usu-rol").value = u.rol; $("#usu-sucursal").value = u.sucursal_id || "";
  $("#usu-clave").value = ""; $("#usu-activo").checked = u.activo;
}
function limpiarUsuario() {
  ["#usu-id", "#usu-nombre", "#usu-usuario", "#usu-clave"].forEach((i) => $(i).value = "");
  $("#usu-activo").checked = true;
}
async function guardarUsuario() {
  const id = $("#usu-id").value;
  const body = {
    nombre: $("#usu-nombre").value.trim(), usuario: $("#usu-usuario").value.trim(),
    rol: $("#usu-rol").value, sucursal_id: $("#usu-sucursal").value ? parseInt($("#usu-sucursal").value) : null,
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
  if (!confirm(`¿DESBLOQUEAR a ${u.nombre} (${u.usuario})?\nPodrá iniciar sesión de nuevo con sus credenciales.`)) return;
  try {
    await post(`/usuarios/${id}/desbloquear`);
    msg("#usu-msg", `${u.usuario} quedó ACTIVO.`);
    await cargarUsuarios();
  } catch (e) { msg("#usu-msg", e.message, false); }
}

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
const CLAVES_POR_TIPO = { QN: ["1ro", "2do", "3ro"], PL: ["1-2", "1-3", "2-3"], SP: ["sp"] };
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
  if (l.tipo === "PL") {
    $("#lim-pl-loteria").value = String(l.sorteo_id);
    $("#lim-pl-monto").value = l.monto_max_acumulado;
    if (l.clave_numero === "*") $("#lim-pl-modo").value = "*";
    else {
      $("#lim-pl-modo").value = "uno";
      const partes = l.clave_numero.split("-");
      $("#lim-pl-a").value = partes[0];
      $("#lim-pl-b").value = partes[1] || partes[0];
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
  const cuerpo = { usuario_id: Number(cajera), tipo, id: LIMITE_EDICION };
  if (tipo === "QN") {
    cuerpo.sorteo_id = Number($("#lim-qn-loteria").value);
    cuerpo.numeros = $("#lim-qn-numero").value;
    cuerpo.monto_max_acumulado = Number($("#lim-qn-monto").value);
  } else {
    cuerpo.sorteo_id = Number($("#lim-pl-loteria").value);
    cuerpo.numeros = $("#lim-pl-modo").value === "*" ? "*" : `${$("#lim-pl-a").value}-${$("#lim-pl-b").value}`;
    cuerpo.monto_max_acumulado = Number($("#lim-pl-monto").value);
  }
  if (!cuerpo.monto_max_acumulado || cuerpo.monto_max_acumulado <= 0) throw new Error("Indique el monto máximo");
  await post("/limites-cajera", cuerpo);
  LIMITE_EDICION = null;
  msg("#lim-msg", "Límite guardado. Cada número o palé conserva su propio máximo.", true);
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
    const d = await post("/panel/tickets/pagar", { ...llaveTicket(), sucursal_id: parseInt($("#tic-sucursal").value) });
    pintarTicket(d); msg("#tic-msg", `Ticket PAGADO ✔ ${fmt(d.premio_total)}`);
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
  } catch (e) { msg("#tic-msg", e.message, false); }
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
async function guardarComision() {
  const cajera = $("#com-cajera").value;
  const porcentaje = $("#com-porcentaje").value;
  if (!cajera) throw new Error("Seleccione una cajera");
  if (porcentaje === "" || Number(porcentaje) < 0 || Number(porcentaje) > 100) {
    throw new Error("El porcentaje debe estar entre 0 y 100");
  }
  const r = await post("/comisiones", { usuario_id: Number(cajera), porcentaje: Number(porcentaje) });
  msg("#com-msg", `Porcentaje de ${r.cajera}: ${r.porcentaje}%`, true);
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
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  $("#ini-hoy").addEventListener("click", () => consultarPeriodo("hoy").catch((e) => msg("#inicio-msg", e.message, false)));
  $("#ini-ayer").addEventListener("click", () => consultarPeriodo("ayer").catch((e) => msg("#inicio-msg", e.message, false)));
  $("#ini-quince").addEventListener("click", () => consultarPeriodo("quince").catch((e) => msg("#inicio-msg", e.message, false)));
  $("#ini-consultar").addEventListener("click", () => cargarInicio($("#ini-desde").value, $("#ini-hasta").value).catch((e) => msg("#inicio-msg", e.message, false)));
  $("#btn-login").addEventListener("click", entrar);
  $("#login-clave").addEventListener("keydown", (e) => { if (e.key === "Enter") entrar(); });
  $("#btn-salir").addEventListener("click", salir);
  $("#btn-menu").addEventListener("click", alternarMenuMovil);
  $("#nav-fondo").addEventListener("click", cerrarMenuMovil);
  $$(".navbtn").forEach((b) => b.addEventListener("click", () => ir(b.dataset.sec)));
  $("#btn-suc-guardar").addEventListener("click", guardarSucursal);
  $("#btn-suc-limpiar").addEventListener("click", limpiarSucursal);
  $("#btn-recargar").addEventListener("click", recargarSaldo);
  $("#btn-movimientos").addEventListener("click", () => verMovimientos().catch((e) => alert(e.message)));
  $("#btn-usu-guardar").addEventListener("click", guardarUsuario);
  $("#btn-usu-limpiar").addEventListener("click", limpiarUsuario);
  $("#btn-sor-guardar").addEventListener("click", guardarSorteo);
  $("#btn-sor-limpiar").addEventListener("click", limpiarSorteo);
  $("#tab-tipo").addEventListener("change", actualizarClavesTabla);
  $("#btn-tab-guardar").addEventListener("click", guardarFactor);
  $("#lim-sucursal").addEventListener("change", () => { pintarCajerasLimite(); pintarLimites().catch(() => {}); });
  $("#lim-cajera").addEventListener("change", () => pintarLimites().catch(() => {}));
  $("#btn-lim-qn").addEventListener("click", () => guardarLimiteCajera("QN").catch((e) => msg("#lim-msg", e.message, false)));
  $("#btn-lim-pl").addEventListener("click", () => guardarLimiteCajera("PL").catch((e) => msg("#lim-msg", e.message, false)));
  $("#btn-res-buscar").addEventListener("click", () => buscarResultado().catch((e) => msg("#res-msg", e.message, false)));
  $("#btn-res-guardar").addEventListener("click", guardarResultado);
  $("#btn-res-confirmar").addEventListener("click", confirmarResultado);
  $("#btn-res-revertir").addEventListener("click", revertirResultado);
  $("#btn-res-importar").addEventListener("click", importarConectate);
  $("#res-fecha").addEventListener("change", () => { cargarResultadosDia().catch(() => {}); });
  $("#btn-tic-consultar").addEventListener("click", consultarTicket);
  $("#btn-tic-pagar").addEventListener("click", pagarTicketPanel);
  $("#btn-tic-anular").addEventListener("click", anularTicketPanel);
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
  $("#btn-com-ver").addEventListener("click", () => verComisiones().catch((e) => msg("#com-res-msg", e.message, false)));
  $("#btn-com-liquidar").addEventListener("click", () => liquidarComision().catch((e) => msg("#com-res-msg", e.message, false)));
  $("#caj-sucursal").addEventListener("change", () => { cargarCuadres().catch(() => {}); });
  $("#btn-rep-ver").addEventListener("click", verResumen);
  $("#btn-ven-ver").addEventListener("click", verVentas);
  $("#btn-pen-ver").addEventListener("click", verPendientes);
  $("#btn-pen-texto").addEventListener("click", verPendientesTexto);
  $("#btn-pen-imprimir").addEventListener("click", imprimirPendientes);
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

async function cargarFuente() {
  const datos = await api("/fuente-resultados");
  const trabajador = datos.trabajador || {};
  $("#fuente-estado").textContent =
    `${datos.aviso} Intervalo ${datos.intervalo_segundos} s. ` +
    `Trabajador ${trabajador.activo ? "activo" : "detenido"}. ` +
    `Última consulta: ${trabajador.ultimo_intento || "—"}. ` +
    `Último éxito: ${trabajador.ultimo_ok || "—"}. ` +
    `Error: ${trabajador.ultimo_error || "ninguno"}.`;
  tabla("#fuente-tabla",
    ["Sorteo", "Identificador", "Sesión", "Hora de la fuente", "Conexión", "Motivo"],
    datos.sorteos.map((s) => `<tr><td>${esc(s.sorteo)}</td><td>${esc(s.game || "—")}</td><td>${esc(s.session || "—")}</td>
      <td>${esc(s.hora_fuente || "—")}</td><td>${s.conectada ? "Conectada" : "Sin conexión"}</td><td>${esc(s.motivo || "")}</td></tr>`));
}

async function consultarFuente() {
  msg("#fuente-msg", "Consultando RDLotto…");
  const r = await post("/fuente-resultados/sincronizar", {});
  msg("#fuente-msg", r.ok ? `Guardados en verificación: ${r.guardados || 0}` : (r.motivo || "La fuente falló"), !!r.ok);
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
  modal.hidden = false;
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
  if (modal) modal.hidden = true;
}

window.verTicketGanador = verTicketGanador;
window.cerrarModalGanador = cerrarModalGanador;
