"""Navegación a la sección de documentos del trabajador (nivel PERSONA).

NO es Cargas Masivas → plantillas (cmsd_* / faena). Los XPaths de esta
sección están pendientes de captura en el portal; el flujo avisa claro.
"""

from __future__ import annotations

import logging
import time

from browser import click_xpath, screenshot, escribir_xpath, xpk
from flows.llegar_a_plantillas import hacer_login
from flows.nivel_carga import NivelCarga
from xpaths import xpath_pendiente

logger = logging.getLogger(__name__)

NIVEL = NivelCarga.PERSONA

# Orden de navegación hasta la búsqueda por RUT (capturar en portal).
PASOS_NAV_PERSONA: list[str] = [
    "persona.menu",
    "persona.seccion_documentos",
]


def _pasos_pendientes() -> list[str]:
    return [k for k in PASOS_NAV_PERSONA if xpath_pendiente(k)]


def navegar_a_documentos_persona(driver, wait) -> str | None:
    """
    Desde home (ya logueado) hasta la UI de documentos por trabajador.
    Returns: clave xpath pendiente, o None si llegó.
    """
    pendientes = _pasos_pendientes()
    if pendientes:
        logger.warning(
            "[nivel=%s] XPaths pendientes de captura: %s. "
            "Flujo: documentos_trabajador (PERSONA, por RUT). "
            "No usar nav.cargar_plantillas / cmsd_* (eso es FAENA).",
            NIVEL.value,
            pendientes,
        )
        for k in pendientes:
            screenshot(driver, f"pendiente_{k.replace('.', '_')}.png")
        return pendientes[0]

    for key in PASOS_NAV_PERSONA:
        logger.info("[nivel=%s] Click: %s", NIVEL.value, key)
        click_xpath(driver, wait, xpk(driver, key))
        time.sleep(1.2)
        screenshot(driver, f"{key.replace('.', '_')}.png")
    logger.info("[nivel=%s] En sección documentos del trabajador", NIVEL.value)
    return None


def llegar_a_documentos_persona(driver, wait) -> str | None:
    """Login + navegación a documentos por trabajador (PERSONA)."""
    hacer_login(driver, wait)
    return navegar_a_documentos_persona(driver, wait)


def buscar_trabajador_por_rut(driver, wait, rut: str) -> str | None:
    """
    Ubica la ficha del trabajador por RUT en la sección PERSONA.
    Returns: clave xpath pendiente, o None si abrió la ficha.
    """
    for key in (
        "persona.input_buscar_rut",
        "persona.btn_buscar",
        "persona.abrir_ficha",
    ):
        if xpath_pendiente(key):
            logger.warning(
                "[nivel=%s] XPath pendiente para buscar RUT=%s: %s",
                NIVEL.value,
                rut,
                key,
            )
            screenshot(driver, f"pendiente_{key.replace('.', '_')}.png")
            return key

    logger.info("[nivel=%s] Buscando trabajador RUT=%s", NIVEL.value, rut)
    escribir_xpath(driver, wait, xpk(driver, "persona.input_buscar_rut"), rut)
    click_xpath(driver, wait, xpk(driver, "persona.btn_buscar"))
    time.sleep(1)
    click_xpath(driver, wait, xpk(driver, "persona.abrir_ficha"))
    time.sleep(1)
    screenshot(driver, f"persona_ficha_{rut}.png")
    return None
