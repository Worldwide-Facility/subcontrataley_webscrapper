"""Cliente GCP Workflows / Cloud Run para descargas dirigidas (contrato F1).

Encapsula el argument `objetivo` del PR de fase 1 en
Worldwide-Facility/cargas_documentos_instalaciones_webscrapper
para poder ajustar el contrato en un solo módulo.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import google.auth
from google.auth.transport.requests import AuthorizedSession

from auditor.config import (
    JOB_MANIFIESTO_POR_TIPO,
    PROJECT_ID,
    REGION,
    SYNC_TIPO_POR_AUDITOR,
)
from auditor.modelos import LoteDescarga, construir_argumento_workflow

logger = logging.getLogger(__name__)

# Workflows que implican scrapers ControlRoll / Previred (no cancelar ajenos).
WORKFLOWS_CONTROLROLL_PREVIRED = frozenset(
    {
        "documentos-liquidaciones",
        "documentos-asistencias",
        "documentos-cotizaciones",
        "documentos-finiquitos",
        "documentos-contratos",
        "documentos-anexos",
        "documentos-jornadas",
    }
)

# Tipos que no pueden correr en paralelo entre sí
CONFLICTOS = {
    "liquidacion": frozenset({"asistencia"}),
    "asistencia": frozenset({"liquidacion"}),
}


@dataclass
class EjecucionWorkflow:
    workflow: str
    execution_name: str
    argument: dict[str, Any]
    estado: str = "STARTED"


class WorkflowsCliente:
    """
    Interfaz delgada sobre Workflows Executions API + Cloud Run Jobs.

    Nunca cancela ejecuciones ajenas: solo espera o aborta con mensaje.
    """

    def __init__(
        self,
        *,
        project: str = PROJECT_ID,
        region: str = REGION,
        session: AuthorizedSession | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.project = project
        self.region = region
        if session is None:
            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            session = AuthorizedSession(creds)
        self.session = session
        self.sleep = sleep_fn

    # --- helpers HTTP -------------------------------------------------

    def _wf_base(self, workflow: str) -> str:
        return (
            f"https://workflowexecutions.googleapis.com/v1/"
            f"projects/{self.project}/locations/{self.region}/"
            f"workflows/{workflow}"
        )

    def _run_base(self) -> str:
        return (
            f"https://run.googleapis.com/v2/projects/{self.project}/"
            f"locations/{self.region}"
        )

    # --- listado / espera ---------------------------------------------

    def listar_ejecuciones_activas(self, workflow: str) -> list[dict[str, Any]]:
        url = f"{self._wf_base(workflow)}/executions"
        # filter ACTIVE
        params = {"filter": 'state="ACTIVE"', "pageSize": 50}
        resp = self.session.get(url, params=params, timeout=60)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("executions") or [])

    def hay_controlroll_previred_activo(
        self,
        *,
        extra_workflows: Iterable[str] | None = None,
    ) -> list[str]:
        """Devuelve nombres de workflows con ejecución ACTIVE."""
        names = set(WORKFLOWS_CONTROLROLL_PREVIRED)
        if extra_workflows:
            names.update(extra_workflows)
        ocupados = []
        for wf in sorted(names):
            try:
                act = self.listar_ejecuciones_activas(wf)
            except Exception as exc:
                logger.warning("No pude listar ejecuciones de %s: %s", wf, exc)
                continue
            if act:
                ocupados.append(wf)
        return ocupados

    def esperar_libre(
        self,
        *,
        abortar: bool = False,
        poll_segundos: int = 30,
        timeout_segundos: int = 7200,
        tip: str = "",
    ) -> None:
        """Espera a que no haya scrapers ControlRoll/Previred activos."""
        inicio = time.time()
        while True:
            ocupados = self.hay_controlroll_previred_activo()
            if not ocupados:
                return
            msg = (
                "Hay ejecuciones ControlRoll/Previred activas: "
                + ", ".join(ocupados)
                + (f" ({tip})" if tip else "")
            )
            if abortar:
                raise RuntimeError(msg + ". Abortando (AUDITOR_ABORTAR_SI_OCUPADO=1).")
            if time.time() - inicio > timeout_segundos:
                raise TimeoutError(msg + f". Timeout {timeout_segundos}s.")
            logger.info("%s — esperando %ss…", msg, poll_segundos)
            self.sleep(poll_segundos)

    # --- lanzamiento --------------------------------------------------

    def construir_argumento_lote(
        self,
        lote: LoteDescarga,
        *,
        forzar: bool = False,
        dry_run: bool = False,
        incluir_industry: bool = False,
        sync: str = "no",
    ) -> dict[str, Any]:
        """Delega al contrato F1 encapsulado en modelos."""
        return construir_argumento_workflow(
            ruts=lote.ruts,
            periodos=lote.periodo,
            empresa=lote.empresa,
            fuente="lista",
            forzar="1" if forzar else "0",
            dry_run="1" if dry_run else "0",
            solicitud_id=lote.solicitud_id,
            incluir_industry=incluir_industry,
            sync=sync,
        )

    def lanzar_workflow(
        self,
        workflow: str,
        argument: dict[str, Any],
    ) -> EjecucionWorkflow:
        url = f"{self._wf_base(workflow)}/executions"
        body = {"argument": json.dumps(argument, ensure_ascii=False)}
        logger.info(
            "Lanzando workflow %s solicitud=%s ruts=%s",
            workflow,
            (argument.get("objetivo") or {}).get("solicitud_id"),
            len(((argument.get("objetivo") or {}).get("ruts") or "").split(","))
            if (argument.get("objetivo") or {}).get("ruts")
            else 0,
        )
        resp = self.session.post(url, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        name = data.get("name") or ""
        return EjecucionWorkflow(
            workflow=workflow,
            execution_name=name,
            argument=argument,
            estado=data.get("state") or "ACTIVE",
        )

    def esperar_ejecucion(
        self,
        execution_name: str,
        *,
        poll_segundos: int = 30,
        timeout_segundos: int = 54000,
    ) -> dict[str, Any]:
        url = f"https://workflowexecutions.googleapis.com/v1/{execution_name}"
        inicio = time.time()
        while True:
            resp = self.session.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            state = data.get("state") or ""
            if state in ("SUCCEEDED", "FAILED", "CANCELLED", "UNAVAILABLE"):
                return data
            if time.time() - inicio > timeout_segundos:
                raise TimeoutError(
                    f"Timeout esperando {execution_name} ({timeout_segundos}s); "
                    "NO se cancela la ejecución ajena."
                )
            self.sleep(poll_segundos)

    def lanzar_lotes_en_serie(
        self,
        lotes: list[LoteDescarga],
        *,
        forzar: bool = False,
        dry_run: bool = False,
        incluir_industry: bool = False,
        esperar: bool = True,
        abortar_si_ocupado: bool = False,
        poll_segundos: int = 30,
        timeout_segundos: int = 54000,
    ) -> list[EjecucionWorkflow]:
        """
        Lanza lotes uno tras otro (nunca en paralelo).

        sync=no en cada uno; el orquestador hace un sync final.
        Si hay liquidacion y asistencia en la cola, ya van en serie y además
        se espera a que no haya scrapers activos antes de cada uno.
        """
        resultados: list[EjecucionWorkflow] = []
        for lote in lotes:
            if not lote.ruts:
                continue
            tip = f"{lote.tipo_auditor}/{lote.empresa}"
            self.esperar_libre(
                abortar=abortar_si_ocupado,
                poll_segundos=poll_segundos,
                tip=tip,
            )
            # Guardrail adicional: no solapar liquidaciones con asistencias
            conflictos = CONFLICTOS.get(lote.tipo_auditor, frozenset())
            if conflictos:
                for otro in conflictos:
                    wf_otro = {
                        "liquidacion": "documentos-liquidaciones",
                        "asistencia": "documentos-asistencias",
                    }.get(otro)
                    if wf_otro and self.listar_ejecuciones_activas(wf_otro):
                        msg = (
                            f"No se puede lanzar {lote.workflow}: hay {wf_otro} activa "
                            f"(liquidaciones y asistencias no simultáneas)."
                        )
                        if abortar_si_ocupado:
                            raise RuntimeError(msg)
                        logger.info("%s Esperando…", msg)
                        while self.listar_ejecuciones_activas(wf_otro):
                            self.sleep(poll_segundos)

            # Cotizaciones: Industry excluido por ahora (incluir_industry=false)
            industry = False if lote.tipo_auditor == "cotizaciones" else incluir_industry
            arg = self.construir_argumento_lote(
                lote,
                forzar=forzar,
                dry_run=dry_run,
                incluir_industry=industry,
                sync="no",
            )

            ej = self.lanzar_workflow(lote.workflow, arg)
            if esperar and not dry_run:
                final = self.esperar_ejecucion(
                    ej.execution_name,
                    poll_segundos=poll_segundos,
                    timeout_segundos=timeout_segundos,
                )
                ej.estado = final.get("state") or ej.estado
            resultados.append(ej)
        return resultados

    def sync_final(self, tipos_tocados: list[str]) -> dict[str, Any] | None:
        """Un solo sync al final con SYNC_TIPOS de lo tocado."""
        sync_tipos = []
        seen = set()
        for t in tipos_tocados:
            st = SYNC_TIPO_POR_AUDITOR.get(t, t)
            if st and st not in seen:
                seen.add(st)
                sync_tipos.append(st)
        if not sync_tipos:
            logger.info("Sync final omitido: ningún tipo tocado")
            return None
        value = ",".join(sync_tipos)
        url = f"{self._run_base()}/jobs/documentos-sync:run"
        body = {
            "overrides": {
                "containerOverrides": [
                    {"env": [{"name": "SYNC_TIPOS", "value": value}]}
                ]
            }
        }
        logger.info("Sync final documentos-sync SYNC_TIPOS=%s", value)
        resp = self.session.post(url, json=body, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def leer_manifiesto(
        self,
        *,
        bucket_name: str,
        gcs_base_path: str,
        solicitud_id: str,
        tipo_auditor: str,
        storage_client=None,
    ) -> dict[str, Any] | None:
        """Lee manifiesto F1: .../ejecuciones_dirigidas/{solicitud}/{job}.json"""
        from google.cloud import storage

        job = JOB_MANIFIESTO_POR_TIPO.get(tipo_auditor, tipo_auditor)
        path = (
            f"{gcs_base_path.strip('/')}/ejecuciones_dirigidas/"
            f"{solicitud_id}/{job}.json"
        )
        client = storage_client or storage.Client(project=self.project)
        blob = client.bucket(bucket_name).blob(path)
        if not blob.exists():
            logger.warning("Manifiesto no encontrado: gs://%s/%s", bucket_name, path)
            return None
        return json.loads(blob.download_as_text(encoding="utf-8"))
