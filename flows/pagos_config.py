"""Configs de flujos de pago (1 archivo por línea, mismo PDF Cotizaciones)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlujoPagoConfig:
    clave: str
    nombre_ui: str  # texto exacto del <select> Documento
    # Los 4 usan el mismo PDF de cotizaciones Previred en GCS
    tipo_gcs: str = "Cotizaciones"
    layout_gcs: str = "yyyy_mm"  # .../Cotizaciones/2026/06/
    # True: la plantilla del portal es POR FAENA (sin RUT). La base RUT→faena es la
    # planilla de Liquidaciones guardada para ese mes. Se fusiona 1 PDF por faena
    # y se rellena la plantilla propia (mismo esquema que Libro de Asistencia).
    por_faena: bool = False
    # Etiqueta del PDF fusionado: {slug_faena}_{etiqueta}_{periodo}.pdf
    etiqueta_archivo: str = ""


PAGOS_AFP_AFC = FlujoPagoConfig(
    clave="pagos_afp_afc",
    nombre_ui="Pagos AFP y AFC",
)

PAGOS_ISAPRE_FONASA = FlujoPagoConfig(
    clave="pagos_isapre_fonasa",
    # Texto real del portal (2026-10-09): "Pagos Isapres / FONASA" (con "s").
    # El texto anterior no matcheaba ni exacto ni por "contiene".
    nombre_ui="Pagos Isapres / FONASA",
)

PAGOS_MUTUALIDADES = FlujoPagoConfig(
    clave="pagos_mutualidades",
    nombre_ui="Pagos Mutualidades",
    por_faena=True,
    etiqueta_archivo="Mutualidades",
)

PAGOS_CAJAS = FlujoPagoConfig(
    clave="pagos_cajas_compensacion",
    nombre_ui="Pagos Cajas de Compensación",
    por_faena=True,
    etiqueta_archivo="CajasCompensacion",
)

def fuente_por_faena(cfg: FlujoPagoConfig):
    """Fuente GCS de los PDF por RUT a fusionar por faena (Mutualidades / Cajas)."""
    from compilar_asistencias import FuenteDocsFaena

    return FuenteDocsFaena(
        tipo_gcs=cfg.tipo_gcs,          # 'Cotizaciones'
        layout=cfg.layout_gcs,          # Trabajadores/{rut}/Cotizaciones/{YYYY}/{MM}/
        etiqueta=cfg.etiqueta_archivo or cfg.clave,
        orden="rut",
        staging_nombre=f"staging_{cfg.clave}",
    )


TODOS_PAGOS: tuple[FlujoPagoConfig, ...] = (
    PAGOS_AFP_AFC,
    PAGOS_ISAPRE_FONASA,
    PAGOS_MUTUALIDADES,
    PAGOS_CAJAS,
)
