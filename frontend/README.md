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
    - **Instruction** (`/instruction`): plain text every project in the
      collection shares (the AI follows it; projects show it read-only).
      Saved as you type; if someone else saved in between, it says so and
      offers **Reload**.
    - **Workflows** (`/workflows`): the collection's workflows; one is
      **Active** and every project runs on it. **Make active** switches all
      projects (steps the new one lacks are hidden, not deleted);
      **Copy from another collection…** brings one in.
    - **Share** (`/share`): the people (owner and editors, with what each
      generated today), inviting an editor by email with daily limits
      (blank: no limit; the owner pays), pending invites, removing an
      editor, or leaving.
  - **Settings** (`#/settings`): language, account, today's usage by
    collection and person, and (admins) which collections have no daily
    limit.
- **Two views**, switched by **Basic | Canvas** in a project's header
  (remembered in this browser). Both show the same project:
  - **Basic** (the default): one page per workflow step, with the step's
    form and its nodes as cards. Under each step in the workflow bar, its
    results are listed with their IDs (click one to copy it).
  - **Canvas**: every node on a canvas, with the open step in a panel on the
    right. The menu, adding and linking nodes, selecting and moving the view
    below are the canvas's.
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
  - **Instruction** — the collection's instruction (read-only here) and
    **Describe this video**, the project's own description. Editing it
    (saved as you type) changes only this project.
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
- **Hand and Select tools** (H / V, or the buttons bottom left): with the
  hand, dragging empty canvas moves the view; with select, dragging draws a
  selection box (what it touches), and holding Space moves the view.
  ⌘/Ctrl/Shift-click adds to the selection; ⌘A / Ctrl+A selects every node,
  Esc clears. The wheel and the +/- buttons zoom; dragging in the map in
  the corner moves the view.
- **Delete:** the trash icon in a node's header, or Backspace. Connections
  touching a deleted node go with it, and running jobs are cancelled.
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

A **workflow** belongs to a collection (**Workflows** in its menu); every
project in it runs on the active one. The default has five steps:
**Character** (images) → **Dish brainstorming** (text) → **Dish image** →
**Script overview** (text) → **Video per scene**.

- **Designing**: a workflow is a name and a list of steps; each step has a
  name, what it makes (text, image, video), a description (sent to the AI,
  shown read-only in projects), a default count, and its **context for later
  steps**: *Automatic* (every later step is given its results) or *Only when
  @* (a later step sees one only if its prompt mentions it). Names are your
  own text and are never translated.
- **Running a step**: write an instruction for it (optional) and how many
  results you want. The collection's instruction, the project's description
  and the nodes it mentions (their text; images are shown to the model) go
  to the text model:
  - a text step: **Generate** makes that many results, one text node each;
  - an image or video step takes two parts: **1 Fill in prompts** (one node
    each, referring to the mentioned nodes it uses; check or edit them),
    then **2 Generate** (videos ask first: each is a paid job).
  Or **Provide my own**: type the texts, or upload the files, yourself.
  Running a step again replaces its nodes.
- **Each node**: flip through versions; click a text result to type over it
  (saved as a new version when you click away); change its prompt (or a
  step's text result) with **Edit prompt with AI**; generate it again. A
  step's node selector moves the view to a node.
- **The workflow bar** shows each step (✓ once every node has an output,
  with how many are made). Workflow nodes show their step and number, and
  can't be deleted or switched to another kind.

## Layout

```
src/
  api/        schema.d.ts (generated), types.ts, client.ts (typed fetch)
  auth.ts     sign-in (Firebase Google sign-in; dev sign-in on `npm run dev`)
  i18n.ts     English/Chinese strings, the language setting, useT()
  router.ts   hash routes: #/ (collections), #/settings, #/c/<id>[/<section>],
              #/project/<id>
  projectView.ts  which view a project is shown in
  pages/      HomePage.tsx (collections and projects), CollectionAssets.tsx,
              CollectionInstruction.tsx, WorkflowDesigner.tsx, Share.tsx,
              Settings.tsx, SignIn.tsx (sign-in page and the gate in front
              of the app)
  store/      the open project's state and every API call:
              canvas.ts (useCanvas: composes the parts), types.ts (the state's
              shape), core.ts (shared helpers: saving, polling, history),
              actions/ (project, graph, media, generation, workflow, ai)
  node/       a node's parts, shared by both views: NodePreview.tsx (its
              output), TextResult.tsx (typed straight into), NodeBody.tsx
              (prompt card), NodeSettings.tsx, Takes.tsx (versions),
              UploadInfo.tsx, MediaThumb.tsx
  project/    Instruction.tsx (the collection instruction and "Describe this
              video")
  canvas/     the canvas view: Canvas.tsx, GenNode.tsx, Sidebar.tsx (menu),
              NodeName.tsx, ProjectBar.tsx (with the Basic | Canvas switch),
              inputs.ts
  basic/      the basic view (the default): BasicView.tsx, one page per
              workflow step with its nodes as cards; StepResults.tsx, each
              step's results under the workflow bar
  workflow/   status.ts (step states, from runs and nodes), keepOpen.ts ("keep
              this page open" while generating), StepRun.tsx (running a step,
              shared by both views), WorkflowBar.tsx, StepPanel.tsx,
              ManualForm.tsx (Provide my own), confirm.ts
  styles.css  light/dark tokens
bin/yuzu-canva       the launcher
```

`npm run typecheck`, `npm run build`, and `npm run gen:api` (after the
contract changes; `make contract` in backend/ runs it for you).
