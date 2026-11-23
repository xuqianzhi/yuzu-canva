"""Signing in, keeping users' things apart, media links, and spending limits."""

from __future__ import annotations

from dataclasses import replace

import pytest

from canvas_api.app import create_app
from canvas_api.config import Limits
from canvas_api.contract import Operation

from .conftest import ALICE, BOB, PNG, auth, open_store, signed_in, wait_for_job
from .test_api import default_collection, error_code, generate, new_node, new_project


def test_every_route_but_health_needs_a_sign_in(client):
    assert client.get("/api/health", headers={"Authorization": ""}).status_code == 200
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer nonsense"}):
        response = client.get("/api/collections", headers=headers)
        assert (response.status_code, error_code(response)) == (401, "unauthenticated")


def test_me(client):
    me = client.get("/api/me").json()
    assert me["email"] == ALICE
    assert me["used_today"] == {"text": 0, "image": 0, "video": 0}
    assert me["daily_limits"] == {"text": 200, "image": 50, "video": 10}


def test_only_allowlisted_emails_get_in(settings, fake_image):
    allowlisted = replace(settings, allowed_emails=frozenset({ALICE}))
    with signed_in(create_app(allowlisted, {Operation.image_generate: fake_image})) as client:
        assert client.get("/api/me").status_code == 200
        response = client.get("/api/me", headers=auth(BOB))
        assert (response.status_code, error_code(response)) == (403, "forbidden")


def test_people_only_see_and_touch_collections_theyre_in(client):
    collection = default_collection(client)
    project = new_project(client, collection=collection)
    node = new_node(client, project)["id"]
    job = generate(client, node).json()["id"]
    wait_for_job(client, job)
    [workflow] = client.get(f"/api/collections/{collection}/workflows").json()

    bob = auth(BOB)
    assert client.get("/api/collections", headers=bob).json() == []
    # Anything of Alice's is "not found" for Bob, whatever he tries.
    for method, path in [
        ("GET", f"/api/collections/{collection}"),
        ("PATCH", f"/api/collections/{collection}"),
        ("DELETE", f"/api/collections/{collection}"),
        ("GET", f"/api/collections/{collection}/projects"),
        ("POST", f"/api/collections/{collection}/projects"),
        ("GET", f"/api/collections/{collection}/members"),
        ("POST", f"/api/collections/{collection}/invites"),
        ("GET", f"/api/collections/{collection}/assets"),
        ("GET", f"/api/projects/{project}"),
        ("PATCH", f"/api/projects/{project}"),
        ("DELETE", f"/api/projects/{project}"),
        ("POST", f"/api/projects/{project}/lock"),
        ("PATCH", f"/api/nodes/{node}"),
        ("POST", f"/api/nodes/{node}/generate"),
        ("GET", f"/api/nodes/{node}/outputs"),
        ("GET", f"/api/jobs/{job}"),
        ("POST", f"/api/jobs/{job}/cancel"),
        ("PUT", f"/api/workflows/{workflow['id']}"),
        ("POST", f"/api/workflows/{workflow['id']}/activate"),
    ]:
        body = {"name": "x", "version": 1} if method in ("PATCH", "PUT", "POST") else None
        response = client.request(method, path, headers=bob, json=body)
        assert (response.status_code, error_code(response)) == (404, "not_found"), path
    assert client.get(f"/api/projects/{project}").status_code == 200


def test_media_links_are_signed(client):
    project = new_project(client)
    node = new_node(client, project)["id"]
    output = wait_for_job(client, generate(client, node).json()["id"])["output_id"]
    [take] = client.get(f"/api/nodes/{node}/outputs").json()
    assert take["id"] == output
    url = take["asset"]["url"]
    assert "?e=" in url and "&s=" in url
    # No sign-in header needed (an <img> can't send one) ...
    response = client.get(url, headers={"Authorization": ""})
    assert (response.status_code, response.content) == (200, PNG)
    # ... but the signature must match.
    assert client.get(url[:-2] + "xx", headers={"Authorization": ""}).status_code == 404
    assert client.get(url.split("?")[0], headers={"Authorization": ""}).status_code == 422


@pytest.fixture
def limited(settings, fake_image, fake_text):
    tight = replace(
        settings,
        limits=Limits(images_per_day=2, text_per_day=1, active_jobs=0, text_per_minute=0),
    )
    app = create_app(tight, {Operation.image_generate: fake_image}, fake_text)
    with signed_in(app) as client:
        yield client


def test_daily_limits(limited):
    project = new_project(limited)
    nodes = [new_node(limited, project)["id"] for _ in range(3)]
    for node in nodes[:2]:
        assert generate(limited, node).status_code == 202
    over = generate(limited, nodes[2])
    assert (over.status_code, error_code(over)) == (429, "quota_exceeded")
    assert "2 of 2 images" in over.json()["error"]["message"]
    assert limited.get("/api/me").json()["used_today"]["image"] == 2
    # A run that would make more images than are left is refused whole.
    run = limited.post(
        f"/api/projects/{project}/workflow/steps/characters/run",
        json={"prompt": "a fox", "count": 1},
    )
    assert (run.status_code, error_code(run)) == (429, "quota_exceeded")


def test_text_calls_are_rate_limited(settings, fake_image, fake_text):
    tight = replace(settings, limits=Limits(text_per_minute=1))
    app = create_app(tight, {Operation.image_generate: fake_image}, fake_text)
    with signed_in(app) as client:
        project = new_project(client)
        url = f"/api/projects/{project}/workflow/steps/dishes/run"
        assert client.post(url, json={"prompt": "soups", "count": 1}).status_code == 202
        again = client.post(url, json={"prompt": "soups", "count": 1})
        assert (again.status_code, error_code(again)) == (429, "quota_exceeded")


def test_generation_can_be_turned_off(settings, fake_image):
    off = replace(settings, generation_off=True)
    with signed_in(create_app(off, {Operation.image_generate: fake_image})) as client:
        project = new_project(client)
        node = new_node(client, project)["id"]
        response = generate(client, node)
        assert (response.status_code, error_code(response)) == (503, "generation_off")


def test_a_run_cut_off_by_a_restart_is_failed(settings, fake_image):
    with signed_in(create_app(settings, {Operation.image_generate: fake_image})) as client:
        project = new_project(client)
    store = open_store(settings)
    store.start_run(project, "dishes", "soups", 2)
    store.close()
    with signed_in(create_app(settings, {Operation.image_generate: fake_image})) as client:
        [run] = client.get(f"/api/projects/{project}").json()["runs"]
        assert run["status"] == "failed" and "restart" in run["error"]
