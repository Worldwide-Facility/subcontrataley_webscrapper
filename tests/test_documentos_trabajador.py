"""Catálogo de documentos vigentes, proveedor y selección de flujo masivo."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flows import FLUJOS_CARGA  # noqa: E402
from flows.carga_masiva_compartida import ejecutar_carga_masiva_excel_y_pdfs  # noqa: E402
from flows.documentos_trabajador import (  # noqa: E402
    DOCUMENTOS_TRABAJADOR,
    documentos_desde_env,
    ejecutar_carga_documento_trabajador,
    seleccionar_documentos,
    usa_carga_masiva_compartida,
)
from flows.proveedor_documentos_trabajador import (  # noqa: E402
    ProveedorLocal,
    fuente_desde_env,
    proveedor_desde_env,
)
from gcs_docs import TIPOS_PERSONALES_SCL  # noqa: E402

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


def test_contratos_usa_clave_contrato():
    doc = next(d for d in DOCUMENTOS_TRABAJADOR if d.clave == "contratos_trabajo")
    assert doc.tipo_gcs == "Contrato"
    assert doc.nombre_ui == "Contratos de Trabajo"


def test_tipos_catalogo_en_scl():
    """Las claves de tipo del catálogo siguen alineadas al set SCL conocido."""
    for doc in DOCUMENTOS_TRABAJADOR:
        assert doc.tipo_gcs in TIPOS_PERSONALES_SCL


def test_flujos_registrados_y_carga_masiva():
    for doc in DOCUMENTOS_TRABAJADOR:
        assert usa_carga_masiva_compartida(doc)
        nombre, ejecutar = FLUJOS_CARGA[doc.clave]
        assert nombre == doc.nombre_ui
        assert callable(ejecutar)
        assert ejecutar.__name__ == f"ejecutar_{doc.clave}"


def test_seleccionar_documentos_filtra_y_valida():
    subset = seleccionar_documentos(["cedulas_identidad", "contratos_trabajo"])
    assert [d.clave for d in subset] == ["cedulas_identidad", "contratos_trabajo"]
    assert seleccionar_documentos(None) == DOCUMENTOS_TRABAJADOR
    assert seleccionar_documentos([]) == DOCUMENTOS_TRABAJADOR
    with pytest.raises(ValueError, match="desconocidas"):
        seleccionar_documentos(["no_existe"])


def test_documentos_desde_env(monkeypatch):
    monkeypatch.delenv("DOCUMENTOS_TRABAJADOR_CLAVES", raising=False)
    assert len(documentos_desde_env()) == 15
    monkeypatch.setenv("DOCUMENTOS_TRABAJADOR_CLAVES", "seguro_vida, entrega_epp")
    assert [d.clave for d in documentos_desde_env()] == ["seguro_vida", "entrega_epp"]


def test_proveedor_desde_env_local_requiere_root(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUMENTOS_TRABAJADOR_FUENTE", "local")
    monkeypatch.delenv("DOCUMENTOS_TRABAJADOR_LOCAL_ROOT", raising=False)
    with pytest.raises(ValueError, match="LOCAL_ROOT"):
        proveedor_desde_env()
    monkeypatch.setenv("DOCUMENTOS_TRABAJADOR_LOCAL_ROOT", str(tmp_path))
    prov = proveedor_desde_env()
    assert isinstance(prov, ProveedorLocal)
    assert fuente_desde_env() == "local"


def test_proveedor_local_indice_y_materializar(tmp_path):
    tipo = "CedulaIdentidad"
    carpeta = tmp_path / tipo
    carpeta.mkdir()
    (carpeta / "12345678_ci.pdf").write_bytes(b"%PDF-1.4")
    (carpeta / "87654321-ci.pdf").write_bytes(b"%PDF-1.4")
    (carpeta / "sin_rut.pdf").write_bytes(b"%PDF-1.4")
    prov = ProveedorLocal(tmp_path)
    idx = prov.indice_por_rut(tipo)
    assert set(idx) == {"12345678", "87654321"}
    assert idx["12345678"].nombre == "12345678_ci.pdf"
    staging = tmp_path / "staging"
    paths = prov.materializar(list(idx.values()), staging)
    assert len(paths) == 2
    assert all(p.exists() for p in paths)


def test_proveedor_fuente_invalida(monkeypatch):
    monkeypatch.setenv("DOCUMENTOS_TRABAJADOR_FUENTE", "s3")
    with pytest.raises(ValueError, match="inválida"):
        proveedor_desde_env()


def test_ejecutar_usa_carga_masiva_compartida(monkeypatch):
    """La selección de flujo debe pasar por la fase compartida, no por GCS hardcodeado."""
    llamado = {}

    def fake_prep(driver, wait, cfg, proveedor):
        llamado["prep"] = (cfg.clave, proveedor.nombre)
        return Path("/tmp/fake.xlsx"), [Path("/tmp/a.pdf")], "ok"

    def fake_carga(driver, wait, **kwargs):
        llamado["carga"] = kwargs["etiqueta"]
        return kwargs["plantilla"]

    monkeypatch.setattr(
        "flows.documentos_trabajador._preparar_plantilla_y_pdfs", fake_prep
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.ejecutar_carga_masiva_excel_y_pdfs", fake_carga
    )
    cfg = next(d for d in DOCUMENTOS_TRABAJADOR if d.clave == "cedulas_identidad")
    out = ejecutar_carga_documento_trabajador(
        None, None, cfg, proveedor=ProveedorLocal(Path("/tmp"))
    )
    assert out == Path("/tmp/fake.xlsx")
    assert llamado["prep"][0] == "cedulas_identidad"
    assert llamado["carga"] == "cedulas_identidad"
    assert ejecutar_carga_masiva_excel_y_pdfs is not None


def test_asegurar_resultado_post_carga_fallos():
    from browser import asegurar_resultado_post_carga

    with pytest.raises(RuntimeError, match="ok=False|Post-carga falló"):
        asegurar_resultado_post_carga({"ok": False, "agregados": None}, etiqueta="t")
    with pytest.raises(RuntimeError, match="subidos=0"):
        asegurar_resultado_post_carga(
            {"ok": True, "subidos": 0, "errores": 3, "agregados": 0}, etiqueta="t"
        )
    ok = asegurar_resultado_post_carga(
        {"ok": True, "agregados": 5, "errores": 0}, etiqueta="t"
    )
    assert ok["agregados"] == 5
