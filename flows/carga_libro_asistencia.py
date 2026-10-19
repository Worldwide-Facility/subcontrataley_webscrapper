"""
Flujo completo: Libro de Asistencia.

1) Planilla de Liquidaciones del mes (guardada al cargarlas, o descarga si aún no existe) → RUT por faena
2) Compila 1 PDF de asistencia por faena desde GCS
3) Descarga plantilla Libro de Asistencia y la rellena
4) Sube Excel + PDFs (espera fin de upload) → Validar → Carga Masiva → post
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from browser import (
    click_mutante,
    dry_run,
    enviar_archivos,
    xpk,
    click_xpath,
    click_y_esperar_descarga,
    esperar_select_cargado,
    esperar_zona_documentos_habilitada,
    screenshot,
    seleccionar_periodo_mes_anterior,
    seleccionar_por_texto,
)
from compilar_asistencias import compilar_asistencias_por_faena
from config import DOWNLOAD_DIR
from flows.llegar_a_plantillas import (
    llegar_a_cargar_plantillas,
    navegar_a_cargar_plantillas,
)
from flows.plantilla_schema import GLOB_PLANTILLA
from gcs_docs import periodo_gcs_texto
from plantilla_liquidaciones_store import asegurar_plantilla_liquidaciones
from rellenar_plantilla_asistencias import rellenar_plantilla_asistencias
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from xpaths import candidatos

logger = logging.getLogger(__name__)

NOMBRE = "Libro de Asistencia"
TIPO_LIQUIDACIONES = "Liquidaciones de Sueldo"
TIPO_ASISTENCIA = "Libro de Asistencia"


def _elegir_tipo_y_periodo(driver, wait, tipo: str) -> str:
    seleccionar_por_texto(driver, wait, xpk(driver, "liquidaciones.select_tipo"), tipo)
    esperar_select_cargado(
        driver, wait, xpk(driver, "liquidaciones.select_periodo"), min_opciones=1
    )
    periodo_ui = seleccionar_periodo_mes_anterior(
        driver, wait, xpk(driver, "liquidaciones.select_periodo")
    )
    time.sleep(1)
    return periodo_ui


def _esperar_clickable(driver, xpath: str, timeout: float = 300) -> None:
    WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )


def ejecutar(driver, wait) -> Path:
    llegar_a_cargar_plantillas(driver, wait)
    periodo_gcs = periodo_gcs_texto()
    logger.info("[%s] Periodo GCS: %s", NOMBRE, periodo_gcs)

    # --- 1. Excel liquidaciones (universo RUT/faena) ---
    def _bajar_liquidaciones() -> Path:
        logger.info("[%s] Descargando plantilla de liquidaciones", NOMBRE)
        periodo_ui = _elegir_tipo_y_periodo(driver, wait, TIPO_LIQUIDACIONES)
        screenshot(driver, "asist_e2e_liq_tipo_periodo.png")
        bajada = click_y_esperar_descarga(
            driver,
            wait,
            xpk(driver, "liquidaciones.btn_descargar_plantilla"),
            glob_pat=GLOB_PLANTILLA,
        )
        screenshot(driver, "asist_e2e_liq_descargada.png")
        logger.info("[%s] Excel liquidaciones: %s (UI=%s)", NOMBRE, bajada.name, periodo_ui)
        return bajada

    plantilla_liq = asegurar_plantilla_liquidaciones(
        periodo_gcs,
        DOWNLOAD_DIR / "plantillas_liquidaciones",
        _bajar_liquidaciones,
    )

    # --- 2. Compilar PDFs por faena (offline GCS) ---
    logger.info("[%s] Compilando asistencias GCS por faena…", NOMBRE)
    compilado = compilar_asistencias_por_faena(plantilla_liq, periodo=periodo_gcs)
    pdf_dir = compilado.staging / "por_faena"
    logger.info(
        "[%s] Compilados=%s sin_pdf_ruts=%s → %s",
        NOMBRE,
        len(compilado.pdfs),
        sum(len(v) for v in compilado.sin_pdf.values()),
        pdf_dir,
    )

    # --- 3. Plantilla Libro de Asistencia ---
    logger.info("[%s] Volviendo a 'Descarga Plantilla Nueva'", NOMBRE)
    try:
        click_xpath(driver, wait, xpk(driver, "liquidaciones.ir_a_descargar"))
        time.sleep(1)
    except Exception as exc:
        logger.warning("[%s] Toggle descarga falló (%s); re-navegando", NOMBRE, exc)
        try:
            navegar_a_cargar_plantillas(driver, wait)
        except Exception:
            llegar_a_cargar_plantillas(driver, wait)

    periodo_ui = _elegir_tipo_y_periodo(driver, wait, TIPO_ASISTENCIA)
    screenshot(driver, "asist_e2e_asi_tipo_periodo.png")
    plantilla_asi = click_y_esperar_descarga(
        driver,
        wait,
        xpk(driver, "liquidaciones.btn_descargar_plantilla"),
        glob_pat=GLOB_PLANTILLA,
    )
    screenshot(driver, "asist_e2e_asi_descargada.png")

    dest_excel = (
        DOWNLOAD_DIR
        / "staging_asistencias"
        / periodo_gcs.replace(" ", "_")
        / "plantilla_asistencias_rellena.xlsx"
    )
    relleno = rellenar_plantilla_asistencias(
        plantilla_asi,
        pdf_dir,
        periodo=periodo_gcs,
        guardar_como=dest_excel,
    )
    logger.info(
        "[%s] Relleno filas=%s pdfs=%s sin_pdf=%s → %s",
        NOMBRE,
        relleno.filas,
        len(relleno.pdfs),
        relleno.sin_pdf,
        relleno.plantilla,
    )

    # --- 4. Subir Excel + PDFs ---
    logger.info("[%s] Ir a pantalla de carga", NOMBRE)
    click_xpath(driver, wait, xpk(driver, "liquidaciones.ir_a_cargar"))
    time.sleep(2)
    screenshot(driver, "asist_e2e_pantalla_carga.png")

    logger.info("[%s] Subiendo Excel %s", NOMBRE, relleno.plantilla.name)
    enviar_archivos(driver, wait, "liquidaciones.input_excel", [relleno.plantilla])
    time.sleep(1)
    click_mutante(
        driver, wait, "liquidaciones.btn_enviar_excel",
        "click 'Cargar Excel' (sube la plantilla al portal)",
    )
    logger.info("[%s] Esperando que el portal habilite la zona de PDFs…", NOMBRE)
    if dry_run():
        # La zona solo se habilita tras 'Cargar Excel' (omitido): no exigir el
        # elemento aquí; enviar_archivos lo verifica tolerando su ausencia.
        zona_docs = "asistencias.zona_upload_documentos"
        logger.warning(
            "[DRY_RUN] se omitiría: esperar habilitación de la zona de documentos "
            "(solo ocurre tras 'Cargar Excel', que no se ejecutó)"
        )
    else:
        zona_docs = xpk(driver, "asistencias.zona_upload_documentos", visible=False)
        esperar_zona_documentos_habilitada(driver, zona_docs, timeout=180)
    screenshot(driver, "asist_e2e_excel_procesado.png")

    logger.info("[%s] Subiendo %s PDFs uno a uno → %s", NOMBRE, len(relleno.pdfs), zona_docs)
    enviar_archivos(
        driver,
        wait,
        "asistencias.zona_upload_documentos",
        relleno.pdfs,
        multiples=True,
        esperar=True,
        timeout=900,
        uno_a_uno=True,
    )
    screenshot(driver, "asist_e2e_pdfs_listos.png")

    # --- 5. Validar Documentos ---
    logger.info("[%s] Validar Documentos", NOMBRE)
    click_mutante(
        driver, wait, "liquidaciones.btn_validar_documentos",
        "click 'Validar Documentos' (envía la carga a validación)",
    )
    if dry_run():
        logger.warning(
            "[DRY_RUN] se omitiría: esperar resultado de validación, "
            "'Realizar Carga Masiva' y botón post-carga"
        )
        click_mutante(
            driver, wait, "asistencias.btn_realizar_carga_masiva",
            "click 'Realizar Carga Masiva' (carga definitiva)",
        )
        click_mutante(
            driver, wait, "asistencias.btn_despues_carga_masiva",
            "click botón post-carga masiva",
        )
        screenshot(driver, "asist_e2e_dry_run_fin.png")
        logger.info(
            "[%s] DRY_RUN: carga NO enviada | excel=%s | faenas=%s | pdfs=%s | periodo=%s",
            NOMBRE, relleno.plantilla.name, relleno.filas, len(relleno.pdfs), periodo_gcs,
        )
        return relleno.plantilla
    # Esperar resultado 2.3 (plantilla correcta / 0 errores)
    WebDriverWait(driver, 180).until(
        lambda d: "0" in (d.page_source or "")
        and (
            "correcta" in (d.page_source or "").lower()
            or "errores encontrados" in (d.page_source or "").lower()
        )
    )
    time.sleep(2)
    screenshot(driver, "asist_e2e_validado.png")

    # --- 6. Realizar Carga Masiva ---
    logger.info("[%s] Realizar Carga Masiva", NOMBRE)
    _esperar_clickable(
        driver, xpk(driver, "asistencias.btn_realizar_carga_masiva", timeout=180), timeout=180
    )
    click_mutante(
        driver, wait, "asistencias.btn_realizar_carga_masiva",
        "click 'Realizar Carga Masiva' (carga definitiva)",
    )
    time.sleep(3)
    screenshot(driver, "asist_e2e_carga_masiva_click.png")

    # --- 7. Esperar fin y botón post (solo cuando ya terminó) ---
    logger.info("[%s] Esperando botón post-carga…", NOMBRE)
    post_cands = candidatos("asistencias.btn_despues_carga_masiva")
    # Alternativas por texto por si cambia el DOM tras la carga
    post_alts = [
        *post_cands,
        "//button[contains(.,'Aceptar') or contains(.,'Continuar') or contains(.,'Finalizar') or contains(.,'Cerrar')]/span",
        "//button[contains(.,'Aceptar') or contains(.,'Continuar') or contains(.,'Finalizar')]",
    ]
    clicked_post = False
    t_end = time.time() + 600
    while time.time() < t_end and not clicked_post:
        for cand in post_alts:
            try:
                els = driver.find_elements(By.XPATH, cand)
                for el in els:
                    if el.is_displayed() and el.is_enabled():
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", el
                        )
                        time.sleep(0.5)
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        clicked_post = True
                        logger.info("[%s] Post-carga click: %s", NOMBRE, cand)
                        break
                if clicked_post:
                    break
            except Exception:
                continue
        if not clicked_post:
            time.sleep(2)
    if not clicked_post:
        screenshot(driver, "asist_e2e_sin_post_carga.png")
        logger.warning(
            "[%s] Carga masiva ok (sin botón post visible a tiempo); revisar UI",
            NOMBRE,
        )
    else:
        time.sleep(2)
        screenshot(driver, "asist_e2e_post_carga.png")

    logger.info(
        "[%s] OK | excel=%s | faenas=%s | pdfs=%s | periodo=%s",
        NOMBRE,
        relleno.plantilla.name,
        relleno.filas,
        len(relleno.pdfs),
        periodo_gcs,
    )
    return relleno.plantilla
