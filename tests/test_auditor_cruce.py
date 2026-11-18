"""Tests unitarios del cruce del auditor (líquido 0, finiquitado, plan)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditor.config import WORKFLOW_POR_TIPO
from auditor.cruce import (
    InventarioRut,
    auditar_trabajador,
    candidatos_transferencia,
    finiquitado_en_periodo,
    generar_plan_descargas,
    requiere_transferencia,
)
from auditor.modelos import EstadoFiniquito, TrabajadorPlantilla

PER = date(2026, 10, 1)
TIPOS = (
    "liquidacion",
    "transferencia",
    "cotizaciones",
    "asistencia",
    "finiquito",
)


def _trab(rut: str = "27168649-8", **kw) -> TrabajadorPlantilla:
    cuerpo = rut.split("-")[0]
    return TrabajadorPlantilla(
        rut=rut,
        rut_cuerpo=cuerpo,
        nombre=kw.get("nombre", "Test"),
        faena=kw.get("faena", "Faena A"),
        local=kw.get("local", "Local 1"),
        fecha_fin_contrato=kw.get("fecha_fin_contrato"),
    )


def test_requiere_transferencia_liquido_cero():
    ok, motivo = requiere_transferencia(0)
    assert ok is False
    assert "líquido 0" in (motivo or "")
    assert requiere_transferencia(1000)[0] is True
    assert requiere_transferencia(None)[0] is True


def test_finiquitado_en_periodo_usa_fecha_finiquito_no_contrato():
    assert finiquitado_en_periodo("Finiquitado", "2026-10-15", PER) is True
    assert finiquitado_en_periodo("Finiquitado", "2026-09-30", PER) is False
    assert finiquitado_en_periodo("Activo", "2026-10-01", PER) is True
    assert finiquitado_en_periodo("Activo", None, PER) is False
    # fecha_fin_contrato de plantilla NO debe usarse aquí (solo fecha_finiquito)
    assert finiquitado_en_periodo("", "0000-00-00", PER) is False


def test_cruce_liquido_cero_no_exige_transferencia():
    t = _trab()
    inv = InventarioRut(
        rutas_gcs=[
            "Trabajadores/27168649/Liquidacion/octubre 2026/27168649_Liquidacion_octubre 2026.pdf",
            "Trabajadores/27168649/Cotizaciones/2026/10/27168649_Cotizacion_202610.pdf",
            "Trabajadores/27168649/Asistencia/octubre 2026/27168649_Asistencia_octubre 2026.pdf",
        ],
        rutas_bq=set(),
        liquido=0,
        empresa_gcs="Security",
    )
    fila = auditar_trabajador(
        t,
        periodo=PER,
        tipos=TIPOS,
        inventario=inv,
        finiquito=EstadoFiniquito(rut_cuerpo="27168649", estado="Activo"),
    )
    assert fila.docs["transferencia"].requerido is False
    assert "transferencia" not in fila.faltantes
    assert fila.docs["liquidacion"].presente_gcs is True
    assert fila.faltantes == []  # finiquito no aplica


def test_cruce_finiquitado_exige_finiquito():
    t = _trab("22564605-8", fecha_fin_contrato="2026-10-20")  # plantilla: ignorar
    inv = InventarioRut(
        rutas_gcs=[
            "Trabajadores/22564605/Liquidacion/octubre 2026/x.pdf",
            "Trabajadores/22564605/Transferencia/octubre 2026/x.pdf",
            "Trabajadores/22564605/Cotizaciones/2026/10/x.pdf",
            "Trabajadores/22564605/Asistencia/octubre 2026/x.pdf",
        ],
        rutas_bq=set(),
        liquido=500000,
        empresa_gcs="Security",
    )
    # Sin marca de finiquito en reclutamiento → no exige aunque plantilla diga fin contrato
    fila_no = auditar_trabajador(
        t,
        periodo=PER,
        tipos=TIPOS,
        inventario=inv,
        finiquito=EstadoFiniquito(
            rut_cuerpo="22564605",
            estado="Activo",
            fecha_finiquito=None,
        ),
    )
    assert "finiquito" not in fila_no.faltantes
    assert fila_no.docs["finiquito"].requerido is False

    fila_si = auditar_trabajador(
        t,
        periodo=PER,
        tipos=TIPOS,
        inventario=inv,
        finiquito=EstadoFiniquito(
            rut_cuerpo="22564605",
            estado="Finiquitado",
            fecha_finiquito="2026-10-12",
            finiquitado_en_periodo=True,
        ),
    )
    assert fila_si.finiquitado is True
    assert "finiquito" in fila_si.faltantes


def test_generar_plan_y_candidatos_transferencia():
    t1 = _trab("27168649-8")
    t2 = _trab("19792448-9")
    inv1 = InventarioRut(
        rutas_gcs=[],
        rutas_bq=set(),
        liquido=None,
        empresa_gcs="Security",
    )
    inv2 = InventarioRut(
        rutas_gcs=[
            "Trabajadores/19792448/Liquidacion/octubre 2026/19792448_Liquidacion_octubre 2026.pdf",
        ],
        rutas_bq=set(),
        liquido=250000,
        empresa_gcs="Security",
    )
    f1 = auditar_trabajador(t1, periodo=PER, tipos=TIPOS, inventario=inv1)
    f2 = auditar_trabajador(t2, periodo=PER, tipos=TIPOS, inventario=inv2)
    plan = generar_plan_descargas(
        [f1, f2],
        periodo=PER,
        solicitud_id="test-sol",
        workflow_por_tipo=WORKFLOW_POR_TIPO,
    )
    tipos_plan = [L.tipo_auditor for L in plan]
    assert "liquidacion" in tipos_plan
    assert "transferencia" not in tipos_plan  # se crea en el auditor, no workflow
    # liquidacion antes que asistencia
    if "liquidacion" in tipos_plan and "asistencia" in tipos_plan:
        assert tipos_plan.index("liquidacion") < tipos_plan.index("asistencia")

    cands = candidatos_transferencia([f1, f2])
    assert len(cands) == 1
    assert cands[0].trabajador.rut_cuerpo == "19792448"


def test_contrato_fuera_por_defecto():
    t = _trab()
    inv = InventarioRut(rutas_gcs=[], rutas_bq=set(), liquido=None)
    fila = auditar_trabajador(t, periodo=PER, tipos=TIPOS, inventario=inv)
    assert "contrato" not in fila.docs
    fila2 = auditar_trabajador(
        t, periodo=PER, tipos=TIPOS + ("contrato",), inventario=inv
    )
    assert "contrato" in fila2.faltantes


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
