"""
Carga masiva: ingreso de trabajadores (Crear trabajadores → Subir plantilla).

Patrón:
  login → Carga Masiva → Crear trabajadores → Subir Plantilla
  → subir Excel → Validar → Realizar Carga Masiva → esperar fin.

Uso:
  python run_flujo.py ingreso_trabajadores
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from browser import (
    click_clave_si_existe,
    click_mutante,
    click_xpath,
    dry_run,
    enviar_archivos,
    screenshot,
    xpk,
)
from config import DOWNLOAD_DIR
from flows.llegar_a_plantillas import hacer_login
from xpaths import xpath_pendiente

logger = logging.getLogger(__name__)

NOMBRE = "Ingreso trabajadores (crear / subir plantilla)"

PASOS_NAV: list[str] = [
    "ingreso.crear_trabajadores",
    "ingreso.subir_plantilla",
]

# Segundos máximos esperando fin de "Realizar Carga Masiva"
CARGA_TIMEOUT = int(os.getenv("INGRESO_CARGA_TIMEOUT", "600"))


def _resolver_plantilla(path: Path | None = None) -> Path:
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(p)
        return p
    root = DOWNLOAD_DIR / "staging_trabajadores"
    candidatos = sorted(
        [
            p
            for p in root.glob("*/plantilla_ingreso_trabajadores*.xlsx")
            if not p.name.startswith("~$")
        ],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if not candidatos:
        raise FileNotFoundError(
            f"No hay plantilla_ingreso_trabajadores*.xlsx en {root}. "
            "Corré el pipeline o: python rellenar_plantilla_trabajadores.py"
        )
    return candidatos[0]


def _click_carga_masiva(driver, wait) -> None:
    logger.info("Nav Carga Masiva (nav.paso_1)")
    click_xpath(driver, wait, xpk(driver, "nav.paso_1"))
    time.sleep(1)
    screenshot(driver, "ingreso_carga_masiva.png")


def _navegar_pasos(driver, wait) -> str | None:
    for key in PASOS_NAV:
        if xpath_pendiente(key):
            logger.warning(
                "XPath pendiente: '%s'.\n"
                "  flujo: ingreso_trabajadores\n"
                "  paso: %s\n"
                "  xpath: /html/body/...",
                key,
                key,
            )
            screenshot(driver, f"pendiente_{key.replace('.', '_')}.png")
            return key
        logger.info("Click: %s", key)
        click_xpath(driver, wait, xpk(driver, key))
        time.sleep(1.2)
        screenshot(driver, f"{key.replace('.', '_')}.png")
    return None


def _validacion_ok(driver) -> bool:
    try:
        body = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return False
    b = body.lower()
    if "cantidad de errores encontrados: 0" in b:
        return True
    if "plantilla subida se encuentra correcta" in b:
        return True
    return False


def _aceptar_alerta_si_hay(driver) -> str | None:
    try:
        alert = driver.switch_to.alert
        texto = alert.text
        logger.warning("Alerta del portal: %s", texto)
        alert.accept()
        time.sleep(0.5)
        return texto
    except Exception:
        return None


def _parse_progreso_carga(body: str) -> dict[str, int | str | None]:
    """Extrae % y conteos de la pantalla 3.- CARGA MASIVA."""
    out: dict[str, int | str | None] = {
        "pct": None,
        "agregados": None,
        "total": None,
    }
    m = re.search(r"(\d+)\s*%", body)
    if m:
        out["pct"] = int(m.group(1))
    m = re.search(
        r"Trabajadores\s+Agregados\s*:?\s*(\d+)", body, flags=re.I
    )
    if m:
        out["agregados"] = int(m.group(1))
    m = re.search(r"\bTotal\s*:?\s*(\d+)", body, flags=re.I)
    if m:
        out["total"] = int(m.group(1))
    return out


def _carga_masiva_terminada(driver) -> bool:
    """
    Éxito = apareció 'Trabajadores Agregados' (o mensaje de fin).
    No depende de pct==100: la barra del portal puede no llegar a 100% (bug).
    """
    try:
        body = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return False
    b = body.lower()
    prog = _parse_progreso_carga(body)
    # Criterio principal (análogo a 'Documentos Agregados' en cmsd_*).
    if prog["agregados"] is not None:
        return True
    if re.search(r"trabajadores\s+agregados", b, flags=re.I):
        return True
    for frag in (
        "carga masiva finalizada",
        "carga finalizada",
        "proceso finalizado",
        "se realizó la carga",
        "se realizo la carga",
        "carga realizada con éxito",
        "carga realizada con exito",
    ):
        if frag in b:
            return True
    return False


def esperar_carga_masiva(
    driver,
    *,
    timeout: float | None = None,
) -> bool:
    """Espera 'Trabajadores Agregados' / mensaje de fin tras Realizar Carga Masiva."""
    limite = float(timeout if timeout is not None else CARGA_TIMEOUT)
    t0 = time.time()
    ultimo_log = 0.0
    while time.time() - t0 < limite:
        _aceptar_alerta_si_hay(driver)
        if _carga_masiva_terminada(driver):
            screenshot(driver, "ingreso_carga_masiva_ok.png")
            logger.info("Carga masiva terminada (%.0fs).", time.time() - t0)
            return True
        if time.time() - ultimo_log >= 15:
            try:
                body = driver.find_element(By.TAG_NAME, "body").text or ""
                prog = _parse_progreso_carga(body)
                logger.info(
                    "Carga masiva en curso… pct=%s agregados=%s total=%s (%.0fs)",
                    prog["pct"],
                    prog["agregados"],
                    prog["total"],
                    time.time() - t0,
                )
            except Exception:
                logger.info("Carga masiva en curso… (%.0fs)", time.time() - t0)
            ultimo_log = time.time()
        time.sleep(2)
    screenshot(driver, "ingreso_carga_masiva_timeout.png")
    logger.warning("Timeout esperando fin de carga masiva (%.0fs).", limite)
    return False


def ejecutar(
    driver,
    wait,
    *,
    plantilla: Path | None = None,
    pausa_exploracion: float = 180,
    ya_logueado: bool = False,
) -> Path | None:
    """
    Login → Crear trabajadores → Subir → Validar → Realizar Carga Masiva.

    Returns:
        Path del Excel subido, o None si faltan XPaths (exploración).
    Raises:
        RuntimeError: validación con errores.
        TimeoutError: no apareció fin de carga masiva a tiempo.
    """
    excel = _resolver_plantilla(plantilla)
    logger.info("Plantilla a cargar: %s", excel)

    if not ya_logueado:
        hacer_login(driver, wait)
        screenshot(driver, "ingreso_post_login.png")
        _click_carga_masiva(driver, wait)
    else:
        # Pipeline reusa sesión: volver a hub Cargas Masivas
        if click_clave_si_existe(driver, wait, "nav.paso_1", timeout=3):
            time.sleep(1)

    pendiente = _navegar_pasos(driver, wait)
    if pendiente is not None:
        logger.info(
            "Navegador abierto ~%.0fs para capturar '%s'.",
            pausa_exploracion,
            pendiente,
        )
        time.sleep(pausa_exploracion)
        return None

    if xpath_pendiente("ingreso.input_excel"):
        logger.warning("XPath pendiente: 'ingreso.input_excel'.")
        screenshot(driver, "pendiente_ingreso_input_excel.png")
        time.sleep(pausa_exploracion)
        return None

    logger.info("Subiendo Excel a la zona de carga…")
    enviar_archivos(driver, wait, "ingreso.input_excel", [excel])
    time.sleep(1.5)
    _aceptar_alerta_si_hay(driver)
    screenshot(driver, "ingreso_excel_cargado.png")

    if xpath_pendiente("ingreso.btn_enviar"):
        logger.warning("XPath pendiente: 'ingreso.btn_enviar'.")
        screenshot(driver, "pendiente_ingreso_btn_enviar.png")
        time.sleep(pausa_exploracion)
        return None

    logger.info("Validar Plantilla")
    click_mutante(
        driver, wait, "ingreso.btn_enviar",
        "click 'Validar Plantilla' (envía el Excel al portal)",
    )
    if dry_run():
        # Sin Excel ni validación real: verificar el botón final y terminar.
        click_mutante(
            driver, wait, "ingreso.btn_realizar_carga_masiva",
            "click 'Realizar Carga Masiva' (crea trabajadores/contratos)",
        )
        logger.warning(
            "[DRY_RUN] se omitiría: esperar fin de carga masiva. "
            "No se cargó nada al portal. excel=%s", excel,
        )
        screenshot(driver, "ingreso_dry_run_fin.png")
        return excel
    time.sleep(3)
    _aceptar_alerta_si_hay(driver)
    screenshot(driver, "ingreso_despues_enviar.png")

    if not _validacion_ok(driver):
        screenshot(driver, "ingreso_validacion_con_errores.png")
        raise RuntimeError(
            "Validación con errores (no se dispara Carga Masiva). "
            "Revisá debug/ingreso_despues_enviar.png"
        )

    logger.info("Validación OK (0 errores). Realizar Carga Masiva…")
    btn_key = "ingreso.btn_realizar_carga_masiva"
    if xpath_pendiente(btn_key):
        logger.warning("XPath pendiente: '%s'", btn_key)
        screenshot(driver, "pendiente_ingreso_btn_carga_masiva.png")
        time.sleep(pausa_exploracion)
        return None

    WebDriverWait(driver, 60).until(
        EC.element_to_be_clickable(
            (By.XPATH, xpk(driver, btn_key, timeout=60))
        )
    )
    click_mutante(
        driver, wait, btn_key,
        "click 'Realizar Carga Masiva' (crea trabajadores/contratos)",
    )
    time.sleep(2)
    _aceptar_alerta_si_hay(driver)
    screenshot(driver, "ingreso_despues_carga_masiva.png")

    ok = esperar_carga_masiva(driver)
    if not ok:
        raise TimeoutError(
            "Carga masiva no confirmó fin a tiempo "
            "(no apareció 'Trabajadores Agregados' ni mensaje de fin)."
        )
    logger.info("Carga masiva OK. excel=%s", excel)
    return excel
