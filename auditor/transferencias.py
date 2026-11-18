"""Genera, sube e indexa certificados de transferencia faltantes."""

from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from google.cloud import bigquery, storage

from auditor.config import PROJECT_ID
from auditor.modelos import FilaAuditoria
from auditor.periodo import periodo_texto
from generar_transferencia import crear_transferencia_una_linea
from gcs_docs import rut_cuerpo
from parse_liquidacion import parse_total_liquido

logger = logging.getLogger(__name__)


def metadata_gcs_documento(
    *,
    codcecoscr: str | None = None,
    empresa: str | None = None,
    rut: str | None = None,
    ambito: str | None = "trabajadores",
) -> dict[str, str]:
    """Metadata custom (mismo contrato que cargas_documentos)."""
    meta: dict[str, str] = {}
    if codcecoscr:
        meta["codcecoscr"] = str(codcecoscr).strip()
    if empresa:
        meta["empresa"] = str(empresa).strip()
    if rut:
        meta["rut"] = rut_cuerpo(rut) or str(rut).strip()
    if ambito:
        meta["ambito"] = str(ambito)
    return meta


def ruta_transferencia(cuerpo: str, periodo: date) -> str:
    per = periodo_texto(periodo)
    c = rut_cuerpo(cuerpo)
    return f"Trabajadores/{c}/Transferencia/{per}/{c}_Transferencia_{per}.pdf"


def upsert_documentos_gcs_transferencias(
    filas: list[dict[str, Any]],
    *,
    project: str = PROJECT_ID,
    client: bigquery.Client | None = None,
) -> None:
    """
    Upsert best-effort en app_clientes.documentos_gcs__transferencias.

    Réplica simplificada de utils_bq_documentos_indice.upsert_filas_tipo
    (sin depender del otro repo).
    """
    if not filas:
        return
    bq = client or bigquery.Client(project=project)
    destino = f"{project}.app_clientes.documentos_gcs__transferencias"
    stage = f"{project}.app_clientes._stg_doc_transferencias_auditor"
    rebuild = f"{project}.app_clientes._rebuild_doc_transferencias_auditor"
    columnas = (
        "ruta_gcs, nombre, tipo, codcecoscr, instalacion_rol, empresa, "
        "tamano, fecha_creacion_gcs, content_type, fecha_sincronizacion, activo"
    )
    vistos: dict[str, dict] = {}
    for fila in filas:
        ruta = fila.get("ruta_gcs")
        if ruta:
            vistos[ruta] = fila
    if not vistos:
        return
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=[
            bigquery.SchemaField("ruta_gcs", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("nombre", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("tipo", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("codcecoscr", "STRING"),
            bigquery.SchemaField("instalacion_rol", "STRING"),
            bigquery.SchemaField("empresa", "STRING"),
            bigquery.SchemaField("tamano", "INTEGER"),
            bigquery.SchemaField("fecha_creacion_gcs", "TIMESTAMP"),
            bigquery.SchemaField("content_type", "STRING"),
            bigquery.SchemaField("fecha_sincronizacion", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("activo", "BOOLEAN", mode="REQUIRED"),
        ],
    )
    load = bq.load_table_from_json(list(vistos.values()), stage, job_config=job_config)
    load.result()

    def _ddl(table_id: str, select_sql: str) -> str:
        return f"""
        CREATE OR REPLACE TABLE `{table_id}`
        PARTITION BY DATE(fecha_sincronizacion)
        CLUSTER BY codcecoscr, ruta_gcs
        AS
        {select_sql}
        """

    try:
        bq.get_table(destino)
        existe = True
    except Exception:
        existe = False
    try:
        if not existe:
            bq.query(_ddl(destino, f"SELECT {columnas} FROM `{stage}`")).result()
        else:
            bq.query(
                _ddl(
                    rebuild,
                    f"""
                    SELECT {columnas} FROM `{destino}`
                    WHERE ruta_gcs NOT IN (SELECT ruta_gcs FROM `{stage}`)
                    UNION ALL
                    SELECT {columnas} FROM `{stage}`
                    """,
                )
            ).result()
            bq.query(_ddl(destino, f"SELECT {columnas} FROM `{rebuild}`")).result()
    finally:
        bq.delete_table(rebuild, not_found_ok=True)
        bq.delete_table(stage, not_found_ok=True)
    logger.info("Índice transferencias actualizado (%s rutas)", len(vistos))


def crear_transferencias_faltantes(
    candidatos: list[FilaAuditoria],
    *,
    periodo: date,
    bucket_name: str,
    project: str = PROJECT_ID,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Para cada candidato (liq + líquido>0 sin transferencia):
    genera PDF, sube sin sobrescribir, indexa en BQ.
    """
    if not candidatos:
        return []
    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)
    per = periodo_texto(periodo)
    resultados: list[dict[str, Any]] = []
    a_indexar: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="auditor_tr_") as tmp_name:
        tmp = Path(tmp_name)
        for fila in candidatos:
            c = fila.trabajador.rut_cuerpo
            dest = ruta_transferencia(c, periodo)
            blob = bucket.blob(dest)
            row: dict[str, Any] = {
                "rut": fila.trabajador.rut,
                "ruta_gcs": dest,
                "liquido": fila.liquido,
                "empresa": fila.empresa,
                "cecos": fila.cecos,
            }
            if blob.exists():
                row["resultado"] = "ya_existia"
                resultados.append(row)
                continue

            # Descargar liquidación
            liq_doc = (fila.docs.get("liquidacion") or None)
            ruta_liq = liq_doc.ruta_gcs if liq_doc else None
            if not ruta_liq:
                row["resultado"] = "sin_liquidacion"
                resultados.append(row)
                continue
            local_liq = tmp / f"{c}_liq.pdf"
            bucket.blob(ruta_liq).download_to_filename(str(local_liq))
            monto = fila.liquido
            if monto is None:
                monto = parse_total_liquido(local_liq)
            if monto is None or int(monto) <= 0:
                row["resultado"] = "liquido_cero_o_ilegible"
                row["liquido"] = monto
                resultados.append(row)
                continue

            gen = crear_transferencia_una_linea(local_liq, tmp, per, int(monto))
            if gen is None:
                row["resultado"] = "no_generado"
                resultados.append(row)
                continue

            if dry_run:
                row["resultado"] = "dry_run"
                row["pdf_local"] = str(gen)
                resultados.append(row)
                continue

            # Nunca sobrescribir (re-check)
            if blob.exists():
                row["resultado"] = "ya_existia"
                resultados.append(row)
                continue

            empresa = fila.empresa if fila.empresa not in ("", "?") else None
            if empresa and "/" in empresa:
                empresa = empresa.split("/")[0]
            blob.metadata = metadata_gcs_documento(
                codcecoscr=fila.cecos or None,
                empresa=empresa,
                rut=c,
                ambito="trabajadores",
            )
            blob.upload_from_filename(str(gen), content_type="application/pdf")
            blob.reload()
            row["resultado"] = "subido"
            resultados.append(row)
            a_indexar.append(
                {
                    "ruta_gcs": dest,
                    "nombre": dest.rsplit("/", 1)[-1],
                    "tipo": "transferencias",
                    "codcecoscr": fila.cecos or "",
                    "instalacion_rol": None,
                    "empresa": empresa,
                    "tamano": blob.size,
                    "fecha_creacion_gcs": (
                        blob.time_created.isoformat()
                        if blob.time_created
                        else datetime.now(timezone.utc).isoformat()
                    ),
                    "content_type": blob.content_type or "application/pdf",
                    "fecha_sincronizacion": datetime.now(timezone.utc).isoformat(),
                    "activo": True,
                }
            )

    if a_indexar and not dry_run:
        try:
            upsert_documentos_gcs_transferencias(a_indexar, project=project)
        except Exception as exc:
            logger.warning("No se pudo indexar transferencias en BQ: %s", exc)
    return resultados
