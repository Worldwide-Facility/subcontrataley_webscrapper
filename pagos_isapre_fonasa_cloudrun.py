#!/usr/bin/env python3
"""Entry point Cloud Run Job: Pagos Isapre / FONASA."""

from __future__ import annotations

import logging
import sys
import time

from browser import iniciar_navegador, screenshot
from config import DRY_RUN, DOWNLOAD_DIR, HEADLESS, IS_CLOUD_RUN, mascarar, require_credentials
from errores_operativos import registrar_fallo
from flows.carga_pagos_isapre_fonasa import ejecutar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> int:
    logger.info(
        "=== Pagos Isapre / FONASA Cloud Run | headless=%s cloud=%s downloads=%s ===",
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
        logger.info("OK fin de flujo. excel=%s", plantilla)
        if not IS_CLOUD_RUN:
            time.sleep(15)
        return 0
    except Exception as exc:
        if driver is not None:
            try:
                screenshot(driver, "error_pagos_isapre_fonasa_cloudrun.png")
            except Exception:
                pass
        return registrar_fallo(logger, "Pagos Isapre / FONASA", exc)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
            logger.info("Navegador cerrado")


if __name__ == "__main__":
    sys.exit(main())
