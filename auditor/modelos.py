"""Modelos del cruce y del plan de descargas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrabajadorPlantilla:
    rut: str
    rut_cuerpo: str
    nombre: str = ""
    ingreso_faena: str | None = None
    salida_faena: str | None = None
    contrato_id: str | None = None
    faenacontratista_id: str | None = None
    faena: str = ""
    local: str = ""
    fecha_fin_contrato: str | None = None  # NO usar para finiquito


@dataclass
class EstadoFiniquito:
    rut_cuerpo: str
    estado: str = ""
    fecha_finiquito: str | None = None
    empresa: str = ""
    cecos: str = ""
    finiquitado_en_periodo: bool = False


@dataclass
class PresenciaDoc:
    """Presencia de un tipo documental para un RUT."""

    tipo: str
    presente_gcs: bool = False
    presente_bq: bool = False
    ruta_gcs: str | None = None
    requerido: bool = True
    motivo_no_req: str | None = None

    @property
    def ok(self) -> bool:
        if not self.requerido:
            return True
        return self.presente_gcs

    @property
    def faltante(self) -> bool:
        return self.requerido and not self.presente_gcs


@dataclass
class FilaAuditoria:
    trabajador: TrabajadorPlantilla
    empresa: str = ""
    cecos: str = ""
    finiquitado: bool = False
    fecha_finiquito: str | None = None
    liquido: int | None = None
    docs: dict[str, PresenciaDoc] = field(default_factory=dict)
    observacion: list[str] = field(default_factory=list)
    post_descarga: dict[str, str] = field(default_factory=dict)

    @property
    def faltantes(self) -> list[str]:
        return [t for t, d in self.docs.items() if d.faltante]

    @property
    def completo(self) -> bool:
        return not self.faltantes


@dataclass
class LoteDescarga:
    """RUTs a pedir a un workflow documentos-{tipo}."""

    tipo_auditor: str
    workflow: str
    empresa: str
    ruts: list[str] = field(default_factory=list)
    periodo: str = ""
    solicitud_id: str = ""

    def argument_objetivo(
        self,
        *,
        fuente: str = "lista",
        forzar: str = "0",
        dry_run: str = "0",
        incluir_industry: bool = False,
        sync: str = "no",
    ) -> dict[str, Any]:
        """Contrato F1: argument JSON del workflow documentos_tipo."""
        return construir_argumento_workflow(
            ruts=self.ruts,
            periodos=self.periodo,
            empresa=self.empresa,
            fuente=fuente,
            forzar=forzar,
            dry_run=dry_run,
            solicitud_id=self.solicitud_id,
            incluir_industry=incluir_industry,
            sync=sync,
        )


def construir_argumento_workflow(
    *,
    ruts: list[str] | str,
    periodos: str,
    empresa: str = "Security",
    fuente: str = "lista",
    forzar: str = "0",
    dry_run: str = "0",
    solicitud_id: str = "",
    incluir_industry: bool = False,
    sync: str = "no",
    ruts_gcs: str = "",
) -> dict[str, Any]:
    """
    Arma el argument del workflow F1 (PR fase 1).

    Encapsulado aquí para ajustar el contrato sin tocar el orquestador.
    """
    if isinstance(ruts, list):
        ruts_txt = ",".join(ruts)
    else:
        ruts_txt = str(ruts or "")
    objetivo: dict[str, Any] = {
        "ruts": ruts_txt,
        "periodos": periodos,
        "empresa": empresa,
        "fuente": fuente,
        "forzar": str(forzar),
        "dry_run": str(dry_run),
        "solicitud_id": solicitud_id,
    }
    if ruts_gcs:
        objetivo["ruts_gcs"] = ruts_gcs
    return {
        "incluir_industry": "true" if incluir_industry else "false",
        "sync": sync,
        "objetivo": objetivo,
    }
