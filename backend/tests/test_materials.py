"""Node names, uploaded materials, and uploaded nodes."""

from __future__ import annotations

import io

from PIL import Image

from .conftest import PNG, wait_for_job
from .helpers import VIDEO, jpeg, upload
from .test_api import connect, error_code, generate, new_node, new_project, restore

# --- names ---------------------------------------------------------------------


def test_names_are_optional_trimmed_and_unique(client):
    project = new_project(client)
    a = client.post(
        f"/api/projects/{project}/nodes",
        json={"kind": "image", "position": {"x": 0, "y": 0}, "name": "  Hero_shot "},
    ).json()
    assert a["name"] == "Hero_shot"
    b = new_node(client, project, name=None)
    assert b["name"] is None

    # Case and spacing don't make a name different.
    response = client.patch(f"/api/nodes/{b['id']}", json={"name": "hero_SHOT"})
    assert response.status_code == 409
    assert error_code(response) == "duplicate_name"

    assert (
        client.patch(f"/api/nodes/{b['id']}", json={"name": "Background"}).json()["name"]
        == "Background"
    )
    # Renaming to its own name is fine; blank or null clears it.
    assert client.patch(f"/api/nodes/{b['id']}", json={"name": "background"}).status_code == 200
    assert client.patch(f"/api/nodes/{b['id']}", json={"name": "   "}).json()["name"] is None
    assert client.patch(f"/api/nodes/{a['id']}", json={"name": None}).json()["name"] is None
    # Other edits leave the name alone.
    client.patch(f"/api/nodes/{b['id']}", json={"name": "Keep"})
    assert client.patch(f"/api/nodes/{b['id']}", json={"prompt": "x"}).json()["name"] == "Keep"


def test_names_are_unique_per_project_only(client):
    p1, p2 = new_project(client), new_project(client)
    for project in (p1, p2):
        response = client.post(
            f"/api/projects/{project}/nodes",
            json={"kind": "image", "position": {"x": 0, "y": 0}, "name": "Same"},
        )
        assert response.status_code == 201


def test_deleted_nodes_free_their_name_and_get_a_new_one_on_restore(client):
    project = new_project(client)
    old = client.post(
        f"/api/projects/{project}/nodes",
        json={"kind": "image", "position": {"x": 0, "y": 0}, "name": "Fox"},
    ).json()["id"]
    client.delete(f"/api/nodes/{old}")
    client.post(
        f"/api/projects/{project}/nodes",
        json={"kind": "image", "position": {"x": 0, "y": 0}, "name": "Fox"},
    )
    assert restore(client, project, nodes=[old])["nodes"][0]["name"] == "Fox_2"


# --- materials ------------------------------------------------------------------


def test_upload_list_and_delete_materials(client, data_dir):
    project = new_project(client)
    image = upload(client, project, "fox.png", PNG, "image/png")
    assert image.status_code == 201, image.text
    image = image.json()
    assert image["name"] == "fox.png"
    asset = image["asset"]
    assert (asset["kind"], asset["mime"], asset["width"], asset["height"]) == (
        "image",
        "image/png",
        2,
        3,
    )
    assert client.get(asset["url"]).content == PNG

    # The type comes from the content, not the name.
    photo = upload(client, project, "photo.png", jpeg()).json()
    assert (photo["asset"]["mime"], photo["asset"]["width"]) == ("image/jpeg", 40)
    clip = upload(client, project, "walk.mp4", VIDEO).json()
    assert (clip["asset"]["kind"], clip["asset"]["mime"]) == ("video", "video/mp4")
    assert (clip["asset"]["width"], clip["asset"]["height"], clip["asset"]["duration_s"]) == (
        320,
        180,
        3.0,
    )

    listed = client.get(f"/api/projects/{project}/materials").json()
    assert [m["name"] for m in listed] == ["walk.mp4", "photo.png", "fox.png"]

    assert client.delete(f"/api/materials/{image['id']}").status_code == 204
    assert client.get(asset["url"]).status_code == 404
    assert len(client.get(f"/api/projects/{project}/materials").json()) == 2


def test_quicktime_is_recognized(client):
    project = new_project(client)
    mov = VIDEO[:8] + b"qt  " + VIDEO[12:]
    material = upload(client, project, "clip.mov", mov).json()
    assert material["asset"]["mime"] == "video/quicktime"


def test_unsupported_uploads_are_refused(client):
    project = new_project(client)
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    for name, data in [("notes.txt", b"hello"), ("anim.gif", gif.getvalue())]:
        response = upload(client, project, name, data)
        assert response.status_code == 415
        assert error_code(response) == "unsupported_media"
    assert client.get(f"/api/projects/{project}/materials").json() == []


def test_placed_material_is_an_uploaded_node_that_feeds_others(client, fake_image):
    project = new_project(client)
    material = upload(client, project, "fox.png", PNG).json()

    node = client.post(
        f"/api/materials/{material['id']}/place", json={"position": {"x": 5, "y": 6}}
    )
    assert node.status_code == 201, node.text
    node = node.json()
    assert (node["source"], node["kind"], node["name"]) == ("upload", "image", "fox")
    assert node["position"] == {"x": 5, "y": 6}
    takes = client.get(f"/api/nodes/{node['id']}/outputs").json()
    assert [t["id"] for t in takes] == [node["selected_output_id"]]
    assert takes[0]["job_id"] is None
    # Its own copy: deleting the material leaves the node's file alone.
    assert takes[0]["asset"]["id"] != material["asset"]["id"]
    client.delete(f"/api/materials/{material['id']}")
    assert client.get(takes[0]["asset"]["url"]).content == PNG

    # Placing again gets a unique name.
    again = upload(client, project, "fox.png", PNG).json()
    second = client.post(
        f"/api/materials/{again['id']}/place", json={"position": {"x": 0, "y": 0}}
    ).json()
    assert second["name"] == "fox_2"

    # It cannot generate, change kind or settings...
    response = generate(client, node["id"])
    assert (response.status_code, error_code(response)) == (409, "not_generatable")
    assert client.patch(f"/api/nodes/{node['id']}", json={"kind": "video"}).status_code == 422
    # ...but it works as another node's input straight away.
    target = new_node(client, project, prompt="restyle image 1")["id"]
    connect(client, project, node["id"], target)
    job = wait_for_job(client, generate(client, target).json()["id"])
    assert job["operation"] == "image_edit" and job["status"] == "succeeded"
    assert fake_image.requests[-1].files[0].read() == PNG


def test_ids_have_no_spaces_or_punctuation(client):
    project = new_project(client)
    node = new_node(client, project, name=None)
    for bad in ["two words", "a.b", "@x", "x/y"]:
        response = client.patch(f"/api/nodes/{node['id']}", json={"name": bad})
        assert response.status_code == 422, bad
    for good in ["兔子老板", "fox-2", "Fox_3", "ネコ"]:
        assert client.patch(f"/api/nodes/{node['id']}", json={"name": good}).status_code == 200
