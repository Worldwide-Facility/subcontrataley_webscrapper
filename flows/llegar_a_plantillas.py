"""
Tronco común: login → home → pantalla 'Cargar plantillas'.

Desde ahí cada flujo específico (tipo de plantilla / documento)
sigue con sus propios clicks en flows/<nombre>.py.
"""

from __future__ import annotations

import logging
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from browser import click_xpath, escribir_xpath, screenshot, click_clave_si_existe, xpk
from config import require_credentials
from xpaths import LOGIN_URL, LOGOUT_URL

logger = logging.getLogger(__name__)


def cerrar_modales_post_login(driver, wait) -> None:
    """
    Intento rápido de cerrar el aviso post-login; no bloquea el flujo.
    Si no hay Cancelar en ~1s, Escape y se sigue con la navegación.
    """
    # Intento corto (no esperar 10+ s)
    if click_clave_si_existe(driver, wait, "post_login.btn_cancelar", timeout=1):
        logger.info("Modal cerrado con Cancelar")
        time.sleep(0.3)
        return

    if click_clave_si_existe(driver, wait, "post_login.boton", timeout=0.5):
        logger.info("Modal cerrado con post_login.boton")
        time.sleep(0.3)
        return

    try:
        driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    except Exception:
        from selenium.webdriver.common.action_chains import ActionChains

        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    logger.info("Post-login: Escape enviado; continúo al siguiente paso")
    time.sleep(0.3)


def hacer_login(driver, wait) -> None:
    """Autenticación + cierre rápido del modal post-login."""
    user, password = require_credentials()

    logger.info("Abriendo %s", LOGIN_URL)
    driver.get(LOGIN_URL)

    escribir_xpath(driver, wait, xpk(driver, "login.usuario"), user)
    escribir_xpath(driver, wait, xpk(driver, "login.password"), password)
    click_xpath(driver, wait, xpk(driver, "login.boton_iniciar"))

    # Espera por condición (antes: sleep fijo de 2 s): salir de login.php
    try:
        WebDriverWait(driver, 15).until(lambda d: "login.php" not in d.current_url)
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        # Login fallido: vaciar campos ANTES de cualquier screenshot (no filtrar usuario)
        driver.execute_script(
            "for (const id of ['username','password']) {"
            " const e = document.getElementById(id); if (e) e.value = ''; }"
        )
        logger.error("Login no salió de login.php (credenciales o portal).")
    logger.info("URL post-login: %s", driver.current_url)
    screenshot(driver, "post_login.png")

    cerrar_modales_post_login(driver, wait)


def hacer_logout(driver) -> None:
    """Cierra sesión en el portal (best-effort; no debe tumbar el flujo)."""
    logger.info("Cerrando sesión: %s", LOGOUT_URL)
    driver.get(LOGOUT_URL)
    try:
        WebDriverWait(driver, 10).until(
            lambda d: "login.php" in (d.current_url or "")
            or "logout" in (d.current_url or "")
        )
    except TimeoutException:
        logger.warning(
            "Logout: no se confirmó redirección (url=%s)",
            getattr(driver, "current_url", "?"),
        )
    logger.info("Sesión cerrada (url=%s)", getattr(driver, "current_url", "?"))


def navegar_a_cargar_plantillas(driver, wait) -> None:
    """Navegación desde home hasta el punto de derivación (Cargar plantillas)."""
    logger.info("Nav paso 1")
    click_xpath(driver, wait, xpk(driver, "nav.paso_1"))
    # sin sleep fijo: el resolver del paso siguiente espera su elemento
    screenshot(driver, "nav_paso_1.png")

    logger.info("Nav paso 2")
    click_xpath(driver, wait, xpk(driver, "nav.paso_2"))
    screenshot(driver, "nav_paso_2.png")

    logger.info("Entrar a Cargar plantillas")
    click_xpath(driver, wait, xpk(driver, "nav.cargar_plantillas"))
    time.sleep(1)
    screenshot(driver, "nav_cargar_plantillas.png")


def llegar_a_cargar_plantillas(driver, wait) -> None:
    """
    Camino general completo. Punto de rama para flujos específicos.

    Uso típico::

        llegar_a_cargar_plantillas(driver, wait)
        # aquí: flujo_liquidaciones(driver, wait)  o el que corresponda
    """
    hacer_login(driver, wait)
    navegar_a_cargar_plantillas(driver, wait)
    logger.info("En Cargar plantillas — listo para derivar a un flujo específico")
