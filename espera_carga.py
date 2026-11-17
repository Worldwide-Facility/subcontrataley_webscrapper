"""Lógica pura de espera de uploads y post-carga masiva (testeable sin Selenium).

Criterios (producción 17-nov: cerrar al ver el primer 'Documentos Agregados'
dejó filas sin subir mientras el portal seguía con 'Se esta realizando la carga
masiva'):

1) Dropzone: todos los archivos esperados visibles, sin processing/progreso.
2) Post 'Realizar Carga Masiva': NO basta la primera aparición del contador.
   Hay que esperar a que desaparezca el mensaje en curso y que el contador
   alcance el esperado o se estabilice X segundos. La barra al 100% no cuenta
   (bug del portal: nunca llega).

'esperado' post-carga = filas de la plantilla Excel subida (docs principales),
no el total de PDFs auxiliares (p.ej. transferencias en liquidaciones).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


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


def dropzone_carga_completa(
    visibles: list[dict[str, Any]],
    esperados: list[str],
) -> dict[str, Any]:
    """
    Compara previews del dropzone con la lista esperada (nombres exactos).

    OK solo si: todos presentes, ninguno con error y ninguno aún procesando.
    Un nombre cuenta OK si hay al menos una preview sin error (y no solo
    processing sin success).
    """
    esperados_u = list(dict.fromkeys(esperados))
    ok_names = {
        v["name"]
        for v in visibles
        if v.get("name")
        and not v.get("error")
        and (v.get("success") or not v.get("processing"))
    }
    err_names = {v["name"] for v in visibles if v.get("name") and v.get("error")}
    proc_names = {
        v["name"]
        for v in visibles
        if v.get("name") and v.get("processing") and not v.get("success")
    }
    faltan = [n for n in esperados_u if n not in ok_names and n not in err_names]
    con_error = [n for n in esperados_u if n in err_names and n not in ok_names]
    procesando = [n for n in esperados_u if n in proc_names and n not in ok_names]
    extra = sorted({v["name"] for v in visibles if v.get("name")} - set(esperados_u))
    return {
        "esperados": len(esperados_u),
        "visibles": len({v["name"] for v in visibles if v.get("name")}),
        "ok_names": sorted(ok_names & set(esperados_u)),
        "faltan": faltan,
        "con_error": con_error,
        "procesando": procesando,
        "extra": extra,
        "ok": not faltan and not con_error and not procesando,
    }


def zona_upload_lista(
    estado: dict[str, Any],
    *,
    n_min: int | None = None,
) -> bool:
    """
    True si la zona no tiene progreso/processing pendiente y el conteo alcanza n_min.

    No acepta complete==0 como atajo: hace falta items (y complete si el portal
    marca success) o, como mínimo, progress==0 y processing==0 con items>=n_min.
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
    if errors > 0 and complete < items:
        return False
    if items <= 0:
        return False
    # Si hay marcas success/complete, exigir cobertura razonable
    if complete > 0 and n_min is not None and complete < n_min:
        return False
    return True


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
        en_curso = bool(
            re_en_curso(blob)
        )
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
) -> DecisionPostCarga:
    """
    Un paso de la máquina de espera post-carga (puro / simulable).

    Termina cuando:
      - no hay mensaje en curso, Y
      - agregados >= esperado, O
      - agregados se mantuvo igual durante estable_s segundos (tras no estar en curso).

    Si termina estable por debajo de esperado → terminado=True, ok=False.
    Nunca usa la barra de progreso al 100% como criterio.
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
        return DecisionPostCarga(
            terminado=True,
            ok=True,
            motivo=f"alcanzado_esperado:{agg}>={int(esperado)}",
            estado=EstadoEsperaPostCarga(
                estable_desde=ahora,
                ultimo_agregados=agg,
                vio_en_curso=est.vio_en_curso,
            ),
        )

    if est.ultimo_agregados == agg and est.estable_desde is not None:
        if ahora - est.estable_desde >= float(estable_s):
            ok = esperado is None or agg >= int(esperado)
            if ok:
                motivo = f"estable_ok:{agg}"
            else:
                motivo = f"estable_bajo_esperado:{agg}<{int(esperado)}"
            return DecisionPostCarga(
                terminado=True,
                ok=ok,
                motivo=motivo,
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
) -> dict[str, Any]:
    """Dict compatible con exigir_ok_post_carga / asegurar_resultado_post_carga."""
    return {
        "ok": bool(decision.ok and decision.terminado),
        "agregados": lectura.agregados,
        "subidos": lectura.subidos,
        "errores": lectura.errores,
        "modals": lectura.modals,
        "en_curso": lectura.en_curso,
        "esperado": esperado,
        "motivo": decision.motivo,
        "elapsed_s": elapsed_s,
        "criterio_esperado": (
            "filas_plantilla_docs_principales"
            if esperado is not None
            else "estabilizacion_sin_esperado"
        ),
    }
