# yuzu-canva

A canvas for AI generation. Each node takes a prompt and generates text, an
image or a video, and can reference other nodes' outputs.

- Text and images: OpenAI. Video: Seedance (Volcengine Ark).

```
yuzu-canva/
├── contract/   openapi.json, generated from the backend models
├── backend/    FastAPI, runs in Docker on 127.0.0.1:8788
└── frontend/   React canvas (coming next), opens in Chrome; typed API client
```

## Status

The canvas works: add, move, name and delete nodes, upload your own images
and videos as nodes (per project, or as a collection's assets every new
project in it starts with), connect one node's output into another, generate
images and videos, and see the result; everything saves, and ⌘Z undoes it.

- **Collections**: projects (one video each) live in collections ("Anime",
  "Educational"), each with its own workflows (one active, which all its
  projects run on), instruction and assets. A collection's owner invites
  editors by email; editors can do everything but delete projects or the
  collection. The owner pays for everything generated there and can limit
  each editor per day. One person (one browser tab) edits a project at a
  time; others see it view-only until it's free.
- **Workflows**: designed per collection (a list of steps, each a
  name and what it makes); its projects run on the active one. In a project,
  each step runs with an optional instruction and a number: with the project
  description and what earlier steps settled on, the AI writes that many
  results (text) or prompts (images, videos: checked, then generated). See
  frontend/README.md.
- **Text nodes** (OpenAI `OPENAI_TEXT_MODEL`, default gpt-5-mini).
- **Image nodes** (OpenAI): text to image with no inputs, image edit with
  one or more image inputs ("image 1", "image 2" in the prompt).
- **Video nodes** (Seedance 2.0 on Volcengine Ark): text to video, with up
  to 9 image and 3 video inputs ("图片1", "视频1" in the prompt). Video jobs
  survive an API restart: polling resumes on the same Ark task.

Uploads to Ark (Beijing) can be very slow from outside China (a few KB/s).
As in seedance-ui, reference images are therefore sent as JPEG, at most
1024 px on the long edge at quality 80 (the node keeps its full-size file).
This applies to every provider, OpenAI included: providers only get
reference files through `RefFile.load()`, which compresses images. One Ark
request may take up to `SEEDANCE_HTTP_TIMEOUT` (default 900s).
If a create request is lost mid-upload, the backend checks Ark for the task
(by its seed) before reporting a failure, so you are never charged twice.

Data is in Postgres (locally the compose `db` service; deployed, Supabase),
media under `data/` locally or in Cloud Storage when deployed. Poll
`GET /api/jobs/{id}` for progress; a workflow step runs in the background
(poll the graph until its run is `done`).

Every API route but `/api/health` needs a sign-in: deployed, a Firebase ID
token (Google sign-in) for an allowlisted email; locally, `dev:<email>` (the
frontend's dev sign-in). Each user sees only their own projects, templates,
assets and settings, within daily limits. Media links are signed instead.

Deploying (Firebase Hosting + Cloud Run + Supabase): see [DEPLOY.md](DEPLOY.md).

## Backend

Needs Docker Desktop.

```bash
cd backend
make setup      # creates .env -- add OPENAI_API_KEY and ARK_API_KEY
make up         # Postgres + API on http://127.0.0.1:8788, docs at /docs
make test       # tests in Docker (each test gets its own Postgres schema)
make down
```

Every Seedance task Ark creates is billed, so the backend never sends a create request twice by accident. The rules, and a list of every other guard against paying twice, are in one place: `backend/src/canvas_api/providers/billing_safety.py`.

## Changing the contract

Edit the models in `backend/src/canvas_api/contract/`, then:

```bash
cd backend && make contract   # regenerates contract/openapi.json and the TS types
```

Needs Node.js for the TypeScript step (`cd frontend && npm install` once).
Export in Docker (as `make contract` does), not a local Python: status-code
wording differs between Python versions and would fail the drift test.
See [contract/README.md](contract/README.md).
