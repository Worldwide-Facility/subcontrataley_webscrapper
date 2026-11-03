"""Documentos vigentes de trabajador: 1 PDF por RUT, sin carpeta de mes.

GCS: Trabajadores/{rut}/{tipo_gcs}/{archivo}.pdf
El portal igual pide periodo; ese mes solo se elige en la UI.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from browser import (
    cargar_documentos_dropzone,
    click_mutante,
    click_xpath,
    click_y_esperar_descarga,
    dry_run,
    enviar_archivos,
    esperar_post_carga,
    esperar_resultado_validacion,
    esperar_select_cargado,
    screenshot,
    seleccionar_periodo_mes_anterior,
    seleccionar_por_texto,
    xpk,
)
from config import DOWNLOAD_DIR
from flows.llegar_a_plantillas import llegar_a_cargar_plantillas
from flows.plantilla_schema import GLOB_PLANTILLA
from gcs_docs import descargar_docs
from rellenar_plantilla_unico import rellenar_plantilla_un_documento

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentoTrabajador:
    clave: str
    nombre_ui: str  # texto exacto del <select> Documento
    tipo_gcs: str  # carpeta Trabajadores/{rut}/{tipo_gcs}/


DOCUMENTOS_TRABAJADOR: tuple[DocumentoTrabajador, ...] = (
    DocumentoTrabajador(
        clave="capacitacion_prevencion",
        nombre_ui="Capacitación para Pers. Trab. en Prevención de Riesgos Laborales",
        tipo_gcs="CapacitacionPrevencion",
    ),
    DocumentoTrabajador(
        clave="capacitacion_uso_epp",
        nombre_ui="Capacitación Uso y Mantención de EPP",
        tipo_gcs="CapacitacionUsoEPP",
    ),
    DocumentoTrabajador(
        clave="certificado_os10",
        nombre_ui="Certificado Curso de Guardia de Seguridad (OS10 o SPD)",
        tipo_gcs="CertificadoOS10",
    ),
    DocumentoTrabajador(
        clave="certificado_antecedentes",
        nombre_ui="Certificado de Antecedentes",
        tipo_gcs="CertificadoAntecedentes",
    ),
    DocumentoTrabajador(
        clave="contratos_trabajo",
        nombre_ui="Contratos de Trabajo",
        tipo_gcs="Contrato",
    ),
    DocumentoTrabajador(
        clave="cedulas_identidad",
        nombre_ui="Cédulas de Identidad",
        tipo_gcs="CedulaIdentidad",
    ),
    DocumentoTrabajador(
        clave="entrega_epp",
        nombre_ui="Entrega EPP",
        tipo_gcs="EntregaEPP",
    ),
    DocumentoTrabajador(
        clave="guia_practica_seguridad",
        nombre_ui="Guía Práctica de Seguridad",
        tipo_gcs="GuiaPracticaSeguridad",
    ),
    DocumentoTrabajador(
        clave="recepcion_reglamento_contratistas",
        nombre_ui="Recepción Reglamento Especial de Empresas Contratistas (Trabajador)",
        tipo_gcs="RecepcionReglamentoContratistas",
    ),
    DocumentoTrabajador(
        clave="registro_difusion_reglamento",
        nombre_ui="Registro Difusión Trabajador Reglamento Interno",
        tipo_gcs="RegistroDifusionReglamento",
    ),
    DocumentoTrabajador(
        clave="seguro_vida",
        nombre_ui="Seguro de Vida Individual Trabajador",
        tipo_gcs="SeguroVida",
    ),
    DocumentoTrabajador(
        clave="toma_conocimiento_iper",
        nombre_ui="Toma Conoc. Trab. Matriz IPER del Contratista",
        tipo_gcs="TomaConocimientoIPER",
    ),
    DocumentoTrabajador(
        clave="toma_conocimiento_procedimiento",
        nombre_ui="Toma Conoc. Trab. Procedimiento de Trabajo Seguro",
        tipo_gcs="TomaConocimientoProcedimiento",
    ),
    DocumentoTrabajador(
        clave="toma_conocimiento_programa",
        nombre_ui="Toma Conoc. Trab. Programa de Trabajo Preventivo",
        tipo_gcs="TomaConocimientoPrograma",
    ),
    DocumentoTrabajador(
        clave="toma_conocimiento_riesgos",
        nombre_ui="Toma de Conoc. de Trab. Información de Riesgos Laborales",
        tipo_gcs="TomaConocimientoRiesgos",
    ),
)


def ejecutar_documento(cfg: DocumentoTrabajador) -> Callable:
    """Fábrica para FLUJOS_CARGA: ejecutar(driver, wait)."""

    def ejecutar(driver, wait) -> Path:
        return ejecutar_carga_documento_trabajador(driver, wait, cfg)

    ejecutar.__name__ = f"ejecutar_{cfg.clave}"
    return ejecutar


def _elegir_tipo_y_periodo(driver, wait, clave: str, tipo: str) -> str:
    logger.info("[%s] Eligiendo tipo: %s", clave, tipo)
    seleccionar_por_texto(driver, wait, xpk(driver, "liquidaciones.select_tipo"), tipo)
    logger.info("[%s] Esperando select de periodo…", clave)
    esperar_select_cargado(
        driver, wait, xpk(driver, "liquidaciones.select_periodo"), min_opciones=1
    )
    logger.info("[%s] Periodo mes anterior (solo UI; el PDF es vigente)", clave)
    periodo_ui = seleccionar_periodo_mes_anterior(
        driver, wait, xpk(driver, "liquidaciones.select_periodo")
    )
    time.sleep(1)
    return periodo_ui


def ejecutar_carga_documento_trabajador(driver, wait, cfg: DocumentoTrabajador) -> Path:
    """Carga masiva de un documento vigente: plantilla por RUT + 1 PDF."""
    llegar_a_cargar_plantillas(driver, wait)
    periodo_ui = _elegir_tipo_y_periodo(driver, wait, cfg.clave, cfg.nombre_ui)
    screenshot(driver, f"{cfg.clave}_tipo_periodo.png")

    logger.info("[%s] Descargando plantilla", cfg.clave)
    plantilla = click_y_esperar_descarga(
        driver,
        wait,
        xpk(driver, "liquidaciones.btn_descargar_plantilla"),
        glob_pat=GLOB_PLANTILLA,
    )
    screenshot(driver, f"{cfg.clave}_plantilla_descargada.png")

    logger.info(
        "[%s] Rellenando Excel (UI='%s', GCS vigente, tipo=%s)",
        cfg.clave,
        periodo_ui,
        cfg.tipo_gcs,
    )
    resultado = rellenar_plantilla_un_documento(
        plantilla,
        tipo_gcs=cfg.tipo_gcs,
        layout="vigente",
    )
    plantilla = resultado.plantilla

    staging = DOWNLOAD_DIR / f"staging_{cfg.clave}" / "vigente"
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
