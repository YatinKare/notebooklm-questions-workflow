#!/usr/bin/env bash
# Usage: ./infra/deploy-frontend.sh [--project <cf-project-name>]
# Builds the SvelteKit static site and deploys to Cloudflare Pages.
# Requires: wrangler authenticated (run `npx wrangler login` once first).
# PUBLIC_API_BASE must be set in frontend/.env before running this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"
BUILD_DIR="$FRONTEND_DIR/build"

CF_PROJECT="${1:-notebooklm-questions}"

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
echo "     gcloud run services update screenshot-answers \\"
echo "       --update-env-vars CORS_ORIGIN=<pages-url> \\"
echo "       --project notebooklm-questions-workflow \\"
echo "       --region us-central1"
