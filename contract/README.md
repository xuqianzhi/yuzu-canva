# contract/

`openapi.json` is the API contract between the backend and the frontend.
**It is generated — do not edit it by hand.**

```
backend/src/canvas_api/contract/*.py   (Pydantic models: the source of truth)
        │  make contract
        ▼
contract/openapi.json                  (committed, reviewed in diffs)
        │  npm run gen:api   (also run by make contract)
        ▼
frontend/src/api/schema.d.ts           (TypeScript types)
```

`backend/tests/test_api.py` fails if `openapi.json` is out of date with the
models, so a model change without `make contract` is caught by `make test`.

## Model in one paragraph

A **project** is one canvas. A **node** has a `kind` (`text | image | video`),
a prompt and kind-specific `params`. An **edge** `source → target` means the
target *references* the source. Generating a node creates a **job**; the
backend picks the provider and operation from the node's kind and its
references' kinds, and each reference resolves to the source node's
`selected_output_id`. A successful job produces an **output** (one "take"),
and image/video outputs point at a stored **asset**.

A node's `name` is its **ID** (the UI's word; `id` is the internal key):
optional, unique per project ignoring case, letters/digits/`_`/`-`. A prompt
mentions a node by containing its ID -- no "@" (longest existing ID wins;
Latin IDs only as whole words; Chinese needs no spaces). For every
generating node, links exist **exactly** when the prompt mentions the
source: the backend re-syncs links after every prompt, ID, delete or restore
change, and on startup;
creating such a link appends the ID to the target's prompt and deleting one
removes the mentions.
Nothing links out of a node without an ID (`no_id`); a mention that would
make a loop stays unlinked.

A node may have a `name`: optional, unique in its project ignoring case and
spacing (`duplicate_name` otherwise). A node's `source` is `generate` (a
prompt and a model) or `upload` (a file placed from the project's
materials; it cannot generate, and its take has no job).

Nodes have no subtypes: a node is text, image or video, and its prompt says
what it is for. (Older "character" nodes became image nodes whose prompt
keeps their description and traits, the trait images as IDs.)

The UI calls a project's materials **Assets**. **Global assets** belong to no
project: each has a required, unique name, and `createProject` turns every
one into an uploaded node (named after it, with its own copy of the file),
down the left side of the new canvas.

**Instructions** are plain text (up to 20,000 characters). There is one
global instruction (`/global-instruction`, empty until set), and every
project has its own `instruction`: `createProject` copies the global one
unless the body gives one, and `updateProject` edits it. Changing the
global instruction never touches existing projects. Workflow text steps
include the project's instruction in what the model is told.

**Language** (`/settings`, `language`: `en` or `zh`, default `en`): the
app's language. The backend words every prompt it writes in it: workflow
step instructions and headings, chat framing, plain text nodes' system
prompt, and how OpenAI prompts name reference images
("image 1" / "图片1"); each job records it (`job.input.language`). Workflow
definitions carry their labels, help and step prompts in every language
(`Localized`: `{"en": …, "zh": …}`); readers fall back to English.

**Workflows** (`contract/workflow.py`): a **template**
(`/workflow-templates`) is a name and a list of steps, each a `key`, a
`name` (the user's text, never translated), a node `kind` and an `output`
use: `independent` (nodes get IDs "<key>_<n>"; later prompts use them by
mentioning the IDs) or `one_to_one` (no IDs; node *i* feeds node *i* of the
next step through a workflow edge; not allowed on the last step). A project
copies a template when created (`workflow_template_id`, else the default)
into `project.workflow`.

`runStep` runs a step with a `prompt` and a `count` (1-20; ignored after a
one-to-one step, which sets it). With the project instruction and the nodes
the prompt mentions (text quoted, images sent to the model), a text model
writes exactly that many items (strict JSON schema, one retry): a text
step's nodes' takes, or an image or video step's prompts (each keeps the
prompt's mentions, so those nodes are its references), queued at once.
After a one-to-one step: media fed by text uses each text as its prompt
(no model call; the prompt is optional extra direction), media fed by media
uses the prompt for each with its input as reference, and text writes one
result per input. Running again replaces the step's nodes; `graph.runs`
keeps each step's last prompt and count. Workflow nodes can't be deleted or
retyped, and one-to-one nodes can't be given an ID (409 `workflow_locked`).

Deleting a node or edge is soft: it disappears from every response but is
kept (with its takes and files) so `restore` can undo it. Anything deleted
more than a day ago is erased when the API starts.

## Endpoints (all under `/api`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET, POST | `/projects` | list / create |
| GET, PATCH, DELETE | `/projects/{id}` | whole graph / rename, viewport, instruction / delete |
| POST | `/projects/{id}/nodes` | create node |
| PATCH, DELETE | `/nodes/{id}` | edit / delete node |
| GET | `/nodes/{id}/outputs` | takes, newest first |
| POST | `/nodes/{id}/generate` | queue a job (202) |
| POST | `/projects/{id}/edges` | add reference (409 on cycle) |
| DELETE | `/edges/{id}` | remove reference |
| POST | `/projects/{id}/restore` | undo deletes (nodes with their takes, edges) |
| GET, POST | `/projects/{id}/materials` | list / upload (multipart `file`) materials |
| DELETE | `/materials/{id}` | remove from the library (placed nodes keep a copy) |
| POST | `/materials/{id}/place` | put a material on the canvas as an uploaded node |
| GET, POST | `/global-assets` | list / upload (multipart `file` + `name`) global assets |
| PATCH, DELETE | `/global-assets/{id}` | rename / delete a global asset |
| GET | `/global-assets/{id}/content` | the file |
| GET, PUT | `/global-instruction` | read / replace the global instruction |
| GET, PUT | `/settings` | the app's language (`en`, `zh`) |
| GET, POST | `/workflow-templates` | list / create workflow templates |
| PUT, DELETE | `/workflow-templates/{id}` | replace (version + 1) / delete (not the default) |
| POST | `/workflow-templates/{id}/default` | make it the default for new projects |
| POST | `/projects/{id}/workflow/steps/{key}/run` | run a step with a prompt and a count (returns the graph) |
| POST | `/nodes/{id}/takes` | a hand-written text take |
| GET, POST | `/nodes/{id}/chat` | a text node's chat / ask (returns your message and the answer) |
| POST | `/chat/{message_id}/apply` | turn an answer's proposal into a take |
| GET | `/jobs/{id}` | job status |
| POST | `/jobs/{id}/cancel` | cancel |
| GET | `/assets/{id}/content` | media bytes |
| WS | `/projects/{id}/events` | `job.updated`, `output.created` |

Every error is `{"error": {"code", "message", "context"}}`; see `ErrorCode`.

## Routing (what generate calls)

| Node kind | References | Operation |
|---|---|---|
| text | text inlined, images as vision input | OpenAI `text_generate` |
| image | no image refs | OpenAI `image_generate` |
| image | 1–10 image refs | OpenAI `image_edit` |
| video | 0–9 image refs, 0–3 video refs | Seedance `video_generate` |

Video references into text or image nodes fail with `unsupported_ref`.
