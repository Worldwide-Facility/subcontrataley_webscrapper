"""Cliente GCS: buscar documentos personales por RUT + periodo (Tres raíces).

Convención bucket `worldwide-documentos-instalaciones`:
  Trabajadores/{rut}/{Tipo}/{periodo|YYYY/MM}/archivo.pdf   ← mensual
  Trabajadores/{rut}/{Tipo}/archivo.pdf                     ← vigente (sin mes)
  Instalaciones/{Industry|Security}/{cecos}/{Tipo}/...      ← faena (no usa SCL)
  Documentos_Generales/{carpeta}/...                        ← globales (no usa SCL)

Tipos que consume Subcontrataley (todos personales):
  Liquidacion, Transferencia, Asistencia, Cotizaciones
  y los documentos vigentes de trabajador (ver TIPOS_PERSONALES_SCL).

Lectura dual durante migración (layouts mensuales): primero `Trabajadores/`,
luego globs legacy. El layout `vigente` solo lee la carpeta directa del RUT.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from google.cloud import storage

from browser import MESES_ES, mes_anterior
from config import GCS_BUCKET_NAME, GCS_CREDENTIALS_PATH

logger = logging.getLogger(__name__)

RAIZ_TRABAJADORES = "Trabajadores"

# Tipos personales que Subcontrataley lee desde Trabajadores/{rut}/...
TIPOS_PERSONALES_SCL = frozenset(
    {
        "Liquidacion",
        "Transferencia",
        "Asistencia",
        "Cotizaciones",
        "Contrato",
        "CapacitacionPrevencion",
        "CapacitacionUsoEPP",
        "CertificadoOS10",
        "CertificadoAntecedentes",
        "CedulaIdentidad",
        "EntregaEPP",
        "GuiaPracticaSeguridad",
        "RecepcionReglamentoContratistas",
        "RegistroDifusionReglamento",
        "SeguroVida",
        "TomaConocimientoIPER",
        "TomaConocimientoProcedimiento",
        "TomaConocimientoPrograma",
        "TomaConocimientoRiesgos",
    }
)

_RUT_CARPETA_RE = re.compile(r"^(\d{7,8})(?:-[\dkK])?$")


def es_pdf_vigente(ruta: str, tipo: str) -> bool:
    """True si la ruta es Trabajadores/{rut}/{tipo}/{archivo}.pdf (cuatro segmentos)."""
    partes = [p for p in str(ruta).strip("/").split("/") if p]
    if len(partes) != 4:
        return False
    if partes[0] != RAIZ_TRABAJADORES or partes[2] != tipo:
        return False
    if not partes[3].lower().endswith(".pdf"):
        return False
    return _RUT_CARPETA_RE.match(partes[1].strip()) is not None


@dataclass
class DocGCS:
    nombre: str
    ruta_gcs: str
    rut_cuerpo: str
    tipo: str  # Liquidacion | Transferencia | Asistencia | Cotizaciones


def periodo_gcs_texto(referencia: date | None = None) -> str:
    """Periodo de carpeta/archivo en GCS: 'junio 2026' (mes anterior a la ejecución)."""
    p = mes_anterior(referencia)
    return f"{MESES_ES[p.month]} {p.year}"


def rut_cuerpo(rut: str) -> str:
    """
    Cuerpo numérico del RUT (sin DV), como en nombres GCS.
    '15.666.622-K' / '15666622-K' / '15666622' → '15666622'
    """
    if rut is None:
        return ""
    s = re.sub(r"[.\s]", "", str(rut)).upper()
    if "-" in s:
        return re.sub(r"\D", "", s.split("-", 1)[0])
    m = re.match(r"^(\d{7,8})[0-9K]?$", s)
    if m:
        return m.group(1)
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return digits[:8] if len(digits) > 8 else digits[:-1] if len(digits) == 9 else digits
    return digits


def _cliente() -> storage.Client:
    """ADC en Cloud Run; JSON local si GCS_CREDENTIALS_PATH está definido."""
    if GCS_CREDENTIALS_PATH:
        return storage.Client.from_service_account_json(GCS_CREDENTIALS_PATH)
    return storage.Client()


def _rut_desde_nombre_archivo(nombre: str) -> str:
    base = nombre.split("/")[-1]
    m = re.match(r"^(\d{7,8})(?:[-_][0-9Kk])?_", base)
    if m:
        return m.group(1)
    m2 = re.match(r"^(\d{7,8})_", base)
    return m2.group(1) if m2 else ""


def _rut_desde_ruta_gcs(ruta: str) -> str:
    """
    RUT desde Tres raíces: Trabajadores/{rut}/Tipo/...
    Acepta carpeta con o sin DV (`12345678` o `12345678-9`).
    """
    partes = [p for p in str(ruta).strip("/").split("/") if p]
    if len(partes) < 2 or partes[0] != RAIZ_TRABAJADORES:
        return ""
    m = _RUT_CARPETA_RE.match(partes[1].strip())
    if not m:
        return ""
    return m.group(1)


def _rut_cuerpo_de_blob(ruta_gcs: str, nombre: str) -> str:
    """Prefiere RUT del nombre de archivo; si falta, carpeta Trabajadores/{rut}/."""
    cuerpo = _rut_desde_nombre_archivo(nombre)
    if cuerpo:
        return cuerpo
    return _rut_desde_ruta_gcs(ruta_gcs)


def _es_ruta_trabajadores(ruta: str) -> bool:
    return str(ruta).startswith(f"{RAIZ_TRABAJADORES}/")


def periodo_cotizaciones(
    hoy: date | None = None,
    *,
    override: str | None = None,
    dia_disponible: int | None = None,
) -> date:
    """
    Mes (día 1) de cotizaciones a cargar por defecto.

    La cotización del mes M está disponible desde el día `dia_disponible` (env
    COTIZACIONES_DIA_DISPONIBLE, default 14) de M+1, hora America/Santiago:
    hoy >= día → M-1 ; hoy < día → M-2.
    `override` (o env COTIZACIONES_PERIODO) "YYYY-MM" fija el periodo explícito.
    """
    import config as _cfg

    ov = override if override is not None else _cfg.COTIZACIONES_PERIODO
    if ov:
        m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", ov)
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise ValueError(f"COTIZACIONES_PERIODO inválido (esperado YYYY-MM): {ov!r}")
        return date(int(m.group(1)), int(m.group(2)), 1)
    if hoy is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        hoy = datetime.now(ZoneInfo("America/Santiago")).date()
    dia = _cfg.COTIZACIONES_DIA_DISPONIBLE if dia_disponible is None else dia_disponible
    atras = 1 if hoy.day >= dia else 2
    idx = hoy.year * 12 + (hoy.month - 1) - atras
    return date(idx // 12, idx % 12 + 1, 1)


def referencia_para_periodo(periodo: date) -> date:
    """Fecha cuya 'mes anterior' es `periodo` (para APIs basadas en mes_anterior)."""
    idx = periodo.year * 12 + (periodo.month - 1) + 1
    return date(idx // 12, idx % 12 + 1, 1)


def periodo_gcs_yyyy_mm(referencia: date | None = None) -> tuple[str, str, str]:
    """
    Periodo mes anterior como (texto 'junio 2026', '2026', '06').
    Útil para Cotizaciones: .../Cotizaciones/2026/06/...
    """
    p = mes_anterior(referencia)
    texto = f"{MESES_ES[p.month]} {p.year}"
    return texto, str(p.year), f"{p.month:02d}"


def _globs_periodo(
    tipo: str,
    *,
    layout: str,
    periodo: str,
    anio: str | None,
    mes: str | None,
) -> list[tuple[str, str]]:
    """
    Lista de (glob, etiqueta) en orden de preferencia.
    1) Tres raíces Trabajadores/
    2) Legacy **/{Tipo}/... (cecos o Industry/Security/cecos)

    layout vigente: solo Trabajadores/{rut}/{tipo}/{archivo}.pdf, sin legacy.
    """
    out: list[tuple[str, str]] = []
    if layout == "vigente":
        return [(f"{RAIZ_TRABAJADORES}/**/{tipo}/*.pdf", "tres_raices")]
    if layout == "yyyy_mm":
        assert anio and mes
        mes_alt = str(int(mes))
        out.append(
            (
                f"{RAIZ_TRABAJADORES}/**/{tipo}/{anio}/{mes}/*.pdf",
                "tres_raices",
            )
        )
        if mes_alt != mes:
            out.append(
                (
                    f"{RAIZ_TRABAJADORES}/**/{tipo}/{anio}/{mes_alt}/*.pdf",
                    "tres_raices_mes_alt",
                )
            )
        out.append((f"**/{tipo}/{anio}/{mes}/*.pdf", "legacy"))
        if mes_alt != mes:
            out.append((f"**/{tipo}/{anio}/{mes_alt}/*.pdf", "legacy_mes_alt"))
    else:
        out.append(
            (
                f"{RAIZ_TRABAJADORES}/**/{tipo}/{periodo}/*.pdf",
                "tres_raices",
            )
        )
        out.append((f"**/{tipo}/{periodo}/*.pdf", "legacy"))
    return out


def _needles_periodo(
    tipo: str,
    *,
    layout: str,
    periodo: str,
    anio: str | None,
    mes: str | None,
) -> list[str]:
    """Substrings para fallback por prefix (sin listar todo el bucket)."""
    if layout == "vigente":
        return [f"/{tipo}/"]
    if layout == "yyyy_mm":
        assert anio and mes
        mes_alt = str(int(mes))
        needles = [f"/{tipo}/{anio}/{mes}/"]
        if mes_alt != mes:
            needles.append(f"/{tipo}/{anio}/{mes_alt}/")
        return needles
    return [f"/{tipo}/{periodo}/"]


def listar_docs_periodo(
    tipo: str,
    periodo: str,
    *,
    bucket_name: str | None = None,
    layout: str = "mes_anio",
    anio: str | None = None,
    mes: str | None = None,
) -> list[DocGCS]:
    """
    Lista PDFs de un tipo/periodo en el bucket.

    layout:
      - mes_anio: {Tipo}/{periodo}/*.pdf  (ej. Liquidacion/junio 2026)
      - yyyy_mm:  {Tipo}/{anio}/{mes}/*.pdf  (ej. Cotizaciones/2026/06)
      - vigente:  Trabajadores/{rut}/{Tipo}/{archivo}.pdf  (sin mes ni legacy)

    Preferencia Tres raíces (`Trabajadores/...`); fallback legacy en layouts mensuales.
    """
    bucket_name = bucket_name or GCS_BUCKET_NAME
    client = _cliente()
    bucket = client.bucket(bucket_name)

    if layout == "yyyy_mm":
        if not anio or not mes:
            _, anio, mes = periodo_gcs_yyyy_mm()
    else:
        anio = mes = None

    globs = _globs_periodo(
        tipo, layout=layout, periodo=periodo, anio=anio, mes=mes
    )
    needles = _needles_periodo(
        tipo, layout=layout, periodo=periodo, anio=anio, mes=mes
    )

    por_ruta: dict[str, DocGCS] = {}

    def _add_blob(blob_name: str) -> None:
        if blob_name.endswith("/") or not blob_name.lower().endswith(".pdf"):
            return
        if layout == "vigente" and not es_pdf_vigente(blob_name, tipo):
            return
        if not any(n in blob_name for n in needles):
            return
        if blob_name in por_ruta:
            return
        nombre = blob_name.rsplit("/", 1)[-1]
        cuerpo = _rut_cuerpo_de_blob(blob_name, nombre)
        if not cuerpo:
            return
        por_ruta[blob_name] = DocGCS(
            nombre=nombre,
            ruta_gcs=blob_name,
            rut_cuerpo=cuerpo,
            tipo=tipo,
        )

    def _collect_glob(glob_pattern: str) -> int:
        n = 0
        try:
            for blob in bucket.list_blobs(match_glob=glob_pattern):
                before = len(por_ruta)
                _add_blob(blob.name)
                if len(por_ruta) > before:
                    n += 1
        except Exception as exc:
            logger.warning("match_glob falló (%s): %s", glob_pattern, exc)
        return n

    # 1) Tres raíces + legacy vía match_glob
    for glob_pat, label in globs:
        logger.info("GCS list gs://%s match_glob=%s [%s]", bucket_name, glob_pat, label)
        got = _collect_glob(glob_pat)
        logger.info("GCS %s → +%s archivo(s)", label, got)
        # Si Tres raíces ya trajo resultados, aún corremos legacy por dual-read
        # (algunos PDFs pueden quedar solo en cecos legacy).

    # 2) Fallback acotado: listar solo bajo Trabajadores/ (nunca el bucket entero)
    if not por_ruta:
        logger.warning(
            "GCS match_glob vacío para %s/%s; fallback prefix=%s/",
            tipo,
            periodo,
            RAIZ_TRABAJADORES,
        )
        for blob in bucket.list_blobs(prefix=f"{RAIZ_TRABAJADORES}/"):
            _add_blob(blob.name)

    docs = list(por_ruta.values())
    # Preferencia estable: Trabajadores primero al iterar (índice luego pisa con preferencia)
    docs.sort(key=lambda d: (0 if _es_ruta_trabajadores(d.ruta_gcs) else 1, d.ruta_gcs))
    logger.info(
        "GCS %s/%s → %s archivo(s) (%s en Trabajadores/)",
        tipo,
        periodo,
        len(docs),
        sum(1 for d in docs if _es_ruta_trabajadores(d.ruta_gcs)),
    )
    return docs


def indice_por_rut(docs: Iterable[DocGCS]) -> dict[str, DocGCS]:
    """
    Un doc por RUT. Si hay duplicados (legacy + Tres raíces), gana Trabajadores/.
    """
    out: dict[str, DocGCS] = {}
    for d in docs:
        prev = out.get(d.rut_cuerpo)
        if prev is None:
            out[d.rut_cuerpo] = d
            continue
        if _es_ruta_trabajadores(d.ruta_gcs) and not _es_ruta_trabajadores(prev.ruta_gcs):
            out[d.rut_cuerpo] = d
    return out


def buscar_docs_tipo(
    tipo_gcs: str,
    *,
    periodo: str | None = None,
    layout: str = "mes_anio",
    referencia: date | None = None,
) -> tuple[dict[str, DocGCS], str]:
    """Índice RUT → doc para un tipo GCS."""
    if layout == "vigente":
        docs = listar_docs_periodo(tipo_gcs, "vigente", layout="vigente")
        return indice_por_rut(docs), "vigente"
    if layout == "yyyy_mm":
        texto, anio, mes = periodo_gcs_yyyy_mm(referencia)
        docs = listar_docs_periodo(
            tipo_gcs, texto, layout="yyyy_mm", anio=anio, mes=mes
        )
        return indice_por_rut(docs), texto
    periodo = periodo or periodo_gcs_texto(referencia)
    docs = listar_docs_periodo(tipo_gcs, periodo, layout="mes_anio")
    return indice_por_rut(docs), periodo


def buscar_liquidaciones_y_transferencias(
    periodo: str | None = None,
    referencia: date | None = None,
) -> tuple[dict[str, DocGCS], dict[str, DocGCS], str]:
    periodo = periodo or periodo_gcs_texto(referencia)
    liqs = indice_por_rut(listar_docs_periodo("Liquidacion", periodo))
    trs = indice_por_rut(listar_docs_periodo("Transferencia", periodo))
    return liqs, trs, periodo


def tiene_finiquito(cuerpo: str, *, bucket_name: str | None = None) -> bool:
    """True si Trabajadores/{rut}/Finiquito/ tiene al menos un PDF."""
    cuerpo = rut_cuerpo(cuerpo)
    if not cuerpo:
        return False
    client = _cliente()
    bucket = client.bucket(bucket_name or GCS_BUCKET_NAME)
    prefix = f"{RAIZ_TRABAJADORES}/{cuerpo}/Finiquito/"
    for blob in bucket.list_blobs(prefix=prefix, max_results=5):
        if blob.name.lower().endswith(".pdf"):
            return True
    return False


def descargar_doc(doc: DocGCS, dest_dir: Path, *, bucket_name: str | None = None) -> Path:
    """Descarga el blob GCS a dest_dir conservando el nombre exacto (como en el Excel)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / doc.nombre
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Ya existe local: %s", dest.name)
        return dest
    client = _cliente()
    bucket = client.bucket(bucket_name or GCS_BUCKET_NAME)
    blob = bucket.blob(doc.ruta_gcs)
    blob.download_to_filename(str(dest))
    logger.info("Descargado gs://%s/%s → %s", bucket_name or GCS_BUCKET_NAME, doc.ruta_gcs, dest)
    return dest


def descargar_docs(
    docs: Iterable[DocGCS],
    dest_dir: Path,
) -> list[Path]:
    paths: list[Path] = []
    vistos: set[str] = set()
    for doc in docs:
        if doc.nombre in vistos:
            continue
        vistos.add(doc.nombre)
        paths.append(descargar_doc(doc, dest_dir))
    return paths
