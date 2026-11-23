# Shared by the deploy scripts: settings from deploy/deploy.env.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -f "$ROOT/deploy/deploy.env" ]; then
  echo "Missing deploy/deploy.env: copy deploy/deploy.env.example and fill it in." >&2
  exit 1
fi
# shellcheck disable=SC1091
. "$ROOT/deploy/deploy.env"
: "${PROJECT:?set PROJECT in deploy/deploy.env}"
: "${REGION:?set REGION}"
: "${SERVICE:?set SERVICE}"
: "${BUCKET:?set BUCKET}"
SA="${SERVICE}@${PROJECT}.iam.gserviceaccount.com"
