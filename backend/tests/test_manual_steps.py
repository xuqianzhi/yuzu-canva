"""Completing a workflow step by hand: the user's own texts, images or
videos become the step's nodes; nothing is generated or charged."""

from __future__ import annotations

from .conftest import PNG, signed_in, wait_for_job
from .helpers import (
    VIDEO,
    complete,
    graph_of,
    jpeg,
    material,
    run_of,
    run_step,
    step_nodes,
)
from .test_api import new_project


def test_a_text_step_by_hand(client, fake_text):
    project = new_project(client)
    response = complete(
        client,
        project,
        "dishes",
        {"id": "番茄炒蛋", "text": " eggs and tomato "},
        {"text": "soup"},
    )
    assert response.status_code == 200, response.text
    graph = response.json()
    nodes = step_nodes(graph, "dishes")
    assert [n["name"] for n in nodes] == ["番茄炒蛋", "dishes_2"]
    outputs = {o["id"]: o for o in graph["outputs"]}
    assert [outputs[n["selected_output_id"]]["text"] for n in nodes] == [
        "eggs and tomato",
        "soup",
    ]
    run = run_of(graph, "dishes")
    assert (run["status"], run["manual"], run["count"], run["prompt"]) == ("done", True, 2, "")
    assert fake_text.calls == []
    assert client.get("/api/me").json()["used_today"] == {"text": 0, "image": 0, "video": 0}


def test_an_image_step_by_hand(client, fake_image, fake_text):
    project = new_project(client)
    first = material(client, project, "chef.png", PNG)
    second = material(client, project, "fox.jpg", jpeg())
    graph = complete(
        client,
        project,
        "characters",
        {"material_id": first},
        {"id": "fox", "material_id": second},
    ).json()
    nodes = step_nodes(graph, "characters")
    assert [n["name"] for n in nodes] == ["characters_1", "fox"]
    assert all(n["prompt"] == "" and n["source"] == "generate" for n in nodes)
    assert graph["active_jobs"] == []  # nothing generated
    outputs = {o["id"]: o for o in graph["outputs"]}
    takes = [outputs[n["selected_output_id"]] for n in nodes]
    assert [t["asset"]["mime"] for t in takes] == ["image/png", "image/jpeg"]
    # Each node has its own copy: the library can lose the upload.
    assert client.delete(f"/api/materials/{first}").status_code == 204
    assert client.get(takes[0]["asset"]["url"]).content == PNG
    assert client.get("/api/me").json()["used_today"]["image"] == 0
    # The nodes are used like generated ones: a mention sends the image along.
    assert run_step(client, project, "dishes", "a soup for fox", 1).status_code == 200
    call = fake_text.calls[-1]
    assert '<reference id="fox">' in call["messages"][0]["content"]
    assert len(call["images"]) == 1


def test_entries_must_fit_the_step(client):
    project = new_project(client)
    other = new_project(client, "Other")
    image = material(client, project, "a.png", PNG)
    video = material(client, project, "a.mp4", VIDEO)
    elsewhere = material(client, other, "b.png", PNG)

    assert complete(client, project, "characters", {"text": "a fox"}).status_code == 422
    assert complete(client, project, "characters", {"material_id": video}).status_code == 422
    assert (
        complete(client, project, "characters", {"material_id": elsewhere}).status_code == 404
    )
    assert complete(client, project, "dishes", {"material_id": image}).status_code == 422
    assert complete(client, project, "dishes", {"text": "  "}).status_code == 422
    both = {"text": "x", "material_id": image}
    assert complete(client, project, "dishes", both).status_code == 422
    assert complete(client, project, "dishes").status_code == 422  # nothing
    assert complete(client, project, "nope", {"text": "x"}).status_code == 404
    # Nothing was made.
    assert step_nodes(graph_of(client, project), "characters") == []


def test_by_hand_then_with_ai(client, fake_text):
    project = new_project(client)
    run_step(client, project, "dishes", "winter soups", 2)
    graph = complete(client, project, "dishes", {"text": "my own soup"}).json()
    run = run_of(graph, "dishes")
    # The prompt stays, for running it again.
    assert (run["manual"], run["prompt"], run["count"]) == (True, "winter soups", 1)
    assert len(step_nodes(graph, "dishes")) == 1

    graph = run_step(client, project, "dishes", "winter soups", 2).json()
    assert run_of(graph, "dishes")["manual"] is False
    assert len(step_nodes(graph, "dishes")) == 2


def test_by_hand_cancels_what_the_step_was_making(client, fake_text, fake_image):
    project = new_project(client)
    fake_image.gate.clear()
    graph = run_step(client, project, "characters", "a fox", 1).json()
    job = graph["active_jobs"][0]["id"]
    image = material(client, project, "a.png", PNG)
    complete(client, project, "characters", {"material_id": image})
    fake_image.gate.set()
    assert wait_for_job(client, job)["status"] == "canceled"


def test_outsiders_cannot(client):
    project = new_project(client)
    stranger = signed_in(client.app, "stranger@example.com")
    assert complete(stranger, project, "dishes", {"text": "x"}).status_code == 404
