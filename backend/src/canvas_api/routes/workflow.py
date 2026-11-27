"""Running a project's workflow steps, hand-written takes, and AI edits
of a node. Plus the app's settings. (Workflows themselves belong to
collections: routes/collections.py.)"""

from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.concurrency import iterate_in_threadpool, run_in_threadpool
from fastapi.responses import Response, StreamingResponse

from ..contract import (
    AiEdit,
    AiEditRequest,
    AppSettings,
    AppSettingsUpdate,
    EditTarget,
    ErrorCode,
    MediaKind,
    Node,
    NodeId,
    NodeSource,
    Output,
    ProjectGraph,
    ProjectId,
    RunStatus,
    StepCompleteRequest,
    StepRunRequest,
    TakeCreate,
    VideoParams,
    WorkflowStep,
)
from ..deps import SpendingDep, StoreDep, TextModelDep, UserDep, WorkerDep
from ..domain.workflow import (
    Instructions,
    Naming,
    Piece,
    RunFormatError,
    RunItem,
    W,
    carried_piece,
    edit_messages,
    edit_spec,
    image_label,
    keep_used,
    name_images,
    parse_edit,
    parse_run,
    run_messages,
    run_spec,
    step_by_key,
    step_index,
)
from ..errors import ApiError, responses
from ..files import FileMissing
from ..jobs.queue import queue_generation, ref_file
from ..providers.base import ProviderError, RefFile

router = APIRouter(tags=["workflow"])
log = logging.getLogger(__name__)


def _provider_error(exc: ProviderError) -> ApiError:
    return ApiError(502, ErrorCode.provider_error, str(exc))


def _step_or_404(project, key: str) -> WorkflowStep:
    step = step_by_key(project.workflow, key)
    if step is None:
        raise ApiError(404, ErrorCode.not_found, f"workflow step {key} not found")
    return step


# --- running a step --------------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    """A step run, worked out before it starts."""

    project_id: str
    collection_id: str
    step: WorkflowStep
    prompt: str
    count: int
    media: bool


@router.post(
    "/projects/{project_id}/workflow/steps/{step_key}/run",
    status_code=202,
    operation_id="runStep",
    responses=responses(404, 409, 429, 503),
)
async def run_step(
    project_id: ProjectId,
    step_key: str,
    body: StepRunRequest,
    request: Request,
    store: StoreDep,
    worker: WorkerDep,
    text_model: TextModelDep,
    spending: SpendingDep,
    user: UserDep,
) -> ProjectGraph:
    """Start running a step; returns the graph with the run ``running``.

    It finishes in the background: poll ``getProjectGraph`` until the step's
    run is ``done`` (its nodes replaced) or ``failed`` (``error`` says why;
    the old nodes are untouched). 409 if the step is already running.

    The prompt, the instructions, what earlier steps settled on and the
    nodes the prompt mentions (by ID) go to a text model, which writes
    ``count`` results (a text step: its nodes' text) or prompts (an image or
    video step: one node each, referring to the mentioned nodes it uses,
    and for a video its length in seconds). Image and video nodes are only
    filled in: ``generateStep`` then generates them.
    """
    run = await run_in_threadpool(_plan_run, store, project_id, step_key, body)
    spending.charge(user.id, run.collection_id, "text")
    await run_in_threadpool(store.start_run, project_id, step_key, run.prompt, run.count)
    task = asyncio.create_task(_finish_run(run, store, worker, text_model))
    tasks: set[asyncio.Task] = request.app.state.tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return await run_in_threadpool(store.get_graph, project_id)


@router.post(
    "/projects/{project_id}/workflow/steps/{step_key}/complete",
    operation_id="completeStep",
    responses=responses(404, 409),
)
def complete_step(
    project_id: ProjectId,
    step_key: str,
    body: StepCompleteRequest,
    store: StoreDep,
    worker: WorkerDep,
) -> ProjectGraph:
    """Complete a step by hand: its nodes are replaced by the given results,
    in order -- texts for a text step, uploaded files (``uploadMaterial``)
    for an image or video step, each copied in as its node's take. Nothing
    is generated or charged. 409 while the step is running."""
    cancelled = store.complete_step(project_id, step_key, body.entries)
    for job_id in cancelled:
        worker.abort(job_id)
    return store.get_graph(project_id)


# --- downloading a step ----------------------------------------------------------------

# Extensions for the usual media types (mimetypes guesses oddly for some).
_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


def _extension(mime: str) -> str:
    return _EXTENSIONS.get(mime) or mimetypes.guess_extension(mime) or ".bin"


def _safe_name(text: str) -> str:
    """A file-name-safe version of `text` (letters in any script kept)."""
    cleaned = re.sub(r"[^\w.-]+", "-", text.strip()).strip("-.")
    return cleaned[:60] or "untitled"


@router.get(
    "/projects/{project_id}/workflow/steps/{step_key}/download",
    operation_id="downloadStep",
    response_class=Response,
    responses={
        200: {"description": "A zip of the step's results", "content": {"application/zip": {}}},
        **responses(404),
    },
)
async def download_step(project_id: ProjectId, step_key: str, store: StoreDep) -> Response:
    """A zip of every result of a step: each node's chosen take, named by
    the node's number (``<step>_01.png``, ``<step>_02.png``, ...; text as
    ``.txt``). Nodes with no take yet are left out; 404 if none has one.
    The zip is streamed as it's made (a step of videos can be large)."""
    name, files = await run_in_threadpool(_step_files, store, project_id, step_key)
    return StreamingResponse(
        iterate_in_threadpool(_zip_stream(store, files)),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "no-store",
        },
    )


@dataclass(frozen=True)
class _ZipEntry:
    name: str
    text: str | None = None  # a text result
    key: str | None = None  # else the media file's key


def _step_files(store, project_id: str, step_key: str) -> tuple[str, list[_ZipEntry]]:
    """The zip's name and what goes in it (checked before anything is sent,
    so a missing step is a plain 404)."""
    project = store.get_project(project_id)
    step = _step_or_404(project, step_key)
    nodes = store.step_nodes(project_id, step_key)
    done = [n for n in nodes if n.selected_output_id]
    if not done:
        raise ApiError(404, ErrorCode.not_found, f"{step.name} has no results to download yet")
    width = max(2, len(str(max(n.workflow_item or 0 for n in nodes))))
    entries = []
    for i, node in enumerate(done, start=1):
        stem = f"{step_key}_{(node.workflow_item or i):0{width}d}"
        output = store.get_output(node.selected_output_id)
        if output.asset is None:
            entries.append(_ZipEntry(f"{stem}.txt", text=output.text or ""))
        else:
            _, key = store.asset_file(output.asset.id)
            entries.append(_ZipEntry(f"{stem}{_extension(output.asset.mime)}", key=key))
    number = step_index(project.workflow, step_key) + 1
    name = f"{_safe_name(project.name)}_step{number}_{_safe_name(step.name)}.zip"
    return name, entries


class _Pipe(io.RawIOBase):
    """Where the zip writes; each chunk is taken out as soon as it's written."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.offset = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # type: ignore[override]
        self.chunks.append(bytes(data))
        self.offset += len(data)
        return len(data)

    def tell(self) -> int:
        return self.offset

    def take(self) -> bytes:
        out, self.chunks = b"".join(self.chunks), []
        return out


def _zip_stream(store, entries: list[_ZipEntry]) -> Iterator[bytes]:
    pipe = _Pipe()
    with zipfile.ZipFile(pipe, "w") as archive:  # type: ignore[arg-type]
        for entry in entries:
            if entry.key is None:
                archive.writestr(
                    entry.name, entry.text or "", compress_type=zipfile.ZIP_DEFLATED
                )
            else:
                try:
                    data = store.files.read(entry.key)
                except FileMissing:
                    log.warning("download: %s is missing", entry.key)
                    continue
                # Media is compressed already: store it as is.
                archive.writestr(entry.name, data)
                del data
            yield pipe.take()
    yield pipe.take()


def _plan_run(store, project_id: str, step_key: str, body: StepRunRequest) -> _Run:
    project = store.get_project(project_id)
    step = _step_or_404(project, step_key)
    media = step.kind != MediaKind.text
    # The prompt is optional: the instructions, the step's description and
    # earlier steps may be enough.
    return _Run(
        project_id,
        project.collection_id,
        step,
        body.prompt.strip(),
        body.count,
        media,
    )


@dataclass(frozen=True)
class _Asked:
    """What a run (read from the database) asks the text model."""

    system: str
    user: str
    images: list
    # Decisions and references, to turn "image 2" in the answer into IDs.
    pieces: list[Piece]
    # The IDs the prompt mentions: each media prompt keeps the ones it uses.
    mentioned: list[str]


async def _finish_run(run: _Run, store, worker, text_model) -> None:
    """The slow part of a run (the text model), then its new nodes. The
    database work runs in threads, off the event loop."""

    async def fail(message: str) -> None:
        await run_in_threadpool(store.fail_run, run.project_id, run.step.key, message)

    try:
        asked = await run_in_threadpool(_ask_for_run, store, run)
        items = await _write_items(text_model, run, asked)
        cancelled = await run_in_threadpool(_save_run, store, run, items)
        for job_id in cancelled:
            worker.abort(job_id)
    except ApiError as exc:
        await fail(exc.detail.message)
    except Exception as exc:  # noqa: BLE001 - shown on the run
        log.exception("running step %s of %s failed", run.step.key, run.project_id)
        await fail(f"internal error: {type(exc).__name__}")


def _save_run(store, run: _Run, items: list[RunItem]):
    return store.replace_step_nodes(
        run.project_id,
        run.step.key,
        run.prompt,
        [i.text for i in items],
        run.count,
        names=[i.name for i in items],
        prompts=[i.prompt or "" for i in items],
        params=[_params(run.step, i) for i in items],
    )


def _params(step: WorkflowStep, item: RunItem) -> VideoParams | None:
    """A video node's settings: the defaults, with the length the model gave."""
    if step.kind != MediaKind.video or item.seconds is None:
        return None
    return VideoParams(duration_s=item.seconds)


@router.post(
    "/projects/{project_id}/workflow/steps/{step_key}/generate",
    operation_id="generateStep",
    responses=responses(404, 409, 429, 503),
)
def generate_step(
    project_id: ProjectId,
    step_key: str,
    store: StoreDep,
    worker: WorkerDep,
    spending: SpendingDep,
    user: UserDep,
) -> ProjectGraph:
    """Generate an image or video step's nodes from their filled-in prompts
    and settings (``runStep`` fills them in), skipping any already
    generating. 409 while the step is running, before it has nodes, or
    while a node's prompt is empty."""
    project = store.get_project(project_id)
    step = _step_or_404(project, step_key)
    if step.kind == MediaKind.text:
        raise ApiError(409, ErrorCode.not_generatable, "a text step has nothing to generate")
    run = next((r for r in store.list_runs(project_id) if r.step == step_key), None)
    if run is not None and run.status == RunStatus.running:
        raise ApiError(409, ErrorCode.workflow_locked, "wait until the prompts are filled in")
    nodes = store.step_nodes(project_id, step_key)
    if not nodes:
        raise ApiError(409, ErrorCode.workflow_blocked, "fill in the prompts first")
    if any(not n.prompt.strip() for n in nodes):
        raise ApiError(409, ErrorCode.workflow_blocked, "every node needs a prompt first")
    _generate_nodes(store, worker, spending, project.collection_id, step, nodes, user.id)
    return store.get_graph(project_id)


def _generate_nodes(
    store, worker, spending, collection_id: str, step, nodes, actor: str
) -> None:
    """Queue generation for a step's nodes not already generating (uploaded
    ones have nothing to generate), paid as one batch; 429 if it's over a
    limit (then nothing is queued)."""
    todo = [n for n in nodes if n.source != NodeSource.upload and not store.active_job(n.id)]
    if not todo:
        return
    spending.check_jobs(collection_id, len(todo))
    spending.charge(actor, collection_id, step.kind.value, len(todo))
    for node in todo:
        queue_generation(store, worker, node, actor)


def _context(
    store, project, step: WorkflowStep | None, mentioned: list[tuple[Node, Output]]
) -> tuple[list[Piece], list[Piece], list[RefFile]]:
    """What a text model is shown besides the request: (references, decisions,
    files). References are the mentioned nodes, an image attached (and
    labelled in order) so the model can see it. Decisions are what earlier
    steps settled on, as text (images and videos by ID and the prompt that
    made them: never attached, they're costly), minus the mentioned ones."""
    files: list[RefFile] = []

    def reference(node: Node, output: Output) -> Piece:
        label = None
        if output.kind == MediaKind.image and output.asset is not None:
            files.append(ref_file(store, node.id, output.asset.id))
            label = image_label(len(files))
        text = output.text if output.kind == MediaKind.text else None
        if output.kind == MediaKind.video:
            # Not attached: the prompt that made it says what's in it.
            text = carried_piece("", node, output).text
        return Piece(kind=output.kind.value, text=text, label=label, name=node.name)

    references = [reference(n, o) for n, o in mentioned]
    taken = {n.id for n, _ in mentioned}
    decisions = (
        [
            carried_piece(name, n, o)
            for name, n, o in store.carried_forward(project, step.key)
            if n.id not in taken
        ]
        if step is not None
        else []
    )
    return references, decisions, files


def _ask_for_run(store, run: _Run) -> _Asked:
    """What a run says to the text model (see _write_items)."""
    project = store.get_project(run.project_id)
    # The step's own nodes are being replaced: mentioning them (say, by the
    # names the last run gave them) means nothing.
    mentioned = [
        (n, o)
        for n, o in store.mentioned_nodes(project.id, run.prompt)
        if n.workflow_step != run.step.key
    ]
    references, decisions, files = _context(store, project, run.step, mentioned)
    # The model names the results, afresh each run (the step's current IDs
    # are free to use again, not kept).
    current = [n.name for n in store.step_nodes(project.id, run.step.key) if n.name]
    taken = [name for name in store.node_names(project.id) if name not in current]
    system, user = run_messages(
        run.step,
        run.prompt,
        run.count,
        Instructions.of(project),
        references,
        Naming(taken=taken),
        decisions,
    )
    return _Asked(
        system,
        user,
        [f.load() for f in files],
        [*decisions, *references],
        [n.name for n, _ in mentioned if n.name],
    )


async def _write_items(text_model, run: _Run, asked: _Asked) -> list[RunItem]:
    """Ask the text model for the run's `count` results (or prompts)."""
    for _ in range(2):  # one retry: a malformed answer is rare, and cheap to ask again
        try:
            answer = await text_model.complete(
                asked.system,
                [{"role": "user", "content": asked.user}],
                run_spec(
                    run.count,
                    named=True,
                    seconds=run.step.kind == MediaKind.video,
                    prompted=run.step.kind == MediaKind.text,
                    uses=run.media and bool(asked.mentioned),
                ),
                asked.images,
            )
            items = parse_run(answer, run.count)
            texts = name_images([i.text for i in items], asked.pieces)
            items = [replace(i, text=t) for t, i in zip(texts, items, strict=True)]
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        except RunFormatError:
            continue
        if items:
            if run.media:
                # Each prompt gets the mentioned references it uses, not all of them.
                items = [keep_used(i, asked.mentioned) for i in items]
            return items
    raise ApiError(502, ErrorCode.provider_error, "the model returned no results; try again")


# --- takes and AI edits --------------------------------------------------------------------


@router.post(
    "/nodes/{node_id}/takes",
    status_code=201,
    operation_id="createTextTake",
    responses=responses(404, 409),
)
def create_text_take(node_id: NodeId, body: TakeCreate, store: StoreDep) -> Output:
    """A text take written by hand; it becomes the selected take."""
    return store.add_text_take(node_id, body.text)


@router.post(
    "/nodes/{node_id}/ai-edit",
    operation_id="editWithAi",
    responses=responses(404, 409, 429, 502, 503),
)
async def edit_with_ai(
    node_id: NodeId,
    body: AiEditRequest,
    store: StoreDep,
    text_model: TextModelDep,
    spending: SpendingDep,
    user: UserDep,
) -> AiEdit:
    """Suggest an edit of one node's prompt, changed only as ``instruction``
    asks ("a dog, not a cat": "a cat surfing" becomes "a dog surfing").
    Nothing is saved or generated: the answer is applied by the client.

    For a workflow text node (its prompt only made its result) it's the
    result that is edited, applied as a new take; so too for a text node
    with a result and no prompt. A video's length comes
    back too (kept unless asked to change). The model sees what a step run
    would: the instructions, the step, what earlier steps settled on and
    the nodes the text mentions. 409 ``not_generatable`` for an uploaded
    node; 502 if the model fails."""
    edit = await run_in_threadpool(_prepare_edit, store, spending, user.id, node_id, body)
    for _ in range(2):  # one retry: a malformed answer is rare, and cheap to ask again
        try:
            answer = await text_model.complete(
                edit.system, [{"role": "user", "content": edit.user}], edit_spec(edit.video)
            )
            text, seconds = parse_edit(answer)
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        except RunFormatError:
            continue
        return AiEdit(target=edit.target, text=text, seconds=seconds if edit.video else None)
    raise ApiError(502, ErrorCode.provider_error, "the model returned no text; try again")


@dataclass(frozen=True)
class _EditAsk:
    """What an AI edit says to the text model, and what it edits."""

    system: str
    user: str
    target: EditTarget
    video: bool


def _prepare_edit(store, spending, actor: str, node_id: str, body: AiEditRequest) -> _EditAsk:
    node = store.get_node(node_id)
    if node.source == NodeSource.upload:
        raise ApiError(409, ErrorCode.not_generatable, "an uploaded node has no prompt to edit")
    project = store.get_project(node.project_id)
    step = step_by_key(project.workflow, node.workflow_step) if node.workflow_step else None
    # A workflow text node's result is what it's for (its prompt only made
    # it): the edit changes the result, as a new take.
    edits_result = node.workflow_step is not None or not node.prompt.strip()
    if node.kind == MediaKind.text and edits_result and node.selected_output_id:
        target = EditTarget.text
        current = store.get_output(node.selected_output_id).text or ""
        what = W["what_text"]
    else:
        target, current = EditTarget.prompt, node.prompt
        what = W["what_prompt"].format(kind=node.kind.value)
    video = target == EditTarget.prompt and isinstance(node.params, VideoParams)
    spending.charge(actor, project.collection_id, "text")
    mentioned = [
        (n, o) for n, o in store.mentioned_nodes(project.id, current) if n.id != node.id
    ]
    references, decisions, _ = _context(store, project, step, mentioned)
    system, user = edit_messages(
        Instructions.of(project),
        step,
        what,
        current,
        body.instruction,
        references,
        decisions,
        node.params.duration_s if video else None,
    )
    return _EditAsk(system, user, target, video)


# --- settings --------------------------------------------------------------------------


@router.get("/settings", operation_id="getSettings", responses=responses(), tags=["settings"])
def get_settings(store: StoreDep, user: UserDep) -> AppSettings:
    """Your settings: the language of the UI."""
    return AppSettings(language=store.get_language(user.id))


@router.put("/settings", operation_id="setSettings", responses=responses(), tags=["settings"])
def set_settings(body: AppSettingsUpdate, store: StoreDep, user: UserDep) -> AppSettings:
    return AppSettings(language=store.set_language(user.id, body.language))
