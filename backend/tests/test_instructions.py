"""A collection's instruction, and each project's own copy of it."""

from __future__ import annotations

from .test_api import error_code, list_projects, new_collection, new_project


def set_instruction(client, collection: str, text: str):
    version = client.get(f"/api/collections/{collection}").json()["version"]
    return client.patch(
        f"/api/collections/{collection}", json={"version": version, "instruction": text}
    )


def test_a_collections_instruction_starts_empty_and_can_be_set(client):
    collection = new_collection(client)
    assert client.get(f"/api/collections/{collection}").json()["instruction"] == ""
    saved = set_instruction(client, collection, "Pastel colours.")
    assert saved.status_code == 200, saved.text
    assert saved.json()["instruction"] == "Pastel colours."
    too_long = set_instruction(client, collection, "x" * 20_001)
    assert too_long.status_code == 422
    made = new_collection(client, "Given", instruction="Ink only.")
    assert client.get(f"/api/collections/{made}").json()["instruction"] == "Ink only."


def test_new_projects_copy_the_instruction_then_keep_their_own(client):
    collection = new_collection(client)
    set_instruction(client, collection, "Pastel colours.")
    project = new_project(client, "P", collection)
    assert client.get(f"/api/projects/{project}").json()["project"]["instruction"] == (
        "Pastel colours."
    )

    edited = client.patch(f"/api/projects/{project}", json={"instruction": "Neon, at night."})
    assert edited.json()["instruction"] == "Neon, at night."
    # Other edits leave it alone, and so does changing the collection's.
    client.patch(f"/api/projects/{project}", json={"name": "Q"})
    set_instruction(client, collection, "Black and white.")
    graph = client.get(f"/api/projects/{project}").json()
    assert graph["project"]["instruction"] == "Neon, at night."
    listed = {p["id"]: p for p in list_projects(client, collection)}
    assert listed[project]["instruction"] == "Neon, at night."

    explicit = new_project(client, "R", collection, instruction="")
    assert client.get(f"/api/projects/{explicit}").json()["project"]["instruction"] == ""
    later = new_project(client, "S", collection)
    assert client.get(f"/api/projects/{later}").json()["project"]["instruction"] == (
        "Black and white."
    )


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
