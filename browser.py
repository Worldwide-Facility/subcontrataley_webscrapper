"""Utilidades mínimas de Selenium para ir armando el scraper paso a paso."""

from __future__ import annotations

import logging
import os
import re
import sys
import time
import unicodedata
from calendar import month_name
from datetime import date
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import (
    InvalidSelectorException,
    StaleElementReferenceException,
    TimeoutException,
)

import config as _config
from config import (
    CHROME_BIN,
    CHROMEDRIVER_PATH,
    DEBUG_DIR,
    DOWNLOAD_DIR,
    EXPLICIT_WAIT,
    HEADLESS,
    IMPLICIT_WAIT,
    IS_CLOUD_RUN,
)

logger = logging.getLogger(__name__)

# remote_connection en DEBUG vuelca el payload de cada comando (incluye el texto
# de send_keys = credenciales). Nunca dejarlo bajar de INFO.
for _ruidoso in ("selenium.webdriver.remote.remote_connection", "urllib3.connectionpool"):
    logging.getLogger(_ruidoso).setLevel(max(logging.INFO, logging.getLogger(_ruidoso).level))

IS_WINDOWS = sys.platform == "win32"

MESES_ES = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def mes_anterior(referencia: date | None = None) -> date:
    ref = referencia or date.today()
    if ref.month == 1:
        return date(ref.year - 1, 12, 1)
    return date(ref.year, ref.month - 1, 1)


def _chrome_bin() -> str | None:
    if CHROME_BIN and Path(CHROME_BIN).exists():
        return CHROME_BIN
    if IS_WINDOWS:
        for p in (
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
            ),
        ):
            if p and Path(p).exists():
                return p
        return None
    for p in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"):
        if Path(p).exists():
            return p
    return None


def _chromedriver_path() -> str | None:
    if CHROMEDRIVER_PATH and Path(CHROMEDRIVER_PATH).exists():
        return CHROMEDRIVER_PATH
    linux_sys = Path("/usr/local/bin/chromedriver")
    if not IS_WINDOWS and linux_sys.exists() and os.access(linux_sys, os.X_OK):
        return str(linux_sys)
    return None


def iniciar_navegador(
    headless: bool | None = None,
    download_dir: Path | None = None,
) -> tuple[webdriver.Chrome, WebDriverWait]:
    options = Options()
    use_headless = HEADLESS if headless is None else headless
    if use_headless or IS_CLOUD_RUN:
        options.add_argument("--headless=new")
        options.add_argument("--remote-debugging-port=9222")

    # Obligatorias en Cloud Run / contenedor
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if IS_CLOUD_RUN or use_headless:
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")

    chrome_bin = _chrome_bin()
    if chrome_bin:
        options.binary_location = chrome_bin
        logger.info("Chrome binary: %s", chrome_bin)

    dest = Path(download_dir or DOWNLOAD_DIR).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(dest),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "plugins.always_open_pdf_externally": True,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        },
    )
    options.add_argument("--disable-save-password-bubble")
    options.add_argument(
        "--disable-features=PasswordManagerOnboarding,PasswordCheck,PasswordManager"
    )

    driver_path = _chromedriver_path()
    if driver_path:
        logger.info("ChromeDriver: %s", driver_path)
        service = Service(driver_path)
    else:
        logger.info("ChromeDriver: webdriver-manager")
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(IMPLICIT_WAIT)
    wait = WebDriverWait(driver, EXPLICIT_WAIT)
    logger.info(
        "Navegador iniciado headless=%s cloud=%s descargas=%s",
        use_headless or IS_CLOUD_RUN,
        IS_CLOUD_RUN,
        dest,
    )
    return driver, wait


def _es_visible(el) -> bool:
    try:
        return el.is_displayed()
    except StaleElementReferenceException:
        return False


def resolver_selector(
    driver,
    key: str,
    *,
    timeout: float | None = None,
    visible: bool = True,
    obligatorio: bool = True,
):
    """
    Resuelve una clave de xpaths.py probando sus candidatos EN ORDEN.

    Gana el primer candidato con exactamente 1 match (visible si visible=True).
    Candidatos con 0 o >1 matches se saltan (ambigüedad = no confiable).
    Reintenta hasta `timeout` (actúa como espera por condición).

    Returns:
        (elemento, xpath_resuelto). xpath_resuelto identifica ese único nodo
        (si el candidato tenía nodos ocultos extra se indexa: "(xp)[n]"),
        así sirve para los helpers existentes que reciben XPath.
        Con obligatorio=False devuelve (None, None) si no resolvió.
    """
    from xpaths import candidatos

    cands = candidatos(key)
    limite = EXPLICIT_WAIT if timeout is None else timeout
    deadline = time.time() + limite
    driver.implicitly_wait(0)  # el implicit wait multiplicaría el tiempo por candidato
    diag: list[str] = []
    try:
        while True:
            diag = []
            for i, cand in enumerate(cands):
                try:
                    els = driver.find_elements(By.XPATH, cand)
                except InvalidSelectorException:
                    diag.append(f"#{i}:xpath-invalido")
                    continue
                if visible:
                    sel = [(j, e) for j, e in enumerate(els) if _es_visible(e)]
                else:
                    sel = list(enumerate(els))
                diag.append(f"#{i}:{len(sel)}/{len(els)}")
                if len(sel) != 1:
                    continue
                j, el = sel[0]
                xp_final = cand if len(els) == 1 else f"({cand})[{j + 1}]"
                if i > 0:
                    # Carrera: el DOM pudo insertarse entre consultas. Re-probar
                    # los candidatos previos antes de declarar drift.
                    for i2, c2 in enumerate(cands[:i]):
                        try:
                            e2 = driver.find_elements(By.XPATH, c2)
                        except InvalidSelectorException:
                            continue
                        s2 = [(j2, x) for j2, x in enumerate(e2) if (not visible or _es_visible(x))]
                        if len(s2) == 1 and s2[0][1] == el:
                            i, cand = i2, c2
                            xp_final = c2 if len(e2) == 1 else f"({c2})[{s2[0][0] + 1}]"
                            break
                if i == 0:
                    logger.debug("Selector '%s' → candidato #0", key)
                else:
                    logger.warning(
                        "Selector '%s': candidato #0 falló; usado respaldo #%s/%s "
                        "(%s). Revisar xpaths.py (drift del portal). diag=%s",
                        key, i, len(cands) - 1, cand, " ".join(diag),
                    )
                return el, xp_final
            if time.time() >= deadline:
                break
            time.sleep(0.25)
    finally:
        driver.implicitly_wait(IMPLICIT_WAIT)

    msg = (
        f"Selector '{key}' sin match único tras {limite:.0f}s "
        f"(visible={visible}). matches visibles/total por candidato: {' '.join(diag)}"
    )
    if obligatorio:
        raise TimeoutException(msg)
    logger.info(msg)
    return None, None


def xpk(driver, key: str, **kwargs) -> str:
    """XPath resuelto (único) de una clave; drop-in para helpers que reciben XPath."""
    return resolver_selector(driver, key, **kwargs)[1]


def click_clave(driver, wait: WebDriverWait, key: str, **kwargs) -> None:
    """Resuelve la clave (espera hasta match único visible) y hace click."""
    click_xpath(driver, wait, xpk(driver, key, **kwargs))


def click_clave_si_existe(
    driver, wait: WebDriverWait, key: str, timeout: float = 5
) -> bool:
    """Como click_si_existe, pero resolviendo candidatos de la clave."""
    _, xp_res = resolver_selector(driver, key, timeout=timeout, obligatorio=False)
    if not xp_res:
        return False
    return click_si_existe(driver, wait, xp_res, timeout=max(timeout, 1))


# ---------------------------------------------------------------------------
# DRY_RUN: guardas centrales para acciones que cargan/modifican datos en el portal
# ---------------------------------------------------------------------------
def dry_run() -> bool:
    """Lee config.DRY_RUN en tiempo de ejecución (default false = producción)."""
    return bool(getattr(_config, "DRY_RUN", False))


def _estado_elemento(driver, el) -> str:
    try:
        vis = el.is_displayed()
        hab = el.is_enabled() and el.get_attribute("disabled") is None
        return f"presente, {'visible' if vis else 'oculto'}, {'habilitado' if hab else 'deshabilitado'}"
    except StaleElementReferenceException:
        return "presente (stale)"


def _dry_run_destino_archivos(driver, xpath: str, paths: list[Path]) -> None:
    """Verifica que el destino (input file / dropzone) exista, SIN enviar nada."""
    estado = "no presente"
    try:
        driver.implicitly_wait(0)
        els = driver.find_elements(By.XPATH, xpath)
        if els:
            estado = _estado_elemento(driver, els[0])
            if not (els[0].tag_name.lower() == "input"
                    and (els[0].get_attribute("type") or "").lower() == "file"):
                tiene = driver.execute_script(
                    "const r=(arguments[0].closest&&arguments[0].closest('.dropzone'))||arguments[0];"
                    "return !!(r.dropzone&&r.dropzone.hiddenFileInput) || "
                    "!!r.querySelector('input[type=file]');",
                    els[0],
                )
                estado += f", input file asociado={'sí' if tiene else 'no'}"
    except Exception as exc:  # solo diagnóstico
        estado = f"no verificable ({type(exc).__name__})"
    finally:
        driver.implicitly_wait(IMPLICIT_WAIT)
    nombres = ", ".join(p.name for p in paths[:5]) + (" …" if len(paths) > 5 else "")
    logger.warning(
        "[DRY_RUN] se omitiría: enviar %s archivo(s) [%s] a %s (destino: %s)",
        len(paths), nombres, xpath, estado,
    )


def enviar_archivos(
    driver,
    wait: WebDriverWait,
    key: str,
    rutas: list[Path],
    *,
    multiples: bool = False,
    **kwargs,
) -> bool:
    """
    Envía archivos al input/dropzone de `key` (resuelto con fallbacks).
    DRY_RUN: verifica el destino y NO envía nada. Devuelve True si envió.
    """
    paths = [Path(p).resolve() for p in rutas]
    if dry_run():
        el, xp_res = resolver_selector(
            driver, key, visible=False, timeout=5, obligatorio=False
        )
        if el is None:
            logger.warning(
                "[DRY_RUN] se omitiría: enviar %s archivo(s) a '%s' (destino ausente: "
                "aparece solo tras un paso de carga omitido)", len(paths), key,
            )
            return False
        _dry_run_destino_archivos(driver, xp_res, paths)
        return False
    xp_res = xpk(driver, key, visible=False)
    if multiples:
        subir_archivos(driver, wait, xp_res, paths, **kwargs)
    else:
        for p in paths:
            subir_archivo(driver, wait, xp_res, p)
    return True


def click_mutante(
    driver,
    wait: WebDriverWait,
    key: str,
    accion: str,
    *,
    timeout: float | None = None,
    timeout_verificacion: float = 5,
) -> bool:
    """
    Click en un botón que carga/valida/confirma datos en el portal.
    DRY_RUN: verifica presencia/estado (resolver) y NO hace click. Devuelve True si clickeó.
    """
    if dry_run():
        el, _ = resolver_selector(
            driver, key, timeout=timeout_verificacion, obligatorio=False
        )
        if el is None:
            el_any, _ = resolver_selector(
                driver, key, visible=False, timeout=0, obligatorio=False
            )
            estado = (
                f"existe pero {_estado_elemento(driver, el_any)}" if el_any is not None
                else "ausente (aparece solo tras un paso de carga omitido)"
            )
        else:
            estado = _estado_elemento(driver, el)
        logger.warning("[DRY_RUN] se omitiría: %s ('%s'; %s)", accion, key, estado)
        return False
    click_xpath(driver, wait, xpk(driver, key, timeout=timeout))
    return True


def escribir_xpath(driver, wait: WebDriverWait, xpath: str, texto: str) -> None:
    """Escribe en un input. Nunca loguea `texto` (puede ser credencial)."""
    el = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
    el.clear()
    el.send_keys(texto)


def click_xpath(driver, wait: WebDriverWait, xpath: str) -> None:
    el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", el
        )
        time.sleep(0.3)
        el.click()
    except Exception:
        # Overlay / chat / footer interceptando el click nativo
        logger.warning("Click nativo interceptado; reintento con JS: %s", xpath)
        driver.execute_script("arguments[0].click();", el)


def disparar_change(driver, el) -> None:
    """Dispara change/input para que la UI habilite botones dependientes."""
    driver.execute_script(
        """
        const el = arguments[0];
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        if (window.jQuery) { jQuery(el).trigger('change'); }
        """,
        el,
    )


def click_si_existe(driver, wait: WebDriverWait, xpath: str, timeout: float = 5) -> bool:
    """Click si el elemento aparece; no falla si no está. Respeta timeout corto."""
    try:
        # Evitar que el implicit wait (10s) alargue un timeout de 1s
        driver.implicitly_wait(0)
        corto = WebDriverWait(driver, timeout)
        el = corto.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        el.click()
        logger.info("Click OK: %s", xpath)
        return True
    except Exception:
        return False
    finally:
        driver.implicitly_wait(IMPLICIT_WAIT)


def _resolver_input_archivo(driver, wait: WebDriverWait, xpath: str):
    """Devuelve un input[type=file]: el nodo, hijo, Dropzone.hiddenFileInput o hermano."""
    el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    tag = (el.tag_name or "").lower()
    tipo = (el.get_attribute("type") or "").lower()
    if tag == "input" and tipo == "file":
        return el

    # Dropzone.js: el input real es .dz-hidden-input (a menudo fuera del árbol UI)
    try:
        dz_inp = driver.execute_script(
            """
            const el = arguments[0];
            if (!el) return null;
            let root = el;
            if (el.classList && el.classList.contains('dz-message')) {
                root = el.parentElement || el;
            }
            root = (root.closest && root.closest('.dropzone')) || root;
            if (root && root.dropzone && root.dropzone.hiddenFileInput) {
                return root.dropzone.hiddenFileInput;
            }
            // Fallback: último dz-hidden-input multiple (el dropzone de docs suele ser el 2º)
            const all = Array.from(document.querySelectorAll('input.dz-hidden-input'));
            const multi = all.filter(i => i.multiple);
            if (multi.length) return multi[multi.length - 1];
            return all.length ? all[all.length - 1] : null;
            """,
            el,
        )
        if dz_inp is not None:
            logger.info("Input Dropzone resuelto desde zona %s", xpath)
            return dz_inp
    except Exception as exc:
        logger.debug("Dropzone resolve falló: %s", exc)

    internos = el.find_elements(By.XPATH, ".//input[@type='file']")
    if internos:
        return internos[0]
    # A veces el input está como hermano cercano
    hermanos = driver.find_elements(
        By.XPATH, xpath + "/following::input[@type='file'][1]"
    )
    if hermanos:
        return hermanos[0]
    raise ValueError(f"No hay input[type=file] en ni bajo: {xpath}")


def esperar_zona_documentos_habilitada(
    driver,
    zona_xpath: str,
    *,
    timeout: float = 120,
    estable_s: float = 3.0,
) -> None:
    """
    Tras 'Cargar Excel', espera a que la zona de documentos acepte PDFs.
    Considera dropzone.hiddenFileInput y ausencia del bloqueo 'SUBA SU PLANTILLA…'.
    """
    if dry_run():
        logger.warning(
            "[DRY_RUN] se omitiría: esperar habilitación de la zona de documentos "
            "(solo ocurre tras 'Cargar Excel', que no se ejecutó)"
        )
        return
    t0 = time.time()
    last_log = 0.0
    estable_desde: float | None = None
    while time.time() - t0 < timeout:
        ok = driver.execute_script(
            """
            const xpath = arguments[0];
            const zona = document.evaluate(
                xpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
            if (!zona) return false;
            const root = (zona.closest && zona.closest('.dropzone')) || zona;
            // Zona realmente lista: visible, sin bloqueo, sin overlay de carga,
            // con instancia Dropzone propia (no el fallback global) y habilitada.
            if (root.offsetParent === null) return false;
            const txt = ((root.innerText || root.textContent || '') + '').toUpperCase();
            if (txt.includes('SUBA SU PLANTILLA ANTES')) return false;
            if (root.classList.contains('dz-disabled')
                || root.getAttribute('aria-disabled') === 'true') return false;
            const busy = Array.from(document.querySelectorAll(
                '.blockUI.blockOverlay, .swal2-loading'
            )).some(e => e.offsetParent !== null);
            if (busy) return false;
            const dz = root.dropzone;
            return !!(dz && dz.hiddenFileInput && !dz.hiddenFileInput.disabled
                      && document.body.contains(dz.hiddenFileInput)
                      && !(dz.getActiveFiles && dz.getActiveFiles().length));
            """,
            zona_xpath,
        )
        if ok:
            # Debe mantenerse lista de forma estable (el portal re-renderiza la
            # zona tras procesar el Excel; enviar antes pierde los primeros PDFs).
            if estable_desde is None:
                estable_desde = time.time()
            elif time.time() - estable_desde >= estable_s:
                logger.info("Zona de documentos habilitada y estable (%.0fs)", time.time() - t0)
                return
        else:
            estable_desde = None
        now = time.time()
        if now - last_log >= 5:
            logger.info(
                "Esperando habilitación de zona docs tras Cargar Excel… (%.0fs)",
                now - t0,
            )
            last_log = now
        time.sleep(0.5)
    raise TimeoutError(
        f"Timeout {timeout:.0f}s: zona de documentos no se habilitó tras Cargar Excel"
    )


def subir_archivo(driver, wait: WebDriverWait, xpath: str, ruta: Path) -> None:
    """Envía un archivo a un input file (o zona con input oculto)."""
    path = Path(ruta).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if dry_run():
        _dry_run_destino_archivos(driver, xpath, [path])
        return
    inp = _resolver_input_archivo(driver, wait, xpath)
    inp.send_keys(str(path))
    logger.info("Archivo enviado: %s", path.name)


def _estado_zona_upload(driver, zona_xpath: str) -> dict:
    """
    Inspecciona la zona de documentos (Dropzone Subcontrataley / template cards).
    Cuenta .card con dz-* o filas .pdf en el texto (no solo .dz-preview clásico).
    """
    return driver.execute_script(
        """
        const xpath = arguments[0];
        const zona = document.evaluate(
            xpath, document, null,
            XPathResult.FIRST_ORDERED_NODE_TYPE, null
        ).singleNodeValue;
        if (!zona) return {items: 0, processing: 0, progress: 0, ready: false};

        const root = (zona.closest && zona.closest('.dropzone')) || zona;

        // UI Subcontrataley: cada archivo es .card con clases dz-*
        let cards = root.querySelectorAll(
            '.card.dz-success, .card.dz-complete, .card.dz-processing, .card.dz-error'
        );
        if (!cards.length) {
            cards = root.querySelectorAll('.dz-preview, .dz-file-preview');
        }
        if (!cards.length) {
            cards = root.querySelectorAll('.card.mt-1');
        }
        let items = cards.length;
        if (!items) {
            const texts = (root.innerText || '').split(/\\n+/).filter(t => /\\.pdf/i.test(t));
            items = texts.length;
        }

        const processing = root.querySelectorAll(
            '.dz-processing:not(.dz-success):not(.dz-complete), .dz-uploading, .uploading'
        ).length;

        let progress = 0;
        root.querySelectorAll('.progress-bar, .dz-upload, progress').forEach(el => {
            const styleW = (el.style && el.style.width) ? parseFloat(el.style.width) : NaN;
            const w = !isNaN(styleW) ? styleW : parseFloat(el.getAttribute('aria-valuenow') || 'NaN');
            if (!isNaN(w) && w < 99.5) progress += 1;
            else if (isNaN(w) && el.offsetParent !== null && el.classList.contains('progress-bar')) {
                // barra sin ancho numérico: no asumir incompleto si ya hay success
            }
        });

        const errors = root.querySelectorAll('.dz-error, .qq-upload-fail').length;
        const complete = root.querySelectorAll(
            '.card.dz-success, .card.dz-complete, .dz-success, .dz-complete'
        ).length;

        return {
            items: items,
            processing: processing,
            progress: progress,
            complete: complete,
            errors: errors,
            ready: progress === 0 && items > 0,
        };
        """,
        zona_xpath,
    )


def esperar_uploads_completos(
    driver,
    zona_xpath: str,
    *,
    n_min: int | None = None,
    timeout: float = 600,
    estable_s: float = 3.0,
) -> dict:
    """
    Espera a que terminen las subidas en la zona (sin barras de progreso activas).
    Si n_min, también exige al menos esa cantidad de items en la UI.
    """
    t0 = time.time()
    last_log = 0.0
    estable_desde: float | None = None
    ultimo: dict = {}

    while time.time() - t0 < timeout:
        ultimo = _estado_zona_upload(driver, zona_xpath) or {}
        items = int(ultimo.get("items") or 0)
        progress = int(ultimo.get("progress") or 0)
        complete = int(ultimo.get("complete") or 0)
        ok_n = n_min is None or items >= n_min
        # Completo si no hay progreso y conteo OK; refuerzo si Dropzone marca success.
        ready = ok_n and progress == 0 and (complete >= (n_min or 0) or complete == 0 or complete >= items * 0.9)

        if ready:
            if estable_desde is None:
                estable_desde = time.time()
            elif time.time() - estable_desde >= estable_s:
                logger.info(
                    "Uploads OK zona=%s items=%s complete=%s (%.0fs)",
                    zona_xpath,
                    items,
                    ultimo.get("complete"),
                    time.time() - t0,
                )
                return ultimo
        else:
            estable_desde = None

        now = time.time()
        if now - last_log >= 5:
            logger.info(
                "Esperando uploads… items=%s processing=%s progress=%s complete=%s n_min=%s (%.0fs)",
                items,
                ultimo.get("processing"),
                progress,
                complete,
                n_min,
                now - t0,
            )
            last_log = now
        time.sleep(0.5)

    raise TimeoutError(
        f"Timeout {timeout:.0f}s esperando uploads en {zona_xpath}. "
        f"Último estado={ultimo}"
    )


def subir_archivos(
    driver,
    wait: WebDriverWait,
    xpath: str,
    rutas: list[Path],
    *,
    esperar: bool = True,
    timeout: float = 600,
    uno_a_uno: bool = True,
) -> None:
    """
    Envía archivos a un input file (o zona Dropzone).

    Por defecto sube de a uno: en Chrome/Windows un send_keys multi con
    rutas con espacios a menudo no inserta ningún archivo.
    """
    paths = [Path(p).resolve() for p in rutas]
    faltan = [str(p) for p in paths if not p.exists()]
    if faltan:
        raise FileNotFoundError(f"No existen: {faltan[:5]}")
    if not paths:
        logger.warning("sin archivos para subir en %s", xpath)
        return
    if dry_run():
        _dry_run_destino_archivos(driver, xpath, paths)
        return

    base = int((_estado_zona_upload(driver, xpath) or {}).get("items") or 0)

    if uno_a_uno:
        for i, path in enumerate(paths, start=1):
            # Re-resolve cada vez: Dropzone a veces recrea el hidden input
            inp = _resolver_input_archivo(driver, wait, xpath)
            try:
                driver.execute_script(
                    "arguments[0].style.display='block';"
                    "arguments[0].removeAttribute('hidden');",
                    inp,
                )
            except Exception:
                pass
            inp.send_keys(str(path))
            logger.info("PDF %s/%s enviado: %s", i, len(paths), path.name)
            if not esperar:
                continue
            objetivo = base + i
            t0 = time.time()
            ok = False
            while time.time() - t0 < min(120.0, max(60.0, timeout)):
                st = _estado_zona_upload(driver, xpath) or {}
                items = int(st.get("items") or 0)
                # Nombre visible en la zona (más fiable que solo el contador)
                visible = driver.execute_script(
                    """
                    const xp = arguments[0], name = arguments[1];
                    const el = document.evaluate(
                        xp, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    ).singleNodeValue;
                    const root = (el && el.closest)
                        ? (el.closest('.dropzone') || el) : el;
                    return !!(root && (root.innerText || '').includes(name));
                    """,
                    xpath,
                    path.name,
                )
                if visible and items >= objetivo:
                    ok = True
                    break
                if visible and items >= i:  # tolerar base distinto
                    ok = True
                    break
                time.sleep(0.35)
            if not ok:
                logger.warning(
                    "PDF %s no confirmado a tiempo (objetivo items=%s)",
                    path.name,
                    objetivo,
                )
            else:
                # estabilizar barras un momento
                time.sleep(0.4)
        # Espera final global sin progreso
        if esperar:
            esperar_uploads_completos(
                driver,
                xpath,
                n_min=len(paths),
                timeout=min(120.0, timeout),
                estable_s=2.0,
            )
        logger.info(
            "Enviados %s archivo(s) uno-a-uno (base=%s) a %s",
            len(paths),
            base,
            xpath,
        )
        return

    # Fallback multi (puede fallar con espacios en el nombre)
    inp = _resolver_input_archivo(driver, wait, xpath)
    inp.send_keys("\n".join(str(p) for p in paths))
    logger.info("Enviados %s archivo(s) multi a %s", len(paths), xpath)
    if esperar:
        esperar_uploads_completos(
            driver, xpath, n_min=base + len(paths), timeout=timeout
        )


# ---------------------------------------------------------------------------
# Verificación de archivos en Dropzone (reutilizable por todos los flujos)
# ---------------------------------------------------------------------------

JS_DZ_ARCHIVOS = """
const xpath = arguments[0];
const zona = document.evaluate(
    xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
).singleNodeValue;
if (!zona) return {found: false, files: []};
const root = (zona.closest && zona.closest('.dropzone')) || zona;
const out = [];
const vistos = new Set();
root.querySelectorAll('.dz-preview, .card.dz-success, .card.dz-complete, .card.dz-processing, .card.dz-error')
  .forEach(p => {
    if (vistos.has(p)) return;
    vistos.add(p);
    const n = p.querySelector('[data-dz-name]') || p.querySelector('.dz-filename span')
           || p.querySelector('.dz-filename');
    const name = n ? (n.textContent || '').trim() : '';
    if (!name) return;
    const em = p.querySelector('[data-dz-errormessage], .dz-error-message');
    const errmsg = em ? (em.textContent || '').trim() : '';
    const cl = p.classList;
    out.push({
      name: name,
      error: cl.contains('dz-error'),
      success: cl.contains('dz-success') || cl.contains('dz-complete'),
      processing: cl.contains('dz-processing') && !cl.contains('dz-success')
                  && !cl.contains('dz-complete') && !cl.contains('dz-error'),
      errmsg: errmsg.slice(0, 200),
    });
  });
// Estado interno de Dropzone.js (si existe) como complemento
const dz = root.dropzone;
const internos = (dz && dz.files) ? dz.files.map(f => ({name: f.name, status: f.status})) : null;
return {found: true, files: out, dz_files: internos};
"""


def nombres_archivo_plantilla(
    xlsx: Path, *, hoja: str | None = None, columna: str = "nombre_de_archivo"
) -> list[str]:
    """Lee los nombres (únicos, en orden) de la columna `nombre_de_archivo`."""
    from openpyxl import load_workbook

    wb = load_workbook(xlsx, read_only=True, data_only=True)
    try:
        if hoja is None:
            from flows.plantilla_schema import HOJA_DOCUMENTOS

            hoja = HOJA_DOCUMENTOS if HOJA_DOCUMENTOS in wb.sheetnames else wb.sheetnames[0]
        ws = wb[hoja]
        filas = ws.iter_rows(values_only=True)
        cab = [str(c).strip().lower() if c is not None else "" for c in next(filas, [])]
        if columna.lower() not in cab:
            raise KeyError(f"No existe columna '{columna}' en hoja '{hoja}' de {xlsx}")
        idx = cab.index(columna.lower())
        out: list[str] = []
        for fila in filas:
            v = fila[idx] if idx < len(fila) else None
            if v is None or str(v).strip() == "":
                continue
            s = str(v).strip()
            if s not in out:
                out.append(s)
        return out
    finally:
        wb.close()


def comparar_archivos_dropzone(esperados: list[str], visibles: list[dict]) -> dict:
    """
    Lógica pura (testeable offline). Coincidencia EXACTA de nombre.
    visibles: [{name, error, success, processing}].
    Un archivo cuenta como OK si al menos una preview con ese nombre no tiene error.
    """
    ok_names = {v["name"] for v in visibles if not v.get("error")}
    err_names = {v["name"] for v in visibles if v.get("error")}
    proc_names = {v["name"] for v in visibles if v.get("processing")}
    esperados_u = list(dict.fromkeys(esperados))
    faltan = [n for n in esperados_u if n not in ok_names and n not in err_names]
    con_error = [n for n in esperados_u if n in err_names and n not in ok_names]
    procesando = [n for n in esperados_u if n in proc_names]
    extra = sorted({v["name"] for v in visibles} - set(esperados_u))
    return {
        "esperados": len(esperados_u),
        "visibles": len({v["name"] for v in visibles}),
        "faltan": faltan,
        "con_error": con_error,
        "procesando": procesando,
        "extra": extra,
        "ok": not faltan and not con_error,
    }


def leer_archivos_dropzone(driver, zona_xpath: str) -> list[dict]:
    r = driver.execute_script(JS_DZ_ARCHIVOS, zona_xpath) or {}
    return list(r.get("files") or [])


def _quitar_previews_con_error(driver, zona_xpath: str, nombres: list[str]) -> None:
    """Quita del Dropzone los archivos marcados con error (para re-subirlos limpio)."""
    if not nombres:
        return
    driver.execute_script(
        """
        const zona = document.evaluate(arguments[0], document, null,
            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        if (!zona) return;
        const root = (zona.closest && zona.closest('.dropzone')) || zona;
        const nombres = new Set(arguments[1]);
        const dz = root.dropzone;
        if (dz && dz.files) {
            dz.files.filter(f => nombres.has(f.name) && f.status === 'error')
                .forEach(f => dz.removeFile(f));
        }
        """,
        zona_xpath,
        nombres,
    )


def verificar_archivos_dropzone(
    driver,
    wait: WebDriverWait,
    zona_xpath: str,
    esperados: list[str],
    rutas: list[Path],
    *,
    reintentos: int = 3,
    timeout_upload: float = 300,
    etiqueta: str = "dropzone",
) -> dict:
    """
    Compara los nombres visibles en el Dropzone con `esperados` (exacto).
    Re-sube faltantes / con error hasta `reintentos` veces. Si persisten,
    screenshot + RuntimeError listándolos.
    """
    if dry_run():
        logger.warning("[DRY_RUN] se omitiría: verificar archivos en %s", etiqueta)
        return {"ok": True, "dry_run": True}
    por_nombre = {Path(p).name: Path(p) for p in rutas}
    sin_ruta = [n for n in esperados if n not in por_nombre]
    if sin_ruta:
        logger.warning("[%s] Nombres de la plantilla sin PDF local: %s", etiqueta, sin_ruta)

    def _esperar_sin_procesar(limite: float) -> list[dict]:
        t0 = time.time()
        vis = leer_archivos_dropzone(driver, zona_xpath)
        while time.time() - t0 < limite:
            if not any(v.get("processing") for v in vis):
                break
            time.sleep(1)
            vis = leer_archivos_dropzone(driver, zona_xpath)
        return vis

    res: dict = {}
    for intento in range(0, reintentos + 1):
        vis = _esperar_sin_procesar(timeout_upload)
        res = comparar_archivos_dropzone(esperados, vis)
        logger.info(
            "[%s] Verificación dropzone (intento %s/%s): esperados=%s visibles=%s "
            "faltan=%s con_error=%s extra=%s",
            etiqueta, intento, reintentos, res["esperados"], res["visibles"],
            len(res["faltan"]), len(res["con_error"]), len(res["extra"]),
        )
        if res["ok"]:
            return res
        if res["faltan"]:
            logger.warning("[%s] Faltan en dropzone: %s", etiqueta, res["faltan"])
        if res["con_error"]:
            errs = {v["name"]: v.get("errmsg") for v in vis if v.get("error")}
            logger.warning(
                "[%s] Con error en dropzone: %s",
                etiqueta, {n: errs.get(n) for n in res["con_error"]},
            )
        if intento == reintentos:
            break
        resubir = [por_nombre[n] for n in res["faltan"] + res["con_error"] if n in por_nombre]
        if not resubir:
            break
        _quitar_previews_con_error(driver, zona_xpath, res["con_error"])
        logger.info("[%s] Re-subiendo %s archivo(s) (reintento %s)", etiqueta, len(resubir), intento + 1)
        subir_archivos(driver, wait, zona_xpath, resubir, esperar=False, uno_a_uno=True)
        time.sleep(2)

    shot = screenshot(driver, f"{etiqueta.replace(' ', '_')}_dropzone_incompleto.png")
    raise RuntimeError(
        f"[{etiqueta}] Archivos no presentes/OK en dropzone tras {reintentos} reintentos: "
        f"faltan={res.get('faltan')} con_error={res.get('con_error')} "
        f"(esperados={res.get('esperados')} visibles={res.get('visibles')}) screenshot={shot}"
    )


def cargar_documentos_dropzone(
    driver,
    wait: WebDriverWait,
    key: str,
    rutas: list[Path],
    *,
    plantilla: Path | None = None,
    columna: str = "nombre_de_archivo",
    etiqueta: str = "carga",
    timeout_zona: float = 180,
    timeout_upload: float = 900,
    reintentos: int = 3,
) -> None:
    """
    Paso compartido para TODOS los flujos con dropzone:
    1) espera la zona realmente lista (visible, Dropzone propio, estable);
    2) sube uno a uno esperando cada archivo;
    3) verifica nombres visibles vs `columna` de la plantilla (exacto),
       re-sube faltantes/error hasta `reintentos` y si no, error claro + screenshot.
    DRY_RUN: solo verifica el destino (no envía nada).
    """
    if not rutas:
        logger.warning("[%s] Sin archivos para %s", etiqueta, key)
        return
    if dry_run():
        enviar_archivos(driver, wait, key, rutas, multiples=True)
        return
    zona = xpk(driver, key, visible=False)
    esperar_zona_documentos_habilitada(driver, zona, timeout=timeout_zona)
    logger.info("[%s] Subiendo %s archivo(s) uno a uno → %s", etiqueta, len(rutas), zona)
    subir_archivos(driver, wait, zona, rutas, esperar=True, timeout=timeout_upload, uno_a_uno=True)
    if plantilla is not None:
        esperados = nombres_archivo_plantilla(Path(plantilla), columna=columna)
    else:
        esperados = [Path(p).name for p in rutas]
    verificar_archivos_dropzone(
        driver, wait, zona, esperados, rutas,
        reintentos=reintentos, timeout_upload=300, etiqueta=f"{etiqueta}:{columna}",
    )


JS_RESULTADO_VALIDACION = """
const b = document.getElementById('cmsd_btn_realizar_carga_masiva');
const vis = e => !!(e && e.offsetParent !== null);
const txt = (document.body.innerText || '');
let m = txt.match(/errores\\s+encontrados\\s*:\\s*(\\d+)/i)
     || txt.match(/(\\d+)\\s*errores\\s+encontrados/i);
if (m && parseInt(m[1], 10) > 0) return 'errores:' + m[1];
// innerText solo incluye texto visible: cualquier aparición = fallo inmediato.
const fm = txt.match(/[^\\n]*(planilla no v[a\u00e1]lida|subir plantilla nuevamente)[^\\n]*/i);
if (fm) return 'invalida:' + fm[0].trim().slice(0, 200);
if (vis(b) && !b.disabled) return 'ok';
const modal = document.querySelector('.modal.in, .modal.show, .swal2-popup, .bootbox');
if (modal && vis(modal) && /error|inv[a\u00e1]lid|no se pudo/i.test(modal.innerText || ''))
    return 'modal:' + (modal.innerText || '').trim().slice(0, 200);
return null;
"""

XP_DESCARGAR_REVISADA = (
    "//button[contains(normalize-space(.),'Descargar Plantilla Revisada')]"
    " | //a[contains(normalize-space(.),'Descargar Plantilla Revisada')]"
)


def comentarios_plantilla_revisada(xlsx: Path, etiqueta: str = "carga") -> list[tuple[int, str, str]]:
    """(fila, nombre_de_archivo, comentario) de los comentarios de celda en columna A."""
    from openpyxl import load_workbook

    out: list[tuple[int, str, str]] = []
    try:
        wb = load_workbook(xlsx)  # comentarios requieren modo normal (no read_only)
    except Exception as exc:
        logger.warning("[%s] No se pudo abrir plantilla revisada %s: %s", etiqueta, xlsx, exc)
        return out
    for ws in wb.worksheets:
        cab = [str(c.value or "").strip().lower() for c in ws[1]]
        col_n = cab.index("nombre_de_archivo") + 1 if "nombre_de_archivo" in cab else None
        for row in range(1, ws.max_row + 1):
            cm = ws.cell(row, 1).comment
            if cm and (cm.text or "").strip():
                nombre = str(ws.cell(row, col_n).value or "") if col_n else ""
                out.append((row, nombre, " ".join(cm.text.split())))
    return out


def descargar_plantilla_revisada(driver, etiqueta: str = "carga") -> Path | None:
    """Solo lectura: baja el Excel con las observaciones del portal."""
    try:
        w = WebDriverWait(driver, 30)
        p = click_y_esperar_descarga(driver, w, XP_DESCARGAR_REVISADA, glob_pat="*.xls*")
        logger.error("[%s] Plantilla revisada (errores del portal): %s", etiqueta, p)
        for fila, nombre, comentario in comentarios_plantilla_revisada(p, etiqueta):
            logger.error("[%s] Fila %s (%s): %s", etiqueta, fila, nombre, comentario)
        return p
    except Exception as exc:
        logger.warning("[%s] No se pudo descargar la plantilla revisada: %s", etiqueta, exc)
        return None


def esperar_resultado_validacion(
    driver, *, timeout: float = 180, etiqueta: str = "carga", prefijo_shot: str = "carga"
) -> None:
    """Tras 'Validar Documentos': OK solo si 0 errores y botón Realizar habilitado.
    Errores / 'Planilla no válida' / modal de error → screenshot, descarga la
    plantilla revisada y lanza excepción (nunca se llega a 'Realizar')."""
    t0 = time.time()
    last = 0.0
    while time.time() - t0 < timeout:
        r = driver.execute_script(JS_RESULTADO_VALIDACION)
        if r == "ok":
            logger.info("[%s] Validación OK (%.0fs)", etiqueta, time.time() - t0)
            return
        if r:
            screenshot(driver, f"{prefijo_shot}_validacion_error.png")
            revisada = descargar_plantilla_revisada(driver, etiqueta)
            raise RuntimeError(
                f"[{etiqueta}] Validación de documentos falló: {r} | plantilla revisada: {revisada}"
            )
        if time.time() - last >= 5:
            logger.info("[%s] Esperando resultado de validación… (%.0fs)", etiqueta, time.time() - t0)
            last = time.time()
        time.sleep(0.5)
    screenshot(driver, f"{prefijo_shot}_validacion_timeout.png")
    raise TimeoutError(f"Timeout {timeout:.0f}s esperando resultado de 'Validar Documentos'")


JS_RESUMEN_CARGA = """
const t = document.body.innerText || '';
const m = t.match(/Documentos\\s+Agregados\\s*:\\s*(\\d+)/i);
const vis = e => !!(e && e.offsetParent !== null);
const modals = [...document.querySelectorAll('.modal,.swal2-popup,.bootbox,.alert,[role=alert]')]
  .filter(vis).map(e => (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 300));
return {agregados: m ? parseInt(m[1], 10) : null, modals: modals};
"""


def esperar_post_carga(
    driver, *, etiqueta: str = "carga", prefijo_shot: str = "carga", timeout: float = 120
) -> dict:
    """
    Tras el ÚNICO click en 'Realizar Carga Masiva'. El modal 'Enviando correo...
    Documentos Agregados: N' nunca llega al 100% (bug del sitio): en cuanto aparece
    se registra N, screenshot y se retorna éxito. No clickea ningún botón.
    """
    t0 = time.time()
    resumen: dict = {}
    while time.time() - t0 < timeout:
        try:
            resumen = driver.execute_script(JS_RESUMEN_CARGA) or {}
        except Exception:
            resumen = {}
        modals = " ".join(resumen.get("modals") or [])
        if resumen.get("agregados") is not None or re.search(r"enviando correo|documentos agregados", modals, re.I):
            time.sleep(2)  # dejar que el contador avance un poco antes de capturar
            try:
                resumen = driver.execute_script(JS_RESUMEN_CARGA) or resumen
            except Exception:
                pass
            screenshot(driver, f"{prefijo_shot}_post_carga.png")
            resumen = dict(resumen, ok=True)
            logger.info(
                "[%s] Carga masiva enviada: Documentos Agregados=%s | %s (%.0fs)",
                etiqueta, resumen.get("agregados"), resumen.get("modals"), time.time() - t0,
            )
            return resumen
        time.sleep(1)
    screenshot(driver, f"{prefijo_shot}_sin_progreso_post_carga.png")
    logger.warning("[%s] No apareció 'Documentos Agregados' en %.0fs; revisar UI", etiqueta, timeout)
    return dict(resumen, ok=False)


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def _select_el(wait: WebDriverWait, xpath: str) -> Select:
    el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    return Select(el)


def seleccionar_por_texto(
    driver, wait: WebDriverWait, xpath: str, texto: str, timeout: float | None = None
) -> str:
    """
    Elige una opción de <select> por texto visible (match exacto o contenido).

    Espera (por condición, hasta `timeout`/EXPLICIT_WAIT) a que la opción exista:
    el portal llena las opciones por AJAX después de mostrar el formulario y
    antes se fallaba con "Opciones: ['Seleccione']".
    """
    objetivo = _norm(texto)
    limite = time.time() + (EXPLICIT_WAIT if timeout is None else timeout)
    disponibles: list[str] = []
    while True:
        try:
            el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            select = Select(el)
            disponibles = []
            for opt in select.options:
                label = (opt.text or "").strip()
                if not label:
                    continue
                disponibles.append(label)
                if _norm(label) == objetivo or objetivo in _norm(label):
                    select.select_by_visible_text(opt.text)
                    disparar_change(driver, el)
                    logger.info("Select %s → '%s'", xpath, opt.text.strip())
                    return opt.text.strip()
        except StaleElementReferenceException:
            pass  # el portal re-renderizó el select; reintentar
        if time.time() >= limite:
            break
        time.sleep(0.3)
    raise ValueError(
        f"No encontré '{texto}' en select {xpath}. Opciones: {disponibles}"
    )


def _opciones_periodo_utiles(select: Select) -> list:
    skip = {"", "seleccione", "seleccionar", "periodo", "período", "-"}
    utiles = []
    for opt in select.options:
        label = (opt.text or "").strip()
        if not label or _norm(label) in skip:
            continue
        utiles.append(opt)
    return utiles


def esperar_select_cargado(
    driver,
    wait: WebDriverWait,
    xpath: str,
    *,
    min_opciones: int = 1,
    timeout: float | None = None,
) -> Select:
    """
    Espera a que un <select> esté habilitado y tenga opciones útiles
    (tras un cambio async, p.ej. tipo de documento → periodos).
    Tolera StaleElementReference mientras el DOM se regenera.
    """
    from selenium.common.exceptions import StaleElementReferenceException

    t = timeout if timeout is not None else EXPLICIT_WAIT
    skip = {"", "seleccione", "seleccionar", "periodo", "período", "-", "todos", "todas"}

    def _listo(drv):
        try:
            els = drv.find_elements(By.XPATH, xpath)
            if not els:
                return False
            el = els[0]
            if not el.is_displayed():
                return False
            if el.get_attribute("disabled") is not None:
                return False
            # Re-leer opciones desde el DOM actual (evita stale mid-reload)
            options = el.find_elements(By.TAG_NAME, "option")
            utiles = 0
            for o in options:
                try:
                    label = (o.text or "").strip()
                except StaleElementReferenceException:
                    return False
                if label and _norm(label) not in skip:
                    utiles += 1
            return utiles >= min_opciones
        except StaleElementReferenceException:
            return False

    WebDriverWait(driver, t).until(_listo)
    # Re-obtener select fresco (el DOM se reescribe al elegir documento)
    for intento in range(5):
        try:
            el = driver.find_element(By.XPATH, xpath)
            select = Select(el)
            n = len(_opciones_periodo_utiles(select))
            logger.info("Select cargado (%s opciones útiles): %s", n, xpath)
            return select
        except StaleElementReferenceException:
            time.sleep(0.3)
    el = driver.find_element(By.XPATH, xpath)
    select = Select(el)
    n = len(_opciones_periodo_utiles(select))
    logger.info("Select cargado (%s opciones útiles): %s", n, xpath)
    return select


def _periodo_coincide(label: str, anio: int, mes: int) -> bool:
    """
    Match estricto de periodo UI tipo 'Jun 2026' / 'junio 2026' / '06/2026'.
    No usa el dígito suelto del mes (evita que '6' matchee dentro de '2026').
    """
    n = _norm(label)
    anio_s = str(anio)
    if anio_s not in n:
        return False

    mes_es = MESES_ES[mes]
    mes_en = month_name[mes].lower()
    abbr_es = (
        "",
        "ene",
        "feb",
        "mar",
        "abr",
        "may",
        "jun",
        "jul",
        "ago",
        "sep",
        "oct",
        "nov",
        "dic",
    )[mes]
    abbr_en = mes_en[:3]  # jan, feb, ..., jun
    mes_2 = f"{mes:02d}"

    # Tokens de mes con límite de palabra (no substring dentro del año)
    patrones = [
        rf"\b{re.escape(mes_es)}\b",
        rf"\b{re.escape(mes_en)}\b",
        rf"\b{re.escape(abbr_es)}\b",
        rf"\b{re.escape(abbr_en)}\b",
        rf"\b{mes_2}/{anio}\b",
        rf"\b{mes}/{anio}\b",
        rf"\b{anio}-{mes_2}\b",
        rf"\b{anio}/{mes_2}\b",
        rf"\b{mes_2}\s+{anio}\b",
    ]
    return any(re.search(p, n) for p in patrones)


def seleccionar_periodo_mes_anterior(
    driver,
    wait: WebDriverWait,
    xpath: str,
    referencia: date | None = None,
    *,
    estricto: bool = False,
) -> str:
    """
    Elige el periodo del mes anterior a la ejecución.
    Si no hay match de texto, usa la última opción disponible del select
    (o, con estricto=True, falla listando las opciones: evita cargar documentos
    de un periodo en la plantilla de otro).
    """
    ref = referencia or date.today()
    periodo = mes_anterior(ref)
    el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    select = Select(el)
    utiles = _opciones_periodo_utiles(select)

    if not utiles:
        raise ValueError(f"Select de periodo sin opciones útiles: {xpath}")

    elegido = None
    for opt in utiles:
        if _periodo_coincide(opt.text, periodo.year, periodo.month):
            select.select_by_visible_text(opt.text)
            elegido = opt.text.strip()
            logger.info(
                "Periodo mes anterior %04d-%02d → '%s'",
                periodo.year,
                periodo.month,
                elegido,
            )
            break

    if elegido is None and estricto:
        raise ValueError(
            f"El portal no ofrece el periodo {periodo.year:04d}-{periodo.month:02d} "
            f"en {xpath}; opciones: {[o.text.strip() for o in utiles]}"
        )
    if elegido is None:
        opt = utiles[-1]
        select.select_by_visible_text(opt.text)
        elegido = opt.text.strip()
        logger.warning(
            "No matcheé mes anterior %04d-%02d; usé última opción: '%s'",
            periodo.year,
            periodo.month,
            elegido,
        )

    disparar_change(driver, el)
    return elegido


def _archivos_completos(directorio: Path, glob_pat: str) -> set[Path]:
    """Archivos que ya terminaron de bajar (sin .crdownload / .tmp)."""
    incompletos = {".crdownload", ".tmp", ".part"}
    out: set[Path] = set()
    for p in directorio.glob(glob_pat):
        if p.suffix.lower() in incompletos:
            continue
        if any(p.name.endswith(ext) for ext in incompletos):
            continue
        # Chrome a veces deja nombre.xlsx.crdownload
        if p.exists() and p.is_file():
            out.add(p.resolve())
    return out


def esperar_boton_habilitado(
    driver,
    wait: WebDriverWait,
    xpath: str,
    timeout: float | None = None,
):
    """Espera a que el botón exista, esté visible y sin atributo disabled."""
    t = timeout if timeout is not None else EXPLICIT_WAIT

    def _enabled(drv):
        els = drv.find_elements(By.XPATH, xpath)
        if not els:
            return False
        el = els[0]
        if not el.is_displayed():
            return False
        # En HTML, presencia de disabled (aunque sea "") = no clickeable
        if el.get_attribute("disabled") is not None:
            return False
        return el.is_enabled()

    WebDriverWait(driver, t).until(_enabled)
    el = driver.find_element(By.XPATH, xpath)
    logger.info("Botón habilitado: %s", xpath)
    return el


def click_y_esperar_descarga(
    driver,
    wait: WebDriverWait,
    xpath: str,
    *,
    download_dir: Path | None = None,
    glob_pat: str = "cmsd_plantilla_*.xlsx",
    timeout: float = 60,
) -> Path:
    """Click que dispara una descarga; espera un archivo nuevo que matchee glob_pat."""
    dest = Path(download_dir or DOWNLOAD_DIR).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    antes = _archivos_completos(dest, glob_pat)

    esperar_boton_habilitado(driver, wait, xpath, timeout=min(30, timeout))
    click_xpath(driver, wait, xpath)
    logger.info("Click descarga; esperando %s en %s", glob_pat, dest)

    deadline = time.time() + timeout
    while time.time() < deadline:
        # Descarga en curso
        if list(dest.glob("*.crdownload")) or list(dest.glob("*.tmp")):
            time.sleep(0.5)
            continue
        nuevos = _archivos_completos(dest, glob_pat) - antes
        if nuevos:
            archivo = max(nuevos, key=lambda p: p.stat().st_mtime)
            # Asegurar que el tamaño ya no crece
            size1 = archivo.stat().st_size
            time.sleep(0.5)
            size2 = archivo.stat().st_size
            if size1 == size2 and size2 > 0:
                logger.info("Descarga lista: %s (%s bytes)", archivo.name, size2)
                return archivo
        time.sleep(0.5)

    raise TimeoutError(
        f"No apareció descarga '{glob_pat}' en {dest} tras {timeout}s"
    )


def screenshot(driver, nombre: str = "debug.png") -> Path:
    path = DEBUG_DIR / nombre
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        driver.save_screenshot(str(path))
        logger.info("Screenshot: %s", path)
    except Exception as exc:
        logger.warning("Screenshot falló (%s): %s", nombre, exc)
    return path
