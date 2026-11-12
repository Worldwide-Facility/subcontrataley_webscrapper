#!/bin/bash
# Crear/actualizar Cloud Run Jobs de Subcontrataley (misma forma que
# cargas_documentos_instalaciones_webscrapper/deploy_jobs.sh).
#
# Una imagen → N jobs con distinto --args=*_cloudrun.py
#
# Credenciales del portal / tokens: configuralas una vez en Consola o con
# gcloud run jobs update ... --update-env-vars=SUBCONTRATALEY_...
# (este script solo setea vars base).

set -e

PROJECT_ID="worldwide-470917"
REGION="us-east1"
IMAGE="gcr.io/${PROJECT_ID}/subcontrataley-webscrapper:latest"
SERVICE_ACCOUNT="webscrapper@${PROJECT_ID}.iam.gserviceaccount.com"
ENV_BASE="GCS_BUCKET_NAME=worldwide-documentos-instalaciones,HEADLESS=true,IMPLICIT_WAIT=10,EXPLICIT_WAIT=40,INGRESO_CARGA_TIMEOUT=600"

echo "🚀 Desplegando Cloud Run Jobs Subcontrataley..."

gcloud config set project "${PROJECT_ID}"

echo "📦 Construyendo imagen Docker..."
gcloud builds submit --tag "${IMAGE}"

deploy_job() {
    local JOB_NAME=$1
    local SCRIPT_NAME=$2

    echo "🔧 Desplegando job: ${JOB_NAME} → ${SCRIPT_NAME}"

    if gcloud run jobs update "${JOB_NAME}" \
        --image="${IMAGE}" \
        --region="${REGION}" \
        --update-env-vars="${ENV_BASE}" \
        --service-account="${SERVICE_ACCOUNT}" \
        --task-timeout=3600 \
        --memory=4Gi \
        --cpu=2 \
        --max-retries=1 \
        --command=python \
        --args="${SCRIPT_NAME}" 2>/dev/null; then
        echo "✅ Job ${JOB_NAME} actualizado"
    else
        echo "📝 Creando nuevo job ${JOB_NAME}..."
        gcloud run jobs create "${JOB_NAME}" \
            --image="${IMAGE}" \
            --region="${REGION}" \
            --set-env-vars="${ENV_BASE}" \
            --service-account="${SERVICE_ACCOUNT}" \
            --task-timeout=3600 \
            --memory=4Gi \
            --cpu=2 \
            --max-retries=1 \
            --command=python \
            --args="${SCRIPT_NAME}"
        echo "✅ Job ${JOB_NAME} creado"
    fi
}

deploy_job "subcontrataley-libro-asistencia" "libro_asistencia_cloudrun.py"
deploy_job "subcontrataley-ingreso-trabajadores" "ingreso_trabajadores_cloudrun.py"
deploy_job "subcontrataley-liquidaciones" "liquidaciones_cloudrun.py"
deploy_job "subcontrataley-pagos-afp-afc" "pagos_afp_afc_cloudrun.py"
deploy_job "subcontrataley-pagos-isapre-fonasa" "pagos_isapre_fonasa_cloudrun.py"
deploy_job "subcontrataley-pagos-mutualidades" "pagos_mutualidades_cloudrun.py"
deploy_job "subcontrataley-pagos-cajas" "pagos_cajas_compensacion_cloudrun.py"

# 15 docs vigentes: timeout más largo (mismo helper, timeout distinto)
echo "🔧 Desplegando job: subcontrataley-documentos-trabajador → documentos_trabajador_cloudrun.py"
if gcloud run jobs update "subcontrataley-documentos-trabajador" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --update-env-vars="${ENV_BASE}" \
    --service-account="${SERVICE_ACCOUNT}" \
    --task-timeout=10800 \
    --memory=4Gi \
    --cpu=2 \
    --max-retries=1 \
    --command=python \
    --args="documentos_trabajador_cloudrun.py" 2>/dev/null; then
    echo "✅ Job subcontrataley-documentos-trabajador actualizado"
else
    echo "📝 Creando nuevo job subcontrataley-documentos-trabajador..."
    gcloud run jobs create "subcontrataley-documentos-trabajador" \
        --image="${IMAGE}" \
        --region="${REGION}" \
        --set-env-vars="${ENV_BASE}" \
        --service-account="${SERVICE_ACCOUNT}" \
        --task-timeout=10800 \
        --memory=4Gi \
        --cpu=2 \
        --max-retries=1 \
        --command=python \
        --args="documentos_trabajador_cloudrun.py"
    echo "✅ Job subcontrataley-documentos-trabajador creado"
fi

echo "✅ Todos los jobs desplegados."
echo ""
echo "Secrets (una vez, no los pisa el update base):"
echo "  gcloud run jobs update subcontrataley-libro-asistencia --region=${REGION} \\"
echo "    --update-env-vars=\"SUBCONTRATALEY_USERNAME=...,SUBCONTRATALEY_PASSWORD=...\""
echo "  gcloud run jobs update subcontrataley-ingreso-trabajadores --region=${REGION} \\"
echo "    --update-env-vars=\"SUBCONTRATALEY_USERNAME=...,SUBCONTRATALEY_PASSWORD=...,TOKEN_CR_CONTRATOS=...\""
echo "  gcloud run jobs update subcontrataley-documentos-trabajador --region=${REGION} \\"
echo "    --update-env-vars=\"SUBCONTRATALEY_USERNAME=...,SUBCONTRATALEY_PASSWORD=...,DRY_RUN=true\""
echo ""
echo "Ejecutar:"
echo "  gcloud run jobs execute subcontrataley-libro-asistencia --region=${REGION}"
echo "  gcloud run jobs execute subcontrataley-ingreso-trabajadores --region=${REGION}"
echo "  gcloud run jobs execute subcontrataley-documentos-trabajador --region=${REGION}"
