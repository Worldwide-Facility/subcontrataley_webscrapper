"""Lógica pura de espera de uploads y post-carga masiva (testeable sin Selenium).

Criterios:
1) Dropzone: SOLO archivos reales (nombre con extensión); placeholders/avisos
   no cuentan en la base ni en n_min. Éxito = todos los nombres enviados listos
   (o listos >= enviados) y 0 en proceso; con errores → fallar listándolos.
2) Post 'Realizar Carga Masiva': NO basta la primera aparición del contador.
   Esperar a que desaparezca 'Se esta realizando la carga masiva' y que el
   contador se estabilice (o alcance el mínimo razonable). La barra al 100%
   no cuenta.

esperado post-carga (mínimo razonable) =
  min(filas_plantilla, PDFs_principales_únicos[, RUT_únicos])

Regla de fallo vs WARNING:
  - Documentos Agregados < minimo_razonable → FAIL (diferencia > 0)
  - minimo_razonable <= Agregados < filas_plantilla → WARNING (p.ej. RUT
    duplicado en plantilla: 109 filas pero 108 PDFs/RUT únicos) y OK
  - Agregados >= filas_plantilla → OK
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_RE_EXTENSION = re.compile(r"\.[A-Za-z0-9]{2,5}$")
_RE_PLACEHOLDER = re.compile(
    r"arrastr|suelte|drop\s*files|seleccion|haga\s*click|sin\s*archivos|"
    r"placeholder|aqui|aquí|browse|elegir\s*archivo|no\s*hay\s*document",
    flags=re.I,
)


def timeout_upload_s(
    n_archivos: int,
    *,
    base_s: float,
    per_file_s: float,
    minimo_s: float = 60.0,
) -> float:
    """Timeout generoso proporcional a la cantidad de archivos."""
    n = max(0, int(n_archivos))
    return max(float(minimo_s), float(base_s) + n * float(per_file_s))


def es_nombre_archivo_real(name: str | None) -> bool:
    """True si parece un archivo real (tiene extensión) y no es placeholder/aviso."""
    n = (name or "").strip()
    if not n:
        return False
    if _RE_PLACEHOLDER.search(n):
        return False
    if not _RE_EXTENSION.search(n):
        return False
    return True


def filtrar_previews_reales(visibles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deja solo previews con nombre de archivo real (excluye placeholders)."""
    return [v for v in visibles if es_nombre_archivo_real(v.get("name"))]


def dropzone_carga_completa(
    visibles: list[dict[str, Any]],
    esperados: list[str],
) -> dict[str, Any]:
    """
    Compara previews del dropzone con la lista esperada (nombres exactos).

    Solo considera archivos reales. OK si: todos presentes, ninguno con error
    y ninguno aún procesando. Alternativa de conteo: listos >= len(esperados)
    únicos y 0 processing/errores sobre esperados.
    """
    reales = filtrar_previews_reales(visibles)
    esperados_u = list(dict.fromkeys(esperados))
    ok_names = {
        v["name"]
        for v in reales
        if not v.get("error")
        and (v.get("success") or not v.get("processing"))
    }
    err_names = {v["name"] for v in reales if v.get("error")}
    proc_names = {
        v["name"]
        for v in reales
        if v.get("processing") and not v.get("success")
    }
    faltan = [n for n in esperados_u if n not in ok_names and n not in err_names]
    con_error = [n for n in esperados_u if n in err_names and n not in ok_names]
    procesando = [n for n in esperados_u if n in proc_names and n not in ok_names]
    extra = sorted({v["name"] for v in reales if v.get("name")} - set(esperados_u))
    listos = len(ok_names & set(esperados_u))
    # Éxito por nombres completos O por conteo listos >= enviados sin errores/proceso
    ok_nombres = not faltan and not con_error and not procesando
    ok_conteo = (
        listos >= len(esperados_u)
        and not con_error
        and not procesando
        and len(esperados_u) > 0
    )
    return {
        "esperados": len(esperados_u),
        "visibles": len({v["name"] for v in reales if v.get("name")}),
        "listos": listos,
        "ok_names": sorted(ok_names & set(esperados_u)),
        "faltan": faltan,
        "con_error": con_error,
        "procesando": procesando,
        "extra": extra,
        "ok": ok_nombres or ok_conteo,
    }


def zona_upload_lista(
    estado: dict[str, Any],
    *,
    n_min: int | None = None,
) -> bool:
    """
    True si la zona no tiene progreso/processing pendiente y el conteo de
    archivos REALES alcanza n_min. `items` del estado debe venir ya filtrado
    (sin placeholders).
    """
    items = int(estado.get("items") or 0)
    progress = int(estado.get("progress") or 0)
    processing = int(estado.get("processing") or 0)
    complete = int(estado.get("complete") or 0)
    errors = int(estado.get("errors") or 0)
    if n_min is not None and items < n_min:
        return False
    if progress > 0 or processing > 0:
        return False
    if errors > 0:
        return False
    if items <= 0:
        return False
    if complete > 0 and n_min is not None and complete < n_min:
        return False
    return True


def calcular_esperado_post_carga(
    *,
    filas_plantilla: int,
    pdfs_principales_unicos: int,
    ruts_unicos: int | None = None,
) -> dict[str, Any]:
    """
    Calcula el mínimo razonable para Documentos Agregados.

    minimo_razonable = min(filas, PDFs únicos[, RUT únicos])
    - Si la plantilla repite un RUT (109 filas, 108 PDFs/RUT) el mínimo es 108.
    - Fallar solo si Agregados < minimo_razonable (diff > 0 vs ese mínimo).
    - Si minimo <= Agregados < filas → WARNING (no fallo).
    """
    filas = max(0, int(filas_plantilla))
    pdfs = max(0, int(pdfs_principales_unicos))
    candidatos = [filas, pdfs]
    if ruts_unicos is not None:
        candidatos.append(max(0, int(ruts_unicos)))
    # Si algún lado es 0 y el otro no, usar el positivo (evita min(109,0)=0).
    positivos = [c for c in candidatos if c > 0]
    minimo = min(positivos) if positivos else 0
    return {
        "filas_plantilla": filas,
        "pdfs_unicos": pdfs,
        "ruts_unicos": None if ruts_unicos is None else max(0, int(ruts_unicos)),
        "minimo_razonable": minimo,
        "esperado": minimo,
        "criterio": "min(filas_plantilla, pdfs_principales_unicos[, ruts_unicos])",
    }


def evaluar_agregados_vs_esperado(
    agregados: int | None,
    *,
    minimo_razonable: int | None,
    filas_plantilla: int | None = None,
) -> dict[str, Any]:
    """
    Regla post-carga (después de estabilizar / fin de mensaje en curso):

    - agregados >= minimo_razonable → ok=True
    - si además agregados < filas_plantilla → warning=True (duplicados/sobrante)
    - agregados < minimo_razonable → ok=False (diff > 0 vs mínimo razonable)
    """
    if agregados is None:
        return {
            "ok": False,
            "warning": False,
            "diff_vs_minimo": None,
            "motivo": "sin_agregados",
        }
    agg = int(agregados)
    if minimo_razonable is None:
        return {
            "ok": True,
            "warning": False,
            "diff_vs_minimo": 0,
            "motivo": "sin_minimo",
        }
    minimo = int(minimo_razonable)
    diff = minimo - agg
    if diff > 0:
        return {
            "ok": False,
            "warning": False,
            "diff_vs_minimo": diff,
            "motivo": f"bajo_minimo:{agg}<{minimo}",
        }
    filas = int(filas_plantilla) if filas_plantilla is not None else None
    warning = filas is not None and agg < filas
    return {
        "ok": True,
        "warning": warning,
        "diff_vs_minimo": diff,  # <= 0
        "motivo": (
            f"ok_con_warning_filas:{agg}<{filas}"
            if warning
            else f"ok:{agg}>={minimo}"
        ),
    }


@dataclass
class LecturaPostCarga:
    """Snapshot del portal tras 'Realizar Carga Masiva'."""

    agregados: int | None = None
    subidos: int | None = None
    errores: int = 0
    en_curso: bool = False
    modals: list[str] = field(default_factory=list)
    texto: str = ""


@dataclass
class EstadoEsperaPostCarga:
    estable_desde: float | None = None
    ultimo_agregados: int | None = None
    vio_en_curso: bool = False


@dataclass
class DecisionPostCarga:
    terminado: bool
    ok: bool
    motivo: str
    estado: EstadoEsperaPostCarga
    warning: bool = False


def parse_lectura_post_carga(
    *,
    agregados: int | None,
    subidos: int | None = None,
    errores: int = 0,
    modals: list[str] | None = None,
    texto: str = "",
    en_curso: bool | None = None,
) -> LecturaPostCarga:
    """Arma LecturaPostCarga; detecta mensaje en curso si no viene explícito."""
    blob = " ".join([texto or "", " ".join(modals or [])])
    if en_curso is None:
        en_curso = bool(re_en_curso(blob))
    return LecturaPostCarga(
        agregados=agregados,
        subidos=subidos,
        errores=int(errores or 0),
        en_curso=bool(en_curso),
        modals=list(modals or []),
        texto=texto or "",
    )


def re_en_curso(texto: str) -> bool:
    """True si el portal aún muestra el mensaje de carga masiva en curso."""
    return bool(
        re.search(
            r"se\s+est[aá]\s+realizando\s+la\s+carga\s+masiva",
            texto or "",
            flags=re.I,
        )
    )


def avanzar_espera_post_carga(
    lectura: LecturaPostCarga,
    estado: EstadoEsperaPostCarga,
    *,
    ahora: float,
    esperado: int | None,
    estable_s: float,
    filas_plantilla: int | None = None,
) -> DecisionPostCarga:
    """
    Un paso de la máquina de espera post-carga (puro / simulable).

    Termina cuando:
      - no hay mensaje en curso, Y
      - agregados >= esperado (mínimo razonable), O
      - agregados se mantuvo igual durante estable_s segundos.

    Al estabilizar: ok según evaluar_agregados_vs_esperado (WARNING si
    agregados < filas pero >= mínimo). Nunca usa la barra al 100%.
    """
    est = EstadoEsperaPostCarga(
        estable_desde=estado.estable_desde,
        ultimo_agregados=estado.ultimo_agregados,
        vio_en_curso=estado.vio_en_curso or lectura.en_curso,
    )

    if lectura.en_curso:
        return DecisionPostCarga(
            terminado=False,
            ok=False,
            motivo="en_curso",
            estado=EstadoEsperaPostCarga(
                estable_desde=None,
                ultimo_agregados=lectura.agregados,
                vio_en_curso=True,
            ),
        )

    if lectura.agregados is None:
        return DecisionPostCarga(
            terminado=False,
            ok=False,
            motivo="sin_agregados",
            estado=est,
        )

    agg = int(lectura.agregados)

    if esperado is not None and agg >= int(esperado):
        ev = evaluar_agregados_vs_esperado(
            agg, minimo_razonable=esperado, filas_plantilla=filas_plantilla
        )
        return DecisionPostCarga(
            terminado=True,
            ok=True,
            warning=bool(ev.get("warning")),
            motivo=f"alcanzado_esperado:{agg}>={int(esperado)}",
            estado=EstadoEsperaPostCarga(
                estable_desde=ahora,
                ultimo_agregados=agg,
                vio_en_curso=est.vio_en_curso,
            ),
        )

    if est.ultimo_agregados == agg and est.estable_desde is not None:
        if ahora - est.estable_desde >= float(estable_s):
            ev = evaluar_agregados_vs_esperado(
                agg,
                minimo_razonable=esperado,
                filas_plantilla=filas_plantilla,
            )
            return DecisionPostCarga(
                terminado=True,
                ok=bool(ev["ok"]),
                warning=bool(ev.get("warning")),
                motivo=str(ev["motivo"]),
                estado=EstadoEsperaPostCarga(
                    estable_desde=est.estable_desde,
                    ultimo_agregados=agg,
                    vio_en_curso=est.vio_en_curso,
                ),
            )
        return DecisionPostCarga(
            terminado=False,
            ok=False,
            motivo="esperando_estable",
            estado=est,
        )

    return DecisionPostCarga(
        terminado=False,
        ok=False,
        motivo="contador_cambio",
        estado=EstadoEsperaPostCarga(
            estable_desde=ahora,
            ultimo_agregados=agg,
            vio_en_curso=est.vio_en_curso,
        ),
    )


def resumen_desde_decision(
    lectura: LecturaPostCarga,
    decision: DecisionPostCarga,
    *,
    esperado: int | None,
    elapsed_s: float,
    filas_plantilla: int | None = None,
) -> dict[str, Any]:
    """Dict compatible con exigir_ok_post_carga / asegurar_resultado_post_carga."""
    return {
        "ok": bool(decision.ok and decision.terminado),
        "warning": bool(decision.warning),
        "agregados": lectura.agregados,
        "subidos": lectura.subidos,
        "errores": lectura.errores,
        "modals": lectura.modals,
        "en_curso": lectura.en_curso,
        "esperado": esperado,
        "minimo_razonable": esperado,
        "filas_plantilla": filas_plantilla,
        "motivo": decision.motivo,
        "elapsed_s": elapsed_s,
        "criterio_esperado": (
            "min(filas_plantilla, pdfs_unicos[, ruts_unicos])"
            if esperado is not None
            else "estabilizacion_sin_esperado"
        ),
    }
