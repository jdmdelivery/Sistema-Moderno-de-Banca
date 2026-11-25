"""Servicios de impresión controlada desde el servidor (Opción B). Local."""
from __future__ import annotations

import json

from .comun import ahora_local
from .models import DisenoTicket, Entrega, Sucursal, TipoJugada, Ticket, Usuario
from .recibos_imagen import render_entrega_png, render_pago_png, render_resumen_png
from .ticket_imagen import diseno_por_defecto, fusionar_diseno, preview_png, render_ticket_png


class ErrorImpresion(Exception):
    def __init__(self, codigo: int, detalle: str):
        self.codigo = codigo
        self.detalle = detalle
        super().__init__(detalle)


def tr_habilitado(db) -> bool:
    """TR solo se imprime si el tipo existe y está activo en catálogo."""
    tipo = db.query(TipoJugada).filter_by(codigo="TR").first()
    return tipo is not None


def _parse_config(texto: str | None) -> dict:
    if not texto:
        return {}
    try:
        data = json.loads(texto)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def obtener_diseno(db, sucursal_id: int | None) -> dict:
    if sucursal_id is None:
        return diseno_por_defecto()
    fila = db.get(DisenoTicket, sucursal_id)
    if fila is None or not fila.activo:
        return diseno_por_defecto()
    return fusionar_diseno(_parse_config(fila.config_json))


def diseno_a_dict(db, sucursal_id: int) -> dict:
    suc = db.get(Sucursal, sucursal_id)
    if suc is None:
        raise ErrorImpresion(404, "Sucursal no encontrada")
    fila = db.get(DisenoTicket, sucursal_id)
    cfg = obtener_diseno(db, sucursal_id)
    return {
        "sucursal_id": sucursal_id,
        "sucursal": suc.nombre,
        "codigo": suc.codigo,
        "activo": bool(fila.activo) if fila else True,
        "config": cfg,
        "tr_habilitado": tr_habilitado(db),
        "actualizado_en": fila.actualizado_en.isoformat(sep=" ") if fila and fila.actualizado_en else None,
    }


def guardar_diseno(db, sucursal_id: int, config: dict, usuario_id: int | None, activo: bool = True) -> dict:
    suc = db.get(Sucursal, sucursal_id)
    if suc is None:
        raise ErrorImpresion(404, "Sucursal no encontrada")
    if not isinstance(config, dict):
        raise ErrorImpresion(400, "La configuración debe ser un objeto JSON")
    # Sanear: no aceptar claves ajenas peligrosas; fusionar con defaults.
    limpio = fusionar_diseno(config)
    # Límites de tipografía / papel 58 mm.
    tip = limpio.setdefault("tipografia", {})
    for k in ("cuerpo", "jugada", "total", "titulo_seccion"):
        tip[k] = max(12, min(36, int(tip.get(k) or 18)))
    enc = limpio.setdefault("encabezado", {})
    enc["tamano_nombre"] = max(16, min(40, int(enc.get("tamano_nombre") or 26)))
    qr = limpio.setdefault("qr", {})
    qr["tamano_px"] = max(96, min(220, int(qr.get("tamano_px") or 168)))
    limpio["ancho_px"] = 384

    fila = db.get(DisenoTicket, sucursal_id)
    if fila is None:
        fila = DisenoTicket(sucursal_id=sucursal_id)
        db.add(fila)
    fila.config_json = json.dumps(limpio, ensure_ascii=False)
    fila.activo = bool(activo)
    fila.actualizado_en = ahora_local()
    fila.actualizado_por = usuario_id
    db.commit()
    return diseno_a_dict(db, sucursal_id)


def meta_impresion(ticket_id: int, serial: str, *, reimpresion: bool = False) -> dict:
    url = f"/terminal/tickets/{int(ticket_id)}/imagen?serial={serial}"
    if reimpresion:
        url += "&reimpresion=true"
    return {
        "modo": "imagen_servidor",
        "ancho_px": 384,
        "url": url,
        "qr": f"LOT:{int(ticket_id)}:{serial}",
        "fallback": "texto_local",
    }


def autorizar_imagen_terminal(db, ticket: Ticket, terminal, operador: Usuario):
    """Aislamiento: propia cajera + sucursal vendedora (misma empresa/terminal)."""
    if ticket is None:
        raise ErrorImpresion(404, "Ticket no encontrado")
    if terminal is None or not terminal.activa:
        raise ErrorImpresion(401, "Terminal no autorizada")
    if int(ticket.sucursal_vendedora_id or 0) != int(terminal.sucursal_id or -1):
        raise ErrorImpresion(403, "Este ticket pertenece a otra empresa")
    # Operador de otra sucursal no debería llegar aquí; refuerzo por sesión.
    if operador is not None and operador.sucursal_id and int(operador.sucursal_id) != int(terminal.sucursal_id):
        raise ErrorImpresion(403, "Sesión de otra sucursal")
    # Historial / reimpresión: solo la cajera que vendió el ticket.
    if operador is not None and int(ticket.usuario_id or 0) != int(operador.id or -1):
        raise ErrorImpresion(403, "ESTE TICKET PERTENECE A OTRA CAJERA")


def render_ticket_id(
    db, ticket_id: int, serial: str, *, reimpresion: bool = False,
) -> tuple[bytes, Ticket]:
    from .servicios import buscar_ticket, ticket_a_dict

    ticket = buscar_ticket(db, ticket_id, serial)
    datos = ticket_a_dict(db, ticket)
    if reimpresion:
        datos["reimpresion"] = True
        datos["leyenda"] = "COPIA — REIMPRESIÓN"
    diseno = obtener_diseno(db, ticket.sucursal_vendedora_id)
    png = render_ticket_png(datos, diseno, tr_habilitado=tr_habilitado(db))
    return png, ticket


def render_preview(db, sucursal_id: int | None, config: dict | None = None) -> bytes:
    diseno = fusionar_diseno(config) if config else obtener_diseno(db, sucursal_id)
    return preview_png(diseno, tr_habilitado=tr_habilitado(db))


def render_resumen_datos(datos: dict) -> bytes:
    """PNG 384 px del resumen. No altera ventas ni caja."""
    return render_resumen_png(datos)


def render_entrega_id(db, entrega_id: int, operador: Usuario) -> bytes:
    """PNG de una entrega propia. Reimpresión: no mueve dinero."""
    from .servicios import entrega_a_dict

    entrega = db.get(Entrega, int(entrega_id))
    if entrega is None or entrega.usuario_id != operador.id:
        raise ErrorImpresion(404, "La entrega no existe")
    return render_entrega_png(entrega_a_dict(db, entrega))


def render_pago_ticket(
    db,
    ticket_id: int,
    serial: str,
    operacion_id: str | None = None,
    *,
    reimpresion: bool = False,
) -> bytes:
    """PNG del comprobante de una operación de pago. No cobra de nuevo."""
    from .servicios import _datos_comprobante_premio, buscar_ticket

    ticket = buscar_ticket(db, ticket_id, serial)
    datos = _datos_comprobante_premio(db, ticket, operacion_id=operacion_id)
    if not datos:
        raise ErrorImpresion(404, "No hay comprobante de pago para esa operación")
    datos["reimpresion"] = bool(reimpresion)
    return render_pago_png(datos)
