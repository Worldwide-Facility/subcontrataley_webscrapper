"""Errores operativos esperados: mensaje de una línea y exit != 0, sin traceback."""

from __future__ import annotations

import logging
import traceback
from typing import Any


def exigir_ok_post_carga(resumen: dict[str, Any], *, etiqueta: str) -> dict[str, Any]:
    """
    Tras esperar_post_carga: falla si no apareció 'Documentos Agregados'.
    La barra del portal no llega a 100% (bug); ese mensaje es el criterio de éxito.
    """
    if not resumen.get("ok"):
        raise RuntimeError(
            f"[{etiqueta}] Post-carga falló: no apareció 'Documentos Agregados' "
            f"(criterio de éxito; la barra no llega a 100% por bug del portal). "
            f"resumen={resumen}"
        )
    return resumen


def es_error_operativo(exc: BaseException) -> bool:
    """
    True para fallos de datos/periodo conocidos (no bugs de código):
    - PDFs/cotizaciones ausentes del periodo
    - periodo inexistente en el select del portal
    """
    msg = str(exc)
    if isinstance(exc, FileNotFoundError):
        return "No hay PDFs" in msg and "para periodo" in msg
    if isinstance(exc, ValueError):
        if "Ningún RUT tiene" in msg:
            return True
        if "El portal no ofrece el periodo" in msg:
            return True
        if "Select de periodo sin opciones útiles" in msg:
            return True
    return False


def registrar_fallo(
    logger: logging.Logger,
    etiqueta: str,
    exc: BaseException,
) -> int:
    """Registra el fallo y devuelve código de salida 1 (sin traceback si es operativo)."""
    if es_error_operativo(exc):
        logger.error("%s", exc)
        return 1
    logger.error("Fallo %s:\n%s", etiqueta, traceback.format_exc())
    return 1
