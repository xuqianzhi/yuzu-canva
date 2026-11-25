"""Editing one node's prompt (or a workflow text result) with AI."""

from __future__ import annotations

from .conftest import PNG, wait_for_job
from .helpers import graph_of, run_step, step_nodes, upload
from .test_api import error_code, generate, new_node, new_project


def ai_edit(client, node_id: str, instruction: str):
    return client.post(f"/api/nodes/{node_id}/ai-edit", json={"instruction": instruction})


def test_only_the_prompt_changes_and_nothing_is_saved(client, fake_text, fake_image):
    project = new_project(client)
    made = new_node(client, project)
    wait_for_job(client, generate(client, made["id"]).json()["id"])
    other = made["name"]
    node = new_node(client, project, prompt=f"a cat surfing on the ocean, like {other}")
    response = ai_edit(client, node["id"], "a dog, not a cat")
    assert response.status_code == 200, response.text
    edit = response.json()
    assert edit == {
        "target": "prompt",
        "text": f"a cat surfing on the ocean, like {other} (edited)",
        "seconds": None,
    }
    call = fake_text.calls[-1]
    assert "smallest edit" in call["system"]
    assert "<change>\na dog, not a cat\n</change>" in call["messages"][0]["content"]
    assert f'<reference id="{other}">' in call["messages"][0]["content"]
    # Not saved, not generated.
    graph = graph_of(client, project)
    saved = next(n for n in graph["nodes"] if n["id"] == node["id"])
    assert saved["prompt"] == node["prompt"] and graph["active_jobs"] == []
    assert client.get("/api/me").json()["used_today"]["text"] == 1


def test_a_video_edit_gets_its_length_and_returns_one(client, fake_text):
    project = new_project(client)
    node = new_node(client, project, kind="video", prompt="waves at dusk")
    edit = ai_edit(client, node["id"], "make it 8 seconds").json()
    assert edit["target"] == "prompt" and isinstance(edit["seconds"], int)
    call = fake_text.calls[-1]
    assert "4, unless the <change> asks for another length" in call["system"]  # its own: 4 s
    assert call["spec"].schema["required"] == ["content", "seconds"]
    # Other kinds are never asked for one.
    image = new_node(client, project, prompt="a fox")
    assert ai_edit(client, image["id"], "red").json()["seconds"] is None
    assert fake_text.calls[-1]["spec"].schema["required"] == ["content"]


def test_a_workflow_text_result_is_edited_as_a_take(client, fake_text):
    project = new_project(client)
    node = step_nodes(run_step(client, project, "dishes", "soups", 1).json(), "dishes")[0]
    edit = ai_edit(client, node["id"], "spicier").json()
    assert edit["target"] == "text" and edit["text"].startswith("Result 1:")
    assert "This step is called “Dish brainstorming”" in fake_text.calls[-1]["system"]


def test_uploaded_nodes_have_nothing_to_edit(client):
    project = new_project(client)
    image = upload(client, project, "fox.png", PNG).json()
    placed = client.post(
        f"/api/materials/{image['id']}/place", json={"position": {"x": 0, "y": 0}}
    )
    node = placed.json()
    refused = ai_edit(client, node["id"], "brighter")
    assert (refused.status_code, error_code(refused)) == (409, "not_generatable")


def test_changing_a_workflow_nodes_prompt_marks_it_edited(client, fake_text, fake_image):
    project = new_project(client)
    graph = run_step(client, project, "characters", "a fox", 2, generate=False).json()
    first, second = step_nodes(graph, "characters")
    assert not first["edited"]
    changed = client.patch(f"/api/nodes/{first['id']}", json={"prompt": "a dog"}).json()
    assert changed["edited"] is True
    moved = client.patch(f"/api/nodes/{second['id']}", json={"position": {"x": 1, "y": 2}})
    assert moved.json()["edited"] is False  # only the prompt counts
    # A text result written by hand counts too; a fresh run clears it all.
    dish = step_nodes(run_step(client, project, "dishes", "soups", 1).json(), "dishes")[0]
    client.post(f"/api/nodes/{dish['id']}/takes", json={"text": "my soup"})
    graph = graph_of(client, project)
    assert next(n for n in graph["nodes"] if n["id"] == dish["id"])["edited"] is True
    graph = run_step(client, project, "characters", "a fox", 2, generate=False).json()
    assert not any(n["edited"] for n in step_nodes(graph, "characters"))
    # Free nodes are never "edited": nothing would replace them.
    free = new_node(client, project)
    assert (
        client.patch(f"/api/nodes/{free['id']}", json={"prompt": "x"}).json()["edited"] is False
    )
