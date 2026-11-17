"""Errores operativos esperados: mensaje de una línea y exit != 0, sin traceback."""

from __future__ import annotations

import logging
import traceback
from typing import Any


def exigir_ok_post_carga(
    resumen: dict[str, Any],
    *,
    etiqueta: str,
    esperado: int | None = None,
) -> dict[str, Any]:
    """
    Tras esperar_post_carga: falla si la carga no terminó de verdad o si
    Documentos Agregados quedó bajo el esperado (filas de plantilla / docs
    principales). La barra del portal no llega a 100% (bug); no se usa.
    """
    exp = esperado if esperado is not None else resumen.get("esperado")
    if not resumen.get("ok"):
        agg = resumen.get("agregados")
        if exp is not None and agg is not None and int(agg) < int(exp):
            raise RuntimeError(
                f"[{etiqueta}] Post-carga incompleta: Documentos Agregados={agg} "
                f"< esperado={exp} (filas de plantilla / docs principales; "
                f"criterio distinto de la barra al 100%). resumen={resumen}"
            )
        raise RuntimeError(
            f"[{etiqueta}] Post-carga falló: no terminó la carga masiva "
            f"(mensaje en curso o 'Documentos Agregados' ausente/inestable; "
            f"la barra no llega a 100% por bug del portal). resumen={resumen}"
        )
    if exp is not None:
        agg = resumen.get("agregados")
        if agg is None or int(agg) < int(exp):
            raise RuntimeError(
                f"[{etiqueta}] Post-carga incompleta: Documentos Agregados={agg} "
                f"< esperado={exp} (filas de plantilla / docs principales). "
                f"resumen={resumen}"
            )
    return resumen


def es_error_operativo(exc: BaseException) -> bool:
    """
    True para fallos de datos/periodo/carga conocidos (no bugs de código):
    - PDFs/cotizaciones ausentes del periodo
    - periodo inexistente en el select del portal
    - dropzone incompleto / post-carga incompleta o timeout de espera
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
    if isinstance(exc, TimeoutError):
        if "esperando uploads" in msg or "esperando fin" in msg:
            return True
    if isinstance(exc, RuntimeError):
        if "Post-carga incompleta" in msg:
            return True
        if "Post-carga falló" in msg:
            return True
        if "Archivos no presentes/OK en dropzone" in msg:
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
