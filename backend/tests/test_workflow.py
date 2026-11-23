"""Workflows: several per collection, one active (steps are a name and a
kind), and running a step with a prompt and a count."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from canvas_api.domain.workflow import builtin_workflow, parse_run

from .conftest import wait_for_job
from .test_api import default_collection, error_code, new_collection, new_node, new_project


class Finished:
    """A finished run, shaped like a response: 200 with the graph, or 502
    with the run's error."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code, self._body = status_code, body
        self.text = str(body)

    def json(self) -> dict:
        return self._body


def run_step(client: TestClient, project: str, step: str, prompt: str, count: int | None):
    """Start a run and wait for it (it finishes in the background)."""
    response = client.post(
        f"/api/projects/{project}/workflow/steps/{step}/run",
        json={"prompt": prompt, "count": count},
    )
    if response.status_code != 202:
        return response
    started = next(r for r in response.json()["runs"] if r["step"] == step)
    assert started["status"] in ("running", "done", "failed")  # may already be over
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        graph = graph_of(client, project)
        run = next(r for r in graph["runs"] if r["step"] == step)
        if run["status"] == "done":
            return Finished(200, graph)
        if run["status"] == "failed":
            return Finished(502, {"error": {"code": "provider_error", "message": run["error"]}})
        time.sleep(0.02)
    raise AssertionError(f"step {step} still running")


def step_nodes(graph: dict, step: str) -> list[dict]:
    nodes = [n for n in graph["nodes"] if n["workflow_step"] == step]
    return sorted(nodes, key=lambda n: n["workflow_item"])


def graph_of(client: TestClient, project: str) -> dict:
    return client.get(f"/api/projects/{project}").json()


def wait_for_outputs(client: TestClient, project: str, step: str) -> None:
    """Until every node of the step has an output."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        nodes = step_nodes(graph_of(client, project), step)
        if nodes and all(n["selected_output_id"] for n in nodes):
            return
        time.sleep(0.02)
    raise AssertionError(f"{step} nodes still have no output")


def mini() -> dict:
    return {
        "id": "ignored",
        "name": "Mini",
        "steps": [
            {"key": "brief", "name": "Brief", "kind": "text"},
            {"key": "posters", "name": "Posters", "kind": "image"},
        ],
    }


def workflows(client: TestClient, collection: str) -> list[dict]:
    return client.get(f"/api/collections/{collection}/workflows").json()


def add_workflow(client: TestClient, collection: str, definition: dict):
    return client.post(
        f"/api/collections/{collection}/workflows", json={"definition": definition}
    )


def test_a_collection_starts_with_the_builtin_workflow_active(client):
    collection = new_collection(client)
    [builtin] = workflows(client, collection)
    assert builtin["id"].startswith("wfl_") and builtin["active"]
    assert (
        client.get(f"/api/collections/{collection}").json()["active_workflow_id"]
        == (builtin["id"])
    )
    assert [(s["name"], s["kind"]) for s in builtin["definition"]["steps"]] == [
        ("Dish brainstorming", "text"),
        ("Character", "image"),
    ]
    project = graph_of(client, new_project(client, collection=collection))["project"]
    expected = builtin_workflow().model_copy(update={"id": builtin["id"]})
    assert project["workflow"] == expected.model_dump(mode="json")
    # Or start it with a copy of another workflow.
    copied = new_collection(client, "Copy", workflow=mini())
    [only] = workflows(client, copied)
    assert only["definition"]["name"] == "Mini" and only["id"] != "ignored"


def test_projects_run_on_the_active_workflow(client):
    collection = new_collection(client)
    [builtin] = workflows(client, collection)
    project = new_project(client, collection=collection)
    made = add_workflow(client, collection, mini())
    assert made.status_code == 201, made.text
    other = made.json()
    assert not other["active"]
    assert graph_of(client, project)["project"]["workflow"]["name"] != "Mini"

    activated = client.post(f"/api/workflows/{other['id']}/activate")
    assert activated.status_code == 200 and activated.json()["active"]
    assert graph_of(client, project)["project"]["workflow"]["name"] == "Mini"
    # Editing the active one changes it for every project too.
    edited = client.put(
        f"/api/workflows/{other['id']}",
        json={"definition": {**mini(), "name": "Mini 2"}, "base_version": 1},
    )
    assert edited.json()["definition"]["version"] == 2
    assert graph_of(client, project)["project"]["workflow"]["name"] == "Mini 2"
    # Someone else's newer save isn't overwritten.
    stale = client.put(
        f"/api/workflows/{other['id']}", json={"definition": mini(), "base_version": 1}
    )
    assert (stale.status_code, error_code(stale)) == (409, "edit_conflict")

    twice = {**mini(), "steps": [mini()["steps"][0], mini()["steps"][0]]}
    assert add_workflow(client, collection, twice).status_code == 422
    active = client.delete(f"/api/workflows/{other['id']}")
    assert (active.status_code, error_code(active)) == (409, "validation_error")
    client.post(f"/api/workflows/{builtin['id']}/activate")
    assert client.delete(f"/api/workflows/{other['id']}").status_code == 204
    assert [w["id"] for w in workflows(client, collection)] == [builtin["id"]]


def test_switching_workflows_hides_steps_without_deleting_them(client):
    collection = new_collection(client)
    [builtin] = workflows(client, collection)
    project = new_project(client, collection=collection)
    graph = run_step(client, project, "dishes", "soups", 2).json()
    dishes = [n["id"] for n in step_nodes(graph, "dishes")]
    other = add_workflow(client, collection, mini()).json()

    client.post(f"/api/workflows/{other['id']}/activate")
    graph = graph_of(client, project)
    assert step_nodes(graph, "dishes") == [] and graph["runs"] == []
    client.post(f"/api/workflows/{builtin['id']}/activate")
    graph = graph_of(client, project)
    assert [n["id"] for n in step_nodes(graph, "dishes")] == dishes
    assert [r["step"] for r in graph["runs"]] == ["dishes"]


def test_the_active_workflow_cant_change_while_a_step_runs(settings, fake_image):
    from canvas_api.app import create_app
    from canvas_api.contract import Operation
    from canvas_api.providers.fake import FakeTextModel

    from .conftest import signed_in

    slow = FakeTextModel(delay_s=0.5)
    with signed_in(
        create_app(settings, {Operation.image_generate: fake_image}, slow)
    ) as client:
        collection = new_collection(client)
        [builtin] = workflows(client, collection)
        other = add_workflow(client, collection, mini()).json()
        project = new_project(client, collection=collection)
        started = client.post(
            f"/api/projects/{project}/workflow/steps/dishes/run",
            json={"prompt": "soups", "count": 1},
        )
        assert started.status_code == 202
        busy = client.post(f"/api/workflows/{other['id']}/activate")
        assert (busy.status_code, error_code(busy)) == (409, "workflow_locked")
        edit = client.put(
            f"/api/workflows/{builtin['id']}", json={"definition": builtin["definition"]}
        )
        assert edit.status_code == 409
        # An inactive one can be edited meanwhile.
        assert (
            client.put(f"/api/workflows/{other['id']}", json={"definition": mini()}).status_code
            == 200
        )


def test_a_text_step_makes_one_node_per_result(client, fake_text):
    collection = new_collection(client, "Kids", instruction="Cozy, for kids.")
    project = new_project(client, collection=collection)
    response = run_step(client, project, "dishes", "winter soups", 3)
    assert response.status_code == 200, response.text
    graph = response.json()
    nodes = step_nodes(graph, "dishes")
    assert [(n["name"], n["kind"], n["workflow_item"]) for n in nodes] == [
        ("dishes_1", "text", 1),
        ("dishes_2", "text", 2),
        ("dishes_3", "text", 3),
    ]
    outputs = {o["id"]: o for o in graph["outputs"]}
    assert outputs[nodes[0]["selected_output_id"]]["text"].startswith("Result 1:")
    assert graph["runs"][0] | {"updated_at": None} == {
        "step": "dishes",
        "prompt": "winter soups",
        "count": 3,
        "status": "done",
        "error": None,
        "updated_at": None,
    }
    call = fake_text.calls[-1]
    assert (
        "Cozy, for kids." in call["system"]
        and "## This step: Dish brainstorming" in call["system"]
    )
    assert "exactly 3" in call["system"]
    assert call["messages"][0]["content"] == "## Request\nwinter soups"
    schema = call["spec"].schema["properties"]["items"]
    assert (schema["minItems"], schema["maxItems"]) == (3, 3)

    # Running again replaces the step's nodes.
    again = run_step(client, project, "dishes", "summer salads", 2).json()
    assert [n["name"] for n in step_nodes(again, "dishes")] == ["dishes_1", "dishes_2"]
    assert all(n["id"] not in {m["id"] for m in nodes} for n in step_nodes(again, "dishes"))


def test_independent_results_are_used_by_mentioning_their_ids(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "dishes", "winter soups", 2)
    # Nothing flows to the next step by itself.
    run_step(client, project, "characters", "a mascot", 1)
    assert fake_text.calls[-1]["messages"][0]["content"] == "## Request\na mascot"

    fake_image.gate.clear()  # keep the new image jobs running while we look
    graph = run_step(client, project, "characters", "a mascot for dishes_2", 2).json()
    call = fake_text.calls[-1]
    sent = call["messages"][0]["content"]
    assert sent.startswith("## dishes_2\nResult 2:")
    assert sent.endswith("## Request\na mascot for dishes_2")
    assert "write those IDs exactly" in call["system"]
    nodes = step_nodes(graph, "characters")
    assert [n["name"] for n in nodes] == ["characters_1", "characters_2"]
    # Each prompt keeps the mention, so the dish is linked as an input.
    assert all("dishes_2" in n["prompt"] for n in nodes)
    dish = step_nodes(graph, "dishes")[1]
    into = [e for e in graph["edges"] if e["target_node_id"] == nodes[0]["id"]]
    assert [(e["source_node_id"], e["workflow"]) for e in into] == [(dish["id"], False)]
    # Each image is generated right away.
    assert len(graph["active_jobs"]) == 2
    fake_image.gate.set()
    for job in graph["active_jobs"]:
        assert wait_for_job(client, job["id"])["status"] == "succeeded"


def test_mentioned_images_are_shown_to_the_model(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "characters", "a fox", 1)
    wait_for_outputs(client, project, "characters")
    run_step(client, project, "dishes", "a soup for characters_1", 2)
    call = fake_text.calls[-1]
    assert call["messages"][0]["content"].startswith(
        "## characters_1\n(an image, sent as image 1)"
    )
    assert len(call["images"]) == 1


def one_to_one_template(client, first: str = "text", second: str = "image") -> str:
    definition = {
        "id": "x",
        "name": "Pipeline",
        "steps": [
            {"key": "prompts", "name": "Prompts", "kind": first, "output": "one_to_one"},
            {"key": "scenes", "name": "Scenes", "kind": second},
        ],
    }
    collection = new_collection(client, "Pipeline", workflow=definition)
    return new_project(client, "P", collection)


def test_one_to_one_feeds_each_result_to_its_own_node(client, fake_text, fake_image):
    project = one_to_one_template(client)
    blocked = run_step(client, project, "scenes", "", 2)
    assert (blocked.status_code, error_code(blocked)) == (409, "workflow_blocked")
    graph = run_step(client, project, "prompts", "three scenes", 3).json()
    prompts = step_nodes(graph, "prompts")
    assert [n["name"] for n in prompts] == [None, None, None]  # nothing may refer to them
    renamed = client.patch(f"/api/nodes/{prompts[0]['id']}", json={"name": "p1"})
    assert (renamed.status_code, error_code(renamed)) == (409, "workflow_locked")

    calls = len(fake_text.calls)
    graph = run_step(client, project, "scenes", "", 5).json()  # the count follows the inputs
    scenes = step_nodes(graph, "scenes")
    outputs = {o["id"]: o for o in graph["outputs"]}
    assert [n["prompt"] for n in scenes] == [
        outputs[p["selected_output_id"]]["text"] for p in prompts
    ]
    assert len(fake_text.calls) == calls  # the texts are the prompts: no model call
    pairs = {
        (e["source_node_id"], e["target_node_id"]) for e in graph["edges"] if e["workflow"]
    }
    assert pairs == {(p["id"], s["id"]) for p, s in zip(prompts, scenes, strict=True)}
    assert [n["name"] for n in scenes] == ["scenes_1", "scenes_2", "scenes_3"]
    for job in graph["active_jobs"]:
        assert wait_for_job(client, job["id"])["status"] == "succeeded"

    # A shared direction is added to each.
    graph = run_step(client, project, "scenes", "in watercolour", None).json()
    assert all(n["prompt"].endswith("\nin watercolour") for n in step_nodes(graph, "scenes"))


def test_one_to_one_into_text_writes_one_result_per_input(client, fake_text):
    project = one_to_one_template(client, "text", "text")
    run_step(client, project, "prompts", "ideas", 2)
    graph = run_step(client, project, "scenes", "expand each", None).json()
    assert len(step_nodes(graph, "scenes")) == 2
    call = fake_text.calls[-1]
    assert "one result for each of the 2 inputs" in call["system"]
    assert "## Inputs, one per result\nInput 1: Result 1:" in call["messages"][0]["content"]


def test_one_to_one_images_are_references(client, fake_image, fake_video):
    project = one_to_one_template(client, "image", "video")
    run_step(client, project, "prompts", "two stills", 2)
    wait_for_outputs(client, project, "prompts")
    assert run_step(client, project, "scenes", "", None).status_code == 422  # needs a prompt
    fake_video.gate.clear()  # keep the video jobs running while we look
    graph = run_step(client, project, "scenes", "slow zoom in", None).json()
    scenes = step_nodes(graph, "scenes")
    assert [n["prompt"] for n in scenes] == ["slow zoom in", "slow zoom in"]
    job = graph["active_jobs"][0]
    assert [r["kind"] for r in job["input"]["refs"]] == ["image"]
    fake_video.gate.set()


def test_the_last_step_cant_feed_one_to_one(client):
    definition = {
        "id": "x",
        "name": "Bad",
        "steps": [{"key": "a", "name": "A", "kind": "text", "output": "one_to_one"}],
    }
    collection = default_collection(client)
    assert add_workflow(client, collection, definition).status_code == 422
    assert (
        client.post(
            "/api/collections", json={"name": "Bad", "workflow": definition}
        ).status_code
        == 422
    )


def test_runs_are_checked(client):
    project = new_project(client)
    assert run_step(client, project, "dishes", "", 2).status_code == 422
    assert run_step(client, project, "dishes", "x", None).status_code == 422  # how many?
    assert run_step(client, project, "dishes", "x", 0).status_code == 422
    assert run_step(client, project, "dishes", "x", 21).status_code == 422
    assert run_step(client, project, "nope", "x", 1).status_code == 404
    assert parse_run('{"items": [" a ", "", "b", "c"]}', 2) == ["a", "b"]


def test_workflow_nodes_are_locked_but_editable(client):
    project = new_project(client)
    node = step_nodes(run_step(client, project, "characters", "a fox", 1).json(), "characters")[
        0
    ]
    deleted = client.delete(f"/api/nodes/{node['id']}")
    assert (deleted.status_code, error_code(deleted)) == (409, "workflow_locked")
    retyped = client.patch(f"/api/nodes/{node['id']}", json={"kind": "text"})
    assert (retyped.status_code, error_code(retyped)) == (409, "workflow_locked")
    assert (
        client.patch(f"/api/nodes/{node['id']}", json={"prompt": "a red fox"}).status_code
        == 200
    )


def test_chat_and_takes_on_text_nodes(client, fake_text):
    project = new_project(client)
    node = step_nodes(run_step(client, project, "dishes", "soups", 1).json(), "dishes")[0]
    sent = client.post(f"/api/nodes/{node['id']}/chat", json={"text": "make it spicier"})
    assert sent.status_code == 200, sent.text
    _, answer = sent.json()
    assert "## This step: Dish brainstorming" in fake_text.calls[-1]["system"]
    applied = client.post(f"/api/chat/{answer['id']}/apply").json()
    take = client.post(f"/api/nodes/{node['id']}/takes", json={"text": "my own"}).json()
    outputs = client.get(f"/api/nodes/{node['id']}/outputs").json()
    assert [o["id"] for o in outputs][:2] == [take["id"], applied["id"]]
    image = new_node(client, project)["id"]
    assert client.post(f"/api/nodes/{image}/chat", json={"text": "hi"}).status_code == 409
