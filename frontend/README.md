# frontend/

The canvas UI: React + React Flow (`@xyflow/react` 12) + Zustand, built with
Vite. Runs as a dev server on http://127.0.0.1:5180 that proxies `/api` to
the backend on 8788, and opens in a chromeless Chrome window.

## Run

From the repo root:

```bash
./yuzu-canva            # start API + UI, open the window
./yuzu-canva --fake     # same, with offline placeholder images and videos (no API calls)
./yuzu-canva --stop     # close the window, stop both
./yuzu-canva --status
./yuzu-canva --install  # optional: a `yuzu-canva` command on PATH
```

Or by hand: `cd backend && docker compose up -d api`, then
`cd frontend && npm install && npm run dev`, and open http://127.0.0.1:5180.

## Using it

- **Language:** **English / 中文** under **Settings**, at the bottom of the landing page's left menu.
  It switches the whole UI, and the wording of every prompt the backend
  writes for the models (step instructions, headings,
  how reference images are named). Your own text is sent as written. The
  choice is remembered (on the backend, cached in the browser) until you
  change it. Strings live in `src/i18n.ts`; error messages from the API
  are shown by error code in Chinese.
- **Landing pages:** a menu down the left edge (like the one inside a
  project) switches between full-height pages, each scrolling on its own.
  The address follows the page.
  - **Collections** (`#/`): every collection you own or edit, with
    **Invitations** to accept or decline on top, and **+ New collection**.
  - Inside a collection (`#/c/<id>`), its menu items:
    - **Projects**: its projects, newest first, with a cover, counts, and
      who is editing each right now. **+ New project** creates one; the
      owner can hover a card for **Delete**, or **Delete collection** (type
      its name to confirm).
    - **Assets** (`/assets`): named images and videos that every *new*
      project in the collection starts with, as uploaded nodes down the left
      side of its canvas (oldest first). **Upload** or drop files on the
      page: each is added at once, named after its file (with "_2", "_3"… if
      that name is taken). Names are required and unique in the collection
      (ignoring case) and become the node's ID; click one to rename it, or
      hover a card for ×. Changes never touch projects already made.
    - **Instruction** (`/instruction`): plain text that every *new* project
      starts with as its own instruction. Saved as you type; if someone else
      saved in between, it says so and offers **Reload**.
    - **Workflows** (`/workflows`): the collection's workflows; one is
      **Active** and every project runs on it. **Make active** switches all
      projects (steps the new one lacks are hidden, not deleted);
      **Copy from another collection…** brings one in.
    - **Share** (`/share`): the people (owner and editors, with what each
      generated today), inviting an editor by email with daily limits
      (blank: no limit; the owner pays), pending invites, removing an
      editor, or leaving.
  - **Settings** (`#/settings`): language, account, and today's usage, by
    collection and person.
- Inside a project, **← Projects** goes back to its collection, and the
  name in the header can be edited in place.
- **One editor at a time:** opening a project takes its lock (renewed every
  20 s, released on leaving; see `src/store/lock.ts`). If someone else (or
  your other tab) holds it, the project opens **view only**: a banner says
  who, every control is off, and the view refreshes every 5 s; once they
  leave, **Start editing**. Your own other tab can be taken over.
- **Menu (left edge):**
  - **Assets** — the project's uploaded images (PNG, JPEG, WebP) and
    videos (MP4, MOV). **Upload**, or drop files on the panel. Drag one onto
    the canvas to make it an *uploaded node*. Dropping files from Finder
    straight onto the canvas uploads and places them in one go.
  - **Nodes** — every node by name. Rename here, or click a row to select
    the node and bring it to the middle of the view.
  - **Instruction** — this project's instruction, a copy of its
    collection's made when the project was created. Editing it (saved as you type)
    changes only this project.
- **IDs:** optional, shown above each node; click to edit (Enter saves,
  Escape cancels). Unique in the canvas (ignoring case), and made of letters
  (any script), digits, `_` and `-`. A node needs an ID before anything can
  use its output: without one its output handle is a grey circle (hover it
  for why). Uploaded nodes start out with an ID made from the file name.
- **Using another node's output:** put its ID in a prompt. Any node ID in
  the text links that node as an input (no "@" needed; Latin IDs match as
  whole words, Chinese needs no spaces), and linked IDs are highlighted.
  Typing `@` lists the canvas's IDs; choosing one inserts the bare ID.
  Deleting the ID from the text removes the link: a node's inputs are
  exactly the IDs its prompt contains. Every new link -- dragged onto a
  node, or made from the drag-to-create menu -- adds the source's ID to the
  target's prompt; deleting a link removes it from there. Renaming an ID
  updates every prompt that contains it; removing an ID disconnects
  everything that used it. An ID that would make a loop stays unlinked
  (shown in red and struck through, with a warning on the node).
- **Uploaded nodes** hold a file: no prompt, no inputs, no Generate. Connect
  their output into an image or video node to use the file there.
- **Add a node:** double-click empty canvas. The tabs on a node switch it
  between **Image · Video · Text**. There are no node subtypes: what a node
  is for comes from its prompt (and, for workflow nodes, their step).
- **Add a connected node:** drag from a node's handle and let go on empty
  canvas, then pick Image, Video or Text. Dragged from an output (right),
  the new node uses it; from an input (left), the new node feeds it.
- **Connect existing nodes:** drag from one node's right handle to another's
  left handle. Loops are refused.
- **Generate:** type a prompt, press **Generate** at the bottom of the node
  (or ⌘↵). Every node is the same size; images and videos keep their shape
  inside the preview.
- **Inputs** show over the preview as ID thumbnails, in the order the
  prompt first mentions them, which is the order they are sent to the model
  (the backend turns each ID in the prompt into "image 1" for OpenAI, or 图片1 / 视频1
  for Seedance).
- **Video settings:** ratio, duration (4-15s), resolution, audio. Videos
  take a few minutes; the node shows a running timer.
- **Select:** click a node; ⌘/Ctrl/Shift-click to add more; drag on empty
  canvas to draw a selection box (it picks the nodes it touches and the
  connections between them). A bar at the bottom shows what is selected.
- **Move the view:** drag inside the map in the bottom-right corner. Dragging
  the canvas itself selects instead; the wheel and the +/- buttons zoom.
- **Delete:** the trash icon at the bottom of a node, **Delete** in the
  selection bar, or Backspace. Connections touching a deleted node go with
  it, and running jobs are cancelled.
- **Undo / redo:** ⌘Z / ⌘⇧Z (Ctrl+Z / Ctrl+Y), or the arrows in the header.
  Covers adding (also from materials), deleting (takes included),
  connecting, moving, renaming, kind and settings changes, and prompt edits
  (one step per pause in typing). Inside
  a text box, ⌘Z is the box's own text undo. The history lasts while the
  project is open; deleted items are erased for good a day later.
- Everything saves automatically (prompts after a short pause, and on
  leaving a project).

Text, image and video nodes generate. A video can't be an input to an
image or text node.

## The workflow

A **workflow** is designed once (landing page → **Workflows**, under
Defaults) and copied by every new project (pick one when creating a project
if there are several). Projects keep the copy they started with. The
default has two steps: **Dish brainstorming** (text) → **Character**
(images).

- **Designing**: a workflow is a name and a list of steps; each step has a
  name, what it makes (text, image, video), and what its **results are**:
  - *Independent* (the default): its nodes get IDs (`dishes_1`…) and don't
    flow anywhere by themselves. Any later step uses one by mentioning its
    ID in its prompt, e.g. "a mascot for dishes_2".
  - *One-to-one into the next step*: its nodes have no ID (nothing else may
    refer to them); result *i* feeds node *i* of the next step, which makes
    exactly as many. The last step's results are always independent.
  Names are your own text and are never translated; only the choices are.
- **Running a step** (the panel on the right; click a step in the bar):
  write a prompt and how many results you want, then **Generate**. The
  prompt, the project instruction and the nodes it mentions (their text;
  images are shown to the model) go to the text model:
  - a text step gets that many results, one text node each;
  - an image or video step gets that many prompts, one node each,
    generated right away with the mentioned nodes as references (videos
    ask first: each is a paid job).
  After a one-to-one step there's no "how many": one node per result.
  Image or video nodes fed by text take each text as their prompt (the
  prompt box becomes optional extra direction); a text step writes one
  result per input; image → video uses each image as the reference.
  Generating again replaces the step's nodes.
- **Each node**: flip through versions; text can be edited by hand or
  improved in a chat; an image or video node's prompt can be edited and
  generated again.
- **The workflow bar** shows each step (✓ once every node has an output,
  with how many are made). Workflow nodes show their step and number, and
  can't be deleted or switched to another kind.

(A fuller version, with per-step goals, inputs, AI-planned item lists,
approval and out-of-date tracking, is saved in
`.snapshots/full-workflow-2026-11-21.tar.gz`.)

## Layout

```
src/
  api/        schema.d.ts (generated), types.ts, client.ts (typed fetch)
  auth.ts     sign-in (Firebase Google sign-in; dev sign-in on `npm run dev`)
  i18n.ts     English/Chinese strings, the language setting, useT()
  router.ts   hash routes: #/ (projects), #/assets, #/instruction, #/workflows, #/settings,
              #/project/<id>
  pages/      HomePage.tsx (projects), GlobalAssets.tsx, GlobalInstruction.tsx,
              WorkflowDesigner.tsx, Settings.tsx (language, account, usage),
              SignIn.tsx (sign-in page and the gate in front of the app)
  store/      the open project's state and every API call:
              canvas.ts (useCanvas: composes the parts), types.ts (the state's
              shape), core.ts (shared helpers: saving, polling, history),
              actions/ (project, graph, media, generation, workflow, chat)
  canvas/     Canvas.tsx, GenNode.tsx, Sidebar.tsx (menu), NodeName.tsx,
              ProjectBar.tsx, inputs.ts
  workflow/   status.ts (step states, from runs and nodes), keepOpen.ts ("keep
              this page open" while generating), WorkflowBar.tsx,
              StepPanel.tsx, ChatThread.tsx
  styles.css  light/dark tokens
bin/yuzu-canva       the launcher
```

`npm run typecheck`, `npm run build`, and `npm run gen:api` (after the
contract changes; `make contract` in backend/ runs it for you).
