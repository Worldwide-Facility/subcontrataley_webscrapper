#!/usr/bin/env python3
"""Entry point Cloud Run Job: Auditor Subcontrataley."""

from __future__ import annotations

import logging
import sys

from auditor.config import cargar_config
from auditor.orquestador import correr_auditoria
from config import IS_CLOUD_RUN, mascarar, require_credentials

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> int:
    cfg = cargar_config()
    logger.info(
        "=== Auditor Cloud Run | cloud=%s periodo=%s modo=%s ===",
        IS_CLOUD_RUN,
        cfg.periodo_yyyy_mm,
        cfg.modo,
    )
    # Credenciales del portal solo si hará falta bajar plantilla
    try:
        user, _ = require_credentials()
        logger.info("Usuario portal: %s", mascarar(user))
    except ValueError:
        logger.warning(
            "Sin credenciales Subcontrataley: se intentará plantilla cacheada en GCS"
        )

    try:
        resultado = correr_auditoria(cfg)
    except Exception:
        logger.exception("Fallo el auditor Subcontrataley")
        return 1

    logger.info(
        "OK auditor | trabajadores=%s faltantes=%s lotes=%s uris=%s",
        resultado.get("trabajadores"),
        resultado.get("faltantes"),
        resultado.get("lotes"),
        resultado.get("reporte_uris"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
