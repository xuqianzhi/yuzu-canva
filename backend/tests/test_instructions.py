"""The global instruction, and each project's own copy of it."""

from __future__ import annotations


def test_global_instruction_starts_empty_and_can_be_set(client):
    assert client.get("/api/global-instruction").json() == {"instruction": ""}
    saved = client.put("/api/global-instruction", json={"instruction": "Pastel colours."})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"instruction": "Pastel colours."}
    assert client.get("/api/global-instruction").json() == {"instruction": "Pastel colours."}
    too_long = client.put("/api/global-instruction", json={"instruction": "x" * 20_001})
    assert too_long.status_code == 422


def test_new_projects_copy_the_global_instruction_then_keep_their_own(client):
    client.put("/api/global-instruction", json={"instruction": "Pastel colours."})
    project = client.post("/api/projects", json={"name": "P"}).json()
    assert project["instruction"] == "Pastel colours."

    edited = client.patch(
        f"/api/projects/{project['id']}", json={"instruction": "Neon, at night."}
    )
    assert edited.json()["instruction"] == "Neon, at night."
    # Other edits leave it alone, and so does changing the global one.
    client.patch(f"/api/projects/{project['id']}", json={"name": "Q"})
    client.put("/api/global-instruction", json={"instruction": "Black and white."})
    graph = client.get(f"/api/projects/{project['id']}").json()
    assert graph["project"]["instruction"] == "Neon, at night."
    listed = {p["id"]: p for p in client.get("/api/projects").json()}
    assert listed[project["id"]]["instruction"] == "Neon, at night."

    explicit = client.post("/api/projects", json={"name": "R", "instruction": ""}).json()
    assert explicit["instruction"] == ""
    later = client.post("/api/projects", json={"name": "S"}).json()
    assert later["instruction"] == "Black and white."
