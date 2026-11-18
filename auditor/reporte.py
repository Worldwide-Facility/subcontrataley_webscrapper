"""Reporte Excel/CSV + resumen.json en GCS."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from auditor.cruce import resumen_por_tipo
from auditor.modelos import FilaAuditoria, LoteDescarga

logger = logging.getLogger(__name__)


def _detalle_rows(filas: list[FilaAuditoria], tipos: list[str]) -> list[dict[str, Any]]:
    rows = []
    for f in filas:
        row: dict[str, Any] = {
            "RUT": f.trabajador.rut,
            "Nombre": f.trabajador.nombre,
            "faena": f.trabajador.faena,
            "local": f.trabajador.local,
            "empresa": f.empresa,
            "cecos": f.cecos,
            "finiquitado": "SÍ" if f.finiquitado else "NO",
            "fecha_finiquito": f.fecha_finiquito or "",
            "liquido": f.liquido if f.liquido is not None else "",
            "ingreso_faena": f.trabajador.ingreso_faena or "",
            "salida_faena": f.trabajador.salida_faena or "",
            "faltantes": ", ".join(f.faltantes) or "—",
            "completo": "SÍ" if f.completo else "NO",
            "observacion": "; ".join(f.observacion),
        }
        for t in tipos:
            d = f.docs.get(t)
            if d is None:
                row[t] = ""
            elif not d.requerido:
                row[t] = d.motivo_no_req or "NO REQ"
            elif d.presente_gcs:
                row[t] = "SÍ"
            else:
                row[t] = "NO"
            if f.post_descarga.get(t):
                row[f"post_{t}"] = f.post_descarga[t]
        rows.append(row)
    return rows


def escribir_reporte_local(
    filas: list[FilaAuditoria],
    *,
    periodo_yyyy_mm: str,
    tipos: list[str],
    dest_dir: Path,
    plan: list[LoteDescarga] | None = None,
    transferencias: list[dict] | None = None,
    modo: str = "dry-run",
    solicitud_id: str = "",
) -> dict[str, Path]:
    """Escribe Excel, CSV detalle y resumen.json. Devuelve paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    detalle = _detalle_rows(filas, list(tipos))
    resumen_tipos = resumen_por_tipo(filas, tipos)

    # CSV
    csv_path = dest_dir / f"detalle_{periodo_yyyy_mm}.csv"
    if detalle:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(detalle[0].keys()))
            w.writeheader()
            w.writerows(detalle)

    # Excel
    xlsx_path = dest_dir / f"auditoria_{periodo_yyyy_mm}.xlsx"
    wb = Workbook()
    R = wb.active
    R.title = "Resumen"
    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    R.append([f"Auditoría Subcontrataley — período {periodo_yyyy_mm}"])
    R["A1"].font = Font(bold=True, size=13)
    R.append([f"Modo: {modo} | Solicitud: {solicitud_id}"])
    R.append(
        [
            f"Trabajadores: {len(filas)} | Completos: "
            f"{sum(1 for f in filas if f.completo)} | Con faltantes: "
            f"{sum(1 for f in filas if not f.completo)}"
        ]
    )
    R.append([])
    R.append(
        ["Tipo", "Requeridos", "Presentes", "Faltantes", "No aplica / no req."]
    )
    for c in R[5]:
        c.font = bold
        c.fill = header_fill
    for s in resumen_tipos:
        R.append(
            [
                s["tipo"],
                s["requeridos"],
                s["presentes"],
                s["faltantes"],
                s["no_aplica"],
            ]
        )

    if plan:
        R.append([])
        R.append(["Plan de descargas (workflows)"])
        R.append(["tipo", "workflow", "empresa", "n_ruts", "solicitud_id"])
        for lote in plan:
            R.append(
                [
                    lote.tipo_auditor,
                    lote.workflow,
                    lote.empresa,
                    len(lote.ruts),
                    lote.solicitud_id,
                ]
            )

    D = wb.create_sheet("Detalle")
    if detalle:
        cols = list(detalle[0].keys())
        D.append(cols)
        for c in D[1]:
            c.font = bold
            c.fill = header_fill
        red = PatternFill("solid", fgColor="F8CBAD")
        grn = PatternFill("solid", fgColor="C6EFCE")
        for row in detalle:
            D.append([row.get(k, "") for k in cols])
        for row in D.iter_rows(min_row=2):
            for c in row:
                if c.value == "NO":
                    c.fill = red
                elif c.value == "SÍ":
                    c.fill = grn
        D.freeze_panes = "B2"
        for i, col in enumerate(D.columns, 1):
            D.column_dimensions[get_column_letter(i)].width = min(
                40, max(10, max(len(str(c.value or "")) for c in col) + 2)
            )

    F = wb.create_sheet("Faltantes")
    F.append(
        [
            "RUT",
            "Nombre",
            "faena",
            "empresa",
            "tipo_faltante",
            "finiquitado",
            "fecha_finiquito",
            "observacion",
        ]
    )
    for c in F[1]:
        c.font = bold
        c.fill = header_fill
    for f in filas:
        for t in f.faltantes:
            F.append(
                [
                    f.trabajador.rut,
                    f.trabajador.nombre,
                    f.trabajador.faena,
                    f.empresa,
                    t,
                    "SÍ" if f.finiquitado else "NO",
                    f.fecha_finiquito or "",
                    "; ".join(f.observacion),
                ]
            )

    if transferencias:
        T = wb.create_sheet("Transferencias")
        keys = list(transferencias[0].keys())
        T.append(keys)
        for r in transferencias:
            T.append([r.get(k, "") for k in keys])

    wb.save(xlsx_path)

    resumen = {
        "periodo": periodo_yyyy_mm,
        "modo": modo,
        "solicitud_id": solicitud_id,
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "trabajadores": len(filas),
        "completos": sum(1 for f in filas if f.completo),
        "con_faltantes": sum(1 for f in filas if not f.completo),
        "resumen_por_tipo": resumen_tipos,
        "plan": [
            {
                "tipo": L.tipo_auditor,
                "workflow": L.workflow,
                "empresa": L.empresa,
                "ruts": L.ruts,
                "solicitud_id": L.solicitud_id,
                "argument": L.argument_objetivo(),
            }
            for L in (plan or [])
        ],
        "transferencias": transferencias or [],
    }
    json_path = dest_dir / "resumen.json"
    json_path.write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return {"xlsx": xlsx_path, "csv": csv_path, "json": json_path}


def subir_reporte(
    paths: dict[str, Path],
    *,
    bucket_name: str,
    prefijo: str,
    project: str | None = None,
) -> list[str]:
    """Sube archivos a gs://{bucket}/{prefijo}/."""
    from google.cloud import storage

    client = storage.Client(project=project) if project else storage.Client()
    bucket = client.bucket(bucket_name)
    uris = []
    for key, path in paths.items():
        if path is None or not Path(path).exists():
            continue
        dest = f"{prefijo.strip('/')}/{Path(path).name}"
        blob = bucket.blob(dest)
        ctype = {
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "csv": "text/csv",
            "json": "application/json",
        }.get(key, "application/octet-stream")
        blob.upload_from_filename(str(path), content_type=ctype)
        uri = f"gs://{bucket_name}/{dest}"
        logger.info("Reporte subido: %s", uri)
        uris.append(uri)
    return uris
