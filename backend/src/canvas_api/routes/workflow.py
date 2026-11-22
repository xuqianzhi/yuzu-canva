"""Workflows: templates, running a step, hand-written takes, and each text
node's chat. Plus the app's settings."""

from __future__ import annotations

import json

from fastapi import APIRouter, Response

from ..contract import (
    AppSettings,
    AppSettingsUpdate,
    ChatMessage,
    ChatRequest,
    ChatRole,
    ErrorCode,
    MediaKind,
    Node,
    NodeId,
    Output,
    OutputUse,
    ProjectGraph,
    ProjectId,
    StepRunRequest,
    TakeCreate,
    WorkflowTemplate,
    WorkflowTemplateSave,
)
from ..deps import StoreDep, TextModelDep, WorkerDep
from ..domain.workflow import (
    Piece,
    RunFormatError,
    chat_spec,
    chat_system,
    current_version_block,
    image_label,
    parse_run,
    run_messages,
    run_spec,
    step_by_key,
    words,
)
from ..errors import ApiError, responses
from ..jobs.queue import queue_generation
from ..providers.base import ProviderError, RefFile
from ..providers.openai_text import parse_chat_answer

router = APIRouter(tags=["workflow"])

# How much of a chat is sent back to the model with each new message.
CHAT_HISTORY = 20


def _provider_error(exc: ProviderError) -> ApiError:
    return ApiError(502, ErrorCode.provider_error, str(exc))


# --- templates -------------------------------------------------------------------------


@router.get("/workflow-templates", operation_id="listWorkflowTemplates", responses=responses())
def list_workflow_templates(store: StoreDep) -> list[WorkflowTemplate]:
    """Every workflow template, oldest first; one is the default."""
    return store.list_templates()


@router.post(
    "/workflow-templates",
    status_code=201,
    operation_id="createWorkflowTemplate",
    responses=responses(),
)
def create_workflow_template(body: WorkflowTemplateSave, store: StoreDep) -> WorkflowTemplate:
    """A new template (422 if two steps share a key)."""
    return store.save_template(None, body.definition)


@router.put(
    "/workflow-templates/{template_id}",
    operation_id="updateWorkflowTemplate",
    responses=responses(404),
)
def update_workflow_template(
    template_id: str, body: WorkflowTemplateSave, store: StoreDep
) -> WorkflowTemplate:
    """Replace a template (its version goes up). Projects already made keep
    their own copy."""
    return store.save_template(template_id, body.definition)


@router.delete(
    "/workflow-templates/{template_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteWorkflowTemplate",
    responses=responses(404, 409),
)
def delete_workflow_template(template_id: str, store: StoreDep) -> None:
    """Not the default one (409)."""
    store.delete_template(template_id)


@router.post(
    "/workflow-templates/{template_id}/default",
    operation_id="setDefaultWorkflowTemplate",
    responses=responses(404),
)
def set_default_workflow_template(template_id: str, store: StoreDep) -> WorkflowTemplate:
    """New projects copy this template."""
    return store.set_default_template(template_id)


# --- running a step --------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/workflow/steps/{step_key}/run",
    operation_id="runStep",
    responses=responses(404, 502),
)
async def run_step(
    project_id: ProjectId,
    step_key: str,
    body: StepRunRequest,
    store: StoreDep,
    worker: WorkerDep,
    text_model: TextModelDep,
) -> ProjectGraph:
    """Run a step; its earlier nodes are replaced. Returns the graph (with
    the new jobs).

    The prompt, the project instruction and the nodes the prompt mentions
    (by ID) go to a text model, which writes ``count`` results (a text
    step: its nodes' text) or prompts (an image or video step: one node
    each, generated right away, with the mentioned nodes as references).
    After a one-to-one step, there is one result per node of that step
    (``count`` is ignored), each made from its own input; an image or video
    step fed by text uses each text as its prompt directly.
    """
    project = store.get_project(project_id)
    step = step_by_key(project.workflow, step_key)
    if step is None:
        raise ApiError(404, ErrorCode.not_found, f"workflow step {step_key} not found")
    prompt = body.prompt.strip()
    sources = _one_to_one_sources(store, project_id, project.workflow, step)
    count = len(sources) if sources is not None else body.count
    if count is None:
        raise ApiError(422, ErrorCode.validation_error, "say how many to make")
    media = step.kind != MediaKind.text
    direct = media and bool(sources) and all(o.kind == MediaKind.text for _, o in sources)
    if not prompt and not direct:
        raise ApiError(422, ErrorCode.validation_error, "write a prompt first")
    mentioned = store.mentioned_nodes(project_id, prompt)

    if direct:
        # Each input text is its node's prompt (with the run's prompt, if any).
        items = [f"{o.text or ''}\n{prompt}".strip() for _, o in sources]
    elif media and sources:
        # Media inputs (e.g. image -> video): the same prompt for each, the
        # input itself going along as a reference.
        items = [prompt] * count
    else:
        items = await _write_items(
            store, text_model, project, step, prompt, count, mentioned, sources
        )
    if media:
        # The prompt's mentions are each node's references: keep them in.
        names = [n.name for n in mentioned if n.name]
        items = [" ".join([item, *(n for n in names if n not in item)]) for item in items]

    nodes, cancelled = store.replace_step_nodes(
        project_id,
        step_key,
        prompt,
        items,
        count,
        sources=[n.id for n, _ in sources] if sources else None,
    )
    for job_id in cancelled:
        worker.abort(job_id)
    if media:
        for node in nodes:
            queue_generation(store, worker, node)
    return store.get_graph(project_id)


def _one_to_one_sources(
    store, project_id: str, workflow, step
) -> list[tuple[Node, Output]] | None:
    """The step before's nodes and outputs when it feeds this one
    one-to-one (all must be made); None otherwise."""
    index = workflow.steps.index(step)
    before = workflow.steps[index - 1] if index else None
    if before is None or before.output != OutputUse.one_to_one:
        return None
    nodes = store.step_nodes(project_id, before.key)
    if not nodes:
        raise ApiError(409, ErrorCode.workflow_blocked, f"run “{before.name}” first")
    if any(not n.selected_output_id for n in nodes):
        raise ApiError(
            409, ErrorCode.workflow_blocked, f"wait until every “{before.name}” node is made"
        )
    return [(n, store.get_output(n.selected_output_id)) for n in nodes]


async def _write_items(
    store,
    text_model,
    project,
    step,
    prompt: str,
    count: int,
    mentioned: list[Node],
    sources: list[tuple[Node, Output]] | None,
) -> list[str]:
    """Ask the text model for `count` results (or prompts). Mentioned nodes
    and one-to-one inputs go along: text quoted, images sent so the model
    can see them (labelled in that order)."""
    language = store.get_language().value
    files: list[RefFile] = []

    def piece(node: Node, output: Output, name: str | None = None) -> Piece:
        label = None
        if output.kind == MediaKind.image and output.asset is not None:
            asset, path = store.asset_file(output.asset.id)
            files.append(RefFile(node_id=node.id, kind=asset.kind, path=path, mime=asset.mime))
            label = image_label(language, len(files))
        text = output.text if output.kind == MediaKind.text else None
        return Piece(kind=output.kind.value, text=text, label=label, name=name)

    references = [piece(n, store.get_output(n.selected_output_id), n.name) for n in mentioned]
    inputs = [piece(n, o) for n, o in sources] if sources else None
    system, user = run_messages(
        step, prompt, count, project.instruction, references, inputs, language
    )
    images = [f.load() for f in files]
    for _ in range(2):  # one retry: a malformed answer is rare, and cheap to ask again
        try:
            answer = await text_model.complete(
                system, [{"role": "user", "content": user}], run_spec(count), images
            )
            items = parse_run(answer, count)
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        except RunFormatError:
            continue
        if items:
            return items
    raise ApiError(502, ErrorCode.provider_error, "the model returned no results; try again")


# --- takes and chat --------------------------------------------------------------------


@router.post(
    "/nodes/{node_id}/takes",
    status_code=201,
    operation_id="createTextTake",
    responses=responses(404, 409),
)
def create_text_take(node_id: NodeId, body: TakeCreate, store: StoreDep) -> Output:
    """A text take written by hand; it becomes the selected take."""
    return store.add_text_take(node_id, body.text)


@router.get("/nodes/{node_id}/chat", operation_id="listChat", responses=responses(404))
def list_chat(node_id: NodeId, store: StoreDep) -> list[ChatMessage]:
    """The node's chat, oldest first."""
    return store.list_messages(node_id)


@router.post(
    "/nodes/{node_id}/chat",
    operation_id="sendChat",
    responses=responses(404, 409, 502),
)
async def send_chat(
    node_id: NodeId, body: ChatRequest, store: StoreDep, text_model: TextModelDep
) -> list[ChatMessage]:
    """Ask the model about a text node; returns your message and its answer.

    The model sees the project instruction (for a workflow node, and its
    step), the current version and the chat so far. When it suggests a new
    version, the answer's ``proposal`` holds it whole; ``applyProposal``
    turns it into a take. Nothing is saved if the model fails (502).
    """
    node = store.get_node(node_id)
    if node.kind != MediaKind.text:
        raise ApiError(409, ErrorCode.not_generatable, "chat works on text nodes")
    language = store.get_language().value
    w = words(language)
    step_name, instruction = None, ""
    if node.workflow_step:
        project = store.get_project(node.project_id)
        step = step_by_key(project.workflow, node.workflow_step)
        step_name = step.name if step else None
        instruction = project.instruction
    current = None
    if node.selected_output_id:
        current = store.get_output(node.selected_output_id).text
    understood = json.dumps({"reply": w["understood"], "proposal": None}, ensure_ascii=False)
    messages = [
        {
            "role": "user",
            "content": f"{current_version_block(current, language)}\n\n{w['context_note']}",
        },
        {"role": "assistant", "content": understood},
    ]
    for message in store.list_messages(node_id)[-CHAT_HISTORY:]:
        if message.role == ChatRole.user:
            messages.append({"role": "user", "content": message.text})
        else:
            said = {"reply": message.text, "proposal": message.proposal}
            messages.append(
                {"role": "assistant", "content": json.dumps(said, ensure_ascii=False)}
            )
    messages.append({"role": "user", "content": body.text})
    try:
        answer = await text_model.complete(
            chat_system(instruction, step_name, language), messages, chat_spec()
        )
        reply, proposal = parse_chat_answer(answer)
    except ProviderError as exc:
        raise _provider_error(exc) from exc
    proposal_text = str(proposal).strip() if proposal is not None else None
    return store.add_messages(
        node_id,
        [(ChatRole.user, body.text, None), (ChatRole.assistant, reply, proposal_text or None)],
    )


@router.post(
    "/chat/{message_id}/apply",
    status_code=201,
    operation_id="applyProposal",
    responses=responses(404, 409),
)
def apply_proposal(message_id: str, store: StoreDep) -> Output:
    """Turn an answer's proposal into a take of its node (selected)."""
    return store.apply_proposal(message_id)


# --- settings --------------------------------------------------------------------------


@router.get("/settings", operation_id="getSettings", responses=responses(), tags=["settings"])
def get_settings(store: StoreDep) -> AppSettings:
    """App-wide settings: the language of the UI and of every prompt the
    backend writes for the models."""
    return AppSettings(language=store.get_language())


@router.put("/settings", operation_id="setSettings", responses=responses(), tags=["settings"])
def set_settings(body: AppSettingsUpdate, store: StoreDep) -> AppSettings:
    return AppSettings(language=store.set_language(body.language))
