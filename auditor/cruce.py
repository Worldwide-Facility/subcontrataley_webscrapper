"""Reglas de cruce: qué documentos faltan por trabajador."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from auditor.modelos import (
    EstadoFiniquito,
    FilaAuditoria,
    LoteDescarga,
    PresenciaDoc,
    TrabajadorPlantilla,
)
from auditor.periodo import periodo_texto, periodo_yyyy_mm, periodo_yyyymm


def _rut_cuerpo(rut: str) -> str:
    """Cuerpo numérico del RUT (sin DV); evita importar gcs_docs/selenium en tests."""
    import re

    if rut is None:
        return ""
    s = re.sub(r"[.\s]", "", str(rut)).upper()
    if "-" in s:
        return re.sub(r"\D", "", s.split("-", 1)[0])
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return digits[:8] if len(digits) > 8 else digits
    return digits


def ruta_esperada(
    tipo: str,
    rut_cuerpo_val: str,
    periodo: date,
) -> str:
    """Ruta canónica Tres raíces para el tipo/periodo."""
    c = _rut_cuerpo(rut_cuerpo_val)
    per = periodo_texto(periodo)
    yyyy_mm = f"{periodo.year:04d}/{periodo.month:02d}"
    yyyymm = periodo_yyyymm(periodo)
    if tipo == "liquidacion":
        return (
            f"Trabajadores/{c}/Liquidacion/{per}/"
            f"{c}_Liquidacion_{per}.pdf"
        )
    if tipo == "transferencia":
        return (
            f"Trabajadores/{c}/Transferencia/{per}/"
            f"{c}_Transferencia_{per}.pdf"
        )
    if tipo == "cotizaciones":
        return (
            f"Trabajadores/{c}/Cotizaciones/{yyyy_mm}/"
            f"{c}_Cotizacion_{yyyymm}.pdf"
        )
    if tipo == "asistencia":
        return f"Trabajadores/{c}/Asistencia/{per}/"
    if tipo == "finiquito":
        return f"Trabajadores/{c}/Finiquito/"
    if tipo == "contrato":
        return f"Trabajadores/{c}/Contrato/"
    raise ValueError(f"Tipo desconocido: {tipo}")


def needles_tipo(tipo: str, periodo: date) -> list[str]:
    """Substrings para detectar presencia en rutas GCS."""
    per = periodo_texto(periodo)
    yyyy_mm = f"{periodo.year:04d}/{periodo.month:02d}"
    if tipo == "liquidacion":
        return [f"/Liquidacion/{per}/"]
    if tipo == "transferencia":
        return [f"/Transferencia/{per}/"]
    if tipo == "cotizaciones":
        return [f"/Cotizaciones/{yyyy_mm}/", f"/Cotizaciones/{periodo.year}/{periodo.month}/"]
    if tipo == "asistencia":
        return [f"/Asistencia/{per}/"]
    if tipo == "finiquito":
        return ["/Finiquito/"]
    if tipo == "contrato":
        return ["/Contrato/"]
    return []


def requiere_transferencia(liquido: int | None) -> tuple[bool, str | None]:
    """Transferencia no se exige si líquido == 0."""
    if liquido == 0:
        return False, "NO REQ (líquido 0)"
    return True, None


def finiquitado_en_periodo(
    estado: str | None,
    fecha_finiquito: str | date | None,
    periodo: date,
) -> bool:
    """
    True si el trabajador está Finiquitado en el mes según reclutamiento.

    NO usar fecha_fin_contrato de la plantilla (falsos positivos).
    """
    est = (estado or "").strip().lower()
    if "finiquit" not in est:
        # Algunos registros marcan solo la fecha sin estado literal
        if not fecha_finiquito:
            return False
    ff = _parse_fecha(fecha_finiquito)
    if ff is None:
        return False
    return ff.year == periodo.year and ff.month == periodo.month


def _parse_fecha(valor) -> date | None:
    if valor is None or valor == "" or valor == "0000-00-00":
        return None
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    try:
        y, m, d = texto.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _hit_ruta(rutas: Iterable[str], needles: list[str]) -> str | None:
    for ruta in rutas:
        low = str(ruta)
        if not low.lower().endswith(".pdf"):
            continue
        for n in needles:
            if n in low:
                return low
    return None


@dataclass
class InventarioRut:
    rutas_gcs: list[str]
    rutas_bq: set[str]
    liquido: int | None = None
    empresa_gcs: str = ""
    cecos_gcs: str = ""


def auditar_trabajador(
    trabajador: TrabajadorPlantilla,
    *,
    periodo: date,
    tipos: Iterable[str],
    inventario: InventarioRut,
    finiquito: EstadoFiniquito | None = None,
) -> FilaAuditoria:
    """Aplica reglas de requerimiento y marca faltantes."""
    tipos_l = list(tipos)
    fin_en_mes = False
    fecha_f = None
    empresa = inventario.empresa_gcs or ""
    cecos = inventario.cecos_gcs or ""
    if finiquito:
        fin_en_mes = finiquito.finiquitado_en_periodo or finiquitado_en_periodo(
            finiquito.estado, finiquito.fecha_finiquito, periodo
        )
        fecha_f = finiquito.fecha_finiquito
        if not empresa and finiquito.empresa:
            empresa = finiquito.empresa
        if not cecos and finiquito.cecos:
            cecos = finiquito.cecos

    fila = FilaAuditoria(
        trabajador=trabajador,
        empresa=empresa or "?",
        cecos=cecos,
        finiquitado=fin_en_mes,
        fecha_finiquito=fecha_f,
        liquido=inventario.liquido,
    )

    for tipo in tipos_l:
        needles = needles_tipo(tipo, periodo)
        hit = _hit_ruta(inventario.rutas_gcs, needles)
        req = True
        motivo = None
        if tipo == "transferencia":
            req, motivo = requiere_transferencia(inventario.liquido)
        elif tipo == "finiquito":
            if not fin_en_mes:
                req = False
                motivo = "NO APLICA (no finiquitado en el mes)"
        elif tipo == "contrato":
            # Fuera del cálculo por defecto; si está en tipos, se exige
            pass

        presente_bq = bool(hit and hit in inventario.rutas_bq)
        doc = PresenciaDoc(
            tipo=tipo,
            presente_gcs=bool(hit),
            presente_bq=presente_bq,
            ruta_gcs=hit,
            requerido=req,
            motivo_no_req=motivo,
        )
        fila.docs[tipo] = doc
        if hit and not presente_bq:
            fila.observacion.append(f"{tipo} no indexado en BQ")

    if inventario.liquido == 0:
        fila.observacion.append("líquido 0: no requiere transferencia")
    if "liquidacion" in fila.faltantes:
        fila.observacion.append("sin liquidación")
    return fila


def generar_plan_descargas(
    filas: Iterable[FilaAuditoria],
    *,
    periodo: date,
    solicitud_id: str,
    workflow_por_tipo: Mapping[str, str],
    empresa_default: str = "Security",
) -> list[LoteDescarga]:
    """
    Agrupa faltantes por (tipo, empresa) para lanzar workflows en serie.

    Transferencia no genera lote de workflow (se crea en el auditor).
    """
    buckets: dict[tuple[str, str], LoteDescarga] = {}
    per = periodo_yyyy_mm(periodo)
    for fila in filas:
        empresa = _normalizar_empresa(fila.empresa) or empresa_default
        for tipo in fila.faltantes:
            if tipo == "transferencia":
                continue
            wf = workflow_por_tipo.get(tipo)
            if not wf:
                continue
            key = (tipo, empresa)
            lote = buckets.get(key)
            if lote is None:
                lote = LoteDescarga(
                    tipo_auditor=tipo,
                    workflow=wf,
                    empresa=empresa,
                    periodo=per,
                    solicitud_id=f"{solicitud_id}-{tipo}-{empresa.lower()}",
                )
                buckets[key] = lote
            rut = fila.trabajador.rut
            if rut not in lote.ruts:
                lote.ruts.append(rut)
    # Orden estable: liquidacion → cotizaciones → finiquito → contrato → asistencia
    orden = {
        "liquidacion": 0,
        "cotizaciones": 1,
        "finiquito": 2,
        "contrato": 3,
        "asistencia": 4,
    }
    return sorted(
        buckets.values(),
        key=lambda L: (orden.get(L.tipo_auditor, 50), L.empresa, L.tipo_auditor),
    )


def candidatos_transferencia(filas: Iterable[FilaAuditoria]) -> list[FilaAuditoria]:
    """Liquidación presente, líquido>0, transferencia faltante."""
    out = []
    for f in filas:
        liq = f.docs.get("liquidacion")
        tr = f.docs.get("transferencia")
        if liq is None or tr is None:
            continue
        if not liq.presente_gcs:
            continue
        if f.liquido is None or f.liquido <= 0:
            continue
        if tr.faltante:
            out.append(f)
    return out


def _normalizar_empresa(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s or s == "?":
        return ""
    # Puede venir "Security/Industry" si hay metadata mixta
    partes = [p.strip() for p in s.replace("|", "/").split("/") if p.strip()]
    for p in partes:
        if p.lower() == "security":
            return "Security"
        if p.lower() == "industry":
            return "Industry"
    return ""


def resumen_por_tipo(filas: list[FilaAuditoria], tipos: Iterable[str]) -> list[dict]:
    out = []
    for tipo in tipos:
        vals = []
        for f in filas:
            d = f.docs.get(tipo)
            if d is None:
                continue
            if not d.requerido:
                vals.append("NO_REQ")
            elif d.presente_gcs:
                vals.append("SI")
            else:
                vals.append("NO")
        out.append(
            {
                "tipo": tipo,
                "requeridos": sum(v in ("SI", "NO") for v in vals),
                "presentes": vals.count("SI"),
                "faltantes": vals.count("NO"),
                "no_aplica": vals.count("NO_REQ"),
            }
        )
    return out
