#!/usr/bin/env bash
# Copy the API's secrets from backend/.env into Secret Manager, without
# printing them: OPENAI_API_KEY, ARK_API_KEY, DATABASE_URL. Run it again
# after changing any of them (e.g. rotating a key), then redeploy the API.
# Also creates the media-link signing secret once (never changed after).
. "$(dirname "$0")/common.sh"
ENV_FILE="$ROOT/backend/.env"
[ -f "$ENV_FILE" ] || { echo "Missing backend/.env" >&2; exit 1; }

# The value of KEY in .env (quotes removed), read without running the file.
value_of() {
  python3 -I - "$ENV_FILE" "$1" <<'PY'
import sys
path, key = sys.argv[1], sys.argv[2]
value = ""
for line in open(path, encoding="utf-8"):
    line = line.strip()
    if line.startswith("export "):
        line = line[7:].lstrip()
    if line.startswith(key + "="):
        value = line[len(key) + 1:].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
sys.stdout.write(value)
PY
}

put_secret() {  # put_secret <secret id> <value>, value never echoed
  if gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$2" | gcloud secrets versions add "$1" --project "$PROJECT" --data-file=- >/dev/null
    echo "  $1: new version"
  else
    printf '%s' "$2" | gcloud secrets create "$1" --project "$PROJECT" \
      --replication-policy automatic --data-file=- >/dev/null
    echo "  $1: created"
  fi
}

echo "Secrets in project $PROJECT:"
for pair in OPENAI_API_KEY:openai-api-key ARK_API_KEY:ark-api-key DATABASE_URL:database-url; do
  key="${pair%%:*}"
  id="${pair##*:}"
  secret="$(value_of "$key")"
  if [ -z "$secret" ]; then
    echo "  $key is empty in backend/.env: skipped" >&2
    continue
  fi
  case "$key" in
    DATABASE_URL)
      case "$secret" in
        *pooler.supabase.com*) ;;
        *) echo "  DATABASE_URL doesn't look like a Supabase pooler string: skipped" >&2; continue ;;
      esac ;;
  esac
  put_secret "$id" "$secret"
  secret=""
done

if ! gcloud secrets describe canvas-url-secret --project "$PROJECT" >/dev/null 2>&1; then
  put_secret canvas-url-secret "$(openssl rand -base64 48 | tr -d '\n')"
else
  echo "  canvas-url-secret: kept"
fi
echo "Done. Next: deploy/backend.sh"
