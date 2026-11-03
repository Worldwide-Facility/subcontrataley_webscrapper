"""Catálogo de documentos vigentes y filtro de ruta GCS sin mes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flows import FLUJOS_CARGA  # noqa: E402
from flows.documentos_trabajador import DOCUMENTOS_TRABAJADOR  # noqa: E402
from gcs_docs import TIPOS_PERSONALES_SCL, _globs_periodo, es_pdf_vigente  # noqa: E402

NOMBRES_UI = (
    "Capacitación para Pers. Trab. en Prevención de Riesgos Laborales",
    "Capacitación Uso y Mantención de EPP",
    "Certificado Curso de Guardia de Seguridad (OS10 o SPD)",
    "Certificado de Antecedentes",
    "Contratos de Trabajo",
    "Cédulas de Identidad",
    "Entrega EPP",
    "Guía Práctica de Seguridad",
    "Recepción Reglamento Especial de Empresas Contratistas (Trabajador)",
    "Registro Difusión Trabajador Reglamento Interno",
    "Seguro de Vida Individual Trabajador",
    "Toma Conoc. Trab. Matriz IPER del Contratista",
    "Toma Conoc. Trab. Procedimiento de Trabajo Seguro",
    "Toma Conoc. Trab. Programa de Trabajo Preventivo",
    "Toma de Conoc. de Trab. Información de Riesgos Laborales",
)


def test_quince_claves_y_nombres_literales():
    claves = [d.clave for d in DOCUMENTOS_TRABAJADOR]
    assert len(claves) == 15
    assert len(set(claves)) == 15
    assert tuple(d.nombre_ui for d in DOCUMENTOS_TRABAJADOR) == NOMBRES_UI
    assert len({d.tipo_gcs for d in DOCUMENTOS_TRABAJADOR}) == 15


def test_contratos_usa_carpeta_contrato():
    doc = next(d for d in DOCUMENTOS_TRABAJADOR if d.clave == "contratos_trabajo")
    assert doc.tipo_gcs == "Contrato"
    assert doc.nombre_ui == "Contratos de Trabajo"


def test_tipos_gcs_estan_en_scl():
    for doc in DOCUMENTOS_TRABAJADOR:
        assert doc.tipo_gcs in TIPOS_PERSONALES_SCL


def test_es_pdf_vigente_solo_carpeta_directa():
    assert es_pdf_vigente(
        "Trabajadores/12345678/CedulaIdentidad/a.pdf", "CedulaIdentidad"
    )
    assert es_pdf_vigente(
        "Trabajadores/12345678-9/Contrato/contrato.pdf", "Contrato"
    )
    assert not es_pdf_vigente(
        "Trabajadores/12345678/CedulaIdentidad/junio 2026/a.pdf",
        "CedulaIdentidad",
    )
    assert not es_pdf_vigente(
        "Instalaciones/Security/21-31-44/CedulaIdentidad/a.pdf",
        "CedulaIdentidad",
    )
    assert not es_pdf_vigente("cecos/CedulaIdentidad/a.pdf", "CedulaIdentidad")
    assert not es_pdf_vigente(
        "Trabajadores/12345678/Contrato/a.pdf", "CedulaIdentidad"
    )


def test_glob_vigente_sin_legacy():
    globs = _globs_periodo(
        "CedulaIdentidad",
        layout="vigente",
        periodo="vigente",
        anio=None,
        mes=None,
    )
    assert globs == [("Trabajadores/**/CedulaIdentidad/*.pdf", "tres_raices")]


def test_flujos_registrados():
    for doc in DOCUMENTOS_TRABAJADOR:
        nombre, ejecutar = FLUJOS_CARGA[doc.clave]
        assert nombre == doc.nombre_ui
        assert callable(ejecutar)
