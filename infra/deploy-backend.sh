#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  infra/deploy-backend.sh PROJECT_ID REGION STORAGE_BUCKET NOTEBOOK_ID [SERVICE_NAME]

Required:
  PROJECT_ID       Google Cloud project ID.
  REGION           Cloud Run region, for example us-central1.
  STORAGE_BUCKET   Cloud Storage bucket mounted at /mnt/data.
  NOTEBOOK_ID      NotebookLM notebook ID.

Optional environment variables:
  SERVICE_NAME           Default: screenshot-answers
  AR_REPOSITORY          Default: notebooklm-questions
  MOUNT_PATH             Default: /mnt/data
  NLM_COOKIE_PATH        Default: /mnt/data/profiles/default/cookies.json
  DB_PATH                Default: /mnt/data/app.db
  CORS_ORIGIN            Default: *
  GOOGLE_API_KEY_SECRET  Default: GOOGLE_API_KEY
  EXTRACTOR_MODEL        Default: gemini-2.5-flash
  VERIFIER_MODEL         Default: gemini-2.5-flash
  SERVICE_ACCOUNT        Optional Cloud Run runtime service account email
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 4 || $# -gt 5 ]]; then
  usage >&2
  exit 64
fi

PROJECT_ID="$1"
REGION="$2"
STORAGE_BUCKET="$3"
NOTEBOOK_ID="$4"
SERVICE_NAME="${5:-${SERVICE_NAME:-screenshot-answers}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

AR_REPOSITORY="${AR_REPOSITORY:-notebooklm-questions}"
MOUNT_PATH="${MOUNT_PATH:-/mnt/data}"
NLM_COOKIE_PATH="${NLM_COOKIE_PATH:-${MOUNT_PATH}/profiles/default/cookies.json}"
DB_PATH="${DB_PATH:-${MOUNT_PATH}/app.db}"
CORS_ORIGIN="${CORS_ORIGIN:-*}"
GOOGLE_API_KEY_SECRET="${GOOGLE_API_KEY_SECRET:-GOOGLE_API_KEY}"
EXTRACTOR_MODEL="${EXTRACTOR_MODEL:-gemini-2.5-flash}"
VERIFIER_MODEL="${VERIFIER_MODEL:-gemini-2.5-flash}"
VOLUME_NAME="app-data"
declare -a SERVICE_ACCOUNT_FLAG
SERVICE_ACCOUNT_FLAG=()
if [[ -n "${SERVICE_ACCOUNT:-}" ]]; then
  SERVICE_ACCOUNT_FLAG=(--service-account "${SERVICE_ACCOUNT}")
fi

require_mounted_container_path() {
  local name="$1"
  local value="$2"

  if [[ "${value}" != /* ]]; then
    echo "${name} must be an absolute container path, got: ${value}" >&2
    exit 64
  fi

  case "${value}" in
    "${MOUNT_PATH}" | "${MOUNT_PATH}/"*) ;;
    *)
      cat >&2 <<EOF
${name} must point inside the Cloud Run mounted volume (${MOUNT_PATH}), got:
  ${value}

This usually means a local .env value such as /Users/... leaked into the deploy
environment. Set ${name} to the container path on the mounted bucket instead.
EOF
      exit 64
      ;;
  esac
}

require_mounted_container_path "NLM_COOKIE_PATH" "${NLM_COOKIE_PATH}"
require_mounted_container_path "DB_PATH" "${DB_PATH}"

if git -C "${ROOT_DIR}" rev-parse --short HEAD >/dev/null 2>&1; then
  IMAGE_TAG="$(git -C "${ROOT_DIR}" rev-parse --short HEAD)"
else
  IMAGE_TAG="$(date +%Y%m%d%H%M%S)"
fi

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPOSITORY}/${SERVICE_NAME}:${IMAGE_TAG}"
CLOUDBUILD_CONFIG="$(mktemp)"
trap 'rm -f "${CLOUDBUILD_CONFIG}"' EXIT

echo "Ensuring Artifact Registry repository ${AR_REPOSITORY} exists..."
if ! gcloud artifacts repositories describe "${AR_REPOSITORY}" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${AR_REPOSITORY}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --repository-format docker \
    --description "Container images for notebooklm-questions-workflow"
fi

echo "Building ${IMAGE} from infra/Dockerfile..."
cat > "${CLOUDBUILD_CONFIG}" <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -f
      - infra/Dockerfile
      - -t
      - ${IMAGE}
      - .
images:
  - ${IMAGE}
YAML

gcloud builds submit "${ROOT_DIR}" \
  --project "${PROJECT_ID}" \
  --config "${CLOUDBUILD_CONFIG}"

echo "Deploying ${SERVICE_NAME} to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}" \
  --execution-environment gen2 \
  --memory 1Gi \
  --cpu 1 \
  --no-cpu-throttling \
  --concurrency 10 \
  --min-instances 1 \
  --max-instances 1 \
  --allow-unauthenticated \
  ${SERVICE_ACCOUNT_FLAG[@]+"${SERVICE_ACCOUNT_FLAG[@]}"} \
  --set-env-vars "NOTEBOOK_ID=${NOTEBOOK_ID},NLM_COOKIE_PATH=${NLM_COOKIE_PATH},DB_PATH=${DB_PATH},CORS_ORIGIN=${CORS_ORIGIN},NLM_MCP_COMMAND=notebooklm-mcp,EXTRACTOR_MODEL=${EXTRACTOR_MODEL},VERIFIER_MODEL=${VERIFIER_MODEL}" \
  --set-secrets "GOOGLE_API_KEY=${GOOGLE_API_KEY_SECRET}:latest" \
  --add-volume "name=${VOLUME_NAME},type=cloud-storage,bucket=${STORAGE_BUCKET}" \
  --add-volume-mount "volume=${VOLUME_NAME},mount-path=${MOUNT_PATH}"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --format 'value(status.url)')"

echo "Checking ${SERVICE_URL}/health..."
HEALTH_JSON="$(curl -fsS "${SERVICE_URL}/health")"
python3 - "${HEALTH_JSON}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if payload.get("status") != "ok" or payload.get("db") != "ok" or payload.get("mcp") != "ok":
    raise SystemExit(f"health check failed: {payload}")
print(f"health check passed: {payload}")
PY

echo "Backend URL: ${SERVICE_URL}"
