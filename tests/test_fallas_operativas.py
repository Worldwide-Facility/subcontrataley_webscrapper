"""Post-carga, ingreso trabajadores (cmt_*) y errores operativos claros."""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from errores_operativos import (  # noqa: E402
    es_error_operativo,
    exigir_ok_post_carga,
    registrar_fallo,
)
from flows import carga_ingreso_trabajadores as ingreso  # noqa: E402


class FakeDriver:
    def __init__(self, body: str):
        self._body = body

    def find_element(self, *args, **kwargs):
        el = MagicMock()
        el.text = self._body
        return el


class TestErroresOperativos(unittest.TestCase):
    def test_file_not_found_pdfs_periodo(self):
        exc = FileNotFoundError(
            "No hay PDFs 'Asistencia' en /tmp/x para periodo 'agosto 2026'"
        )
        self.assertTrue(es_error_operativo(exc))

    def test_value_error_ningun_rut_cotizaciones(self):
        exc = ValueError(
            "Ningún RUT tiene 'Cotizaciones' en GCS para periodo 'agosto 2026'."
        )
        self.assertTrue(es_error_operativo(exc))

    def test_value_error_periodo_portal(self):
        exc = ValueError(
            "El portal no ofrece el periodo 2026-08 en //select[@id='cmsd_periodos']; "
            "opciones: ['Jul 2026']"
        )
        self.assertTrue(es_error_operativo(exc))

    def test_otros_errores_no_son_operativos(self):
        self.assertFalse(es_error_operativo(RuntimeError("boom")))
        self.assertFalse(es_error_operativo(FileNotFoundError("/tmp/missing.xlsx")))
        self.assertFalse(es_error_operativo(ValueError("columna inválida")))

    def test_registrar_fallo_operativo_una_linea(self):
        log = MagicMock(spec=logging.Logger)
        exc = ValueError(
            "Ningún RUT tiene 'Cotizaciones' en GCS para periodo 'agosto 2026'."
        )
        code = registrar_fallo(log, "Pagos Mutualidades", exc)
        self.assertEqual(code, 1)
        log.error.assert_called_once_with("%s", exc)
        # Sin traceback en el formato
        self.assertNotIn("\n", log.error.call_args[0][0])


class TestIngresoCargaMasiva(unittest.TestCase):
    def test_terminada_por_trabajadores_agregados_sin_100(self):
        body = (
            "3.- CARGA MASIVA\n"
            "Progreso 47%\n"
            "Trabajadores Agregados: 12\n"
            "Total: 12\n"
        )
        self.assertTrue(ingreso._carga_masiva_terminada(FakeDriver(body)))

    def test_no_terminada_solo_pct_intermedio(self):
        body = "Cargando… 47%\nTotal: 12"
        self.assertFalse(ingreso._carga_masiva_terminada(FakeDriver(body)))

    def test_no_depende_de_pct_100(self):
        """Aunque pct!=100, el mensaje de agregados basta (bug barra portal)."""
        body = "Trabajadores Agregados: 3\nEnviando… 88%"
        prog = ingreso._parse_progreso_carga(body)
        self.assertEqual(prog["agregados"], 3)
        self.assertNotEqual(prog["pct"], 100)
        self.assertTrue(ingreso._carga_masiva_terminada(FakeDriver(body)))

    def test_fallback_mensaje_fin(self):
        body = "Proceso finalizado correctamente."
        self.assertTrue(ingreso._carga_masiva_terminada(FakeDriver(body)))

    def test_pct_100_solo_ya_no_alcanza(self):
        """No usar pct==100 como criterio (barra bugueada puede mentir)."""
        body = "Avance 100%\nTotal: 5"
        # Sin 'Trabajadores Agregados' ni mensaje de fin → no terminada
        self.assertFalse(ingreso._carga_masiva_terminada(FakeDriver(body)))

    def test_validacion_ok_mensajes(self):
        self.assertTrue(
            ingreso._validacion_ok(
                FakeDriver("Cantidad de errores encontrados: 0")
            )
        )
        self.assertTrue(
            ingreso._validacion_ok(
                FakeDriver("La plantilla subida se encuentra correcta.")
            )
        )
        self.assertFalse(
            ingreso._validacion_ok(
                FakeDriver("Validación con errores\nCantidad de errores encontrados: 3")
            )
        )


class TestPostCargaCallersRaise(unittest.TestCase):
    def test_ok_false_hace_raise(self):
        with self.assertRaises(RuntimeError) as ctx:
            exigir_ok_post_carga(
                {"ok": False, "agregados": None, "modals": []},
                etiqueta="pagos_mutualidades",
            )
        msg = str(ctx.exception)
        self.assertIn("Documentos Agregados", msg)
        self.assertIn("pagos_mutualidades", msg)

    def test_ok_true_pasa(self):
        resumen = {"ok": True, "agregados": 4}
        self.assertIs(exigir_ok_post_carga(resumen, etiqueta="liquidaciones"), resumen)


class TestValidacionRaise(unittest.TestCase):
    @patch.object(ingreso, "esperar_carga_masiva", return_value=True)
    @patch.object(ingreso, "click_mutante")
    @patch.object(ingreso, "enviar_archivos")
    @patch.object(ingreso, "_navegar_pasos", return_value=None)
    @patch.object(ingreso, "hacer_login")
    @patch.object(ingreso, "_click_carga_masiva")
    @patch.object(ingreso, "dry_run", return_value=False)
    @patch.object(ingreso, "xpath_pendiente", return_value=False)
    @patch.object(ingreso, "screenshot")
    @patch.object(ingreso, "_resolver_plantilla")
    def test_validacion_con_errores_hace_raise(
        self,
        mock_resolver,
        *_mocks,
    ):
        mock_resolver.return_value = Path("/tmp/plantilla_ingreso_trabajadores.xlsx")
        driver = FakeDriver(
            "Validación con errores\nCantidad de errores encontrados: 2"
        )
        wait = MagicMock()
        with self.assertRaises(RuntimeError) as ctx:
            ingreso.ejecutar(driver, wait, plantilla=Path("/tmp/x.xlsx"))
        self.assertIn("Validación con errores", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
