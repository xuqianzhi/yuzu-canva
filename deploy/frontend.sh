#!/usr/bin/env bash
# Build the frontend and publish it to Firebase Hosting (which forwards
# /api/** to the Cloud Run API), with the Storage rules.
. "$(dirname "$0")/common.sh"
[ -f "$ROOT/frontend/.env.local" ] || {
  echo "Missing frontend/.env.local (the Firebase web config)." >&2
  exit 1
}
(cd "$ROOT/frontend" && npm run build)
(cd "$ROOT" && firebase deploy --only hosting,storage --project "$PROJECT")
echo "Open https://${PROJECT}.web.app"
