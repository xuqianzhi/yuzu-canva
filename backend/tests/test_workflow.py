"""Workflows: templates (steps are a name and a kind), and running a step
with a prompt and a count."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from canvas_api.app import create_app
from canvas_api.contract import Operation
from canvas_api.domain.workflow import BUILTIN_ID, builtin_workflow, parse_run

from .conftest import make_settings, wait_for_job
from .test_api import error_code, new_node, new_project


def run_step(client: TestClient, project: str, step: str, prompt: str, count: int | None):
    return client.post(
        f"/api/projects/{project}/workflow/steps/{step}/run",
        json={"prompt": prompt, "count": count},
    )


def step_nodes(graph: dict, step: str) -> list[dict]:
    nodes = [n for n in graph["nodes"] if n["workflow_step"] == step]
    return sorted(nodes, key=lambda n: n["workflow_item"])


def graph_of(client: TestClient, project: str) -> dict:
    return client.get(f"/api/projects/{project}").json()


def mini() -> dict:
    return {
        "id": "ignored",
        "name": "Mini",
        "steps": [
            {"key": "brief", "name": "Brief", "kind": "text"},
            {"key": "posters", "name": "Posters", "kind": "image"},
        ],
    }


def test_templates_are_designed_once_and_copied_by_projects(client):
    [builtin] = client.get("/api/workflow-templates").json()
    assert builtin["id"] == BUILTIN_ID and builtin["is_default"]
    assert [(s["name"], s["kind"]) for s in builtin["definition"]["steps"]] == [
        ("Dish brainstorming", "text"),
        ("Character", "image"),
    ]
    project = graph_of(client, new_project(client))["project"]
    assert project["workflow"] == builtin_workflow().model_dump(mode="json")

    made = client.post("/api/workflow-templates", json={"definition": mini()})
    assert made.status_code == 201, made.text
    template = made.json()
    on_mini = client.post(
        "/api/projects", json={"name": "M", "workflow_template_id": template["id"]}
    ).json()["id"]
    edited = {**mini(), "name": "Mini 2"}
    updated = client.put(
        f"/api/workflow-templates/{template['id']}", json={"definition": edited}
    )
    assert updated.json()["definition"]["version"] == 2
    assert graph_of(client, on_mini)["project"]["workflow"]["name"] == "Mini"  # kept its copy

    twice = {**mini(), "steps": [mini()["steps"][0], mini()["steps"][0]]}
    assert client.post("/api/workflow-templates", json={"definition": twice}).status_code == 422
    client.post(f"/api/workflow-templates/{template['id']}/default")
    assert client.delete(f"/api/workflow-templates/{template['id']}").status_code == 409
    client.post(f"/api/workflow-templates/{BUILTIN_ID}/default")
    assert client.delete(f"/api/workflow-templates/{template['id']}").status_code == 204


def test_a_text_step_makes_one_node_per_result(client, fake_text):
    client.put("/api/global-instruction", json={"instruction": "Cozy, for kids."})
    project = new_project(client)
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
    for job in graph["active_jobs"]:
        assert wait_for_job(client, job["id"])["status"] == "succeeded"


def test_mentioned_images_are_shown_to_the_model(client, fake_text, fake_image):
    project = new_project(client)
    graph = run_step(client, project, "characters", "a fox", 1).json()
    wait_for_job(client, graph["active_jobs"][0]["id"])
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
    made = client.post("/api/workflow-templates", json={"definition": definition})
    assert made.status_code == 201, made.text
    response = client.post(
        "/api/projects", json={"name": "P", "workflow_template_id": made.json()["id"]}
    )
    return response.json()["id"]


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
    graph = run_step(client, project, "prompts", "two stills", 2).json()
    for job in graph["active_jobs"]:
        wait_for_job(client, job["id"])
    assert run_step(client, project, "scenes", "", None).status_code == 422  # needs a prompt
    graph = run_step(client, project, "scenes", "slow zoom in", None).json()
    scenes = step_nodes(graph, "scenes")
    assert [n["prompt"] for n in scenes] == ["slow zoom in", "slow zoom in"]
    job = graph["active_jobs"][0]
    assert [r["kind"] for r in job["input"]["refs"]] == ["image"]


def test_the_last_step_cant_feed_one_to_one(client):
    definition = {
        "id": "x",
        "name": "Bad",
        "steps": [{"key": "a", "name": "A", "kind": "text", "output": "one_to_one"}],
    }
    assert (
        client.post("/api/workflow-templates", json={"definition": definition}).status_code
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


def test_older_workflows_are_released(data_dir, fake_image):
    """Before: templates and nodes of a richer workflow model."""
    settings = make_settings(data_dir)
    generators = {Operation.image_generate: fake_image}
    with TestClient(create_app(settings, generators)) as client:
        project = new_project(client)
        node = new_node(client, project, kind="text")["id"]
    db = sqlite3.connect(settings.db_path)
    db.execute(
        "UPDATE nodes SET workflow_step = 'shots', workflow_item = 'itm_a' WHERE id = ?",
        (node,),
    )
    db.execute('UPDATE workflow_templates SET definition = \'{"id": "x", "label": {}}\'')
    db.execute("PRAGMA user_version = 3")
    db.commit()
    db.close()
    with TestClient(create_app(settings, generators)) as client:
        graph = graph_of(client, project)
        assert graph["nodes"][0]["workflow_step"] is None
        assert graph["project"]["workflow"]["id"] == BUILTIN_ID
        assert [t["id"] for t in client.get("/api/workflow-templates").json()] == [BUILTIN_ID]
