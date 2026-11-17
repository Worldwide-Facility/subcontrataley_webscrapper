"""Orquestación del auditor Subcontrataley."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from auditor.config import WORKFLOW_POR_TIPO, AuditorConfig, cargar_config
from auditor.cruce import (
    auditar_trabajador,
    candidatos_transferencia,
    generar_plan_descargas,
)
from auditor.finiquitos import consultar_finiquitos
from auditor.inventario import construir_inventarios
from auditor.modelos import FilaAuditoria
from auditor.plantilla import leer_trabajadores_plantilla, obtener_plantilla
from auditor.reporte import escribir_reporte_local, subir_reporte
from auditor.transferencias import crear_transferencias_faltantes
from auditor.workflows_cliente import WorkflowsCliente
from gcs_docs import rut_cuerpo

logger = logging.getLogger(__name__)


def _aplicar_manifiestos(
    filas: list[FilaAuditoria],
    manifiestos: list[dict[str, Any]],
) -> None:
    """Copia estado post-descarga (subido|ya_existia|no_en_portal|error) a cada fila."""
    por_rut: dict[str, dict[str, str]] = {}
    for man in manifiestos:
        if not man:
            continue
        for item in man.get("resultados") or []:
            c = rut_cuerpo(item.get("rut") or "")
            if not c:
                continue
            estado = str(item.get("estado") or "")
            # Inferir tipo desde job del manifiesto
            job = str(man.get("job") or "")
            tipo = None
            if "liquidacion" in job:
                tipo = "liquidacion"
            elif "asistencia" in job:
                tipo = "asistencia"
            elif "cotizacion" in job:
                tipo = "cotizaciones"
            elif "finiquito" in job:
                tipo = "finiquito"
            elif "contrato" in job:
                tipo = "contrato"
            if tipo:
                por_rut.setdefault(c, {})[tipo] = estado
    for f in filas:
        f.post_descarga.update(por_rut.get(f.trabajador.rut_cuerpo, {}))


def correr_auditoria(
    cfg: AuditorConfig | None = None,
    *,
    workflows: WorkflowsCliente | None = None,
    plantilla_path: Path | None = None,
    skip_portal: bool = False,
) -> dict[str, Any]:
    """
    Pipeline completo según AUDITOR_MODO.

    dry-run (default): plantilla → cruce → plan → reporte (sin lanzar ni crear).
    descargar: + workflows en serie + re-auditoría + reporte.
    completo: + transferencias + sync final.
    """
    cfg = cfg or cargar_config()
    logger.info(
        "=== Auditor Subcontrataley | periodo=%s modo=%s tipos=%s solicitud=%s ===",
        cfg.periodo_yyyy_mm,
        cfg.modo,
        ",".join(cfg.tipos),
        cfg.solicitud_id,
    )

    with tempfile.TemporaryDirectory(prefix="auditor_scl_") as tmp_name:
        tmp = Path(tmp_name)

        # 1) Plantilla
        if plantilla_path is not None:
            plantilla = Path(plantilla_path)
        else:
            plantilla = obtener_plantilla(
                cfg.periodo,
                tmp / "plantilla",
                solo_gcs=skip_portal,
            )
        trabajadores = leer_trabajadores_plantilla(plantilla)
        if not trabajadores:
            raise RuntimeError("Plantilla sin trabajadores en hoja Documentos")

        # 2) Finiquitos desde reclutamiento (NO fecha_fin_contrato)
        fin_map = consultar_finiquitos(
            [t.rut_cuerpo for t in trabajadores],
            cfg.periodo,
            project=cfg.project_id,
        )
        emp_rec = {c: e.empresa for c, e in fin_map.items() if e.empresa}
        cecos_rec = {c: e.cecos for c, e in fin_map.items() if e.cecos}

        # 3) Inventario GCS + BQ (+ líquido)
        inventarios = construir_inventarios(
            trabajadores,
            periodo=cfg.periodo,
            bucket_name=cfg.bucket,
            project=cfg.project_id,
            leer_liquidos=True,
            empresas_reclutamiento=emp_rec,
            cecos_reclutamiento=cecos_rec,
        )

        # 4) Cruce
        filas: list[FilaAuditoria] = []
        for t in trabajadores:
            inv = inventarios.get(t.rut_cuerpo)
            assert inv is not None
            filas.append(
                auditar_trabajador(
                    t,
                    periodo=cfg.periodo,
                    tipos=cfg.tipos,
                    inventario=inv,
                    finiquito=fin_map.get(t.rut_cuerpo),
                )
            )

        plan = generar_plan_descargas(
            filas,
            periodo=cfg.periodo,
            solicitud_id=cfg.solicitud_id,
            workflow_por_tipo=WORKFLOW_POR_TIPO,
        )
        logger.info(
            "Cruce: %s trabajadores, %s con faltantes, %s lotes de descarga",
            len(filas),
            sum(1 for f in filas if f.faltantes),
            len(plan),
        )

        transferencias_res: list[dict] = []
        ejecuciones: list[Any] = []
        manifiestos: list[dict] = []
        tipos_tocados: list[str] = []

        # 5) Descargas dirigidas
        if cfg.lanza_descargas and plan:
            wf = workflows or WorkflowsCliente(
                project=cfg.project_id, region=cfg.region
            )
            # Cotizaciones: incluir_industry siempre false a nivel lote
            ejecuciones = wf.lanzar_lotes_en_serie(
                plan,
                forzar=cfg.forzar_descarga,
                dry_run=cfg.dry_run_workflows,
                incluir_industry=cfg.incluir_industry,
                esperar=cfg.esperar_workflows,
                abortar_si_ocupado=cfg.abortar_si_ocupado,
                poll_segundos=cfg.poll_segundos,
                timeout_segundos=cfg.timeout_workflow_segundos,
            )
            tipos_tocados.extend(L.tipo_auditor for L in plan)
            for lote in plan:
                man = wf.leer_manifiesto(
                    bucket_name=cfg.bucket,
                    gcs_base_path=cfg.gcs_base_path,
                    solicitud_id=lote.solicitud_id,
                    tipo_auditor=lote.tipo_auditor,
                )
                if man:
                    manifiestos.append(man)
            _aplicar_manifiestos(filas, manifiestos)

        # 6) Transferencias (completo o flag)
        if cfg.debe_crear_transferencias and "transferencia" in cfg.tipos:
            cands = candidatos_transferencia(filas)
            logger.info("Candidatos a certificado transferencia: %s", len(cands))
            transferencias_res = crear_transferencias_faltantes(
                cands,
                periodo=cfg.periodo,
                bucket_name=cfg.bucket,
                project=cfg.project_id,
                dry_run=False,
            )
            if any(r.get("resultado") == "subido" for r in transferencias_res):
                tipos_tocados.append("transferencia")

        # 7) Sync único al final
        if cfg.lanza_descargas and tipos_tocados and not cfg.dry_run_workflows:
            wf = workflows or WorkflowsCliente(
                project=cfg.project_id, region=cfg.region
            )
            try:
                wf.sync_final(tipos_tocados)
            except Exception as exc:
                logger.warning("Sync final falló (se continúa con reporte): %s", exc)

        # 8) Re-auditoría final si se tocó algo
        if cfg.lanza_descargas or cfg.debe_crear_transferencias:
            inventarios2 = construir_inventarios(
                trabajadores,
                periodo=cfg.periodo,
                bucket_name=cfg.bucket,
                project=cfg.project_id,
                leer_liquidos=True,
                empresas_reclutamiento=emp_rec,
                cecos_reclutamiento=cecos_rec,
            )
            filas_final: list[FilaAuditoria] = []
            for t in trabajadores:
                inv = inventarios2.get(t.rut_cuerpo)
                assert inv is not None
                fila = auditar_trabajador(
                    t,
                    periodo=cfg.periodo,
                    tipos=cfg.tipos,
                    inventario=inv,
                    finiquito=fin_map.get(t.rut_cuerpo),
                )
                # conservar post_descarga previo
                prev = next(
                    (x for x in filas if x.trabajador.rut_cuerpo == t.rut_cuerpo),
                    None,
                )
                if prev:
                    fila.post_descarga = dict(prev.post_descarga)
                filas_final.append(fila)
            filas = filas_final

        # 9) Reporte
        paths = escribir_reporte_local(
            filas,
            periodo_yyyy_mm=cfg.periodo_yyyy_mm,
            tipos=list(cfg.tipos),
            dest_dir=tmp / "reporte",
            plan=plan,
            transferencias=transferencias_res,
            modo=cfg.modo,
            solicitud_id=cfg.solicitud_id,
        )
        # Copiar también fuera de tmp para debugging local
        out_local = Path(
            tempfile.gettempdir()
        ) / f"auditoria_subcontrataley_{cfg.periodo_yyyy_mm}"
        out_local.mkdir(parents=True, exist_ok=True)
        saved = {}
        for k, p in paths.items():
            dest = out_local / p.name
            dest.write_bytes(p.read_bytes())
            saved[k] = dest

        uris = []
        try:
            uris = subir_reporte(
                saved,
                bucket_name=cfg.bucket,
                prefijo=cfg.prefijo_reporte(),
                project=cfg.project_id,
            )
        except Exception as exc:
            logger.warning("No se pudo subir reporte a GCS: %s", exc)

        return {
            "periodo": cfg.periodo_yyyy_mm,
            "modo": cfg.modo,
            "solicitud_id": cfg.solicitud_id,
            "trabajadores": len(filas),
            "faltantes": sum(1 for f in filas if f.faltantes),
            "lotes": len(plan),
            "ejecuciones": [
                {"workflow": e.workflow, "name": e.execution_name, "estado": e.estado}
                for e in ejecuciones
            ],
            "transferencias": transferencias_res,
            "reporte_uris": uris,
            "reporte_local": str(out_local),
            "plan": [
                {
                    "tipo": L.tipo_auditor,
                    "workflow": L.workflow,
                    "empresa": L.empresa,
                    "n_ruts": len(L.ruts),
                    "argument": L.argument_objetivo(
                        incluir_industry=(
                            False
                            if L.tipo_auditor == "cotizaciones"
                            else cfg.incluir_industry
                        )
                    ),
                }
                for L in plan
            ],
        }
