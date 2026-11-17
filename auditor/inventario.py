"""Inventario GCS + BigQuery documentos_gcs + líquido de liquidaciones."""

from __future__ import annotations

import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Iterable

from google.cloud import bigquery, storage

from auditor.config import BQ_DOCUMENTOS, PROJECT_ID
from auditor.cruce import InventarioRut
from auditor.modelos import TrabajadorPlantilla
from gcs_docs import rut_cuerpo
from parse_liquidacion import parse_total_liquido

logger = logging.getLogger(__name__)


def _cliente_storage(project: str = PROJECT_ID) -> storage.Client:
    return storage.Client(project=project)


def _cliente_bq(project: str = PROJECT_ID) -> bigquery.Client:
    return bigquery.Client(project=project)


def listar_rutas_gcs_trabajadores(
    ruts: Iterable[str],
    *,
    bucket_name: str,
    project: str = PROJECT_ID,
) -> dict[str, list[tuple[str, dict]]]:
    """
    Por RUT cuerpo → lista de (ruta_gcs, metadata).

    Lista solo el prefijo Trabajadores/{rut}/ (no el bucket entero).
    """
    client = _cliente_storage(project)
    bucket = client.bucket(bucket_name)
    out: dict[str, list[tuple[str, dict]]] = {}
    for raw in ruts:
        c = rut_cuerpo(raw)
        if not c:
            continue
        files: list[tuple[str, dict]] = []
        # Carpeta con y sin DV
        prefixes = [f"Trabajadores/{c}/"]
        for blob in bucket.list_blobs(prefix=prefixes[0]):
            if blob.name.endswith("/"):
                continue
            meta = dict(blob.metadata or {})
            files.append((blob.name, meta))
        out[c] = files
    return out


def rutas_bq_activas(
    rutas: Iterable[str] | None = None,
    *,
    project: str = PROJECT_ID,
) -> set[str]:
    """Rutas activas en app_clientes.documentos_gcs (opcionalmente filtradas)."""
    client = _cliente_bq(project)
    lista = [r for r in (rutas or []) if r]
    if lista:
        sql = f"""
        SELECT ruta_gcs
        FROM `{BQ_DOCUMENTOS}`
        WHERE activo = TRUE
          AND ruta_gcs IN UNNEST(@rutas)
        """
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("rutas", "STRING", lista),
                ]
            ),
        )
    else:
        # Sin filtro: no listamos todo (caro). Devolver vacío.
        return set()
    return {str(r["ruta_gcs"]) for r in job.result() if r["ruta_gcs"]}


def _empresa_desde_meta(files: list[tuple[str, dict]], finiquito_empresa: str = "") -> tuple[str, str]:
    empresas = sorted(
        {
            (m.get("empresa") or "").strip()
            for _, m in files
            if (m.get("empresa") or "").strip()
        }
    )
    cecos = ""
    for _, m in files:
        if m.get("codcecoscr"):
            cecos = str(m["codcecoscr"]).strip()
            break
    if empresas:
        return "/".join(empresas), cecos
    return (finiquito_empresa or ""), cecos


def _ruta_liquidacion(files: list[tuple[str, dict]], periodo: date) -> str | None:
    from auditor.cruce import needles_tipo

    needles = needles_tipo("liquidacion", periodo)
    for ruta, _ in files:
        if not ruta.lower().endswith(".pdf"):
            continue
        if any(n in ruta for n in needles):
            return ruta
    return None


def leer_liquido_gcs(
    ruta_gcs: str,
    *,
    bucket_name: str,
    project: str = PROJECT_ID,
    dest_dir: Path | None = None,
) -> int | None:
    client = _cliente_storage(project)
    bucket = client.bucket(bucket_name)
    tmp_owned = dest_dir is None
    dest_dir = dest_dir or Path(tempfile.mkdtemp(prefix="auditor_liq_"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = dest_dir / Path(ruta_gcs).name
    try:
        bucket.blob(ruta_gcs).download_to_filename(str(local))
        return parse_total_liquido(local)
    except Exception as exc:
        logger.warning("No se pudo leer líquido de %s: %s", ruta_gcs, exc)
        return None
    finally:
        if tmp_owned:
            try:
                local.unlink(missing_ok=True)
            except Exception:
                pass


def construir_inventarios(
    trabajadores: list[TrabajadorPlantilla],
    *,
    periodo: date,
    bucket_name: str,
    project: str = PROJECT_ID,
    leer_liquidos: bool = True,
    empresas_reclutamiento: dict[str, str] | None = None,
    cecos_reclutamiento: dict[str, str] | None = None,
) -> dict[str, InventarioRut]:
    """Arma InventarioRut por cuerpo de RUT."""
    cuerpos = [t.rut_cuerpo for t in trabajadores]
    por_rut = listar_rutas_gcs_trabajadores(
        cuerpos, bucket_name=bucket_name, project=project
    )
    todas_rutas: list[str] = []
    for files in por_rut.values():
        todas_rutas.extend(r for r, _ in files)
    bq = rutas_bq_activas(todas_rutas, project=project) if todas_rutas else set()

    emp_map = empresas_reclutamiento or {}
    cecos_map = cecos_reclutamiento or {}
    out: dict[str, InventarioRut] = {}
    for c, files in por_rut.items():
        rutas = [r for r, _ in files]
        emp, cecos = _empresa_desde_meta(files, emp_map.get(c, ""))
        if not cecos:
            cecos = cecos_map.get(c, "")
        liquido = None
        if leer_liquidos:
            ruta_liq = _ruta_liquidacion(files, periodo)
            if ruta_liq:
                liquido = leer_liquido_gcs(
                    ruta_liq, bucket_name=bucket_name, project=project
                )
        out[c] = InventarioRut(
            rutas_gcs=rutas,
            rutas_bq={r for r in rutas if r in bq},
            liquido=liquido,
            empresa_gcs=emp,
            cecos_gcs=cecos,
        )
    # RUTs sin carpeta GCS
    for t in trabajadores:
        if t.rut_cuerpo not in out:
            out[t.rut_cuerpo] = InventarioRut(
                rutas_gcs=[],
                rutas_bq=set(),
                liquido=None,
                empresa_gcs=emp_map.get(t.rut_cuerpo, ""),
                cecos_gcs=cecos_map.get(t.rut_cuerpo, ""),
            )
    return out
