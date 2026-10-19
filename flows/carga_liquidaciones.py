"""Flujo: Liquidaciones de Sueldo."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from browser import (
    cargar_documentos_dropzone,
    esperar_resultado_validacion,
    esperar_post_carga,
    click_mutante,
    dry_run,
    enviar_archivos,
    xpk,
    click_xpath,
    click_y_esperar_descarga,
    screenshot,
    esperar_select_cargado,
    seleccionar_periodo_mes_anterior,
    seleccionar_por_texto,
)
from config import DOWNLOAD_DIR
from flows.llegar_a_plantillas import llegar_a_cargar_plantillas
from flows.plantilla_schema import GLOB_PLANTILLA
from gcs_docs import descargar_docs, periodo_gcs_texto
from plantilla_liquidaciones_store import guardar_plantilla_liquidaciones
from rellenar_plantilla import rellenar_plantilla_liquidaciones

logger = logging.getLogger(__name__)

NOMBRE = "Liquidaciones de Sueldo"
TIPO_PLANTILLA = "Liquidaciones de Sueldo"


def ejecutar(driver, wait) -> Path:
    llegar_a_cargar_plantillas(driver, wait)

    logger.info("Eligiendo tipo: %s", TIPO_PLANTILLA)
    seleccionar_por_texto(
        driver, wait, xpk(driver, "liquidaciones.select_tipo"), TIPO_PLANTILLA
    )

    logger.info("Esperando carga del select de periodo…")
    esperar_select_cargado(
        driver, wait, xpk(driver, "liquidaciones.select_periodo"), min_opciones=1
    )

    logger.info("Eligiendo periodo (mes anterior a la ejecución)")
    periodo_ui = seleccionar_periodo_mes_anterior(
        driver, wait, xpk(driver, "liquidaciones.select_periodo")
    )
    time.sleep(1)
    screenshot(driver, "liquidaciones_tipo_y_periodo.png")

    logger.info("Descargando plantilla Excel (#cmsd_btn_descargar_plantilla)")
    plantilla = click_y_esperar_descarga(
        driver,
        wait,
        xpk(driver, "liquidaciones.btn_descargar_plantilla"),
        glob_pat=GLOB_PLANTILLA,
    )
    screenshot(driver, "liquidaciones_despues_descarga.png")

    periodo_gcs = periodo_gcs_texto()
    # El portal no vuelve a entregar esta planilla después de la carga.
    # Se guarda el Excel original (RUT y faena) para el resto de ejecuciones del mes.
    guardar_plantilla_liquidaciones(plantilla, periodo_gcs)
    staging = DOWNLOAD_DIR / "staging_liquidaciones" / periodo_gcs.replace(" ", "_")
    logger.info(
        "Rellenando plantilla desde GCS (UI='%s', GCS='%s')",
        periodo_ui,
        periodo_gcs,
    )
    resultado = rellenar_plantilla_liquidaciones(
        plantilla,
        periodo_gcs=periodo_gcs,
    )
    plantilla = resultado.plantilla
    logger.info(
        "Descargando PDFs solo de RUTs completos (%s) → %s",
        resultado.filas,
        staging,
    )
    paths_liq = descargar_docs(resultado.docs_liquidacion, staging / "liquidaciones")
    paths_tr = descargar_docs(resultado.docs_transferencia, staging / "transferencias")

    logger.info("Ir a pantalla de carga")
    click_xpath(driver, wait, xpk(driver, "liquidaciones.ir_a_cargar"))
    time.sleep(2)
    screenshot(driver, "liquidaciones_pantalla_carga.png")

    logger.info("Subiendo Excel plantilla: %s", plantilla.name)
    enviar_archivos(driver, wait, "liquidaciones.input_excel", [plantilla])
    time.sleep(1)
    click_mutante(
        driver, wait, "liquidaciones.btn_enviar_excel",
        "click 'Cargar Excel' (sube la plantilla al portal)",
    )
    time.sleep(2)
    screenshot(driver, "liquidaciones_excel_enviado.png")

    logger.info("Subiendo %s liquidaciones", len(paths_liq))
    cargar_documentos_dropzone(
        driver, wait, "liquidaciones.zona_upload_liquidaciones", paths_liq,
        plantilla=plantilla, columna="nombre_de_archivo", etiqueta=NOMBRE,
    )
    screenshot(driver, "liquidaciones_pdfs_liq.png")

    logger.info("Subiendo %s transferencias", len(paths_tr))
    cargar_documentos_dropzone(
        driver, wait, "liquidaciones.zona_upload_transferencias", paths_tr,
        plantilla=plantilla, columna="documento_asociado_1", etiqueta=NOMBRE,
    )
    screenshot(driver, "liquidaciones_pdfs_tr.png")

    logger.info("Confirmando carga")
    click_mutante(
        driver, wait, "liquidaciones.btn_confirmar_carga",
        "click 'Validar Documentos' (envía la carga a validación)",
    )
    if not dry_run():
        esperar_resultado_validacion(
            driver, timeout=180, etiqueta=NOMBRE, prefijo_shot="liquidaciones"
        )
    screenshot(driver, "liquidaciones_despues_confirmar.png")

    logger.info("Click post-confirmar")
    click_mutante(
        driver, wait, "liquidaciones.btn_post_confirmar",
        "click 'Realizar Carga Masiva' (carga definitiva; #cmsd_btn_realizar_carga_masiva)",
    )
    time.sleep(2)
    screenshot(driver, "liquidaciones_despues_post_confirmar.png")
    if not dry_run():
        esperar_post_carga(driver, etiqueta=NOMBRE, prefijo_shot="liquidaciones", timeout=120)

    logger.info(
        "%s: %s | excel=%s | keep=%s | liq=%s | tr=%s | "
        "liquido0=%s | eliminados=%s",
        NOMBRE,
        "DRY_RUN: carga NO enviada" if dry_run() else "carga enviada",
        plantilla.name,
        resultado.filas,
        len(paths_liq),
        len(paths_tr),
        resultado.liquido_cero,
        resultado.eliminadas,
    )
    return plantilla
