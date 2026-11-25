"""Collection assets, and new projects starting with them as nodes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from canvas_api.contract import ASSET_NODE_STEP, ASSET_NODE_X, ASSET_NODE_Y

from .conftest import PNG
from .helpers import VIDEO
from .test_api import default_collection, error_code, new_collection, new_project


def add_asset(
    client: TestClient,
    name: str | None,
    data: bytes = PNG,
    filename="a.png",
    collection: str | None = None,
):
    form = {} if name is None else {"name": name}
    collection = collection or default_collection(client)
    return client.post(
        f"/api/collections/{collection}/assets",
        data=form,
        files={"file": (filename, data, "image/png")},
    )


def assets(client: TestClient, collection: str | None = None) -> list[dict]:
    collection = collection or default_collection(client)
    return client.get(f"/api/collections/{collection}/assets").json()


def test_upload_needs_a_unique_name(client):
    first = add_asset(client, "  Logo  ")
    assert first.status_code == 201, first.text
    assert first.json()["name"] == "Logo"
    assert first.json()["kind"] == "image"
    assert client.get(first.json()["url"]).content == PNG

    assert add_asset(client, None).status_code == 422  # no name field
    blank = add_asset(client, "   ")
    assert (blank.status_code, error_code(blank)) == (422, "validation_error")
    taken = add_asset(client, "LOGO")
    assert (taken.status_code, error_code(taken)) == (409, "duplicate_name")
    spaced = add_asset(client, "Two words")
    assert (spaced.status_code, error_code(spaced)) == (422, "validation_error")
    junk = add_asset(client, "Notes", b"hello", "notes.txt")
    assert (junk.status_code, error_code(junk)) == (415, "unsupported_media")


def test_list_rename_delete(client):
    a = add_asset(client, "Alpha").json()
    b = add_asset(client, "Beta", VIDEO, "walk.mp4").json()
    assert b["kind"] == "video" and b["duration_s"] == 3.0
    assert [g["name"] for g in assets(client)] == ["Alpha", "Beta"]

    renamed = client.patch(f"/api/collection-assets/{a['id']}", json={"name": "Gamma"})
    assert renamed.json()["name"] == "Gamma"
    clash = client.patch(f"/api/collection-assets/{a['id']}", json={"name": "beta"})
    assert (clash.status_code, error_code(clash)) == (409, "duplicate_name")

    assert client.delete(f"/api/collection-assets/{b['id']}").status_code == 204
    assert client.get(b["url"]).status_code == 404
    assert [g["name"] for g in assets(client)] == ["Gamma"]


def test_new_projects_start_with_the_collections_assets_down_the_left(client):
    before = new_project(client, "Before")  # made while there were none
    add_asset(client, "Logo")
    add_asset(client, "Intro_clip", VIDEO, "intro.mp4")
    add_asset(client, "Mascot")

    project = new_project(client, "After")
    graph = client.get(f"/api/projects/{project}").json()
    nodes = sorted(graph["nodes"], key=lambda n: n["position"]["y"])
    assert [(n["name"], n["kind"], n["source"]) for n in nodes] == [
        ("Logo", "image", "upload"),
        ("Intro_clip", "video", "upload"),
        ("Mascot", "image", "upload"),
    ]
    assert [n["position"] for n in nodes] == [
        {"x": ASSET_NODE_X, "y": ASSET_NODE_Y + i * ASSET_NODE_STEP} for i in range(3)
    ]
    # Each node's take is its own copy of the file, ready to use as an input.
    outputs = {o["id"]: o for o in graph["outputs"]}
    for node in nodes:
        take = outputs[node["selected_output_id"]]
        assert take["asset"]["url"].startswith("/api/assets/")
    assert client.get(outputs[nodes[0]["selected_output_id"]]["asset"]["url"]).content == PNG

    # Projects made earlier are not changed.
    assert client.get(f"/api/projects/{before}").json()["nodes"] == []

    # Deleting or renaming an asset leaves existing projects alone.
    for g in assets(client):
        client.delete(f"/api/collection-assets/{g['id']}")
    graph = client.get(f"/api/projects/{project}").json()
    assert len(graph["nodes"]) == 3
    assert (
        client.get(outputs[nodes[0]["selected_output_id"]]["asset"]["url"]).status_code == 200
    )
    # And new projects start empty again.
    assert client.get(f"/api/projects/{new_project(client)}").json()["nodes"] == []


def test_assets_belong_to_their_collection(client):
    anime, school = default_collection(client), new_collection(client, "School")
    add_asset(client, "Hero", collection=anime)
    assert (
        add_asset(client, "Hero", collection=school).status_code == 201
    )  # names per collection
    add_asset(client, "Board", collection=school)
    assert [a["name"] for a in assets(client, anime)] == ["Hero"]
    in_school = new_project(client, "Lesson", collection=school)
    names = [n["name"] for n in client.get(f"/api/projects/{in_school}").json()["nodes"]]
    assert sorted(names) == ["Board", "Hero"]
