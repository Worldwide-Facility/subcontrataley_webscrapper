"""Catálogo PERSONA, proveedor, nivel faena vs persona, selección de flujo."""

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
    usa_carga_nivel_persona,
)
from flows.nivel_carga import NivelCarga  # noqa: E402
from flows.pagos_config import TODOS_PAGOS  # noqa: E402
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


def test_todos_nivel_persona():
    for doc in DOCUMENTOS_TRABAJADOR:
        assert doc.nivel == NivelCarga.PERSONA
        assert usa_carga_nivel_persona(doc)


def test_pagos_siguen_nivel_faena():
    for cfg in TODOS_PAGOS:
        assert cfg.nivel == NivelCarga.FAENA


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
    paths = prov.materializar(list(idx.values()), tmp_path / "staging")
    assert len(paths) == 2


def test_flujo_persona_no_usa_plantillas_faena(monkeypatch):
    """Debe ir a documentos PERSONA y NO a llegar_a_cargar_plantillas (faena)."""
    llamado = {"persona": False, "faena": False, "dropzone": False}

    def fake_llegar_persona(driver, wait):
        llamado["persona"] = True
        return None

    def fake_faena(*_a, **_k):
        llamado["faena"] = True
        raise AssertionError("no debe navegar a plantillas faena")

    def fake_buscar(driver, wait, rut):
        return None

    def fake_tipo(driver, wait, cfg):
        return None

    def fake_dropzone(*_a, **kwargs):
        llamado["dropzone"] = True
        assert kwargs["nivel"] == NivelCarga.PERSONA
        assert kwargs["plantilla"] is None

    monkeypatch.setattr(
        "flows.documentos_trabajador.llegar_a_documentos_persona", fake_llegar_persona
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.buscar_trabajador_por_rut", fake_buscar
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador._elegir_tipo_documento", fake_tipo
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.subir_y_confirmar_dropzone", fake_dropzone
    )
    monkeypatch.setattr(
        "flows.documentos_trabajador.xpath_pendiente", lambda _k: False
    )
    # Si alguien reintroduce faena:
    monkeypatch.setattr(
        "flows.llegar_a_plantillas.llegar_a_cargar_plantillas", fake_faena, raising=False
    )

    cfg = next(d for d in DOCUMENTOS_TRABAJADOR if d.clave == "cedulas_identidad")
    root = Path("/tmp/prov_docs_test")
    tipo_dir = root / cfg.tipo_gcs
    tipo_dir.mkdir(parents=True, exist_ok=True)
    (tipo_dir / "12345678_ci.pdf").write_bytes(b"%PDF-1.4")
    prov = ProveedorLocal(root)

    n = ejecutar_carga_documento_trabajador(None, None, cfg, proveedor=prov)
    assert n == 1
    assert llamado["persona"] is True
    assert llamado["faena"] is False
    assert llamado["dropzone"] is True


def test_flujo_persona_falla_si_xpaths_pendientes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "flows.documentos_trabajador.llegar_a_documentos_persona",
        lambda *_a, **_k: "persona.menu",
    )
    cfg = DOCUMENTOS_TRABAJADOR[0]
    with pytest.raises(RuntimeError, match="PERSONA incompleta|persona.menu"):
        ejecutar_carga_documento_trabajador(
            None, None, cfg, proveedor=ProveedorLocal(tmp_path)
        )


def test_pagos_no_usan_carga_masiva_compartida():
    """Los 4 pagos FAENA no deben depender del módulo compartido de PERSONA."""
    src = inspect.getsource(ejecutar_carga_un_documento)
    assert "carga_masiva_compartida" not in src
    assert "asegurar_resultado_post_carga" not in src
    assert "llegar_a_cargar_plantillas" in src


def test_asegurar_resultado_post_carga_fallos():
    from browser import asegurar_resultado_post_carga

    with pytest.raises(RuntimeError, match="Post-carga falló"):
        asegurar_resultado_post_carga({"ok": False}, etiqueta="t")
    with pytest.raises(RuntimeError, match="subidos=0"):
        asegurar_resultado_post_carga(
            {"ok": True, "subidos": 0, "errores": 3, "agregados": 0}, etiqueta="t"
        )
    assert asegurar_resultado_post_carga(
        {"ok": True, "agregados": 2, "errores": 0}, etiqueta="t"
    )["agregados"] == 2
