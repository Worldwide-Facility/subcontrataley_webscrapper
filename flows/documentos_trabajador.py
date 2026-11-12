"""Documentos vigentes del trabajador — mismo flujo de plantillas que pagos/liq.

Navegación y XPaths: idénticos a liquidaciones/pagos (`llegar_a_cargar_plantillas`,
`liquidaciones.select_tipo`, periodo, plantilla Excel, dropzone cmsd_*).
Única diferencia: opción del select Documento = `nombre_ui` exacto (15 tipos).

Metadato `NivelCarga.PERSONA` (1 PDF por RUT). Origen de archivos desacoplado
vía proveedor (local|gcs provisional; definitivo pendiente).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from browser import (
    click_y_esperar_descarga,
    esperar_select_cargado,
    screenshot,
    seleccionar_periodo_mes_anterior,
    seleccionar_por_texto,
    xpk,
)
from config import DOWNLOAD_DIR
from flows.carga_masiva_compartida import ejecutar_carga_masiva_excel_y_pdfs
from flows.llegar_a_plantillas import llegar_a_cargar_plantillas
from flows.nivel_carga import NivelCarga
from flows.plantilla_schema import GLOB_PLANTILLA
from flows.proveedor_documentos_trabajador import (
    ProveedorArchivosTrabajador,
    proveedor_desde_env,
)
from rellenar_plantilla_unico import rellenar_plantilla_desde_archivos

logger = logging.getLogger(__name__)

NIVEL = NivelCarga.PERSONA


@dataclass(frozen=True)
class DocumentoTrabajador:
    clave: str
    nombre_ui: str  # texto exacto del <select> Documento (liquidaciones.select_tipo)
    tipo_gcs: str  # clave de tipo para el proveedor (provisional)
    nivel: NivelCarga = NivelCarga.PERSONA


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


def seleccionar_documentos(
    claves: Iterable[str] | None = None,
) -> tuple[DocumentoTrabajador, ...]:
    if claves is None:
        return DOCUMENTOS_TRABAJADOR
    pedidas = [c.strip() for c in claves if str(c).strip()]
    if not pedidas:
        return DOCUMENTOS_TRABAJADOR
    por_clave = {d.clave: d for d in DOCUMENTOS_TRABAJADOR}
    desconocidas = [c for c in pedidas if c not in por_clave]
    if desconocidas:
        raise ValueError(
            f"Claves de documento desconocidas: {desconocidas}. "
            f"Válidas: {sorted(por_clave)}"
        )
    return tuple(por_clave[c] for c in pedidas)


def documentos_desde_env(
    env_var: str = "DOCUMENTOS_TRABAJADOR_CLAVES",
) -> tuple[DocumentoTrabajador, ...]:
    raw = (os.environ.get(env_var) or "").strip()
    if not raw:
        return DOCUMENTOS_TRABAJADOR
    return seleccionar_documentos(raw.split(","))


def usa_mismo_flujo_plantillas(cfg: DocumentoTrabajador) -> bool:
    """Los 15 usan el mismo flujo cmsd_*/liquidaciones.*; solo cambia el select."""
    return cfg.clave in {d.clave for d in DOCUMENTOS_TRABAJADOR}


def ejecutar_documento(cfg: DocumentoTrabajador) -> Callable:
    def ejecutar(driver, wait) -> Path:
        return ejecutar_carga_documento_trabajador(driver, wait, cfg)

    ejecutar.__name__ = f"ejecutar_{cfg.clave}"
    return ejecutar


def _elegir_tipo_y_periodo(driver, wait, clave: str, tipo_ui: str) -> str:
    """Mismos selectores que pagos/liquidaciones; `tipo_ui` = opción del select."""
    logger.info("[%s] Eligiendo tipo (select Documento): %s", clave, tipo_ui)
    seleccionar_por_texto(
        driver, wait, xpk(driver, "liquidaciones.select_tipo"), tipo_ui
    )
    logger.info("[%s] Esperando select de periodo…", clave)
    esperar_select_cargado(
        driver, wait, xpk(driver, "liquidaciones.select_periodo"), min_opciones=1
    )
    logger.info("[%s] Periodo mes anterior (UI; origen PDF desacoplado)", clave)
    periodo_ui = seleccionar_periodo_mes_anterior(
        driver, wait, xpk(driver, "liquidaciones.select_periodo")
    )
    time.sleep(1)
    return periodo_ui


def ejecutar_carga_documento_trabajador(
    driver,
    wait,
    cfg: DocumentoTrabajador,
    *,
    proveedor: ProveedorArchivosTrabajador | None = None,
) -> Path:
    """
    Mismo tronco que pagos 1-doc: plantillas → select tipo=`nombre_ui` →
    periodo → Excel + PDFs → dropzone → validar → Documentos Agregados.
    """
    if not usa_mismo_flujo_plantillas(cfg):
        raise ValueError(f"{cfg.clave} no está en el catálogo de 15 docs")
    if cfg.nivel != NivelCarga.PERSONA:
        raise ValueError(f"{cfg.clave}: se espera nivel=PERSONA, got {cfg.nivel}")

    prov = proveedor or proveedor_desde_env()
    logger.info(
        "[%s] nivel=%s | mismo flujo plantillas | select='%s' | proveedor=%s",
        cfg.clave,
        NIVEL.value,
        cfg.nombre_ui,
        prov.nombre,
    )

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

    docs_idx = prov.indice_por_rut(cfg.tipo_gcs)
    logger.info(
        "[%s] Rellenando Excel (UI='%s' periodo_ui='%s', proveedor=%s, ruts=%s)",
        cfg.clave,
        cfg.nombre_ui,
        periodo_ui,
        prov.nombre,
        len(docs_idx),
    )
    resultado = rellenar_plantilla_desde_archivos(
        plantilla,
        tipo=cfg.tipo_gcs,
        docs_idx=docs_idx,
        etiqueta_origen=f"{prov.nombre}:{cfg.tipo_gcs}",
    )
    plantilla = resultado.plantilla

    staging = DOWNLOAD_DIR / f"staging_{cfg.clave}" / prov.nombre
    logger.info("[%s] Materializando %s PDFs → %s", cfg.clave, resultado.filas, staging)
    paths = prov.materializar(list(resultado.archivos), staging)
    resumen = (
        f"keep={resultado.filas} | elim={resultado.eliminadas} | "
        f"proveedor={prov.nombre}"
    )

    return ejecutar_carga_masiva_excel_y_pdfs(
        driver,
        wait,
        etiqueta=cfg.clave,
        plantilla=plantilla,
        paths=paths,
        nivel=NIVEL,
        resumen_prep=resumen,
    )
