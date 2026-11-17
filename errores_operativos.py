"""Errores operativos esperados: mensaje de una línea y exit != 0, sin traceback."""

from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Any

from espera_carga import evaluar_agregados_vs_esperado

ESTADO_PERIODO_NO_DISPONIBLE = "periodo_no_disponible"

_MESES_ES = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


class PeriodoNoDisponible(Exception):
    """
    El periodo objetivo no está en el select del portal (completo o no habilitado).

    No es un fallo de ejecución: no se debe subir nada; exit 0 con
    estado=periodo_no_disponible para que auditor/monitores lo distingan
    de una carga exitosa.
    """

    estado = ESTADO_PERIODO_NO_DISPONIBLE

    def __init__(
        self,
        periodo: date,
        tipo: str = "",
        opciones: list[str] | None = None,
    ):
        self.periodo = periodo
        self.tipo = (tipo or "").strip() or "documento"
        self.opciones = list(opciones or [])
        mes_anio = f"{_MESES_ES[periodo.month].capitalize()} {periodo.year}"
        super().__init__(
            f"Período {mes_anio} no disponible en el portal para {self.tipo} "
            f"(completo o no habilitado); no se sube nada"
        )


def registrar_periodo_no_disponible(
    logger: logging.Logger,
    exc: PeriodoNoDisponible,
    driver=None,
) -> int:
    """Log explícito + logout best-effort; exit 0 (sin pendientes de carga)."""
    logger.info("%s | estado=%s", exc, exc.estado)
    if exc.opciones:
        logger.info(
            "Opciones del select de periodo: %s",
            exc.opciones,
        )
    if driver is not None:
        try:
            from flows.llegar_a_plantillas import hacer_logout

            hacer_logout(driver)
        except Exception as logout_exc:
            logger.warning(
                "Logout no pudo completarse tras periodo no disponible: %s",
                logout_exc,
            )
    return 0


def exigir_ok_post_carga(
    resumen: dict[str, Any],
    *,
    etiqueta: str,
    esperado: int | None = None,
    filas_plantilla: int | None = None,
) -> dict[str, Any]:
    """
    Tras esperar_post_carga.

    Regla (mínimo razonable = esperado = min(filas, PDFs únicos[, RUT únicos])):
      - Agregados < minimo → FAIL (diferencia > 0 vs mínimo razonable)
      - minimo <= Agregados < filas_plantilla → WARNING + OK
        (p.ej. plantilla con RUT duplicado: 109 filas, 108 PDFs)
      - Agregados >= filas → OK
      - sin fin real (timeout / sin contador) → FAIL

    La barra del portal no llega a 100% (bug); no se usa.
    """
    exp = esperado if esperado is not None else resumen.get("esperado")
    filas = (
        filas_plantilla
        if filas_plantilla is not None
        else resumen.get("filas_plantilla")
    )
    agg = resumen.get("agregados")

    if not resumen.get("ok"):
        ev = evaluar_agregados_vs_esperado(
            agg, minimo_razonable=exp, filas_plantilla=filas
        )
        # Estable bajo mínimo: el wait ya marcó ok=False
        if exp is not None and agg is not None and not ev["ok"]:
            raise RuntimeError(
                f"[{etiqueta}] Post-carga incompleta: Documentos Agregados={agg} "
                f"< minimo_razonable={exp} (diff={ev.get('diff_vs_minimo')}; "
                f"filas_plantilla={filas}; criterio=min(filas,pdfs_unicos[,ruts]); "
                f"no se usa la barra al 100%). resumen={resumen}"
            )
        raise RuntimeError(
            f"[{etiqueta}] Post-carga falló: no terminó la carga masiva "
            f"(mensaje en curso o 'Documentos Agregados' ausente/inestable; "
            f"la barra no llega a 100% por bug del portal). resumen={resumen}"
        )

    # ok=True desde el wait: revalidar y emitir WARNING si aplica
    if exp is not None:
        ev = evaluar_agregados_vs_esperado(
            agg, minimo_razonable=exp, filas_plantilla=filas
        )
        if not ev["ok"]:
            raise RuntimeError(
                f"[{etiqueta}] Post-carga incompleta: Documentos Agregados={agg} "
                f"< minimo_razonable={exp} (diff={ev.get('diff_vs_minimo')}; "
                f"filas_plantilla={filas}). resumen={resumen}"
            )
        if ev.get("warning"):
            logging.getLogger(__name__).warning(
                "[%s] Documentos Agregados=%s < filas_plantilla=%s pero "
                ">= minimo_razonable=%s (posible fila/RUT duplicado; no se falla).",
                etiqueta,
                agg,
                filas,
                exp,
            )

    subidos = resumen.get("subidos")
    if subidos is None:
        subidos = resumen.get("agregados")
    errores = int(resumen.get("errores") or 0)
    if subidos is not None and int(subidos) == 0 and errores > 0:
        raise RuntimeError(
            f"[{etiqueta}] Post-carga: subidos=0 con errores={errores}: {resumen}"
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
    if isinstance(exc, PeriodoNoDisponible):
        # No es error operativo: se maneja con exit 0 (registrar_periodo_no_disponible).
        return False
    if isinstance(exc, ValueError):
        if "Ningún RUT tiene" in msg:
            return True
        # Select vacío/roto = error de página (exit != 0). Periodo ausente
        # entre opciones válidas ya no llega aquí (PeriodoNoDisponible).
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
        if "Errores en dropzone" in msg:
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
