"""
Ejecuta una rama de carga de plantilla.

Uso:
  python run_flujo.py liquidaciones
  python run_flujo.py libro_asistencia
  python run_flujo.py listado_trabajadores
  python run_flujo.py pagos_afp_afc
  python run_flujo.py pagos_isapre_fonasa
  python run_flujo.py cedulas_identidad
  python run_flujo.py --list
"""

from __future__ import annotations

import argparse
import logging
import time

from browser import iniciar_navegador, screenshot
from config import DRY_RUN
from flows import FLUJOS_CARGA

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Flujos Subcontrataley")
    parser.add_argument(
        "flujo",
        nargs="?",
        choices=sorted(FLUJOS_CARGA.keys()),
        help="Rama a ejecutar",
    )
    parser.add_argument("--list", action="store_true", help="Listar flujos")
    args = parser.parse_args()

    if args.list or not args.flujo:
        print("Flujos disponibles:")
        for key, (nombre, _) in sorted(FLUJOS_CARGA.items()):
            print(f"  {key:36} → {nombre}")
        if not args.flujo:
            parser.error("Indica un flujo, ej: python run_flujo.py liquidaciones")
        return

    nombre, ejecutar = FLUJOS_CARGA[args.flujo]
    logger.info("Iniciando flujo: %s (%s) DRY_RUN=%s", nombre, args.flujo, DRY_RUN)

    driver, wait = iniciar_navegador(headless=False)
    try:
        ejecutar(driver, wait)
        logger.info("Flujo '%s' terminó. Navegador abierto 60s.", nombre)
        time.sleep(60)
    except Exception:
        screenshot(driver, f"error_{args.flujo}.png")
        raise
    finally:
        driver.quit()
        logger.info("Navegador cerrado")


if __name__ == "__main__":
    main()
