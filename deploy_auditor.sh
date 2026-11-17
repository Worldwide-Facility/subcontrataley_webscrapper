#!/bin/bash
# Despliega SOLO el Cloud Run Job del auditor Subcontrataley.
#
# NO crea ni modifica Cloud Scheduler (no hay horario aún).
# NO ejecuta el job. NO hace merge. NO toca el portal.
#
# Uso:
#   bash deploy_auditor.sh
#
# Credenciales / secrets: configúralas una vez en el Job (no las pisa este script
# en updates posteriores de vars base):
#   gcloud run jobs update subcontrataley-auditor --region=us-east1 \
#     --update-env-vars="SUBCONTRATALEY_USERNAME=...,SUBCONTRATALEY_PASSWORD=..."
#
# Ejecutar (ejemplos en README):
#   gcloud run jobs execute subcontrataley-auditor --region=us-east1 \
#     --update-env-vars="AUDITOR_PERIODO=2026-10,AUDITOR_MODO=dry-run"

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-worldwide-470917}"
REGION="${REGION:-us-east1}"
IMAGE="${IMAGE:-gcr.io/${PROJECT_ID}/subcontrataley-webscrapper:latest}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-webscrapper@${PROJECT_ID}.iam.gserviceaccount.com}"
JOB_NAME="subcontrataley-auditor"
SCRIPT_NAME="auditor_cloudrun.py"

ENV_BASE="GCS_BUCKET_NAME=worldwide-documentos-instalaciones,HEADLESS=true,IMPLICIT_WAIT=10,EXPLICIT_WAIT=40,AUDITOR_MODO=dry-run,AUDITOR_CREAR_TRANSFERENCIAS=0,AUDITOR_INCLUIR_INDUSTRY=false"

echo "==> Proyecto ${PROJECT_ID} / región ${REGION}"
echo "==> Job ${JOB_NAME} → ${SCRIPT_NAME}"
echo "==> SIN Cloud Scheduler"
gcloud config set project "${PROJECT_ID}"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "📦 Construyendo imagen Docker..."
  gcloud builds submit --tag "${IMAGE}"
fi

deploy() {
  if gcloud run jobs update "${JOB_NAME}" \
      --image="${IMAGE}" \
      --region="${REGION}" \
      --update-env-vars="${ENV_BASE}" \
      --service-account="${SERVICE_ACCOUNT}" \
      --task-timeout=86400 \
      --memory=4Gi \
      --cpu=2 \
      --max-retries=0 \
      --command=python \
      --args="${SCRIPT_NAME}" 2>/dev/null; then
    echo "✅ Job ${JOB_NAME} actualizado"
  else
    echo "📝 Creando job ${JOB_NAME}..."
    gcloud run jobs create "${JOB_NAME}" \
      --image="${IMAGE}" \
      --region="${REGION}" \
      --set-env-vars="${ENV_BASE}" \
      --service-account="${SERVICE_ACCOUNT}" \
      --task-timeout=86400 \
      --memory=4Gi \
      --cpu=2 \
      --max-retries=0 \
      --command=python \
      --args="${SCRIPT_NAME}"
    echo "✅ Job ${JOB_NAME} creado"
  fi
}

deploy

echo ""
echo "Listo. NO se creó scheduler. Para ejecutar a mano:"
echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION} \\"
echo "    --update-env-vars=\"AUDITOR_PERIODO=2026-10,AUDITOR_MODO=dry-run\""
echo ""
echo "Dependencia: PR fase 1 de cargas_documentos_instalaciones_webscrapper"
echo "  (argumento objetivo / DOC_* / manifiestos ejecuciones_dirigidas)."
