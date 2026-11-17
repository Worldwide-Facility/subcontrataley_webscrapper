"""Finiquitos desde cr_reclutamiento_empleados (NO fecha_fin_contrato de plantilla)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from google.cloud import bigquery

from auditor.config import BQ_RECLUTAMIENTO, PROJECT_ID
from auditor.cruce import finiquitado_en_periodo
from auditor.modelos import EstadoFiniquito
from gcs_docs import rut_cuerpo

logger = logging.getLogger(__name__)


def consultar_finiquitos(
    ruts: Iterable[str],
    periodo: date,
    *,
    project: str = PROJECT_ID,
    client: bigquery.Client | None = None,
) -> dict[str, EstadoFiniquito]:
    """
    Estado / fecha_finiquito / empresa / cecos por RUT cuerpo.

    Fuente: worldwide-470917.cr_reportes.cr_reclutamiento_empleados
    """
    cuerpos = []
    seen = set()
    for r in ruts:
        c = rut_cuerpo(r)
        if c and c not in seen:
            seen.add(c)
            cuerpos.append(c)
    if not cuerpos:
        return {}

    bq = client or bigquery.Client(project=project)
    sql = f"""
    SELECT
      CAST(rut AS STRING) AS rut,
      CAST(IFNULL(rut_dv, '') AS STRING) AS rut_dv,
      IFNULL(estado, '') AS estado,
      CAST(fecha_finiquito AS STRING) AS fecha_finiquito,
      IFNULL(empresa, '') AS empresa,
      TRIM(CAST(IFNULL(cecos, '') AS STRING)) AS cecos
    FROM `{BQ_RECLUTAMIENTO}`
    WHERE TRIM(CAST(rut AS STRING)) IN UNNEST(@ruts)
    """

    out: dict[str, EstadoFiniquito] = {}
    chunk_size = 500
    for i in range(0, len(cuerpos), chunk_size):
        chunk = cuerpos[i : i + chunk_size]
        job = bq.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("ruts", "STRING", chunk),
                ]
            ),
        )
        for row in job.result():
            c = rut_cuerpo(row["rut"] or row["rut_dv"] or "")
            if not c:
                continue
            estado = str(row["estado"] or "")
            ff = row["fecha_finiquito"]
            ff_s = str(ff)[:10] if ff else None
            if ff_s in ("None", "nan", "NaT", "0000-00-00"):
                ff_s = None
            est = EstadoFiniquito(
                rut_cuerpo=c,
                estado=estado,
                fecha_finiquito=ff_s,
                empresa=str(row["empresa"] or ""),
                cecos=str(row["cecos"] or ""),
                finiquitado_en_periodo=finiquitado_en_periodo(estado, ff_s, periodo),
            )
            # Preferir fila con fecha_finiquito en el periodo si hay duplicados
            prev = out.get(c)
            if prev is None or (est.finiquitado_en_periodo and not prev.finiquitado_en_periodo):
                out[c] = est
    logger.info(
        "Reclutamiento: %s RUT(s); finiquitados en %04d-%02d: %s",
        len(out),
        periodo.year,
        periodo.month,
        sum(1 for e in out.values() if e.finiquitado_en_periodo),
    )
    return out
