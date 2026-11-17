"""Espera de dropzone y post-carga (contador simulado, sin Selenium)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from espera_carga import (  # noqa: E402
    EstadoEsperaPostCarga,
    LecturaPostCarga,
    avanzar_espera_post_carga,
    dropzone_carga_completa,
    parse_lectura_post_carga,
    re_en_curso,
    resumen_desde_decision,
    timeout_upload_s,
    zona_upload_lista,
)
from errores_operativos import (  # noqa: E402
    es_error_operativo,
    exigir_ok_post_carga,
)


class TestTimeoutUpload(unittest.TestCase):
    def test_proporcional_a_n(self):
        self.assertEqual(
            timeout_upload_s(10, base_s=120, per_file_s=8, minimo_s=60),
            200.0,
        )
        # 217 PDFs → generoso
        self.assertEqual(
            timeout_upload_s(217, base_s=120, per_file_s=8, minimo_s=60),
            120 + 217 * 8,
        )

    def test_minimo(self):
        self.assertEqual(
            timeout_upload_s(0, base_s=10, per_file_s=1, minimo_s=60),
            60.0,
        )


class TestDropzoneCompleta(unittest.TestCase):
    def test_ok_cuando_todos_success(self):
        vis = [
            {"name": "a.pdf", "success": True, "error": False, "processing": False},
            {"name": "b.pdf", "success": True, "error": False, "processing": False},
        ]
        r = dropzone_carga_completa(vis, ["a.pdf", "b.pdf"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["faltan"], [])
        self.assertEqual(r["procesando"], [])

    def test_no_ok_si_procesando(self):
        vis = [
            {"name": "a.pdf", "success": False, "error": False, "processing": True},
            {"name": "b.pdf", "success": True, "error": False, "processing": False},
        ]
        r = dropzone_carga_completa(vis, ["a.pdf", "b.pdf"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["procesando"], ["a.pdf"])

    def test_no_ok_si_faltan(self):
        vis = [
            {"name": "a.pdf", "success": True, "error": False, "processing": False},
        ]
        r = dropzone_carga_completa(vis, ["a.pdf", "b.pdf"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["faltan"], ["b.pdf"])

    def test_no_ok_si_error(self):
        vis = [
            {"name": "a.pdf", "success": False, "error": True, "processing": False},
        ]
        r = dropzone_carga_completa(vis, ["a.pdf"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["con_error"], ["a.pdf"])


class TestZonaUploadLista(unittest.TestCase):
    def test_ready_con_items_sin_progreso(self):
        self.assertTrue(
            zona_upload_lista(
                {"items": 5, "progress": 0, "processing": 0, "complete": 5, "errors": 0},
                n_min=5,
            )
        )

    def test_no_ready_si_progress(self):
        self.assertFalse(
            zona_upload_lista(
                {"items": 5, "progress": 1, "processing": 0, "complete": 4, "errors": 0},
                n_min=5,
            )
        )

    def test_no_ready_complete_cero_no_es_atajo_bajo_n_min(self):
        # Antes: complete==0 permitía ready; ahora exige items>=n_min y sin progreso.
        self.assertFalse(
            zona_upload_lista(
                {"items": 2, "progress": 0, "processing": 0, "complete": 0, "errors": 0},
                n_min=5,
            )
        )

    def test_ready_sin_marcas_complete_si_items_ok(self):
        self.assertTrue(
            zona_upload_lista(
                {"items": 5, "progress": 0, "processing": 0, "complete": 0, "errors": 0},
                n_min=5,
            )
        )


class TestPostCargaSimulado(unittest.TestCase):
    """Simula el contador Documentos Agregados avanzando en el tiempo."""

    def test_no_termina_en_primera_aparicion_si_en_curso(self):
        # Bug 17-nov: Documentos Agregados:111 con mensaje aún en curso.
        estado = EstadoEsperaPostCarga()
        d = avanzar_espera_post_carga(
            LecturaPostCarga(agregados=111, en_curso=True),
            estado,
            ahora=10.0,
            esperado=229,
            estable_s=15.0,
        )
        self.assertFalse(d.terminado)
        self.assertEqual(d.motivo, "en_curso")

    def test_alcanza_esperado_cuando_deja_de_estar_en_curso(self):
        estado = EstadoEsperaPostCarga(vio_en_curso=True)
        d = avanzar_espera_post_carga(
            LecturaPostCarga(agregados=229, en_curso=False),
            estado,
            ahora=100.0,
            esperado=229,
            estable_s=15.0,
        )
        self.assertTrue(d.terminado)
        self.assertTrue(d.ok)
        self.assertIn("alcanzado_esperado", d.motivo)

    def test_estable_bajo_esperado_falla(self):
        # Contador se estabiliza en 109 < 229 tras desaparecer en_curso.
        estado = EstadoEsperaPostCarga()
        t = 0.0
        lecturas = [
            LecturaPostCarga(agregados=50, en_curso=True),
            LecturaPostCarga(agregados=100, en_curso=True),
            LecturaPostCarga(agregados=109, en_curso=False),
            LecturaPostCarga(agregados=109, en_curso=False),
            LecturaPostCarga(agregados=109, en_curso=False),
        ]
        decision = None
        for lec in lecturas:
            t += 10.0  # 10s entre muestras → a los 20s de estable (2×10 tras primer 109)
            decision = avanzar_espera_post_carga(
                lec, estado, ahora=t, esperado=229, estable_s=15.0
            )
            estado = decision.estado
        assert decision is not None
        self.assertTrue(decision.terminado)
        self.assertFalse(decision.ok)
        self.assertIn("estable_bajo_esperado", decision.motivo)
        self.assertIn("109<229", decision.motivo)

    def test_contador_que_sigue_subiendo_no_estabiliza(self):
        estado = EstadoEsperaPostCarga()
        t = 0.0
        for agg in (10, 20, 30, 40, 50):
            t += 20.0
            d = avanzar_espera_post_carga(
                LecturaPostCarga(agregados=agg, en_curso=False),
                estado,
                ahora=t,
                esperado=100,
                estable_s=15.0,
            )
            estado = d.estado
            self.assertFalse(d.terminado, msg=f"agg={agg} motivo={d.motivo}")

    def test_sin_esperado_estable_ok(self):
        estado = EstadoEsperaPostCarga(estable_desde=0.0, ultimo_agregados=12)
        d = avanzar_espera_post_carga(
            LecturaPostCarga(agregados=12, en_curso=False),
            estado,
            ahora=20.0,
            esperado=None,
            estable_s=15.0,
        )
        self.assertTrue(d.terminado)
        self.assertTrue(d.ok)

    def test_parse_detecta_en_curso(self):
        lec = parse_lectura_post_carga(
            agregados=111,
            texto="Se esta realizando la carga masiva… Documentos Agregados: 111",
        )
        self.assertTrue(lec.en_curso)
        self.assertTrue(re_en_curso(lec.texto))

    def test_resumen_criterio_documentado(self):
        lec = LecturaPostCarga(agregados=229, en_curso=False)
        d = avanzar_espera_post_carga(
            lec,
            EstadoEsperaPostCarga(),
            ahora=1.0,
            esperado=229,
            estable_s=15.0,
        )
        r = resumen_desde_decision(lec, d, esperado=229, elapsed_s=1.0)
        self.assertEqual(r["criterio_esperado"], "filas_plantilla_docs_principales")
        self.assertTrue(r["ok"])


class TestExigirOkPostCarga(unittest.TestCase):
    def test_incompleta_es_operativo(self):
        with self.assertRaises(RuntimeError) as ctx:
            exigir_ok_post_carga(
                {
                    "ok": False,
                    "agregados": 109,
                    "esperado": 229,
                    "motivo": "estable_bajo_esperado:109<229",
                },
                etiqueta="Liquidaciones de Sueldo",
                esperado=229,
            )
        msg = str(ctx.exception)
        self.assertIn("Post-carga incompleta", msg)
        self.assertIn("109", msg)
        self.assertIn("229", msg)
        self.assertTrue(es_error_operativo(ctx.exception))

    def test_ok_con_esperado(self):
        r = {"ok": True, "agregados": 229, "esperado": 229}
        self.assertIs(
            exigir_ok_post_carga(r, etiqueta="liq", esperado=229),
            r,
        )


if __name__ == "__main__":
    unittest.main()
