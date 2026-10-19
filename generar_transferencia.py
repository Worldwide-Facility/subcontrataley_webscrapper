"""Comprobante de transferencia de una línea, con el formato de nómina bancaria.

La carga de liquidaciones ya no lo genera. Lo construye el auditor
(`cargas_documentos_instalaciones_webscrapper/construir_transferencias_finiquito.py`)
y lo deja en GCS. Este módulo queda por si hay que regenerar uno a mano.
"""

from __future__ import annotations

import calendar
import logging
import re
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

_TEMPLATE = Path(__file__).resolve().parent / "assets" / "formato_transferencia.pdf"

_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_RE_RUT = re.compile(r"Rut:\s*[\r\n]+\s*([\d.]+)\s*-\s*([\dkK])", re.IGNORECASE)
_RE_NOMBRE = re.compile(r"Nombre:\s*[\r\n]+\s*([^\r\n]+)")
_RE_FECHA_TERMINO = re.compile(r"Fecha\s+Termino:\s*[\r\n]+\s*([^\r\n]+)", re.IGNORECASE)

_CONVENIO = "WORLDWIDE FACILITY SECURITY (REMUNERACIONES - 3050116498)"
_NOMINA_PLANTILLA = "Rem  Julio  2026  Sec"
_FECHA_PLANTILLA = "31-07-2026"


def _fmt_monto(monto: int) -> str:
    grupos = f"{monto:,}".replace(",", ".")
    return f"$ {grupos}"


def _fin_de_mes(periodo: str) -> tuple[str, str]:
    """'agosto 2026' → ('31-08-2026', 'Rem  Agosto  2026  Sec')."""
    partes = periodo.strip().split()
    if len(partes) != 2:
        raise ValueError(f"Periodo inválido: {periodo!r}")
    mes_txt, anio_txt = partes
    mes = _MESES.get(mes_txt.lower())
    if mes is None:
        raise ValueError(f"Mes inválido en periodo: {periodo!r}")
    anio = int(anio_txt)
    ultimo = calendar.monthrange(anio, mes)[1]
    fecha = f"{ultimo:02d}-{mes:02d}-{anio}"
    nomina = f"Rem  {mes_txt.capitalize()}  {anio}  Sec"
    return fecha, nomina


def liquidacion_de_finiquitado(pdf_path: Path) -> bool:
    """True si la liquidación trae Fecha Término con una fecha."""
    doc = fitz.open(pdf_path)
    try:
        texto = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    m = _RE_FECHA_TERMINO.search(texto)
    if not m:
        return False
    valor = re.sub(r"\s+", " ", m.group(1)).strip()
    if valor.lower().startswith("centro"):
        return False
    return bool(re.search(r"\d", valor))


def _datos_liquidacion(pdf_path: Path) -> tuple[str, str] | None:
    doc = fitz.open(pdf_path)
    try:
        texto = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    rut_m = _RE_RUT.search(texto)
    nom_m = _RE_NOMBRE.search(texto)
    if not rut_m or not nom_m:
        logger.warning("No pude leer RUT o nombre en %s", pdf_path.name)
        return None
    cuerpo = re.sub(r"\D", "", rut_m.group(1))
    dv = rut_m.group(2).upper()
    nombre = re.sub(r"\s+", " ", nom_m.group(1)).strip().upper()
    if not cuerpo or not nombre:
        return None
    return f"{cuerpo}-{dv}", nombre


def _tapar(page: fitz.Page, rect: fitz.Rect) -> None:
    page.add_redact_annot(rect, fill=(1, 1, 1))


def _escribir(page: fitz.Page, x: float, baseline: float, texto: str, size: float) -> None:
    page.insert_text(
        (x, baseline),
        texto,
        fontsize=size,
        fontname="helv",
        color=(0, 0, 0),
    )


def crear_transferencia_una_linea(
    liquidacion_pdf: Path,
    dest_dir: Path,
    periodo: str,
    monto: int,
) -> Path | None:
    """
    Arma `{rut}_Transferencia_{periodo}.pdf` con una sola línea de abono.
    `monto` es el TOTAL LIQUIDO ya leído. No genera la línea si el monto es 0.
    """
    if monto <= 0:
        return None
    if not _TEMPLATE.exists():
        raise FileNotFoundError(_TEMPLATE)
    datos = _datos_liquidacion(liquidacion_pdf)
    if datos is None:
        return None
    rut_dv, nombre = datos
    fecha, nomina = _fin_de_mes(periodo)
    cuerpo = rut_dv.split("-", 1)[0]

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{cuerpo}_Transferencia_{periodo}.pdf"

    doc = fitz.open(_TEMPLATE)
    try:
        page = doc[0]
        for texto in (_NOMINA_PLANTILLA, _FECHA_PLANTILLA):
            for rect in page.search_for(texto):
                _tapar(page, rect)
        # Las dos filas de ejemplo, dejando la línea bajo la primera.
        _tapar(page, fitz.Rect(60, 216.2, 580, 245))
        page.apply_redactions()
        page.draw_line(
            fitz.Point(52, 228.5),
            fitz.Point(586, 228.5),
            color=(0, 0, 0),
            width=0.6,
        )
        _escribir(page, 123.12, 138.9, nomina, 6.7)
        _escribir(page, 411.72, 138.9, fecha, 6.7)
        _escribir(page, 71.52, 225.6, rut_dv, 7.2)
        size_nombre = 7.2
        ancho = fitz.get_text_length(nombre, fontname="helv", fontsize=size_nombre)
        while ancho > 185 and size_nombre > 5:
            size_nombre -= 0.2
            ancho = fitz.get_text_length(nombre, fontname="helv", fontsize=size_nombre)
        _escribir(page, 159.4, 225.6, nombre, size_nombre)
        _escribir(page, 355.44, 225.8, "Pagado", 7.2)
        _escribir(page, 438.15, 225.8, fecha, 7.2)
        monto_txt = _fmt_monto(monto)
        ancho_monto = fitz.get_text_length(monto_txt, fontname="helv", fontsize=9)
        _escribir(page, 559 - ancho_monto, 226.6, monto_txt, 9)
        doc.save(str(dest))
    finally:
        doc.close()

    logger.info(
        "Transferencia generada %s | %s | %s | %s",
        dest.name,
        rut_dv,
        nombre,
        _fmt_monto(monto),
    )
    return dest
