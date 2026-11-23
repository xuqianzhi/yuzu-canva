# Deploying yuzu-canva

| Part | Where |
|---|---|
| Frontend (static build) | Firebase Hosting: `https://yuzu-canva.web.app` |
| API (FastAPI + job worker) | Cloud Run service `yuzu-canva-api`, region `us-west1` |
| Sign-in | Firebase Auth (Google) |
| Images and videos | Cloud Storage for Firebase, bucket `yuzu-canva.firebasestorage.app` |
| Database | Supabase Postgres (session pooler) |
| Secrets | Secret Manager: `openai-api-key`, `ark-api-key`, `database-url`, `canvas-url-secret` |

Firebase Hosting forwards `/api/**` to Cloud Run, so the app and the API share
one address (no CORS). The API runs as **at most one instance, and none when
idle**: while someone has the app open, its requests keep the instance up and
generations progress; a while after the last request it shuts down, and
unfinished jobs pick up again on the next visit. The app asks people to keep
the page open while anything generates.

## First deploy

Run everything from the repo root, on your Mac, signed in to `gcloud` and
`firebase` with the account that owns the project.

1. **Settings.** Copy the template and fill in the allowlist (who may sign in):

   ```bash
   cp deploy/deploy.env.example deploy/deploy.env
   ```

   `deploy/deploy.env` is gitignored. Check `BUCKET` matches Firebase console →
   Storage.

2. **One-time Google Cloud setup.** Turns on the APIs, creates the API's
   service account and gives it the bucket, the secrets and link signing:

   ```bash
   deploy/setup.sh
   ```

3. **Secrets.** Copies `OPENAI_API_KEY`, `ARK_API_KEY` and `DATABASE_URL` from
   `backend/.env` into Secret Manager without printing them, and creates the
   media-link signing secret:

   ```bash
   deploy/push-secrets.sh
   ```

4. **API.** Builds the image with Cloud Build and deploys it. The first start
   creates the tables in Supabase.

   ```bash
   deploy/backend.sh
   ```

   It ends with a health check (`"status": "ok"`).

5. **Frontend.** Builds with `frontend/.env.local` (the Firebase web config) and
   publishes Hosting and the Storage rules:

   ```bash
   deploy/frontend.sh
   ```

6. **Try it.** Open `https://yuzu-canva.web.app`, sign in with Google (an
   allowlisted account), create a project, run a step, generate an image.
   Close the tab while a video generates, come back later, and check it
   finishes.

## Later

- **Code changes:** `deploy/backend.sh` for the API, `deploy/frontend.sh` for
  the app.
- **Allowlist or limits:** edit `deploy/deploy.env`, then `deploy/backend.sh`.
- **Rotating a key:** put the new key in `backend/.env`, then
  `deploy/push-secrets.sh` and `deploy/backend.sh` (a new revision reads the
  latest secrets).
- **Turn generation off right now** (e.g. if costs look wrong):

  ```bash
  gcloud run services update yuzu-canva-api --project yuzu-canva --region us-west1 --update-env-vars CANVAS_GENERATION_OFF=1
  ```

  Set `GENERATION_OFF=1` in `deploy/deploy.env` too, so the next deploy keeps
  it off.
- **Logs and errors:** Cloud Run → `yuzu-canva-api` → Logs; exceptions are
  grouped in Error Reporting (turn on its email notifications there).
- **Your old local data:** `python -m canvas_api.copy_local_data` copies the
  old local app's global assets, instruction and workflow templates into a
  new collection of yours (see the help at the top of
  `backend/src/canvas_api/copy_local_data.py`).
- **Sharing:** whoever creates a collection owns it and pays for what's
  generated in it; they invite editors from its Share page. An invited
  person also needs to be in `ALLOWED_EMAILS` to sign in at all.

## Settings the deploy uses

`deploy/backend.sh` sets these on the service (everything else has a default):

| Variable | From |
|---|---|
| `OPENAI_API_KEY`, `ARK_API_KEY`, `DATABASE_URL`, `CANVAS_URL_SECRET` | Secret Manager |
| `FIREBASE_PROJECT_ID` | `PROJECT` |
| `CANVAS_STORAGE=gcs`, `CANVAS_BUCKET` | `BUCKET` |
| `CANVAS_ALLOWED_EMAILS` | `ALLOWED_EMAILS` |
| `CANVAS_LIMIT_*_PER_DAY`, `CANVAS_GENERATION_OFF` | `LIMIT_*`, `GENERATION_OFF` |

Service shape: `--min-instances 0 --max-instances 1 --no-cpu-throttling`
(CPU stays on while an instance is up, so the job worker runs between
requests), 1 CPU, 1 GiB, 300 s request timeout.

## If something fails

- **Build permission errors** in step 4: rerun `deploy/setup.sh` (it gives the
  build account `roles/run.builder`); new projects can take a minute to apply.
- **401 after signing in:** `FIREBASE_PROJECT_ID` must be `yuzu-canva`, and
  the sign-in must come from `yuzu-canva.web.app` (or another domain listed in
  Firebase Auth → Settings → Authorized domains).
- **"No access yet":** the email isn't in `ALLOWED_EMAILS`; add it and run
  `deploy/backend.sh`.
- **Images don't load (403 from storage.googleapis.com):** the service
  account needs Service Account Token Creator on itself; rerun
  `deploy/setup.sh`.
- **Database errors at start:** check `DATABASE_URL` is the *session pooler*
  string (port 5432, host `…pooler.supabase.com`) with the right password,
  then `deploy/push-secrets.sh` and `deploy/backend.sh`.
