"""Instructions: a collection's (shared by its projects, read live) and each
project's own."""

from __future__ import annotations

from .helpers import run_step, step_nodes
from .test_api import error_code, list_projects, new_collection, new_project, patch_collection


def test_a_collections_instruction_starts_empty_and_can_be_set(client):
    collection = new_collection(client)
    assert client.get(f"/api/collections/{collection}").json()["instruction"] == ""
    saved = patch_collection(client, collection, instruction="Pastel colours.")
    assert saved.status_code == 200, saved.text
    assert saved.json()["instruction"] == "Pastel colours."
    too_long = patch_collection(client, collection, instruction="x" * 20_001)
    assert too_long.status_code == 422
    made = new_collection(client, "Given", instruction="Ink only.")
    assert client.get(f"/api/collections/{made}").json()["instruction"] == "Ink only."


def test_projects_read_the_collections_instruction_and_keep_their_description(client):
    collection = new_collection(client)
    patch_collection(client, collection, instruction="Pastel colours.")
    project = new_project(client, "P", collection)
    shown = client.get(f"/api/projects/{project}").json()["project"]
    # Not copied: the project's description starts empty; the collection's
    # instruction is read live.
    assert (shown["description"], shown["collection_instruction"]) == ("", "Pastel colours.")

    edited = client.patch(f"/api/projects/{project}", json={"description": "Neon, at night."})
    assert edited.json()["description"] == "Neon, at night."
    # Other edits leave it alone; the collection's changes show at once.
    client.patch(f"/api/projects/{project}", json={"name": "Q"})
    patch_collection(client, collection, instruction="Black and white.")
    graph = client.get(f"/api/projects/{project}").json()
    assert graph["project"]["description"] == "Neon, at night."
    assert graph["project"]["collection_instruction"] == "Black and white."
    listed = {p["id"]: p for p in list_projects(client, collection)}
    assert listed[project]["description"] == "Neon, at night."
    assert listed[project]["collection_instruction"] == "Black and white."

    given = new_project(client, "R", collection, description="Episode 2.")
    assert client.get(f"/api/projects/{given}").json()["project"]["description"] == "Episode 2."


def test_the_instruction_and_description_go_to_the_ai(client, fake_text):
    collection = new_collection(client, "Series", instruction="Always 3 scenes, 9:16.")
    project = new_project(client, "Ep 1", collection, description="A fox learns to cook.")
    graph = run_step(client, project, "dishes", "soups", 1).json()
    system = fake_text.calls[-1]["system"]
    series = "<collection_instruction>\nAlways 3 scenes, 9:16.\n</collection_instruction>"
    video = "<project_description>\nA fox learns to cook.\n</project_description>"
    assert series in system and video in system
    assert system.index(series) < system.index(video)

    node = step_nodes(graph, "dishes")[0]["id"]
    client.post(f"/api/nodes/{node}/ai-edit", json={"instruction": "shorter"})
    edit = fake_text.calls[-1]["system"]
    assert series in edit and video in edit

    # A project without a description sends only the collection's instruction.
    other = new_project(client, "Ep 2", collection)
    run_step(client, other, "dishes", "soups", 1)
    assert series in fake_text.calls[-1]["system"]
    assert "<project_description>\n" not in fake_text.calls[-1]["system"]


def test_saving_over_someone_elses_change_is_refused(client):
    collection = new_collection(client)
    version = client.get(f"/api/collections/{collection}").json()["version"]
    first = client.patch(
        f"/api/collections/{collection}", json={"version": version, "name": "Anime"}
    )
    assert first.json()["version"] == version + 1
    assert first.json()["updated_by_email"] == "alice@example.com"
    stale = client.patch(
        f"/api/collections/{collection}", json={"version": version, "instruction": "x"}
    )
    assert (stale.status_code, error_code(stale)) == (409, "edit_conflict")
    assert "alice@example.com" in stale.json()["error"]["message"]
