"""Catálogo, select de tipo, proveedor y mismo flujo plantillas que pagos."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flows import FLUJOS_CARGA  # noqa: E402
from flows.carga_documento_unico import ejecutar_carga_un_documento  # noqa: E402
from flows.documentos_trabajador import (  # noqa: E402
    DOCUMENTOS_TRABAJADOR,
    documentos_desde_env,
    ejecutar_carga_documento_trabajador,
    seleccionar_documentos,
    usa_mismo_flujo_plantillas,
)
from flows.nivel_carga import NivelCarga  # noqa: E402
from flows.pagos_config import TODOS_PAGOS  # noqa: E402
from flows.proveedor_documentos_trabajador import (  # noqa: E402
    ProveedorLocal,
    fuente_desde_env,
    proveedor_desde_env,
)
from gcs_docs import TIPOS_PERSONALES_SCL  # noqa: E402
from xpaths import XPATHS  # noqa: E402

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


def test_nivel_persona_metadato_misma_nav():
    for doc in DOCUMENTOS_TRABAJADOR:
        assert doc.nivel == NivelCarga.PERSONA
        assert usa_mismo_flujo_plantillas(doc)


def test_pagos_nivel_faena():
    for cfg in TODOS_PAGOS:
        assert cfg.nivel == NivelCarga.FAENA


def test_sin_xpaths_persona_inventados():
    assert not any(k.startswith("persona.") for k in XPATHS)


def test_contratos_usa_clave_contrato():
    doc = next(d for d in DOCUMENTOS_TRABAJADOR if d.clave == "contratos_trabajo")
    assert doc.tipo_gcs == "Contrato"
    assert doc.nombre_ui == "Contratos de Trabajo"


def test_tipos_catalogo_en_scl():
    for doc in DOCUMENTOS_TRABAJADOR:
        assert doc.tipo_gcs in TIPOS_PERSONALES_SCL


def test_flujos_registrados():
    for doc in DOCUMENTOS_TRABAJADOR:
        nombre, ejecutar = FLUJOS_CARGA[doc.clave]
        assert nombre == doc.nombre_ui
        assert callable(ejecutar)


def test_seleccionar_y_env(monkeypatch):
    assert [d.clave for d in seleccionar_documentos(["cedulas_identidad"])] == [
        "cedulas_identidad"
    ]
    with pytest.raises(ValueError, match="desconocidas"):
        seleccionar_documentos(["x"])
    monkeypatch.delenv("DOCUMENTOS_TRABAJADOR_CLAVES", raising=False)
    assert len(documentos_desde_env()) == 15
    monkeypatch.setenv("DOCUMENTOS_TRABAJADOR_CLAVES", "seguro_vida")
    assert [d.clave for d in documentos_desde_env()] == ["seguro_vida"]


def test_proveedor_local(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUMENTOS_TRABAJADOR_FUENTE", "local")
    monkeypatch.delenv("DOCUMENTOS_TRABAJADOR_LOCAL_ROOT", raising=False)
    with pytest.raises(ValueError, match="LOCAL_ROOT"):
        proveedor_desde_env()
    monkeypatch.setenv("DOCUMENTOS_TRABAJADOR_LOCAL_ROOT", str(tmp_path))
    assert isinstance(proveedor_desde_env(), ProveedorLocal)
    assert fuente_desde_env() == "local"

    tipo = "CedulaIdentidad"
    (tmp_path / tipo).mkdir()
    (tmp_path / tipo / "12345678_ci.pdf").write_bytes(b"%PDF")
    idx = ProveedorLocal(tmp_path).indice_por_rut(tipo)
    assert "12345678" in idx


def test_flujo_usa_plantillas_existentes_y_select_nombre_ui(monkeypatch, tmp_path):
    """Misma nav que pagos (llegar_a_cargar_plantillas); select = nombre_ui."""
    llamado = {}

    def fake_llegar(driver, wait):
        llamado["nav"] = "plantillas"

    def fake_elegir(driver, wait, clave, tipo_ui):
        llamado["tipo_ui"] = tipo_ui
        return "octubre 2026"

    def fake_descarga(*_a, **_k):
        return tmp_path / "plantilla.xlsx"

    def fake_rellenar(plantilla, **kwargs):
        class R:
            plantilla = tmp_path / "rellena.xlsx"
            filas = 1
            eliminadas = 0
            archivos = []

        (tmp_path / "rellena.xlsx").write_bytes(b"x")
        return R()

    def fake_materializar(self, archivos, staging):
        return [tmp_path / "a.pdf"]

    def fake_carga(driver, wait, **kwargs):
        llamado["carga"] = kwargs["etiqueta"]
        llamado["nivel"] = kwargs["nivel"]
        return kwargs["plantilla"]

    monkeypatch.setattr(
        "flows.documentos_trabajador.llegar_a_cargar_plantillas", fake_llegar
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador._elegir_tipo_y_periodo", fake_elegir
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.screenshot", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.xpk", lambda *_a, **_k: "//fake"
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.click_y_esperar_descarga", fake_descarga
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.rellenar_plantilla_desde_archivos", fake_rellenar
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.ejecutar_carga_masiva_excel_y_pdfs", fake_carga
    )
    monkeypatch.setattr(ProveedorLocal, "materializar", fake_materializar)
    monkeypatch.setattr(
        ProveedorLocal,
        "indice_por_rut",
        lambda self, t: {"1": type("A", (), {"nombre": "a.pdf", "rut_cuerpo": "1"})()},
    )

    cfg = next(d for d in DOCUMENTOS_TRABAJADOR if d.clave == "cedulas_identidad")
    out = ejecutar_carga_documento_trabajador(
        None, None, cfg, proveedor=ProveedorLocal(tmp_path)
    )
    assert llamado["nav"] == "plantillas"
    assert llamado["tipo_ui"] == cfg.nombre_ui == "Cédulas de Identidad"
    assert llamado["nivel"] == NivelCarga.PERSONA
    assert out == tmp_path / "rellena.xlsx"


def test_pagos_intactos_sin_carga_masiva_compartida():
    src = inspect.getsource(ejecutar_carga_un_documento)
    assert "carga_masiva_compartida" not in src
    assert "asegurar_resultado_post_carga" not in src


def test_asegurar_post_carga():
    from browser import asegurar_resultado_post_carga

    with pytest.raises(RuntimeError, match="Post-carga falló"):
        asegurar_resultado_post_carga({"ok": False}, etiqueta="t")
    with pytest.raises(RuntimeError, match="subidos=0"):
        asegurar_resultado_post_carga(
            {"ok": True, "subidos": 0, "errores": 2}, etiqueta="t"
        )
