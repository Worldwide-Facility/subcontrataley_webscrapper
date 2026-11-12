#!/usr/bin/env python3
"""
Entry point Cloud Run Job: ingreso de trabajadores en Subcontrataley.

Pipeline: listado SCL → comparar CR/BQ → plantilla fresca → rellenar →
validar → realizar carga masiva (espera fin).

Variables de entorno requeridas:
  SUBCONTRATALEY_USERNAME
  SUBCONTRATALEY_PASSWORD

Opcionales:
  TOKEN_CR_CONTRATOS / TOKEN_DOCUMENTOS_CONTRATOS
  GCS_CREDENTIALS_PATH (local); en Cloud Run usa ADC de la SA del Job
  HEADLESS=true (default en Cloud Run)
  INGRESO_CARGA_TIMEOUT=600
  DOWNLOAD_DIR / DEBUG_DIR
  CHROME_BIN / CHROMEDRIVER_PATH (Dockerfile)

Local headless:
  HEADLESS=true python ingreso_trabajadores_cloudrun.py
"""

from __future__ import annotations

import logging
import sys
import time

from browser import iniciar_navegador, screenshot
from config import DRY_RUN, DOWNLOAD_DIR, HEADLESS, IS_CLOUD_RUN, mascarar, require_credentials
from errores_operativos import registrar_fallo
from flows.pipeline_ingreso_trabajadores import ejecutar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> int:
    logger.info(
        "=== Ingreso trabajadores Cloud Run | headless=%s cloud=%s downloads=%s ===",
        HEADLESS,
        IS_CLOUD_RUN,
        DOWNLOAD_DIR,
    )
    user, _ = require_credentials()
    logger.info("DRY_RUN=%s (true = no sube archivos ni confirma cargas)", DRY_RUN)
    logger.info("Usuario portal: %s", mascarar(user))

    driver = None
    try:
        driver, wait = iniciar_navegador(headless=True if IS_CLOUD_RUN else None)
        plantilla = ejecutar(driver, wait)
        logger.info("OK fin de pipeline. excel=%s", plantilla)
        if not IS_CLOUD_RUN:
            time.sleep(15)
        return 0
    except Exception as exc:
        if driver is not None:
            try:
                screenshot(driver, "error_ingreso_trabajadores_cloudrun.png")
            except Exception:
                pass
        return registrar_fallo(logger, "ingreso trabajadores", exc)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
            logger.info("Navegador cerrado")


if __name__ == "__main__":
    sys.exit(main())
