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
CARGA_TIMEOUT = int(os.getenv("INGRESO_CARGA_TIMEOUT", "3600"))
# Estabilización del contador (mismo criterio que cmsd Documentos Agregados).
CARGA_ESTABLE_S = float(os.getenv("INGRESO_CARGA_ESTABLE_S", "15"))
CARGA_LOG_CADA_S = float(os.getenv("INGRESO_CARGA_LOG_CADA_S", "30"))


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


def _mensaje_carga_en_curso(body: str) -> bool:
    return bool(
        re.search(
            r"se\s+est[aá]\s+realizando\s+la\s+carga\s+masiva",
            body or "",
            flags=re.I,
        )
    )


def _carga_masiva_terminada(driver) -> bool:
    """
    True si hay señal de fin ('Trabajadores Agregados' o mensaje de fin) Y
    ya no está el aviso 'Se esta realizando la carga masiva'.
    No depende de pct==100: la barra del portal puede no llegar a 100% (bug).
    La estabilización del contador la hace esperar_carga_masiva.
    """
    try:
        body = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return False
    if _mensaje_carga_en_curso(body):
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
    esperado: int | None = None,
    estable_s: float | None = None,
) -> bool:
    """
    Espera fin real de 'Realizar Carga Masiva' (Trabajadores Agregados).
    No corta en la primera aparición del contador: exige que desaparezca el
    mensaje en curso y que el contador alcance `esperado` o se estabilice.
    """
    from espera_carga import (
        EstadoEsperaPostCarga,
        LecturaPostCarga,
        avanzar_espera_post_carga,
    )

    limite = float(timeout if timeout is not None else CARGA_TIMEOUT)
    est_s = float(CARGA_ESTABLE_S if estable_s is None else estable_s)
    log_s = float(CARGA_LOG_CADA_S)
    t0 = time.time()
    ultimo_log = 0.0
    estado = EstadoEsperaPostCarga()
    while time.time() - t0 < limite:
        _aceptar_alerta_si_hay(driver)
        try:
            body = driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            body = ""
        prog = _parse_progreso_carga(body)
        lectura = LecturaPostCarga(
            agregados=prog.get("agregados"),
            subidos=prog.get("total"),
            errores=0,
            en_curso=_mensaje_carga_en_curso(body),
            texto=body,
        )
        # Si no hay contador numérico pero ya hay mensaje de fin, simular
        # agregados=esperado (o 1) para poder estabilizar.
        if lectura.agregados is None and _carga_masiva_terminada(driver):
            lectura = LecturaPostCarga(
                agregados=esperado if esperado is not None else 1,
                en_curso=False,
                texto=body,
            )
        ahora = time.time()
        decision = avanzar_espera_post_carga(
            lectura, estado, ahora=ahora, esperado=esperado, estable_s=est_s
        )
        estado = decision.estado
        if ahora - ultimo_log >= log_s or decision.terminado:
            logger.info(
                "Carga masiva ingreso… agregados=%s esperado=%s en_curso=%s "
                "motivo=%s (%.0fs)",
                lectura.agregados,
                esperado,
                lectura.en_curso,
                decision.motivo,
                ahora - t0,
            )
            ultimo_log = ahora
        if decision.terminado:
            if decision.ok:
                screenshot(driver, "ingreso_carga_masiva_ok.png")
                logger.info("Carga masiva terminada (%.0fs).", ahora - t0)
                return True
            screenshot(driver, "ingreso_carga_masiva_incompleta.png")
            logger.error(
                "Carga masiva incompleta: agregados=%s < esperado=%s (%.0fs)",
                lectura.agregados,
                esperado,
                ahora - t0,
            )
            return False
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
