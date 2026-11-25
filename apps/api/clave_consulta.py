"""Cifrado autenticado AES-256-GCM para consulta de claves por el administrador.

La autenticación sigue siendo PBKDF2 (clave_hash). Este módulo solo guarda un
secreto recuperable adicional. La clave maestra vive en la variable de entorno
CLAVE_CONSULTA_USUARIOS (32 bytes en base64) — nunca en PostgreSQL ni en git.

La captura post-login persiste con UPDATE … WHERE clave_hash = :vigente para
no sobrescribir un secreto más nuevo. El rate-limit de reauth usa la tabla
auditoria (compartida entre procesos/workers).
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from datetime import timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, text

logger = logging.getLogger("banca.clave_consulta")

_ENV = "CLAVE_CONSULTA_USUARIOS"
_PREFIJO = "v1$gcm$"
_AAD = b"banca-moderna-clave-consulta-v1"

_MAX_FALLIDOS = 5
_VENTANA_SEG = 15 * 60
_ACCION_FALLO = "ver_clave_fallo_reauth"
_ACCION_OK = "ver_clave_reauth_ok"


def _clave_maestra() -> bytes | None:
    crudo = (os.environ.get(_ENV) or "").strip()
    if not crudo:
        return None
    try:
        clave = base64.b64decode(crudo, validate=True)
    except Exception:
        logger.error("CLAVE_CONSULTA_USUARIOS no es base64 válido")
        return None
    if len(clave) != 32:
        logger.error("CLAVE_CONSULTA_USUARIOS debe decodificar a 32 bytes")
        return None
    return clave


def cifrado_disponible() -> bool:
    return _clave_maestra() is not None


def cifrar_clave_consulta(texto: str) -> str:
    """Devuelve blob `v1$gcm$<iv>$<ct>` (ct incluye tag GCM). Lanza si no hay clave."""
    if texto is None:
        raise ValueError("clave vacía")
    plano = str(texto)
    if not plano:
        raise ValueError("clave vacía")
    maestro = _clave_maestra()
    if maestro is None:
        raise RuntimeError("CLAVE_CONSULTA_USUARIOS no configurada")
    iv = secrets.token_bytes(12)
    ct = AESGCM(maestro).encrypt(iv, plano.encode("utf-8"), _AAD)
    return (
        f"{_PREFIJO}{base64.urlsafe_b64encode(iv).decode('ascii')}:"
        f"{base64.urlsafe_b64encode(ct).decode('ascii')}"
    )


def descifrar_clave_consulta(blob: str) -> str:
    if not blob or not str(blob).startswith(_PREFIJO):
        raise ValueError("blob de clave consulta inválido")
    maestro = _clave_maestra()
    if maestro is None:
        raise RuntimeError("CLAVE_CONSULTA_USUARIOS no configurada")
    resto = str(blob)[len(_PREFIJO) :]
    partes = resto.split(":")
    if len(partes) != 2:
        raise ValueError("blob de clave consulta inválido")
    iv = base64.urlsafe_b64decode(partes[0].encode("ascii"))
    ct = base64.urlsafe_b64decode(partes[1].encode("ascii"))
    plano = AESGCM(maestro).decrypt(iv, ct, _AAD)
    return plano.decode("utf-8")


def _update_consulta_si_hash(db, usuario_id: int, blob, hash_vigente: str) -> int:
    """UPDATE condicionado. Devuelve filas afectadas (0 = hash ya no vigente)."""
    resultado = db.execute(
        text(
            "UPDATE usuarios SET clave_consulta_cifrada = :blob "
            "WHERE id = :id AND clave_hash = :hash"
        ),
        {"blob": blob, "id": int(usuario_id), "hash": hash_vigente},
    )
    return int(resultado.rowcount or 0)


def guardar_consulta_en_usuario(db, usuario, clave_plana: str, *, invalidar_si_falla: bool) -> bool:
    """Cifra y persiste solo si clave_hash del usuario sigue siendo el actual en BD.

    Si falla el cifrado e invalidar_si_falla, pone NULL con el mismo WHERE.
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        return False
    hash_vigente = getattr(usuario, "clave_hash", None)
    if not hash_vigente:
        return False
    if clave_plana is None or str(clave_plana) == "":
        if invalidar_si_falla:
            _update_consulta_si_hash(db, usuario.id, None, hash_vigente)
            usuario.clave_consulta_cifrada = None
        return False
    try:
        blob = cifrar_clave_consulta(str(clave_plana))
    except Exception:
        logger.exception("No se pudo cifrar clave_consulta (sin registrar la clave)")
        if invalidar_si_falla:
            _update_consulta_si_hash(db, usuario.id, None, hash_vigente)
            usuario.clave_consulta_cifrada = None
        return False
    afectadas = _update_consulta_si_hash(db, usuario.id, blob, hash_vigente)
    if afectadas:
        usuario.clave_consulta_cifrada = blob
        return True
    # Carrera: otro proceso cambió la clave; no dejar el ORM sucio con blob viejo.
    db.expire(usuario, ["clave_consulta_cifrada"])
    return False


def capturar_tras_login(db, usuario, clave_plana: str) -> None:
    """Best-effort tras login OK. UPDATE condicionado al hash que se verificó."""
    if usuario is None or not clave_plana or db is None:
        return
    try:
        from .security import verificar_clave

        hash_vigente = getattr(usuario, "clave_hash", None)
        if not hash_vigente or not verificar_clave(str(clave_plana), hash_vigente):
            return
        guardar_consulta_en_usuario(db, usuario, clave_plana, invalidar_si_falla=False)
    except Exception:
        logger.exception("captura post-login falló (login no se interrumpe)")


def sincronizar_consulta_si_hash_coincide(db, usuario, clave_plana: str, hash_esperado: str) -> bool:
    """Tras cambiar la clave: cifra solo si el hash en memoria es el recién calculado."""
    if usuario is None or not clave_plana or not hash_esperado:
        return False
    if getattr(usuario, "clave_hash", None) != hash_esperado:
        return False
    return guardar_consulta_en_usuario(db, usuario, clave_plana, invalidar_si_falla=True)


# ---- rate limit multi-proceso vía auditoría ----

def exceso_intentos_ver_clave(db, actor_id: int, ahora) -> bool:
    """True si hay >=5 fallos de reauth desde el último OK en la ventana."""
    from .models import Auditoria

    desde = ahora - timedelta(seconds=_VENTANA_SEG)
    ultimo_ok = (
        db.query(func.max(Auditoria.creado_en))
        .filter(
            Auditoria.usuario_id == int(actor_id),
            Auditoria.accion.in_([_ACCION_OK, "ver_clave"]),
            Auditoria.creado_en >= desde,
        )
        .scalar()
    )
    q = db.query(Auditoria.id).filter(
        Auditoria.usuario_id == int(actor_id),
        Auditoria.accion == _ACCION_FALLO,
        Auditoria.creado_en >= desde,
    )
    if ultimo_ok is not None:
        q = q.filter(Auditoria.creado_en > ultimo_ok)
    return q.count() >= _MAX_FALLIDOS


def registrar_fallo_ver_clave(db, actor_id: int, objetivo_id: int | None = None) -> None:
    from . import servicios

    servicios.auditar(
        db,
        "usuario",
        int(actor_id),
        _ACCION_FALLO,
        usuario_id=int(actor_id),
        detalle={"objetivo_id": objetivo_id} if objetivo_id else {},
    )


def registrar_reauth_ok_ver_clave(db, actor_id: int) -> None:
    from . import servicios

    servicios.auditar(
        db,
        "usuario",
        int(actor_id),
        _ACCION_OK,
        usuario_id=int(actor_id),
        detalle={},
    )
