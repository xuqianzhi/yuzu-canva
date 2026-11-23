#!/usr/bin/env bash
# One-time Google Cloud setup for the API (safe to run again):
# turns on the services it uses, creates its service account, and lets it
# use the bucket, read its secrets and sign media links.
. "$(dirname "$0")/common.sh"

# A new service account takes a little while to be usable in permissions.
retry() {
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    "$@" >/dev/null 2>&1 && return 0
    echo "  not ready yet, retrying in 6s ($attempt/10)…"
    sleep 6
  done
  "$@" >/dev/null
}

echo "Turning on the Cloud Run, Cloud Build, Artifact Registry, Secret Manager and IAM APIs…"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  iamcredentials.googleapis.com --project "$PROJECT"

if ! gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1; then
  echo "Creating the API's service account $SA…"
  gcloud iam service-accounts create "$SERVICE" --project "$PROJECT" \
    --display-name "yuzu-canva API (Cloud Run)"
fi

echo "Letting it read and write the bucket gs://$BUCKET…"
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/storage.objectAdmin

echo "Letting it read secrets…"
retry gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor \
  --condition None

echo "Letting it sign media links (as itself)…"
retry gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/iam.serviceAccountTokenCreator

# Cloud Run builds images from source with the project's default compute
# service account; newer projects don't give it build rights by default.
NUMBER="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
echo "Letting Cloud Build build the API image…"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${NUMBER}-compute@developer.gserviceaccount.com" \
  --role roles/run.builder --condition None >/dev/null

echo "Done. Next: deploy/push-secrets.sh"
