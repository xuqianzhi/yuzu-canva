"""What earlier steps settled on goes to later ones by itself: all of a
step's results, or (carry "none") only what a prompt mentions."""

from __future__ import annotations

import re

from canvas_api.domain.workflow import builtin_workflow

from .conftest import PNG
from .helpers import run_step, step_nodes, upload, wait_for_outputs
from .test_api import new_collection, new_project


def kept(call: dict) -> list[str]:
    """The IDs of the results a run was given as decisions, in
    order (by their tags: the fake model's own results echo text)."""
    return re.findall(r'<kept step="[^"]*" id="([^"]*)"', call["messages"][0]["content"])


def test_the_dish_brainstorm_goes_along_only_when_mentioned(client, fake_text, fake_image):
    # Like a real project: two characters, three dish ideas, then a dish image
    # made from one of them (mentioned); the brainstorm itself isn't carried.
    project = new_project(client)
    run_step(client, project, "characters", "two chefs", 2)
    wait_for_outputs(client, project, "characters")

    run_step(client, project, "dishes", "three soups", 3)
    call = fake_text.calls[-1]
    assert kept(call) == ["characters_1", "characters_2"]
    # Images go as the prompt that made them, never attached (costly).
    assert (
        '<kept step="Character" id="characters_1" kind="image">\n'
        "(a generated image, not attached; made from this prompt:)\nResult 1:"
    ) in call["messages"][0]["content"]
    assert call["images"] == []
    assert "write that id exactly as it is in the prompt" not in call["system"]  # a text step

    run_step(client, project, "dish_images", "dishes_2 on a plate", 1)
    wait_for_outputs(client, project, "dish_images")
    call = fake_text.calls[-1]
    assert kept(call) == ["characters_1", "characters_2"]
    assert '<reference id="dishes_2">' in call["messages"][0]["content"]

    run_step(client, project, "script", "a story", 1)
    # In step order; no dish idea, even the one mentioned earlier.
    assert kept(fake_text.calls[-1]) == ["characters_1", "characters_2", "dish_images_1"]


def test_carried_media_is_never_attached_but_mentions_are(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "characters", "a big cast", 8)
    wait_for_outputs(client, project, "characters")
    # An image step: told to write the carried IDs, which is what gives the
    # pictures to the image model when it generates.
    run_step(client, project, "dish_images", "a soup", 1)
    call = fake_text.calls[-1]
    assert call["images"] == []
    assert len(kept(call)) == 8
    assert "write that id exactly as it is in the prompt" in call["system"]
    # Mentioned, a picture is attached: the user asked for it.
    run_step(client, project, "dish_images", "a soup for characters_3", 1)
    call = fake_text.calls[-1]
    assert len(call["images"]) == 1
    assert "characters_3" not in kept(call)  # a reference, not a decision


def test_provided_media_is_carried_by_name(client, fake_text):
    project = new_project(client)
    image = upload(client, project, "chef.png", PNG).json()["id"]
    complete = client.post(
        f"/api/projects/{project}/workflow/steps/characters/complete",
        json={"entries": [{"id": "主厨", "material_id": image}]},
    )
    assert complete.status_code == 200, complete.text
    run_step(client, project, "dishes", "soups", 1)
    content = fake_text.calls[-1]["messages"][0]["content"]
    assert (
        '<kept step="Character" id="主厨" kind="image">\n'
        "(an image the user provided, not attached)" in content
    )


def test_ai_edit_gets_the_decisions_too(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "characters", "a chef", 1)
    wait_for_outputs(client, project, "characters")
    graph = run_step(client, project, "dishes", "soups", 1).json()
    node = step_nodes(graph, "dishes")[0]["id"]
    client.post(f"/api/nodes/{node}/ai-edit", json={"instruction": "spicier"})
    sent = fake_text.calls[-1]["messages"][0]["content"]
    assert '<decisions>\n<kept step="Character" id="characters_1" kind="image">' in sent


def test_the_setting_is_part_of_the_workflow(client):
    steps = {s.key: s.carry.value for s in builtin_workflow().steps}
    assert steps.pop("dishes") == "none"
    assert set(steps.values()) == {"all"}
    definition = {
        "id": "x",
        "name": "Mine",
        "steps": [{"key": "ideas", "name": "Ideas", "kind": "text"}],
    }
    collection = new_collection(client, "Mine", workflow=definition)
    workflow = client.get(f"/api/collections/{collection}/workflows").json()[0]
    assert workflow["definition"]["steps"][0]["carry"] == "none"  # the default
    for carry in ("used", "some"):  # "used" is gone
        bad = {**definition, "steps": [{**definition["steps"][0], "carry": carry}]}
        response = client.post(
            f"/api/collections/{collection}/workflows", json={"definition": bad}
        )
        assert response.status_code == 422


def test_none_passes_nothing_unless_mentioned(client, fake_text):
    definition = {
        "id": "x",
        "name": "Pipeline",
        "steps": [
            {"key": "ideas", "name": "Ideas", "kind": "text", "carry": "none"},
            {"key": "scenes", "name": "Scenes", "kind": "text", "carry": "all"},
            {"key": "final", "name": "Final", "kind": "text"},
        ],
    }
    collection = new_collection(client, "Pipeline", workflow=definition)
    saved = client.get(f"/api/collections/{collection}/workflows").json()[0]["definition"]
    assert [s["carry"] for s in saved["steps"]] == ["none", "all", "none"]
    project = new_project(client, "P", collection)
    run_step(client, project, "ideas", "an idea", 1)
    run_step(client, project, "scenes", "two scenes", 2)
    run_step(client, project, "final", "wrap up", 1)
    assert kept(fake_text.calls[-1]) == ["scenes_1", "scenes_2"]  # only the scenes
    assert '<kept step="Ideas"' not in fake_text.calls[-1]["messages"][0]["content"]
    # Mentioned, it goes along all the same (as a reference).
    run_step(client, project, "final", "wrap up ideas_1", 1)
    assert '<reference id="ideas_1">' in fake_text.calls[-1]["messages"][0]["content"]
