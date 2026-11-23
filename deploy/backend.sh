#!/usr/bin/env bash
# Build and deploy the API to Cloud Run, from backend/ (Cloud Build builds
# the Dockerfile; backend/.gcloudignore keeps .env out of the upload).
#
# One instance at most (the job worker lives inside it), none when idle;
# CPU stays on while an instance is up, so jobs keep running between
# requests ("instance-based billing").
. "$(dirname "$0")/common.sh"

# Settings are separated by "|" (emails contain "@" and lists contain ",").

ENV_VARS="^|^FIREBASE_PROJECT_ID=${PROJECT}"
ENV_VARS+="|CANVAS_STORAGE=gcs|CANVAS_BUCKET=${BUCKET}"
ENV_VARS+="|CANVAS_ALLOWED_EMAILS=${ALLOWED_EMAILS:-}"
ENV_VARS+="|CANVAS_LIMIT_TEXT_PER_DAY=${LIMIT_TEXT_PER_DAY:-200}"
ENV_VARS+="|CANVAS_LIMIT_IMAGES_PER_DAY=${LIMIT_IMAGES_PER_DAY:-50}"
ENV_VARS+="|CANVAS_LIMIT_VIDEOS_PER_DAY=${LIMIT_VIDEOS_PER_DAY:-10}"
ENV_VARS+="|CANVAS_GENERATION_OFF=${GENERATION_OFF:-0}"

gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --source "$ROOT/backend" \
  --service-account "$SA" \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 1 \
  --no-cpu-throttling --cpu 1 --memory 1Gi \
  --concurrency 80 --timeout 300 \
  --set-secrets "OPENAI_API_KEY=openai-api-key:latest,ARK_API_KEY=ark-api-key:latest,DATABASE_URL=database-url:latest,CANVAS_URL_SECRET=canvas-url-secret:latest" \
  --set-env-vars "$ENV_VARS" \
  --quiet

echo "Health check:"
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
curl -fsS "$URL/api/health" && echo
