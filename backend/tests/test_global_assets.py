"""Global assets, and new projects starting with them as nodes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from canvas_api.contract import GLOBAL_NODE_STEP, GLOBAL_NODE_X, GLOBAL_NODE_Y

from .conftest import PNG
from .test_api import error_code, new_project
from .test_materials import VIDEO


def add_global(client: TestClient, name: str | None, data: bytes = PNG, filename="a.png"):
    form = {} if name is None else {"name": name}
    return client.post(
        "/api/global-assets", data=form, files={"file": (filename, data, "image/png")}
    )


def test_upload_needs_a_unique_name(client):
    first = add_global(client, "  Logo  ")
    assert first.status_code == 201, first.text
    assert first.json()["name"] == "Logo"
    assert first.json()["kind"] == "image"
    assert client.get(first.json()["url"]).content == PNG

    assert add_global(client, None).status_code == 422  # no name field
    blank = add_global(client, "   ")
    assert (blank.status_code, error_code(blank)) == (422, "validation_error")
    taken = add_global(client, "LOGO")
    assert (taken.status_code, error_code(taken)) == (409, "duplicate_name")
    spaced = add_global(client, "Two words")
    assert (spaced.status_code, error_code(spaced)) == (422, "validation_error")
    junk = add_global(client, "Notes", b"hello", "notes.txt")
    assert (junk.status_code, error_code(junk)) == (415, "unsupported_media")


def test_list_rename_delete(client):
    a = add_global(client, "Alpha").json()
    b = add_global(client, "Beta", VIDEO, "walk.mp4").json()
    assert b["kind"] == "video" and b["duration_s"] == 3.0
    assert [g["name"] for g in client.get("/api/global-assets").json()] == ["Alpha", "Beta"]

    renamed = client.patch(f"/api/global-assets/{a['id']}", json={"name": "Gamma"})
    assert renamed.json()["name"] == "Gamma"
    clash = client.patch(f"/api/global-assets/{a['id']}", json={"name": "beta"})
    assert (clash.status_code, error_code(clash)) == (409, "duplicate_name")

    assert client.delete(f"/api/global-assets/{b['id']}").status_code == 204
    assert client.get(b["url"]).status_code == 404
    assert [g["name"] for g in client.get("/api/global-assets").json()] == ["Gamma"]


def test_new_projects_start_with_global_assets_down_the_left(client):
    before = new_project(client, "Before")  # made while there were none
    add_global(client, "Logo")
    add_global(client, "Intro_clip", VIDEO, "intro.mp4")
    add_global(client, "Mascot")

    project = new_project(client, "After")
    graph = client.get(f"/api/projects/{project}").json()
    nodes = sorted(graph["nodes"], key=lambda n: n["position"]["y"])
    assert [(n["name"], n["kind"], n["source"]) for n in nodes] == [
        ("Logo", "image", "upload"),
        ("Intro_clip", "video", "upload"),
        ("Mascot", "image", "upload"),
    ]
    assert [n["position"] for n in nodes] == [
        {"x": GLOBAL_NODE_X, "y": GLOBAL_NODE_Y + i * GLOBAL_NODE_STEP} for i in range(3)
    ]
    # Each node's take is its own copy of the file, ready to use as an input.
    outputs = {o["id"]: o for o in graph["outputs"]}
    for node in nodes:
        take = outputs[node["selected_output_id"]]
        assert take["asset"]["url"].startswith("/api/assets/")
    assert client.get(outputs[nodes[0]["selected_output_id"]]["asset"]["url"]).content == PNG

    # Projects made earlier are not changed.
    assert client.get(f"/api/projects/{before}").json()["nodes"] == []

    # Deleting or renaming a global asset leaves existing projects alone.
    for g in client.get("/api/global-assets").json():
        client.delete(f"/api/global-assets/{g['id']}")
    graph = client.get(f"/api/projects/{project}").json()
    assert len(graph["nodes"]) == 3
    assert (
        client.get(outputs[nodes[0]["selected_output_id"]]["asset"]["url"]).status_code == 200
    )
    # And new projects start empty again.
    assert client.get(f"/api/projects/{new_project(client)}").json()["nodes"] == []
