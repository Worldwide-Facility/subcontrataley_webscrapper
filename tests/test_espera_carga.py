"""Espera de dropzone y post-carga (contador simulado, sin Selenium)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from espera_carga import (  # noqa: E402
    EstadoEsperaPostCarga,
    LecturaPostCarga,
    avanzar_espera_post_carga,
    calcular_esperado_post_carga,
    dropzone_carga_completa,
    es_nombre_archivo_real,
    evaluar_agregados_vs_esperado,
    filtrar_previews_reales,
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
        self.assertEqual(
            timeout_upload_s(217, base_s=120, per_file_s=8, minimo_s=60),
            120 + 217 * 8,
        )

    def test_minimo(self):
        self.assertEqual(
            timeout_upload_s(0, base_s=10, per_file_s=1, minimo_s=60),
            60.0,
        )


class TestArchivosRealesVsPlaceholder(unittest.TestCase):
    """Bug rbldp: base=1 por placeholder → n_min=109 con 108 PDFs."""

    def test_placeholder_no_es_archivo_real(self):
        self.assertFalse(es_nombre_archivo_real("Arrastre archivos aquí"))
        self.assertFalse(es_nombre_archivo_real("Suelte los archivos"))
        self.assertFalse(es_nombre_archivo_real("Drop files to upload"))
        self.assertFalse(es_nombre_archivo_real(""))
        self.assertFalse(es_nombre_archivo_real(None))
        self.assertFalse(es_nombre_archivo_real("sin extension"))

    def test_pdf_si_es_real(self):
        self.assertTrue(es_nombre_archivo_real("15269706-6_liquidacion.pdf"))
        self.assertTrue(es_nombre_archivo_real("a.PDF"))

    def test_filtrar_previews_ignora_placeholder(self):
        vis = [
            {"name": "Arrastre aquí", "success": False, "error": False, "processing": False},
            {"name": "a.pdf", "success": True, "error": False, "processing": False},
            {"name": "b.pdf", "success": True, "error": False, "processing": False},
        ]
        reales = filtrar_previews_reales(vis)
        self.assertEqual([v["name"] for v in reales], ["a.pdf", "b.pdf"])

    def test_dropzone_completa_con_placeholder_y_108_pdfs(self):
        # Zona con aviso + 108 listos: no debe exigir 109.
        vis = [{"name": "Arrastre archivos aquí", "processing": False, "error": False}]
        vis += [
            {
                "name": f"liq_{i}.pdf",
                "success": True,
                "error": False,
                "processing": False,
            }
            for i in range(108)
        ]
        esperados = [f"liq_{i}.pdf" for i in range(108)]
        r = dropzone_carga_completa(vis, esperados)
        self.assertTrue(r["ok"])
        self.assertEqual(r["visibles"], 108)
        self.assertEqual(r["listos"], 108)
        self.assertEqual(r["esperados"], 108)
        self.assertEqual(r["faltan"], [])

    def test_base_vacia_es_cero_aunque_haya_placeholder(self):
        # Simula estado de zona: items debe ser 0 si solo hay placeholder.
        # (el filtrado ocurre en JS; aquí validamos la lógica pura equivalente)
        solo_ph = filtrar_previews_reales(
            [{"name": "Arrastre aquí", "success": False, "error": False}]
        )
        self.assertEqual(len(solo_ph), 0)
        estado = {"items": 0, "progress": 0, "processing": 0, "complete": 0, "errors": 0}
        self.assertFalse(zona_upload_lista(estado, n_min=1))


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

    def test_no_ready_si_errores(self):
        self.assertFalse(
            zona_upload_lista(
                {"items": 5, "progress": 0, "processing": 0, "complete": 4, "errors": 1},
                n_min=5,
            )
        )

    def test_no_ready_complete_cero_no_es_atajo_bajo_n_min(self):
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


class TestEsperadoRutDuplicado(unittest.TestCase):
    """Plantilla 109 filas / RUT 15269706-6 duplicado / 108 PDFs únicos."""

    def test_minimo_es_min_filas_pdfs_ruts(self):
        esp = calcular_esperado_post_carga(
            filas_plantilla=109,
            pdfs_principales_unicos=108,
            ruts_unicos=108,
        )
        self.assertEqual(esp["minimo_razonable"], 108)
        self.assertEqual(esp["esperado"], 108)
        self.assertEqual(esp["filas_plantilla"], 109)
        self.assertIn("min(", esp["criterio"])

    def test_evaluar_agregados_108_vs_109_filas_es_warning_ok(self):
        ev = evaluar_agregados_vs_esperado(
            108, minimo_razonable=108, filas_plantilla=109
        )
        self.assertTrue(ev["ok"])
        self.assertTrue(ev["warning"])
        self.assertEqual(ev["diff_vs_minimo"], 0)

    def test_evaluar_bajo_minimo_falla(self):
        ev = evaluar_agregados_vs_esperado(
            107, minimo_razonable=108, filas_plantilla=109
        )
        self.assertFalse(ev["ok"])
        self.assertEqual(ev["diff_vs_minimo"], 1)

    def test_exigir_ok_warning_no_falla(self):
        with patch("errores_operativos.logging.getLogger") as gl:
            logger = MagicMock()
            gl.return_value = logger
            r = exigir_ok_post_carga(
                {"ok": True, "agregados": 108, "esperado": 108},
                etiqueta="Liquidaciones de Sueldo",
                esperado=108,
                filas_plantilla=109,
            )
            self.assertEqual(r["agregados"], 108)
            logger.warning.assert_called()
            args = logger.warning.call_args[0]
            rendered = args[0] % args[1:] if len(args) > 1 else args[0]
            self.assertIn("109", rendered)
            self.assertIn("108", rendered)


class TestPostCargaSimulado(unittest.TestCase):
    def test_no_termina_en_primera_aparicion_si_en_curso(self):
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
            LecturaPostCarga(agregados=108, en_curso=False),
            estado,
            ahora=100.0,
            esperado=108,
            estable_s=15.0,
            filas_plantilla=109,
        )
        self.assertTrue(d.terminado)
        self.assertTrue(d.ok)
        self.assertTrue(d.warning)  # 108 < 109 filas
        self.assertIn("alcanzado_esperado", d.motivo)

    def test_estable_bajo_minimo_falla(self):
        estado = EstadoEsperaPostCarga()
        t = 0.0
        lecturas = [
            LecturaPostCarga(agregados=50, en_curso=True),
            LecturaPostCarga(agregados=100, en_curso=True),
            LecturaPostCarga(agregados=107, en_curso=False),
            LecturaPostCarga(agregados=107, en_curso=False),
            LecturaPostCarga(agregados=107, en_curso=False),
        ]
        decision = None
        for lec in lecturas:
            t += 10.0
            decision = avanzar_espera_post_carga(
                lec,
                estado,
                ahora=t,
                esperado=108,
                estable_s=15.0,
                filas_plantilla=109,
            )
            estado = decision.estado
        assert decision is not None
        self.assertTrue(decision.terminado)
        self.assertFalse(decision.ok)
        self.assertIn("bajo_minimo", decision.motivo)

    def test_estable_en_minimo_con_filas_mayores_ok_warning(self):
        estado = EstadoEsperaPostCarga(estable_desde=0.0, ultimo_agregados=108)
        d = avanzar_espera_post_carga(
            LecturaPostCarga(agregados=108, en_curso=False),
            estado,
            ahora=20.0,
            esperado=108,
            estable_s=15.0,
            filas_plantilla=109,
        )
        self.assertTrue(d.terminado)
        self.assertTrue(d.ok)
        self.assertTrue(d.warning)

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
        lec = LecturaPostCarga(agregados=108, en_curso=False)
        d = avanzar_espera_post_carga(
            lec,
            EstadoEsperaPostCarga(),
            ahora=1.0,
            esperado=108,
            estable_s=15.0,
            filas_plantilla=109,
        )
        r = resumen_desde_decision(
            lec, d, esperado=108, elapsed_s=1.0, filas_plantilla=109
        )
        self.assertEqual(
            r["criterio_esperado"], "min(filas_plantilla, pdfs_unicos[, ruts_unicos])"
        )
        self.assertTrue(r["ok"])
        self.assertTrue(r["warning"])


class TestExigirOkPostCarga(unittest.TestCase):
    def test_incompleta_es_operativo(self):
        with self.assertRaises(RuntimeError) as ctx:
            exigir_ok_post_carga(
                {
                    "ok": False,
                    "agregados": 107,
                    "esperado": 108,
                    "motivo": "bajo_minimo:107<108",
                },
                etiqueta="Liquidaciones de Sueldo",
                esperado=108,
                filas_plantilla=109,
            )
        msg = str(ctx.exception)
        self.assertIn("Post-carga incompleta", msg)
        self.assertIn("107", msg)
        self.assertIn("108", msg)
        self.assertTrue(es_error_operativo(ctx.exception))

    def test_ok_con_esperado(self):
        r = {"ok": True, "agregados": 108, "esperado": 108}
        self.assertIs(
            exigir_ok_post_carga(r, etiqueta="liq", esperado=108, filas_plantilla=108),
            r,
        )


if __name__ == "__main__":
    unittest.main()
