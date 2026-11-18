"""Periodos del auditor (YYYY-MM ↔ 'octubre 2026')."""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

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

_MESES_INV = {m: i for i, m in enumerate(MESES_ES) if m}


def mes_anterior(referencia: date | None = None) -> date:
    ref = referencia or date.today()
    if ref.month == 1:
        return date(ref.year - 1, 12, 1)
    return date(ref.year, ref.month - 1, 1)


def hoy_santiago() -> date:
    return datetime.now(ZoneInfo("America/Santiago")).date()


def periodo_default(hoy: date | None = None) -> date:
    """Mes anterior a la fecha de ejecución (America/Santiago)."""
    return mes_anterior(hoy or hoy_santiago())


def parse_periodo(raw: str | None, *, hoy: date | None = None) -> date:
    """
    Parsea AUDITOR_PERIODO.

    Acepta: '2026-10', '2026-10-01', 'octubre 2026', 'octubre-2026'.
    Vacío → mes anterior.
    """
    texto = (raw or "").strip()
    if not texto:
        return periodo_default(hoy)

    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", texto)
    if m:
        anio, mes = int(m.group(1)), int(m.group(2))
        if not 1 <= mes <= 12:
            raise ValueError(f"Periodo inválido: {raw!r}")
        return date(anio, mes, 1)

    m2 = re.fullmatch(
        r"([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s*[-/ ]\s*(\d{4})",
        texto,
    )
    if m2:
        nombre = m2.group(1).strip().lower()
        nombre = (
            nombre.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
        )
        mes = _MESES_INV.get(nombre)
        if mes is None:
            raise ValueError(f"Mes no reconocido en periodo: {raw!r}")
        return date(int(m2.group(2)), mes, 1)

    raise ValueError(f"Periodo inválido (esperado YYYY-MM): {raw!r}")


def periodo_texto(periodo: date) -> str:
    """date(2026, 10, 1) → 'octubre 2026'."""
    return f"{MESES_ES[periodo.month]} {periodo.year}"


def periodo_yyyy_mm(periodo: date) -> str:
    return f"{periodo.year:04d}-{periodo.month:02d}"


def periodo_yyyymm(periodo: date) -> str:
    return f"{periodo.year:04d}{periodo.month:02d}"
