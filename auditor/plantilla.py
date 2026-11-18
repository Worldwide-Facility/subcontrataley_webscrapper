"""Descarga / lectura de la plantilla de liquidaciones (hoja Documentos)."""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from auditor.modelos import TrabajadorPlantilla
from auditor.periodo import periodo_texto
from browser import (
    click_y_esperar_descarga,
    iniciar_navegador,
    mes_anterior,
    seleccionar_periodo_mes_anterior,
    seleccionar_por_texto,
    esperar_select_cargado,
    xpk,
)
from flows.carga_liquidaciones import TIPO_PLANTILLA
from flows.llegar_a_plantillas import llegar_a_cargar_plantillas
from flows.plantilla_schema import GLOB_PLANTILLA, HOJA_DOCUMENTOS
from gcs_docs import referencia_para_periodo, rut_cuerpo
from plantilla_liquidaciones_store import (
    asegurar_plantilla_liquidaciones,
    cargar_plantilla_liquidaciones,
)

logger = logging.getLogger(__name__)

COLUMNAS_CLAVE = (
    "RUT",
    "Nombre",
    "ingreso_faena",
    "salida_faena",
    "contrato_id",
    "faenacontratista_id",
    "faena",
    "local",
)


def leer_trabajadores_plantilla(path: Path) -> list[TrabajadorPlantilla]:
    """Lee la hoja Documentos de la plantilla de liquidaciones."""
    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        if HOJA_DOCUMENTOS not in wb.sheetnames:
            raise ValueError(f"No existe hoja '{HOJA_DOCUMENTOS}' en {path}")
        ws = wb[HOJA_DOCUMENTOS]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    idx = {h: i for i, h in enumerate(headers)}
    for col in ("RUT",):
        if col not in idx:
            raise ValueError(f"Falta columna {col} en plantilla: {headers}")

    def _cell(row, name: str) -> str | None:
        i = idx.get(name)
        if i is None or i >= len(row):
            return None
        v = row[i]
        if v is None:
            return None
        return str(v).strip() or None

    out: list[TrabajadorPlantilla] = []
    vistos: set[str] = set()
    for row in rows[1:]:
        if not row:
            continue
        rut_raw = _cell(row, "RUT")
        if not rut_raw:
            continue
        cuerpo = rut_cuerpo(rut_raw)
        if not cuerpo:
            continue
        # Un RUT puede aparecer en 2 faenas; para el cruce usamos la 1ª.
        if cuerpo in vistos:
            continue
        vistos.add(cuerpo)
        rut_norm = rut_raw.replace(".", "").replace(" ", "").upper()
        out.append(
            TrabajadorPlantilla(
                rut=rut_norm,
                rut_cuerpo=cuerpo,
                nombre=_cell(row, "Nombre") or "",
                ingreso_faena=_cell(row, "ingreso_faena"),
                salida_faena=_cell(row, "salida_faena"),
                contrato_id=_cell(row, "contrato_id"),
                faenacontratista_id=_cell(row, "faenacontratista_id"),
                faena=_cell(row, "faena") or "",
                local=_cell(row, "local") or "",
                fecha_fin_contrato=_cell(row, "fecha_fin_contrato"),
            )
        )
    logger.info("Plantilla %s → %s trabajadores (RUT únicos)", path.name, len(out))
    return out


def _descargar_del_portal(periodo: date, dest_dir: Path) -> Path:
    """Login + descarga de plantilla Liquidaciones para el periodo."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    # referencia tal que mes_anterior(ref) == periodo
    referencia = referencia_para_periodo(periodo)
    assert mes_anterior(referencia) == periodo

    driver = None
    try:
        driver, wait = iniciar_navegador(headless=True)
        llegar_a_cargar_plantillas(driver, wait)
        seleccionar_por_texto(
            driver, wait, xpk(driver, "liquidaciones.select_tipo"), TIPO_PLANTILLA
        )
        esperar_select_cargado(
            driver, wait, xpk(driver, "liquidaciones.select_periodo"), min_opciones=1
        )
        periodo_ui = seleccionar_periodo_mes_anterior(
            driver,
            wait,
            xpk(driver, "liquidaciones.select_periodo"),
            referencia=referencia,
            estricto=True,
        )
        logger.info("Periodo UI seleccionado: %s (objetivo %s)", periodo_ui, periodo_texto(periodo))
        time.sleep(1)
        path = click_y_esperar_descarga(
            driver,
            wait,
            xpk(driver, "liquidaciones.btn_descargar_plantilla"),
            glob_pat=GLOB_PLANTILLA,
        )
        return Path(path)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def obtener_plantilla(
    periodo: date,
    dest_dir: Path,
    *,
    forzar_portal: bool = False,
    solo_gcs: bool = False,
) -> Path:
    """
    Obtiene la plantilla del periodo.

    1) Reutiliza la guardada en GCS (plantilla_liquidaciones_store) si existe.
    2) Si no, descarga del portal (mismo login/flujo del repo) y la guarda.
    """
    periodo_gcs = periodo_texto(periodo)
    if not forzar_portal:
        guardada = cargar_plantilla_liquidaciones(periodo_gcs, dest_dir)
        if guardada is not None:
            logger.info("Usando plantilla cacheada GCS para %s", periodo_gcs)
            return guardada
        if solo_gcs:
            raise FileNotFoundError(
                f"No hay plantilla en GCS para {periodo_gcs} y solo_gcs=True"
            )

    return asegurar_plantilla_liquidaciones(
        periodo_gcs,
        dest_dir,
        descargar=lambda: _descargar_del_portal(periodo, dest_dir),
    )
