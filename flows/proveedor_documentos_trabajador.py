"""Proveedor de archivos para documentos vigentes del trabajador.

El ORIGEN definitivo de los PDFs aún no está cerrado (Diego). Esta capa
desacopla el flujo de carga masiva de cualquier ruta concreta.

Selección por env:
  DOCUMENTOS_TRABAJADOR_FUENTE=local|gcs   (default: local)
  DOCUMENTOS_TRABAJADOR_LOCAL_ROOT=...    (obligatorio si fuente=local)

Convenciones PROVISIONALES (solo para armar/probar la base; no son el layout final):
  - local: {LOCAL_ROOT}/{tipo_clave}/*.pdf  con RUT (7-8 dígitos) al inicio del nombre
  - gcs:   reutiliza el helper vigente existente de gcs_docs (layout='vigente')
           como stub temporal; la ruta canónica queda pendiente
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gcs_docs import DocGCS, buscar_docs_tipo, descargar_docs, rut_cuerpo

logger = logging.getLogger(__name__)

_RUT_EN_NOMBRE = re.compile(r"^(\d{7,8})")


@dataclass(frozen=True)
class ArchivoDocumento:
    """Referencia opaca a un PDF listo para rellenar plantilla + materializar."""

    rut_cuerpo: str
    nombre: str  # nombre_de_archivo en la plantilla del portal
    ref: str  # path local o ruta GCS (según proveedor)
    tipo: str


class ProveedorArchivosTrabajador(Protocol):
    """Contrato mínimo: índice por RUT + materializar a disco local."""

    nombre: str

    def indice_por_rut(self, tipo_clave: str) -> dict[str, ArchivoDocumento]:
        ...

    def materializar(
        self, archivos: list[ArchivoDocumento], staging: Path
    ) -> list[Path]:
        ...


def fuente_desde_env(
    env_fuente: str = "DOCUMENTOS_TRABAJADOR_FUENTE",
    env_local_root: str = "DOCUMENTOS_TRABAJADOR_LOCAL_ROOT",
) -> str:
    return (os.environ.get(env_fuente) or "local").strip().lower()


def proveedor_desde_env(
    env_fuente: str = "DOCUMENTOS_TRABAJADOR_FUENTE",
    env_local_root: str = "DOCUMENTOS_TRABAJADOR_LOCAL_ROOT",
) -> ProveedorArchivosTrabajador:
    """Factory configurable. Origen definitivo: pendiente."""
    fuente = fuente_desde_env(env_fuente)
    if fuente == "local":
        root = (os.environ.get(env_local_root) or "").strip()
        if not root:
            raise ValueError(
                f"DOCUMENTOS_TRABAJADOR_FUENTE=local requiere {env_local_root}. "
                "El layout de carpetas es provisional; el origen definitivo está pendiente."
            )
        return ProveedorLocal(Path(root))
    if fuente == "gcs":
        logger.warning(
            "Proveedor GCS de documentos trabajador es PROVISIONAL "
            "(layout vigente de gcs_docs). Origen definitivo pendiente."
        )
        return ProveedorGcsProvisional()
    raise ValueError(
        f"DOCUMENTOS_TRABAJADOR_FUENTE inválida: {fuente!r} (use local|gcs)"
    )


class ProveedorLocal:
    """Carpeta local provisional: {root}/{tipo_clave}/*.pdf."""

    nombre = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def indice_por_rut(self, tipo_clave: str) -> dict[str, ArchivoDocumento]:
        carpeta = self.root / tipo_clave
        if not carpeta.is_dir():
            logger.warning(
                "[proveedor-local] No existe carpeta provisional %s "
                "(origen definitivo pendiente)",
                carpeta,
            )
            return {}
        out: dict[str, ArchivoDocumento] = {}
        for pdf in sorted(carpeta.glob("*.pdf")):
            m = _RUT_EN_NOMBRE.match(pdf.name)
            if not m:
                logger.warning(
                    "[proveedor-local] Sin RUT al inicio del nombre, se omite: %s",
                    pdf.name,
                )
                continue
            cuerpo = rut_cuerpo(m.group(1))
            arch = ArchivoDocumento(
                rut_cuerpo=cuerpo,
                nombre=pdf.name,
                ref=str(pdf),
                tipo=tipo_clave,
            )
            # Si hay varios, gana el primero ordenado (provisional)
            out.setdefault(cuerpo, arch)
        logger.info(
            "[proveedor-local] tipo=%s | root=%s | ruts=%s",
            tipo_clave,
            carpeta,
            len(out),
        )
        return out

    def materializar(
        self, archivos: list[ArchivoDocumento], staging: Path
    ) -> list[Path]:
        staging = Path(staging)
        staging.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        vistos: set[str] = set()
        for a in archivos:
            if a.nombre in vistos:
                continue
            vistos.add(a.nombre)
            src = Path(a.ref)
            dest = staging / a.nombre
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            paths.append(dest)
        return paths


class ProveedorGcsProvisional:
    """Stub GCS: usa layout='vigente' de gcs_docs. Rutas finales PENDING."""

    nombre = "gcs"

    def indice_por_rut(self, tipo_clave: str) -> dict[str, ArchivoDocumento]:
        docs_idx, _periodo = buscar_docs_tipo(tipo_clave, layout="vigente")
        out = {
            rut: ArchivoDocumento(
                rut_cuerpo=doc.rut_cuerpo,
                nombre=doc.nombre,
                ref=doc.ruta_gcs,
                tipo=doc.tipo,
            )
            for rut, doc in docs_idx.items()
        }
        logger.info(
            "[proveedor-gcs-provisional] tipo=%s | ruts=%s (layout vigente; pendiente)",
            tipo_clave,
            len(out),
        )
        return out

    def materializar(
        self, archivos: list[ArchivoDocumento], staging: Path
    ) -> list[Path]:
        docs = [
            DocGCS(
                nombre=a.nombre,
                ruta_gcs=a.ref,
                rut_cuerpo=a.rut_cuerpo,
                tipo=a.tipo,
            )
            for a in archivos
        ]
        return descargar_docs(docs, staging)
