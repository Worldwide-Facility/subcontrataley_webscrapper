"""Configuración Subcontrataley (variables de entorno)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Cloud Run Job / Service
IS_CLOUD_RUN = bool(
    os.getenv("K_SERVICE")
    or os.getenv("CLOUD_RUN_JOB")
    or os.getenv("K_REVISION")
)

HEADLESS = os.getenv(
    "HEADLESS",
    "true" if IS_CLOUD_RUN else "false",
).lower() in ("1", "true", "yes")

# DRY_RUN=true: recorre todo el flujo y verifica los elementos, pero NO envía archivos
# a inputs/dropzones ni hace click en botones que cargan/validan/confirman (ver
# browser.enviar_archivos / click_mutante; log "[DRY_RUN] se omitiría: ...").
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")

IMPLICIT_WAIT = int(os.getenv("IMPLICIT_WAIT", "10"))
EXPLICIT_WAIT = int(os.getenv("EXPLICIT_WAIT", "30" if IS_CLOUD_RUN else "20"))

SUBCONTRATALEY_USERNAME = os.getenv("SUBCONTRATALEY_USERNAME", "")
SUBCONTRATALEY_PASSWORD = os.getenv("SUBCONTRATALEY_PASSWORD", "")

# En Cloud Run: /tmp (filesystem escribible)
_default_dl = (
    Path(tempfile.gettempdir()) / "subcontrataley_downloads"
    if IS_CLOUD_RUN
    else Path(__file__).parent / "downloads"
)
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", str(_default_dl))).resolve()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

_default_debug = (
    Path(tempfile.gettempdir()) / "subcontrataley_debug"
    if IS_CLOUD_RUN
    else Path(__file__).parent / "debug"
)
DEBUG_DIR = Path(os.getenv("DEBUG_DIR", str(_default_debug))).resolve()
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# GCS — documentos
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "worldwide-documentos-instalaciones")
# Local: JSON. Cloud Run: SA del job (ADC) si no se define path.
GCS_CREDENTIALS_PATH = os.getenv("GCS_CREDENTIALS_PATH", "").strip() or None

# Cotizaciones (Previred): la del mes M está disponible desde el día N de M+1
# (America/Santiago). Periodo por defecto = M-1 si hoy >= N, si no M-2.
# Mismo criterio que el scraper de cotizaciones ControlRoll y el auditor.
COTIZACIONES_DIA_DISPONIBLE = int(os.getenv("COTIZACIONES_DIA_DISPONIBLE", "14"))
# Override explícito del periodo de cotizaciones: "YYYY-MM" (vacío = regla del día N).
COTIZACIONES_PERIODO = os.getenv("COTIZACIONES_PERIODO", "").strip() or None

# Chrome en contenedor (Dockerfile)
CHROME_BIN = os.getenv("CHROME_BIN", "").strip() or None
CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH", "").strip() or None

# --- Esperas de carga (dropzone + post 'Realizar Carga Masiva') ---
# Upload: timeout = max(minimo, base + N * per_file). Por lote si aplica.
UPLOAD_TIMEOUT_BASE_S = float(os.getenv("UPLOAD_TIMEOUT_BASE_S", "120"))
UPLOAD_TIMEOUT_PER_FILE_S = float(os.getenv("UPLOAD_TIMEOUT_PER_FILE_S", "8"))
UPLOAD_TIMEOUT_MIN_S = float(os.getenv("UPLOAD_TIMEOUT_MIN_S", "60"))
UPLOAD_ESTABLE_S = float(os.getenv("UPLOAD_ESTABLE_S", "3"))
# Post-carga: no cortar al primer 'Documentos Agregados'; esperar fin real.
# Default 60 min (cargas grandes ~200+ filas).
POST_CARGA_TIMEOUT_S = float(os.getenv("POST_CARGA_TIMEOUT_S", "3600"))
POST_CARGA_ESTABLE_S = float(os.getenv("POST_CARGA_ESTABLE_S", "15"))
POST_CARGA_LOG_CADA_S = float(os.getenv("POST_CARGA_LOG_CADA_S", "30"))


def require_credentials() -> tuple[str, str]:
    user = SUBCONTRATALEY_USERNAME.strip()
    password = SUBCONTRATALEY_PASSWORD.strip()
    if not user or not password:
        raise ValueError(
            "Faltan credenciales. Define SUBCONTRATALEY_USERNAME y "
            "SUBCONTRATALEY_PASSWORD en .env o en el Job de Cloud Run."
        )
    return user, password


def mascarar(valor: str | None, visibles: int = 2) -> str:
    """Enmascara un dato sensible para logs (usuario/RUT): 'ab*******'.
    Nunca usar para contraseñas: esas no se loguean en absoluto."""
    v = (valor or "").strip()
    if not v:
        return "<vacío>"
    if len(v) <= visibles:
        return "*" * len(v)
    return v[:visibles] + "*" * (len(v) - visibles)
