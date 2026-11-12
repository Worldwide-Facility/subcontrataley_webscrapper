"""Helpers reutilizables de dropzone / validación / Documentos Agregados.

Sirven tanto a cargas FAENA (plantillas cmsd_*) como PERSONA (documentos del
trabajador por RUT). Este módulo NO navega ni asume plantilla Excel: solo
la fase común una vez que la zona de upload ya está en pantalla.

Fin de carga = aparición de "Documentos Agregados" (la barra no llega a 100%).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from browser import (
    asegurar_resultado_post_carga,
    cargar_documentos_dropzone,
    click_mutante,
    dry_run,
    esperar_post_carga,
    esperar_resultado_validacion,
    screenshot,
)
from flows.nivel_carga import NivelCarga

logger = logging.getLogger(__name__)


def subir_y_confirmar_dropzone(
    driver,
    wait,
    *,
    etiqueta: str,
    paths: list[Path],
    nivel: NivelCarga,
    zona_key: str,
    btn_validar_key: str,
    btn_realizar_key: str,
    plantilla: Path | None = None,
    columna: str = "nombre_de_archivo",
) -> None:
    """
    Dropzone (zona habilitada + verificación) → Validar → Realizar →
    esperar Documentos Agregados. Respeta DRY_RUN.
    Falla si post-carga ok=False o subidos==0 con errores>0.
    """
    logger.info(
        "[%s] nivel=%s | subiendo %s archivo(s) → %s",
        etiqueta,
        nivel.value,
        len(paths),
        zona_key,
    )
    cargar_documentos_dropzone(
        driver,
        wait,
        zona_key,
        paths,
        plantilla=plantilla,
        columna=columna,
        etiqueta=etiqueta,
    )
    screenshot(driver, f"{etiqueta}_pdfs.png")

    logger.info("[%s] Validar documentos", etiqueta)
    click_mutante(
        driver,
        wait,
        btn_validar_key,
        "click validar documentos (envía a validación)",
    )
    if not dry_run():
        esperar_resultado_validacion(
            driver, timeout=180, etiqueta=etiqueta, prefijo_shot=etiqueta
        )
    screenshot(driver, f"{etiqueta}_confirmar.png")

    logger.info("[%s] Realizar carga", etiqueta)
    click_mutante(
        driver,
        wait,
        btn_realizar_key,
        "click realizar carga (definitiva)",
    )
    time.sleep(2)
    screenshot(driver, f"{etiqueta}_post_confirmar.png")
    if not dry_run():
        post = esperar_post_carga(
            driver, etiqueta=etiqueta, prefijo_shot=etiqueta, timeout=120
        )
        asegurar_resultado_post_carga(post, etiqueta=etiqueta)

    logger.info(
        "[%s] nivel=%s | %s | pdfs=%s",
        etiqueta,
        nivel.value,
        "DRY_RUN: carga NO enviada" if dry_run() else "OK",
        len(paths),
    )
