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
  destino.innerHTML = "<table><thead><tr>" + columnas.map((c) => `<th>${esc(c)}</th>`).join("") +
    "</tr></thead><tbody>" + filas.join("") + "</tbody></table>";
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
    await cargarCatalogos();
    ir("inicio");
  } catch { TOKEN = ""; localStorage.removeItem("lot_token"); }
}

/* --------------------------------------------------------------------- nav */
function ir(sec) {
  $$(".navbtn").forEach((b) => b.classList.toggle("activo", b.dataset.sec === sec));
  $$(".seccion").forEach((s) => s.classList.toggle("activo", s.id === "sec-" + sec));
  const cargar = {
    inicio: cargarInicio, sucursales: cargarSucursales, terminales: cargarTerminales,
    usuarios: cargarUsuarios, sorteos: cargarSorteos, tabla: cargarTabla,
    limites: cargarLimites, resultados: cargarResultados, tickets: async () => {},
    caja: cargarCaja, reportes: cargarReportes, auditoria: async () => {},
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
  $("#ter-sucursal").innerHTML = suc();
  $("#tic-sucursal").innerHTML = suc();
  $("#caj-sucursal").innerHTML = suc();
  $("#pen-sucursal").innerHTML = suc();
  $("#rep-sucursal").innerHTML = suc('<option value="">Todas las sucursales</option>');
  $("#usu-sucursal").innerHTML = suc('<option value="">— Sin sucursal —</option>');
  const sor = opciones(SORTEOS, (s) => s.id, (s) => s.nombre);
  $("#lim-sorteo").innerHTML = sor;
  $("#res-sorteo").innerHTML = sor;
  const tip = opciones(TIPOS, (t) => t.codigo, (t) => `${t.codigo} — ${t.nombre}`);
  $("#tab-tipo").innerHTML = tip;
  $("#lim-tipo").innerHTML = tip;
  $("#caj-terminal").innerHTML = opciones(
    TERMINALES, (t) => t.id, (t) => `${t.sucursal} · Terminal ${t.numero_terminal}`, '<option value="">— Todas / ninguna —</option>');
  actualizarClavesTabla();
}

/* ------------------------------------------------------------------- inicio */
async function cargarInicio() {
  const hoy = hoyISO();
  const r = await api(`/reportes/resumen?desde=${hoy}&hasta=${hoy}&vista=final`);
  const tarjetas = [
    [fmt(r.ventas), "Ventas de hoy"],
    [r.total_tickets, "Tickets de hoy"],
    [fmt(r.premios_pagados), "Premios pagados hoy"],
    [fmt(r.premios_pendientes), "Premios por pagar"],
    [fmt(r.neto), "Neto (ventas − premios pagados)"],
    [fmt(r.comision_total), "Comisión de las bancas"],
  ];
  $("#inicio-cards").innerHTML = tarjetas.map(([n, l]) => `<div class="card"><div class="num">${esc(n)}</div><div class="lbl">${esc(l)}</div></div>`).join("");
}

/* --------------------------------------------------------------- sucursales */
async function cargarSucursales() {
  await cargarCatalogos();
  tabla("#suc-tabla", ["Código", "Nombre", "Comisión %", "Saldo", "Activa", "Acciones"],
    SUCURSALES.map((s) => `<tr><td>${esc(s.codigo)}</td><td>${esc(s.nombre)}</td><td>${esc(s.comision_porcentaje)}</td>
      <td>${fmt(s.saldo_actual)}</td><td>${s.activa ? "Sí" : "No"}</td>
      <td><button class="btn fila" onclick="editarSucursal(${s.id})">Editar</button></td></tr>`));
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
    msg("#rec-msg", `Recarga aplicada ✔ Nuevo saldo: ${fmt(r.saldo_resultante)}`);
    await cargarSucursales();
  } catch (e) { msg("#rec-msg", e.message, false); }
}
async function verMovimientos() {
  const id = $("#mov-sucursal").value;
  const filas = await api(`/sucursales/${id}/movimientos`);
  tabla("#mov-tabla", ["Fecha", "Tipo", "Monto", "Referencia", "Saldo resultante"],
    filas.map((m) => `<tr><td>${esc(m.creado_en)}</td><td>${esc(m.tipo)}</td><td>${fmt(m.monto)}</td><td>${esc(m.referencia || "")}</td><td>${fmt(m.saldo_resultante)}</td></tr>`));
}

/* --------------------------------------------------------------- terminales */
async function cargarTerminales() {
  await cargarCatalogos();
  tabla("#ter-tabla", ["Sucursal", "N.º", "Serial SUNMI", "Activa", "Token", "Última conexión", "Acciones"],
    TERMINALES.map((t) => `<tr><td>${esc(t.sucursal)}</td><td>${t.numero_terminal}</td><td>${esc(t.serial_sunmi)}</td>
      <td>${t.activa ? "Sí" : "No"}</td><td>${t.tiene_token ? "Vigente" : "Revocado"}</td>
      <td>${esc(t.ultima_conexion_en || "—")}</td>
      <td><button class="btn fila" onclick="editarTerminal(${t.id})">Editar</button>
      <button class="btn fila" onclick="revocarTerminal(${t.id})">Revocar</button>
      <button class="btn fila" onclick="reactivarTerminal(${t.id})">Reactivar</button></td></tr>`));
}
function editarTerminal(id) {
  const t = TERMINALES.find((x) => x.id === id); if (!t) return;
  $("#ter-id").value = t.id; $("#ter-sucursal").value = t.sucursal_id; $("#ter-numero").value = t.numero_terminal;
  $("#ter-serial").value = t.serial_sunmi; $("#ter-version").value = t.version_app || ""; $("#ter-activa").checked = t.activa;
}
function limpiarTerminal() {
  ["#ter-id", "#ter-serial", "#ter-version"].forEach((i) => $(i).value = "");
  $("#ter-numero").value = 1; $("#ter-activa").checked = true; $("#ter-token").style.display = "none";
}
function mostrarToken(token) {
  const caja = $("#ter-token");
  caja.style.display = "block";
  caja.innerHTML = `🔑 <b>Token de la terminal (se muestra una sola vez, cópielo ahora):</b><br>${esc(token)}`;
}
async function guardarTerminal() {
  const id = $("#ter-id").value;
  const body = {
    sucursal_id: parseInt($("#ter-sucursal").value), numero_terminal: parseInt($("#ter-numero").value || 1),
    serial_sunmi: $("#ter-serial").value.trim(), version_app: $("#ter-version").value.trim() || null,
    activa: $("#ter-activa").checked,
  };
  try {
    if (id) { await put(`/terminales/${id}`, body); msg("#ter-msg", "Terminal guardada ✔"); limpiarTerminal(); }
    else { const r = await post("/terminales", body); limpiarTerminal(); mostrarToken(r.token); msg("#ter-msg", "Terminal creada ✔ Guarde el token."); }
    await cargarTerminales();
  } catch (e) { msg("#ter-msg", e.message, false); }
}
async function revocarTerminal(id) {
  if (!confirm("¿Revocar esta terminal? Dejará de vender de inmediato.")) return;
  await post(`/terminales/${id}/revocar`); await cargarTerminales();
}
async function reactivarTerminal(id) {
  const r = await post(`/terminales/${id}/reactivar`);
  mostrarToken(r.token); await cargarTerminales();
}

/* ----------------------------------------------------------------- usuarios */
async function cargarUsuarios() {
  const usuarios = await api("/usuarios");
  tabla("#usu-tabla", ["Nombre", "Usuario", "Rol", "Sucursal", "Activo", "Acciones"],
    usuarios.map((u) => {
      const suc = SUCURSALES.find((s) => s.id === u.sucursal_id);
      return `<tr><td>${esc(u.nombre)}</td><td>${esc(u.usuario)}</td><td>${esc(u.rol)}</td>
        <td>${esc(suc ? suc.nombre : "—")}</td><td>${u.activo ? "Sí" : "No"}</td>
        <td><button class="btn fila" onclick="editarUsuario(${u.id})">Editar</button></td></tr>`;
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
async function cargarLimites() {
  const filas = await api("/limites");
  tabla("#lim-tabla", ["Sorteo", "Tipo", "Número", "Máximo acumulado", "Acciones"],
    filas.map((l) => `<tr><td>${esc(l.sorteo)}</td><td>${esc(l.tipo)}</td><td>${esc(l.clave_numero)}</td>
      <td>${fmt(l.monto_max_acumulado)}</td>
      <td><button class="btn fila" onclick="borrarLimite(${l.id})">Eliminar</button></td></tr>`));
}
async function guardarLimite() {
  try {
    await post("/limites", {
      sorteo_id: parseInt($("#lim-sorteo").value), tipo: $("#lim-tipo").value,
      numeros: $("#lim-numeros").value.trim(), monto_max_acumulado: parseFloat($("#lim-monto").value || 0),
    });
    msg("#lim-msg", "Límite guardado ✔"); await cargarLimites();
  } catch (e) { msg("#lim-msg", e.message, false); }
}
async function borrarLimite(id) {
  if (!confirm("¿Eliminar este límite?")) return;
  await del(`/limites/${id}`); await cargarLimites();
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
  caja.textContent = `${r.sorteo} · ${r.fecha} → ${r.premio1} - ${r.premio2} - ${r.premio3} · Estado: ${r.estado.toUpperCase()} · Fuente: ${r.fuente}` +
    (r.liquidado_en ? ` · Liquidado: ${r.liquidado_en}` : "");
}
async function guardarResultado() {
  try {
    const r = await post("/resultados", {
      sorteo_id: parseInt($("#res-sorteo").value), fecha: $("#res-fecha").value || hoyISO(),
      premio1: parseInt($("#res-p1").value), premio2: parseInt($("#res-p2").value), premio3: parseInt($("#res-p3").value),
    });
    RESULTADO_ACTUAL = r;
    msg("#res-msg", `Propuesta guardada ✔ ${r.sorteo}: ${r.premio1}-${r.premio2}-${r.premio3} (sin liquidar todavía)`);
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
  caja.textContent =
    `Ticket ${d.id} · Serial ${d.serial} · ${d.banca} (${d.banca_codigo})\n` +
    `Vendido: ${d.fecha_hora} · Total: ${fmt(d.total)}\n${jugadas}\n` +
    `Estado: ${String(d.estado).toUpperCase()} · Premio: ${fmt(d.premio_total)}\n${d.mensaje || ""}`;
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
  if (!confirm("¿Anular este ticket? El monto vuelve al saldo de la banca vendedora.")) return;
  try {
    const d = await post("/panel/tickets/anular", llaveTicket());
    pintarTicket(d); msg("#tic-msg", "Ticket ANULADO ✔ El saldo fue devuelto a la banca vendedora.");
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

/* ----------------------------------------------------------------- reportes */
async function cargarReportes() {
  const hoy = hoyISO();
  if (!$("#rep-desde").value) { $("#rep-desde").value = hoy; $("#rep-hasta").value = hoy; }
  if (!$("#pen-desde").value) { $("#pen-desde").value = hoy; $("#pen-hasta").value = hoy; }
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
document.addEventListener("DOMContentLoaded", () => {
  $("#btn-login").addEventListener("click", entrar);
  $("#login-clave").addEventListener("keydown", (e) => { if (e.key === "Enter") entrar(); });
  $("#btn-salir").addEventListener("click", salir);
  $$(".navbtn").forEach((b) => b.addEventListener("click", () => ir(b.dataset.sec)));
  $("#btn-suc-guardar").addEventListener("click", guardarSucursal);
  $("#btn-suc-limpiar").addEventListener("click", limpiarSucursal);
  $("#btn-recargar").addEventListener("click", recargarSaldo);
  $("#btn-movimientos").addEventListener("click", () => verMovimientos().catch((e) => alert(e.message)));
  $("#btn-ter-guardar").addEventListener("click", guardarTerminal);
  $("#btn-ter-limpiar").addEventListener("click", limpiarTerminal);
  $("#btn-usu-guardar").addEventListener("click", guardarUsuario);
  $("#btn-usu-limpiar").addEventListener("click", limpiarUsuario);
  $("#btn-sor-guardar").addEventListener("click", guardarSorteo);
  $("#btn-sor-limpiar").addEventListener("click", limpiarSorteo);
  $("#tab-tipo").addEventListener("change", actualizarClavesTabla);
  $("#btn-tab-guardar").addEventListener("click", guardarFactor);
  $("#btn-lim-guardar").addEventListener("click", guardarLimite);
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
  $("#caj-sucursal").addEventListener("change", () => { cargarCuadres().catch(() => {}); });
  $("#btn-rep-ver").addEventListener("click", verResumen);
  $("#btn-pen-ver").addEventListener("click", verPendientes);
  $("#btn-pen-texto").addEventListener("click", verPendientesTexto);
  $("#btn-pen-imprimir").addEventListener("click", imprimirPendientes);
  $("#btn-aud-ver").addEventListener("click", () => verAuditoria().catch((e) => alert(e.message)));
  restaurarSesion();
});
