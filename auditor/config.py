"""Variables de entorno del auditor Subcontrataley."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date

from auditor.periodo import parse_periodo, periodo_texto, periodo_yyyy_mm

PROJECT_ID = "worldwide-470917"
REGION = "us-east1"
BUCKET_DEFAULT = "worldwide-documentos-instalaciones"
BQ_DOCUMENTOS = f"{PROJECT_ID}.app_clientes.documentos_gcs"
BQ_RECLUTAMIENTO = f"{PROJECT_ID}.cr_reportes.cr_reclutamiento_empleados"
GCS_BASE_PATH_DEFAULT = "documentos_instalaciones_colaboradores"
REPORTE_PREFIJO = "auditoria_subcontrataley"

TIPOS_DEFAULT = (
    "liquidacion",
    "transferencia",
    "cotizaciones",
    "asistencia",
    "finiquito",
)
TIPOS_VALIDOS = frozenset(
    {
        "liquidacion",
        "transferencia",
        "cotizaciones",
        "asistencia",
        "finiquito",
        "contrato",
    }
)
MODOS_VALIDOS = frozenset({"dry-run", "descargar", "completo"})

# Workflows documentos-{tipo} (proyecto worldwide-470917, us-east1)
WORKFLOW_POR_TIPO = {
    "liquidacion": "documentos-liquidaciones",
    "asistencia": "documentos-asistencias",
    "cotizaciones": "documentos-cotizaciones",
    "finiquito": "documentos-finiquitos",
    "contrato": "documentos-contratos",
}

# SYNC_TIPOS del job documentos-sync (nombres en el índice BQ)
SYNC_TIPO_POR_AUDITOR = {
    "liquidacion": "liquidaciones",
    "asistencia": "asistencias",
    "cotizaciones": "cotizaciones",
    "finiquito": "finiquitos",
    "contrato": "contratos",
    "transferencia": "transferencias",
}

# Jobs de manifiesto F1 (nombre del Cloud Run job dentro del workflow)
JOB_MANIFIESTO_POR_TIPO = {
    "liquidacion": "documentos-liquidaciones",
    "asistencia": "documentos-asistencias",
    "cotizaciones": "documentos-cotizaciones-v2",
    "finiquito": "documentos-finiquitos",
    "contrato": "documentos-contratos",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "si", "sí")


def _parse_tipos(raw: str | None) -> tuple[str, ...]:
    if not raw or not str(raw).strip():
        return TIPOS_DEFAULT
    out: list[str] = []
    seen: set[str] = set()
    for tok in re_split_csv(raw):
        t = tok.strip().lower()
        # alias
        if t in ("liquidaciones", "liq"):
            t = "liquidacion"
        elif t in ("transferencias", "tr"):
            t = "transferencia"
        elif t in ("cotizacion", "previred"):
            t = "cotizaciones"
        elif t in ("asistencias",):
            t = "asistencia"
        elif t in ("finiquitos",):
            t = "finiquito"
        elif t in ("contratos",):
            t = "contrato"
        if t not in TIPOS_VALIDOS:
            raise ValueError(
                f"AUDITOR_TIPOS inválido: {tok!r}. "
                f"Válidos: {', '.join(sorted(TIPOS_VALIDOS))}"
            )
        if t not in seen:
            seen.add(t)
            out.append(t)
    return tuple(out) if out else TIPOS_DEFAULT


def re_split_csv(raw: str) -> list[str]:
    return [p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()]


@dataclass
class AuditorConfig:
    periodo: date
    modo: str = "dry-run"
    crear_transferencias: bool = False
    tipos: tuple[str, ...] = TIPOS_DEFAULT
    incluir_industry: bool = False
    forzar_descarga: bool = False
    dry_run_workflows: bool = False
    solicitud_id: str = ""
    project_id: str = PROJECT_ID
    region: str = REGION
    bucket: str = BUCKET_DEFAULT
    gcs_base_path: str = GCS_BASE_PATH_DEFAULT
    esperar_workflows: bool = True
    abortar_si_ocupado: bool = False
    poll_segundos: int = 30
    timeout_workflow_segundos: int = 54000

    @property
    def periodo_yyyy_mm(self) -> str:
        return periodo_yyyy_mm(self.periodo)

    @property
    def periodo_texto(self) -> str:
        return periodo_texto(self.periodo)

    @property
    def es_dry_run(self) -> bool:
        return self.modo == "dry-run"

    @property
    def lanza_descargas(self) -> bool:
        return self.modo in ("descargar", "completo")

    @property
    def debe_crear_transferencias(self) -> bool:
        if self.es_dry_run:
            return False
        return bool(self.crear_transferencias)

    def prefijo_reporte(self) -> str:
        return f"{REPORTE_PREFIJO}/{self.periodo_yyyy_mm}"


def cargar_config(*, hoy: date | None = None) -> AuditorConfig:
    periodo = parse_periodo(os.getenv("AUDITOR_PERIODO"), hoy=hoy)
    modo = (os.getenv("AUDITOR_MODO") or "dry-run").strip().lower()
    if modo in ("dryrun", "dry_run", "reporte"):
        modo = "dry-run"
    if modo not in MODOS_VALIDOS:
        raise ValueError(
            f"AUDITOR_MODO inválido: {modo!r}. Use dry-run|descargar|completo"
        )

    # En modo completo default 1; en dry-run/descargar default 0 (override con env).
    crear_default = modo == "completo"
    crear_tr = _env_bool("AUDITOR_CREAR_TRANSFERENCIAS", default=crear_default)
    tipos = _parse_tipos(os.getenv("AUDITOR_TIPOS"))
    solicitud = (os.getenv("AUDITOR_SOLICITUD_ID") or "").strip()
    if not solicitud:
        from datetime import datetime, timezone
        import uuid

        solicitud = (
            f"auditor-{periodo_yyyy_mm(periodo)}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{uuid.uuid4().hex[:6]}"
        )

    return AuditorConfig(
        periodo=periodo,
        modo=modo,
        crear_transferencias=crear_tr,
        tipos=tipos,
        incluir_industry=_env_bool("AUDITOR_INCLUIR_INDUSTRY", False),
        forzar_descarga=_env_bool("AUDITOR_FORZAR", False),
        dry_run_workflows=_env_bool("AUDITOR_WORKFLOW_DRY_RUN", False),
        solicitud_id=solicitud,
        project_id=os.getenv("GCP_PROJECT", PROJECT_ID).strip() or PROJECT_ID,
        region=os.getenv("AUDITOR_REGION", REGION).strip() or REGION,
        bucket=os.getenv("GCS_BUCKET_NAME", BUCKET_DEFAULT).strip() or BUCKET_DEFAULT,
        gcs_base_path=(
            os.getenv("GCS_BASE_PATH", GCS_BASE_PATH_DEFAULT).strip().strip("/")
            or GCS_BASE_PATH_DEFAULT
        ),
        esperar_workflows=_env_bool("AUDITOR_ESPERAR_WORKFLOWS", True),
        abortar_si_ocupado=_env_bool("AUDITOR_ABORTAR_SI_OCUPADO", False),
        poll_segundos=int(os.getenv("AUDITOR_POLL_SEGUNDOS", "30")),
        timeout_workflow_segundos=int(
            os.getenv("AUDITOR_TIMEOUT_WORKFLOW", "54000")
        ),
    )
