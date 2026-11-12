"""
Motor compartido de pagos.

- AFP / Isapre (cfg.por_faena=False): plantilla con 1 fila por RUT → 1 archivo por RUT.
- Mutualidades / Cajas (cfg.por_faena=True): la plantilla del portal es POR FAENA.
  Igual que Libro de Asistencia: usa la planilla de Liquidaciones de ese mes
  (la guardada al cargarla, o una descarga si aún no existe) como base RUT→faena,
  fusiona 1 PDF por faena y rellena la plantilla propia.

Luego: subir excel + PDFs → Validar Documentos → Realizar Carga Masiva.
"""

from __future__ import annotations

import logging
import time
from datetime import date
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
    esperar_select_cargado,
    screenshot,
    seleccionar_periodo_mes_anterior,
    seleccionar_por_texto,
)
from config import COTIZACIONES_DIA_DISPONIBLE, COTIZACIONES_PERIODO, DOWNLOAD_DIR
from flows.llegar_a_plantillas import llegar_a_cargar_plantillas
from flows.pagos_config import FlujoPagoConfig, fuente_por_faena
from flows.plantilla_schema import GLOB_PLANTILLA
from compilar_asistencias import compilar_docs_por_faena
from plantilla_liquidaciones_store import asegurar_plantilla_liquidaciones
from gcs_docs import (
    descargar_docs,
    periodo_cotizaciones,
    periodo_gcs_texto,
    referencia_para_periodo,
)
from rellenar_plantilla_asistencias import rellenar_plantilla_asistencias
from rellenar_plantilla_unico import rellenar_plantilla_un_documento

logger = logging.getLogger(__name__)


TIPO_LIQUIDACIONES = "Liquidaciones de Sueldo"


def _periodo_cotizaciones(cfg: FlujoPagoConfig) -> tuple[date | None, str]:
    """
    (referencia, periodo texto GCS). Para flujos de Cotizaciones aplica la regla
    del día COTIZACIONES_DIA_DISPONIBLE (o el override COTIZACIONES_PERIODO);
    `referencia` es la fecha cuyo 'mes anterior' es el periodo elegido.
    """
    if cfg.tipo_gcs != "Cotizaciones":
        return None, periodo_gcs_texto()
    pmes = periodo_cotizaciones()
    ref = referencia_para_periodo(pmes)
    logger.info(
        "[%s] Periodo cotizaciones %04d-%02d (%s; día disponible=%s)",
        cfg.clave, pmes.year, pmes.month,
        "override COTIZACIONES_PERIODO" if COTIZACIONES_PERIODO else "regla por defecto",
        COTIZACIONES_DIA_DISPONIBLE,
    )
    return ref, periodo_gcs_texto(ref)


def _elegir_tipo_y_periodo(
    driver, wait, clave: str, tipo: str, referencia: date | None = None
) -> str:
    logger.info("[%s] Eligiendo tipo: %s", clave, tipo)
    seleccionar_por_texto(driver, wait, xpk(driver, "liquidaciones.select_tipo"), tipo)
    logger.info("[%s] Esperando select de periodo…", clave)
    esperar_select_cargado(
        driver, wait, xpk(driver, "liquidaciones.select_periodo"), min_opciones=1
    )
    logger.info("[%s] Periodo mes anterior", clave)
    periodo_ui = seleccionar_periodo_mes_anterior(
        driver, wait, xpk(driver, "liquidaciones.select_periodo"), referencia=referencia,
        # Cotizaciones: el periodo debe coincidir con el de los PDF (sin fallback)
        estricto=referencia is not None,
    )
    time.sleep(1)
    return periodo_ui


def _descargar_plantilla(driver, wait) -> Path:
    return click_y_esperar_descarga(
        driver,
        wait,
        xpk(driver, "liquidaciones.btn_descargar_plantilla"),
        glob_pat=GLOB_PLANTILLA,
    )


def _preparar_por_faena(driver, wait, cfg: FlujoPagoConfig) -> tuple[Path, list[Path], str]:
    """
    Base Liquidaciones → RUT por faena → 1 PDF fusionado por faena → rellena la
    plantilla POR FAENA propia del documento. Devuelve (excel, pdfs, resumen).
    """
    ref, periodo_gcs = _periodo_cotizaciones(cfg)
    etiqueta = cfg.etiqueta_archivo or cfg.clave

    # 1) Base: planilla de Liquidaciones del periodo (RUT→faena)
    def _bajar_liquidaciones() -> Path:
        periodo_ui = _elegir_tipo_y_periodo(
            driver, wait, cfg.clave, TIPO_LIQUIDACIONES, referencia=ref
        )
        screenshot(driver, f"{cfg.clave}_base_liq_tipo_periodo.png")
        bajada = _descargar_plantilla(driver, wait)
        logger.info(
            "[%s] Base liquidaciones descargada: %s (UI=%s)",
            cfg.clave,
            bajada.name,
            periodo_ui,
        )
        return bajada

    plantilla_liq = asegurar_plantilla_liquidaciones(
        periodo_gcs,
        DOWNLOAD_DIR / "plantillas_liquidaciones",
        _bajar_liquidaciones,
    )
    logger.info("[%s] Base liquidaciones: %s", cfg.clave, plantilla_liq.name)

    # 2) Fusionar PDFs GCS (tipo cfg.tipo_gcs) por faena, orden por RUT
    compilado = compilar_docs_por_faena(
        plantilla_liq, fuente_por_faena(cfg), periodo=periodo_gcs, referencia=ref
    )
    pdf_dir = compilado.staging / "por_faena"
    n_sin = sum(len(v) for v in compilado.sin_pdf.values())
    logger.info(
        "[%s] Faenas en base=%s | PDFs fusionados=%s | RUT sin PDF=%s (detalle: %s)",
        cfg.clave, len(compilado.por_faena), len(compilado.pdfs), n_sin,
        compilado.staging / "resumen_compilacion.json",
    )

    # 3) Plantilla propia POR FAENA
    logger.info("[%s] Volviendo a 'Descarga Plantilla Nueva'", cfg.clave)
    try:
        click_xpath(driver, wait, xpk(driver, "liquidaciones.ir_a_descargar"))
        time.sleep(1)
    except Exception as exc:
        logger.warning("[%s] Toggle descarga falló (%s); re-navegando", cfg.clave, exc)
        llegar_a_cargar_plantillas(driver, wait)
    periodo_ui = _elegir_tipo_y_periodo(
        driver, wait, cfg.clave, cfg.nombre_ui, referencia=ref
    )
    screenshot(driver, f"{cfg.clave}_tipo_periodo.png")
    plantilla = _descargar_plantilla(driver, wait)
    screenshot(driver, f"{cfg.clave}_plantilla_descargada.png")

    dest_excel = compilado.staging / f"plantilla_{cfg.clave}_rellena.xlsx"
    relleno = rellenar_plantilla_asistencias(
        plantilla,
        pdf_dir,
        periodo=compilado.periodo,
        guardar_como=dest_excel,
        etiqueta=etiqueta,
    )
    if relleno.sin_pdf:
        logger.warning(
            "[%s] Faenas de la plantilla sin PDF (fila queda sin archivo): %s",
            cfg.clave, relleno.sin_pdf,
        )
    resumen = (
        f"faenas_rellenas={relleno.filas} | "
        f"faenas_sin_pdf={len(relleno.sin_pdf)} | rut_sin_pdf={n_sin}"
    )
    return relleno.plantilla, relleno.pdfs, resumen


def ejecutar_carga_un_documento(driver, wait, cfg: FlujoPagoConfig) -> Path:
    llegar_a_cargar_plantillas(driver, wait)

    if cfg.por_faena:
        plantilla, paths, resumen = _preparar_por_faena(driver, wait, cfg)
    else:
        ref, periodo_gcs = _periodo_cotizaciones(cfg)
        periodo_ui = _elegir_tipo_y_periodo(
            driver, wait, cfg.clave, cfg.nombre_ui, referencia=ref
        )
        screenshot(driver, f"{cfg.clave}_tipo_periodo.png")

        logger.info("[%s] Descargando plantilla", cfg.clave)
        plantilla = _descargar_plantilla(driver, wait)
        screenshot(driver, f"{cfg.clave}_plantilla_descargada.png")

        logger.info(
            "[%s] Rellenando Excel (UI='%s', GCS='%s', tipo=%s)",
            cfg.clave,
            periodo_ui,
            periodo_gcs,
            cfg.tipo_gcs,
        )
        resultado = rellenar_plantilla_un_documento(
            plantilla,
            tipo_gcs=cfg.tipo_gcs,
            layout=cfg.layout_gcs,
            periodo_gcs=periodo_gcs,
            referencia=ref,
        )
        plantilla = resultado.plantilla

        staging = (
            DOWNLOAD_DIR
            / f"staging_{cfg.clave}"
            / periodo_gcs.replace(" ", "_")
        )
        logger.info("[%s] Descargando %s PDFs → %s", cfg.clave, resultado.filas, staging)
        paths = descargar_docs(resultado.docs, staging)
        resumen = f"keep={resultado.filas} | elim={resultado.eliminadas}"

    logger.info("[%s] Ir a pantalla de carga", cfg.clave)
    click_xpath(driver, wait, xpk(driver, "liquidaciones.ir_a_cargar"))
    time.sleep(2)
    screenshot(driver, f"{cfg.clave}_pantalla_carga.png")

    logger.info("[%s] Subiendo Excel: %s", cfg.clave, plantilla.name)
    enviar_archivos(driver, wait, "liquidaciones.input_excel", [plantilla])
    time.sleep(1)
    click_mutante(
        driver, wait, "liquidaciones.btn_enviar_excel",
        "click 'Cargar Excel' (sube la plantilla al portal)",
    )
    time.sleep(2)
    screenshot(driver, f"{cfg.clave}_excel_enviado.png")

    logger.info("[%s] Subiendo %s documentos", cfg.clave, len(paths))
    cargar_documentos_dropzone(
        driver, wait, "liquidaciones.zona_upload_liquidaciones", paths,
        plantilla=plantilla, columna="nombre_de_archivo", etiqueta=cfg.clave,
    )
    screenshot(driver, f"{cfg.clave}_pdfs.png")

    logger.info("[%s] Confirmar carga", cfg.clave)
    click_mutante(
        driver, wait, "liquidaciones.btn_confirmar_carga",
        "click 'Validar Documentos' (envía la carga a validación)",
    )
    if not dry_run():
        esperar_resultado_validacion(
            driver, timeout=180, etiqueta=cfg.clave, prefijo_shot=cfg.clave
        )
    screenshot(driver, f"{cfg.clave}_confirmar.png")

    logger.info("[%s] Post-confirmar", cfg.clave)
    click_mutante(
        driver, wait, "liquidaciones.btn_post_confirmar",
        "click 'Realizar Carga Masiva' (carga definitiva; #cmsd_btn_realizar_carga_masiva)",
    )
    time.sleep(2)
    screenshot(driver, f"{cfg.clave}_post_confirmar.png")
    if not dry_run():
        esperar_post_carga(driver, etiqueta=cfg.clave, prefijo_shot=cfg.clave, timeout=120)

    logger.info(
        "[%s] %s | excel=%s | pdfs=%s | %s",
        cfg.clave,
        "DRY_RUN: carga NO enviada" if dry_run() else "OK",
        plantilla.name,
        len(paths),
        resumen,
    )
    return plantilla
