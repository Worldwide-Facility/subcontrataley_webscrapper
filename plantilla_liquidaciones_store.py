"""Planilla original de Liquidaciones de Sueldo, una por periodo.

El portal deja de entregarla después de cargar las liquidaciones. Se guarda
el Excel tal como se descarga (con RUT y faena, sin rellenar) y las otras
ejecuciones de ese mes lo reutilizan.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from config import GCS_BUCKET_NAME

logger = logging.getLogger(__name__)

PREFIJO_GCS = "Subcontrataley/plantillas_liquidaciones"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def clave_periodo(periodo: str) -> str:
    """'septiembre 2026' → 'septiembre_2026'."""
    s = unicodedata.normalize("NFKD", str(periodo or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        raise ValueError("Periodo vacío para la planilla de liquidaciones")
    return s


def ruta_gcs_plantilla_liquidaciones(periodo: str) -> str:
    return f"{PREFIJO_GCS}/{clave_periodo(periodo)}.xlsx"


def _bucket(bucket, bucket_name: str | None):
    if bucket is not None:
        return bucket
    from gcs_docs import _cliente

    nombre = bucket_name or GCS_BUCKET_NAME
    return _cliente().bucket(nombre)


def guardar_plantilla_liquidaciones(
    origen: Path,
    periodo: str,
    *,
    bucket=None,
    bucket_name: str | None = None,
) -> str:
    """Sube el Excel original. Hay que llamarla antes de rellenar o borrar filas."""
    ruta = ruta_gcs_plantilla_liquidaciones(periodo)
    blob = _bucket(bucket, bucket_name).blob(ruta)
    blob.upload_from_filename(str(origen), content_type=_XLSX)
    logger.info(
        "Planilla de liquidaciones guardada para %s → gs://%s/%s",
        periodo,
        getattr(blob, "bucket", None).name if getattr(blob, "bucket", None) else (bucket_name or GCS_BUCKET_NAME),
        ruta,
    )
    return ruta


def cargar_plantilla_liquidaciones(
    periodo: str,
    dest_dir: Path,
    *,
    bucket=None,
    bucket_name: str | None = None,
) -> Path | None:
    """Copia local de la planilla guardada, o None si ese periodo aún no está."""
    ruta = ruta_gcs_plantilla_liquidaciones(periodo)
    blob = _bucket(bucket, bucket_name).blob(ruta)
    if not blob.exists():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"liquidaciones_{clave_periodo(periodo)}.xlsx"
    blob.download_to_filename(str(dest))
    logger.info("Planilla de liquidaciones de %s leída desde gs://%s", periodo, ruta)
    return dest


def asegurar_plantilla_liquidaciones(
    periodo: str,
    dest_dir: Path,
    descargar: Callable[[], Path],
    *,
    bucket=None,
    bucket_name: str | None = None,
) -> Path:
    """
    Planilla del periodo para armar RUT por faena.

    Si ya se guardó al descargar liquidaciones, no vuelve al portal.
    Si no existe, descarga, la guarda y la devuelve.
    """
    guardada = cargar_plantilla_liquidaciones(
        periodo, dest_dir, bucket=bucket, bucket_name=bucket_name
    )
    if guardada is not None:
        logger.info(
            "Reutilizando planilla de liquidaciones guardada para %s (%s)",
            periodo,
            guardada.name,
        )
        return guardada

    logger.info("Sin planilla guardada para %s; se descarga del portal", periodo)
    try:
        bajada = Path(descargar())
    except Exception as exc:
        raise RuntimeError(
            f"No hay planilla de liquidaciones guardada para '{periodo}' "
            "y el portal no permitió descargarla. "
            "Ejecute primero la carga de liquidaciones de ese mes."
        ) from exc
    guardar_plantilla_liquidaciones(
        bajada, periodo, bucket=bucket, bucket_name=bucket_name
    )
    return bajada
