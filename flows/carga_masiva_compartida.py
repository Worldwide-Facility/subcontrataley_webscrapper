"""Fase compartida tras tener plantilla Excel + PDFs listos.

Misma secuencia que liquidaciones/pagos (selectores `liquidaciones.*` ya
existentes): ir a cargar → Excel → dropzone → Validar → Realizar →
Documentos Agregados (la barra no llega a 100%).

Usada por documentos vigentes del trabajador. Los 4 pagos FAENA siguen con
su código propio en `carga_documento_unico` (sin depender de este módulo).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from browser import (
    asegurar_resultado_post_carga,
    cargar_documentos_dropzone,
    click_mutante,
    click_xpath,
    dry_run,
    enviar_archivos,
    esperar_post_carga,
    esperar_resultado_validacion,
    screenshot,
    xpk,
)
from flows.nivel_carga import NivelCarga

logger = logging.getLogger(__name__)


def ejecutar_carga_masiva_excel_y_pdfs(
    driver,
    wait,
    *,
    etiqueta: str,
    plantilla: Path,
    paths: list[Path],
    nivel: NivelCarga,
    zona_key: str = "liquidaciones.zona_upload_liquidaciones",
    columna: str = "nombre_de_archivo",
    resumen_prep: str = "",
) -> Path:
    """
    Pantalla de carga → Excel → dropzone → Validar → Realizar → post-carga.
    Respeta DRY_RUN. Falla si post-carga ok=False o subidos==0 con errores>0.
    """
    logger.info("[%s] nivel=%s | Ir a pantalla de carga", etiqueta, nivel.value)
    click_xpath(driver, wait, xpk(driver, "liquidaciones.ir_a_cargar"))
    time.sleep(2)
    screenshot(driver, f"{etiqueta}_pantalla_carga.png")

    logger.info("[%s] Subiendo Excel: %s", etiqueta, plantilla.name)
    enviar_archivos(driver, wait, "liquidaciones.input_excel", [plantilla])
    time.sleep(1)
    click_mutante(
        driver,
        wait,
        "liquidaciones.btn_enviar_excel",
        "click 'Cargar Excel' (sube la plantilla al portal)",
    )
    time.sleep(2)
    screenshot(driver, f"{etiqueta}_excel_enviado.png")

    logger.info("[%s] Subiendo %s documentos", etiqueta, len(paths))
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

    logger.info("[%s] Confirmar carga", etiqueta)
    click_mutante(
        driver,
        wait,
        "liquidaciones.btn_confirmar_carga",
        "click 'Validar Documentos' (envía la carga a validación)",
    )
    if not dry_run():
        esperar_resultado_validacion(
            driver, timeout=180, etiqueta=etiqueta, prefijo_shot=etiqueta
        )
    screenshot(driver, f"{etiqueta}_confirmar.png")

    logger.info("[%s] Post-confirmar", etiqueta)
    click_mutante(
        driver,
        wait,
        "liquidaciones.btn_post_confirmar",
        "click 'Realizar Carga Masiva' (carga definitiva; #cmsd_btn_realizar_carga_masiva)",
    )
    time.sleep(2)
    screenshot(driver, f"{etiqueta}_post_confirmar.png")
    if not dry_run():
        post = esperar_post_carga(
            driver, etiqueta=etiqueta, prefijo_shot=etiqueta, timeout=120
        )
        asegurar_resultado_post_carga(post, etiqueta=etiqueta)

    logger.info(
        "[%s] nivel=%s | %s | excel=%s | pdfs=%s | %s",
        etiqueta,
        nivel.value,
        "DRY_RUN: carga NO enviada" if dry_run() else "OK",
        plantilla.name,
        len(paths),
        resumen_prep,
    )
    return plantilla
