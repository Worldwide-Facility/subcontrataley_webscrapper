#!/usr/bin/env python3
"""Entry point Cloud Run Job: documentos vigentes del trabajador (nivel PERSONA).

Carga por RUT en la sección de documentos del trabajador (NO plantillas faena).
Por defecto recorre los 15 tipos. Filtrar con
DOCUMENTOS_TRABAJADOR_CLAVES=clave1,clave2 (CSV de claves).
"""

from __future__ import annotations

import logging
import sys
import time
import traceback

from browser import iniciar_navegador, screenshot
from config import DRY_RUN, DOWNLOAD_DIR, HEADLESS, IS_CLOUD_RUN, mascarar, require_credentials
from flows.documentos_trabajador import (
    DOCUMENTOS_TRABAJADOR,
    documentos_desde_env,
    ejecutar_carga_documento_trabajador,
)
from flows.proveedor_documentos_trabajador import fuente_desde_env, proveedor_desde_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> int:
    docs = documentos_desde_env()
    fuente = fuente_desde_env()
    logger.info(
        "=== Documentos trabajador Cloud Run | headless=%s cloud=%s downloads=%s "
        "docs=%s/%s fuente=%s ===",
        HEADLESS,
        IS_CLOUD_RUN,
        DOWNLOAD_DIR,
        len(docs),
        len(DOCUMENTOS_TRABAJADOR),
        fuente,
    )
    user, _ = require_credentials()
    logger.info("DRY_RUN=%s (true = no sube archivos ni confirma cargas)", DRY_RUN)
    logger.info("Usuario portal: %s", mascarar(user))
    logger.info(
        "Documentos a cargar: %s | origen de archivos PENDIENTE "
        "(proveedor provisional=%s)",
        [d.clave for d in docs],
        fuente,
    )

    driver = None
    fallos: list[str] = []
    try:
        proveedor = proveedor_desde_env()
        driver, wait = iniciar_navegador(headless=True if IS_CLOUD_RUN else None)
        for cfg in docs:
            logger.info("--- Inicio %s (%s) ---", cfg.clave, cfg.nombre_ui)
            try:
                n = ejecutar_carga_documento_trabajador(
                    driver, wait, cfg, proveedor=proveedor
                )
                logger.info("OK %s | ruts=%s | nivel=persona", cfg.clave, n)
            except Exception:
                logger.error(
                    "Fallo documento %s:\n%s", cfg.clave, traceback.format_exc()
                )
                fallos.append(cfg.clave)
                if driver is not None:
                    try:
                        screenshot(driver, f"error_{cfg.clave}_cloudrun.png")
                    except Exception:
                        pass
        if fallos:
            logger.error("Documentos con error (%s): %s", len(fallos), fallos)
            return 1
        logger.info("OK fin de flujo. documentos=%s", len(docs))
        if not IS_CLOUD_RUN:
            time.sleep(15)
        return 0
    except Exception:
        logger.error("Fallo Documentos trabajador:\n%s", traceback.format_exc())
        if driver is not None:
            try:
                screenshot(driver, "error_documentos_trabajador_cloudrun.png")
            except Exception:
                pass
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
            logger.info("Navegador cerrado")


if __name__ == "__main__":
    sys.exit(main())
