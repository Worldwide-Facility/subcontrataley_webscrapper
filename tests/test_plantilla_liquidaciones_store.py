"""La planilla de liquidaciones queda guardada y se reutiliza en el mismo periodo."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plantilla_liquidaciones_store import (  # noqa: E402
    asegurar_plantilla_liquidaciones,
    clave_periodo,
    guardar_plantilla_liquidaciones,
    ruta_gcs_plantilla_liquidaciones,
)


class _Blob:
    def __init__(self, store: dict, name: str, bucket_name: str):
        self.store = store
        self.name = name
        self.bucket_name = bucket_name

        class _Bucket:
            name = bucket_name

        self.bucket = _Bucket()

    def upload_from_filename(self, filename, content_type=None):
        self.uploads.append(self.name)
        self.store[self.name] = Path(filename).read_bytes()

    def exists(self):
        return self.name in self.store

    def download_to_filename(self, filename):
        Path(filename).write_bytes(self.store[self.name])


class _Bucket:
    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.name = "test-bucket"
        self.uploads: list[str] = []

    def blob(self, name):
        b = _Blob(self.store, name, self.name)
        b.uploads = self.uploads
        return b


class TestPlantillaLiquidacionesStore(unittest.TestCase):
    def test_clave_de_periodo(self):
        self.assertEqual(clave_periodo("septiembre 2026"), "septiembre_2026")
        self.assertEqual(
            ruta_gcs_plantilla_liquidaciones("septiembre 2026"),
            "Subcontrataley/plantillas_liquidaciones/septiembre_2026.xlsx",
        )

    def test_reutiliza_la_guardada_sin_volver_al_portal(self):
        bucket = _Bucket()
        origen = Path(self.id().replace(".", "_") + ".xlsx")
        try:
            origen.write_bytes(b"planilla-original")
            guardar_plantilla_liquidaciones(origen, "septiembre 2026", bucket=bucket)
        finally:
            origen.unlink(missing_ok=True)

        llamadas = {"n": 0}

        def descargar():
            llamadas["n"] += 1
            raise AssertionError("no debía descargar")

        dest = Path("downloads_test_planilla")
        try:
            path = asegurar_plantilla_liquidaciones(
                "septiembre 2026",
                dest,
                descargar,
                bucket=bucket,
            )
            self.assertEqual(path.read_bytes(), b"planilla-original")
            self.assertEqual(llamadas["n"], 0)
        finally:
            if dest.exists():
                for hijo in dest.iterdir():
                    hijo.unlink()
                dest.rmdir()

    def test_si_no_esta_guardada_descarga_y_deja_copia(self):
        bucket = _Bucket()
        bajada = Path("bajada_portal.xlsx")
        bajada.write_bytes(b"desde-portal")
        dest = Path("downloads_test_planilla_nueva")

        def descargar():
            return bajada

        try:
            path = asegurar_plantilla_liquidaciones(
                "agosto 2026",
                dest,
                descargar,
                bucket=bucket,
            )
            self.assertEqual(path.read_bytes(), b"desde-portal")
            ruta = ruta_gcs_plantilla_liquidaciones("agosto 2026")
            self.assertEqual(bucket.store[ruta], b"desde-portal")

            def no_descargar():
                raise AssertionError("la segunda ejecución debe usar la copia")

            otra = asegurar_plantilla_liquidaciones(
                "agosto 2026",
                dest,
                no_descargar,
                bucket=bucket,
            )
            self.assertEqual(otra.read_bytes(), b"desde-portal")
        finally:
            bajada.unlink(missing_ok=True)
            if dest.exists():
                for hijo in dest.iterdir():
                    hijo.unlink()
                dest.rmdir()


class TestPrimeraDelMes(unittest.TestCase):
    RUTA = ruta_gcs_plantilla_liquidaciones("octubre 2026")

    def setUp(self):
        self._env = os.environ.pop("PLANTILLA_LIQ_FORZAR", None)
        self.origen = Path(self.id().replace(".", "_") + ".xlsx")
        self.origen.write_bytes(b"nueva")

    def tearDown(self):
        self.origen.unlink(missing_ok=True)
        os.environ.pop("PLANTILLA_LIQ_FORZAR", None)
        if self._env is not None:
            os.environ["PLANTILLA_LIQ_FORZAR"] = self._env

    def test_no_existe_sube(self):
        bucket = _Bucket()
        guardar_plantilla_liquidaciones(self.origen, "octubre 2026", bucket=bucket)
        self.assertEqual(bucket.uploads, [self.RUTA])
        self.assertEqual(bucket.store[self.RUTA], b"nueva")

    def test_existe_no_sube(self):
        bucket = _Bucket()
        bucket.store[self.RUTA] = b"primera"
        with self.assertLogs("plantilla_liquidaciones_store", "INFO") as cm:
            ruta = guardar_plantilla_liquidaciones(self.origen, "octubre 2026", bucket=bucket)
        self.assertEqual(ruta, self.RUTA)
        self.assertEqual(bucket.uploads, [])
        self.assertEqual(bucket.store[self.RUTA], b"primera")
        self.assertIn("NO se sobrescribe", "\n".join(cm.output))

    def test_forzado_sube(self):
        os.environ["PLANTILLA_LIQ_FORZAR"] = "1"
        bucket = _Bucket()
        bucket.store[self.RUTA] = b"primera"
        guardar_plantilla_liquidaciones(self.origen, "octubre 2026", bucket=bucket)
        self.assertEqual(bucket.uploads, [self.RUTA])
        self.assertEqual(bucket.store[self.RUTA], b"nueva")

    def test_cuenta_filas_en_log(self):
        from openpyxl import Workbook

        def xlsx(path, n):
            wb = Workbook()
            for i in range(n):
                wb.active.append([f"rut{i}", "faena"])
            wb.save(str(path))

        bucket = _Bucket()
        xlsx(self.origen, 3)
        guardar_plantilla_liquidaciones(self.origen, "octubre 2026", bucket=bucket)
        xlsx(self.origen, 5)
        with self.assertLogs("plantilla_liquidaciones_store", "INFO") as cm:
            guardar_plantilla_liquidaciones(self.origen, "octubre 2026", bucket=bucket)
        self.assertIn("filas guardada=3, nueva=5", "\n".join(cm.output))
        self.assertEqual(len(bucket.uploads), 1)
