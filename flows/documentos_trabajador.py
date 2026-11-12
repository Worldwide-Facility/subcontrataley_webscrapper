"""Documentos vigentes del trabajador — nivel PERSONA (por RUT).

Catálogo de 15 tipos (nombres UI exactos) + carga en la sección de
documentos del trabajador. NO usa Cargas Masivas / plantillas faena
(`llegar_a_cargar_plantillas` / cmsd_*).

Reutiliza de la carga compartida solo dropzone / verificación / validación /
'Documentos Agregados' (`flows.carga_masiva_compartida.subir_y_confirmar_dropzone`).

Origen de PDFs: proveedor desacoplado (local|gcs provisional; definitivo pendiente).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from browser import screenshot, seleccionar_por_texto, xpk
from config import DOWNLOAD_DIR
from flows.carga_masiva_compartida import subir_y_confirmar_dropzone
from flows.llegar_a_documentos_persona import (
    buscar_trabajador_por_rut,
    llegar_a_documentos_persona,
    navegar_a_documentos_persona,
)
from flows.nivel_carga import NivelCarga
from flows.proveedor_documentos_trabajador import (
    ArchivoDocumento,
    ProveedorArchivosTrabajador,
    proveedor_desde_env,
)
from xpaths import xpath_pendiente

logger = logging.getLogger(__name__)

NIVEL = NivelCarga.PERSONA


@dataclass(frozen=True)
class DocumentoTrabajador:
    clave: str
    nombre_ui: str  # texto exacto del tipo de documento en el portal
    # Clave de tipo para el proveedor (provisional; no implica ruta GCS final)
    tipo_gcs: str
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
    """Filtra el catálogo por claves. None / vacío = los 15."""
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


def usa_carga_nivel_persona(cfg: DocumentoTrabajador) -> bool:
    """True si el doc se carga por trabajador (no plantilla faena)."""
    return cfg.nivel == NivelCarga.PERSONA and cfg.clave in {
        d.clave for d in DOCUMENTOS_TRABAJADOR
    }


def ejecutar_documento(cfg: DocumentoTrabajador) -> Callable:
    def ejecutar(driver, wait) -> int:
        return ejecutar_carga_documento_trabajador(driver, wait, cfg)

    ejecutar.__name__ = f"ejecutar_{cfg.clave}"
    return ejecutar


def _elegir_tipo_documento(driver, wait, cfg: DocumentoTrabajador) -> str | None:
    key = "persona.select_tipo_documento"
    if xpath_pendiente(key):
        logger.warning(
            "[%s] nivel=%s XPath pendiente: %s (tipo UI='%s')",
            cfg.clave,
            NIVEL.value,
            key,
            cfg.nombre_ui,
        )
        screenshot(driver, f"pendiente_{key.replace('.', '_')}.png")
        return key
    seleccionar_por_texto(driver, wait, xpk(driver, key), cfg.nombre_ui)
    time.sleep(0.5)
    screenshot(driver, f"{cfg.clave}_tipo.png")
    return None


def _cargar_un_rut(
    driver,
    wait,
    cfg: DocumentoTrabajador,
    archivo: ArchivoDocumento,
    path: Path,
) -> None:
    """Abre ficha del RUT, elige tipo y sube el PDF con helpers compartidos."""
    pend = buscar_trabajador_por_rut(driver, wait, archivo.rut_cuerpo)
    if pend:
        raise RuntimeError(
            f"[{cfg.clave}] No se pudo abrir ficha RUT={archivo.rut_cuerpo}: "
            f"xpath pendiente '{pend}' (nivel={NIVEL.value})"
        )
    pend = _elegir_tipo_documento(driver, wait, cfg)
    if pend:
        raise RuntimeError(
            f"[{cfg.clave}] No se pudo elegir tipo '{cfg.nombre_ui}': "
            f"xpath pendiente '{pend}'"
        )

    for key in (
        "persona.zona_upload",
        "persona.btn_validar",
        "persona.btn_realizar",
    ):
        if xpath_pendiente(key):
            raise RuntimeError(
                f"[{cfg.clave}] XPath pendiente para dropzone PERSONA: '{key}'. "
                "Capturar en el portal (sección documentos del trabajador)."
            )

    etiqueta = f"{cfg.clave}_{archivo.rut_cuerpo}"
    subir_y_confirmar_dropzone(
        driver,
        wait,
        etiqueta=etiqueta,
        paths=[path],
        nivel=NIVEL,
        zona_key="persona.zona_upload",
        btn_validar_key="persona.btn_validar",
        btn_realizar_key="persona.btn_realizar",
        plantilla=None,
    )


def ejecutar_carga_documento_trabajador(
    driver,
    wait,
    cfg: DocumentoTrabajador,
    *,
    proveedor: ProveedorArchivosTrabajador | None = None,
) -> int:
    """
    Carga nivel PERSONA: un PDF por RUT en documentos del trabajador.
    Returns: cantidad de RUTs cargados (0 si solo navegación pendiente).
    """
    if not usa_carga_nivel_persona(cfg):
        raise ValueError(
            f"{cfg.clave} no es carga PERSONA del catálogo (nivel={cfg.nivel})"
        )
    if cfg.nivel != NivelCarga.PERSONA:
        raise ValueError(
            f"{cfg.clave}: nivel={cfg.nivel}; este flujo solo admite PERSONA "
            "(no usar plantillas faena / cmsd_*)"
        )

    prov = proveedor or proveedor_desde_env()
    logger.info(
        "[%s] nivel=%s | UI='%s' | tipo=%s | proveedor=%s "
        "(origen definitivo pendiente; NO faena/plantillas)",
        cfg.clave,
        NIVEL.value,
        cfg.nombre_ui,
        cfg.tipo_gcs,
        prov.nombre,
    )

    pend = llegar_a_documentos_persona(driver, wait)
    if pend:
        raise RuntimeError(
            f"[{cfg.clave}] Navegación PERSONA incompleta: xpath pendiente '{pend}'. "
            "Capturar selectores en xpaths.py (persona.*). "
            "No usar llegar_a_cargar_plantillas (eso es FAENA)."
        )

    docs_idx = prov.indice_por_rut(cfg.tipo_gcs)
    if not docs_idx:
        raise ValueError(
            f"[{cfg.clave}] Proveedor '{prov.nombre}' sin archivos para "
            f"tipo={cfg.tipo_gcs} (origen pendiente de definición)."
        )

    staging = DOWNLOAD_DIR / f"staging_{cfg.clave}" / "persona" / prov.nombre
    paths = prov.materializar(list(docs_idx.values()), staging)
    por_nombre = {p.name: p for p in paths}

    ok = 0
    fallos: list[str] = []
    for rut, archivo in docs_idx.items():
        path = por_nombre.get(archivo.nombre)
        if path is None:
            fallos.append(rut)
            logger.error("[%s] Sin path local para RUT=%s (%s)", cfg.clave, rut, archivo.nombre)
            continue
        try:
            _cargar_un_rut(driver, wait, cfg, archivo, path)
            ok += 1
        except Exception:
            fallos.append(rut)
            logger.exception("[%s] Fallo carga RUT=%s", cfg.clave, rut)
            try:
                screenshot(driver, f"error_{cfg.clave}_{rut}.png")
            except Exception:
                pass
            try:
                navegar_a_documentos_persona(driver, wait)
            except Exception:
                pass

    if fallos:
        raise RuntimeError(
            f"[{cfg.clave}] nivel={NIVEL.value} fallos={len(fallos)} ok={ok}: {fallos}"
        )
    logger.info("[%s] nivel=%s OK ruts=%s", cfg.clave, NIVEL.value, ok)
    return ok
