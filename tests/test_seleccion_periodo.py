"""Regla Diego: sin periodo objetivo en el select → no subir; exit 0.

Ejecutar: python -m pytest tests/test_seleccion_periodo.py
"""
from __future__ import annotations

import logging
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser import (  # noqa: E402
    _periodo_coincide,
    seleccionar_periodo_mes_anterior,
)
from errores_operativos import (  # noqa: E402
    ESTADO_PERIODO_NO_DISPONIBLE,
    PeriodoNoDisponible,
    es_error_operativo,
    registrar_periodo_no_disponible,
)


class _FakeOpt:
    def __init__(self, text: str):
        self.text = text


class _FakeSelect:
    def __init__(self, labels: list[str]):
        self.options = [_FakeOpt(t) for t in labels]
        self.selected: str | None = None

    def select_by_visible_text(self, text: str) -> None:
        self.selected = text


class TestPeriodoCoincide(unittest.TestCase):
    def test_abreviacion_y_completo(self):
        self.assertTrue(_periodo_coincide("Oct 2026", 2026, 10))
        self.assertTrue(_periodo_coincide("octubre 2026", 2026, 10))
        self.assertFalse(_periodo_coincide("Dic 2026", 2026, 10))
        self.assertFalse(_periodo_coincide("Oct 2025", 2026, 10))


class TestSeleccionarPeriodo(unittest.TestCase):
    def _run(self, labels: list[str], referencia: date, tipo: str = "Liquidaciones"):
        fake = _FakeSelect(labels)
        driver = MagicMock()
        wait = MagicMock()
        wait.until.return_value = MagicMock(name="el")
        with (
            patch("browser.Select", return_value=fake),
            patch("browser.disparar_change") as disparar,
        ):
            elegido = seleccionar_periodo_mes_anterior(
                driver,
                wait,
                "//select[@id='cmsd_periodos']",
                referencia=referencia,
                tipo=tipo,
            )
        return elegido, fake, disparar

    def test_periodo_presente_selecciona_ese(self):
        # referencia Nov 2026 → mes anterior Oct 2026
        elegido, fake, disparar = self._run(
            ["Ago 2026", "Sep 2026", "Oct 2026", "Dic 2026"],
            date(2026, 11, 15),
        )
        self.assertEqual(elegido, "Oct 2026")
        self.assertEqual(fake.selected, "Oct 2026")
        disparar.assert_called_once()

    def test_periodo_ausente_no_elige_otra_ni_dispara(self):
        # Oct completo: selector tiene Nov/Dic pero no Oct → no fallback
        fake = _FakeSelect(["Nov 2026", "Dic 2026"])
        driver = MagicMock()
        wait = MagicMock()
        wait.until.return_value = MagicMock(name="el")
        with (
            patch("browser.Select", return_value=fake),
            patch("browser.disparar_change") as disparar,
        ):
            with self.assertRaises(PeriodoNoDisponible) as ctx:
                seleccionar_periodo_mes_anterior(
                    driver,
                    wait,
                    "//select[@id='cmsd_periodos']",
                    referencia=date(2026, 11, 5),
                    tipo="Liquidaciones de Sueldo",
                )
        self.assertIsNone(fake.selected)
        disparar.assert_not_called()
        exc = ctx.exception
        self.assertEqual(exc.estado, ESTADO_PERIODO_NO_DISPONIBLE)
        self.assertEqual(exc.periodo, date(2026, 10, 1))
        self.assertIn("Octubre 2026", str(exc))
        self.assertIn("Liquidaciones de Sueldo", str(exc))
        self.assertIn("no se sube nada", str(exc))
        self.assertEqual(exc.opciones, ["Nov 2026", "Dic 2026"])

    def test_selector_vacio_es_error(self):
        fake = _FakeSelect(["Seleccione", ""])
        driver = MagicMock()
        wait = MagicMock()
        wait.until.return_value = MagicMock(name="el")
        with patch("browser.Select", return_value=fake):
            with self.assertRaises(ValueError) as ctx:
                seleccionar_periodo_mes_anterior(
                    driver,
                    wait,
                    "//select[@id='cmsd_periodos']",
                    referencia=date(2026, 11, 5),
                    tipo="Libro de Asistencia",
                )
        self.assertIn("sin opciones útiles", str(ctx.exception))
        self.assertTrue(es_error_operativo(ctx.exception))


class TestSalidaPeriodoNoDisponible(unittest.TestCase):
    def test_registrar_exit_0_y_estado(self):
        log = MagicMock(spec=logging.Logger)
        driver = MagicMock()
        exc = PeriodoNoDisponible(
            date(2026, 10, 1),
            tipo="Pagos Mutualidades",
            opciones=["Dic 2026"],
        )
        with patch(
            "flows.llegar_a_plantillas.hacer_logout"
        ) as logout:
            code = registrar_periodo_no_disponible(log, exc, driver)
        self.assertEqual(code, 0)
        self.assertFalse(es_error_operativo(exc))
        logout.assert_called_once_with(driver)
        # logger.info("%s | estado=%s", exc, exc.estado)
        fmt, logged_exc, estado = log.info.call_args_list[0][0]
        self.assertEqual(fmt, "%s | estado=%s")
        self.assertIn("no se sube nada", str(logged_exc))
        self.assertEqual(estado, ESTADO_PERIODO_NO_DISPONIBLE)


if __name__ == "__main__":
    unittest.main()
