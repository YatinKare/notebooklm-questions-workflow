#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  infra/deploy-frontend.sh [CF_PROJECT]

Builds the SvelteKit static site and deploys to Cloudflare Pages.
Requires: wrangler authenticated with `npx wrangler login`.

Optional environment variables:
  CLOUD_RUN_SERVICE   Service name to print in the CORS update command.
  GCP_PROJECT_ID      Project ID to print in the CORS update command.
  GCP_REGION          Region to print in the CORS update command.

PUBLIC_API_BASE must be set in frontend/.env before running this script.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"
BUILD_DIR="$FRONTEND_DIR/build"

CF_PROJECT="${1:-notebooklm-questions}"
CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:-<cloud-run-service>}"
GCP_PROJECT_ID="${GCP_PROJECT_ID:-<gcp-project-id>}"
GCP_REGION="${GCP_REGION:-<gcp-region>}"

echo "==> Building frontend..."
cd "$FRONTEND_DIR"
npm install --prefer-offline
npm run build

echo "==> Deploying to Cloudflare Pages project: $CF_PROJECT"
npx wrangler pages deploy "$BUILD_DIR" --project-name "$CF_PROJECT"

echo ""
echo "Done. After first deploy:"
echo "  1. Copy the Pages URL shown above."
echo "  2. Update CORS_ORIGIN in Cloud Run:"
echo "     gcloud run services update ${CLOUD_RUN_SERVICE} \\"
echo "       --update-env-vars CORS_ORIGIN=<pages-url> \\"
echo "       --project ${GCP_PROJECT_ID} \\"
echo "       --region ${GCP_REGION}"
