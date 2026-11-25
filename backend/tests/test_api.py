"""HTTP behaviour: CRUD, references, generation, jobs, assets, errors."""

from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from canvas_api.app import create_app
from canvas_api.contract import ErrorResponse, MediaKind, Operation
from canvas_api.providers.base import GenerationRequest, GenerationResult

from .conftest import PNG, open_store, signed_in, wait_for_job, wait_for_status

OPENAPI_JSON = Path(__file__).resolve().parents[2] / "contract" / "openapi.json"


def error_code(response) -> str:
    return ErrorResponse.model_validate(response.json()).error.code


def new_collection(client: TestClient, name: str = "Tests", **body) -> str:
    response = client.post("/api/collections", json={"name": name, **body})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def patch_collection(client: TestClient, collection: str, **fields):
    """Change a collection's settings, with the version it has now."""
    version = client.get(f"/api/collections/{collection}").json()["version"]
    return client.patch(f"/api/collections/{collection}", json={"version": version, **fields})


def default_collection(client: TestClient) -> str:
    """The signed-in user's first own collection (made if there's none)."""
    mine = [c for c in client.get("/api/collections").json() if c["your_role"] == "owner"]
    return mine[-1]["id"] if mine else new_collection(client)


def new_project(
    client: TestClient, name: str = "Demo", collection: str | None = None, **body
) -> str:
    collection = collection or default_collection(client)
    response = client.post(
        f"/api/collections/{collection}/projects", json={"name": name, **body}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def list_projects(client: TestClient, collection: str | None = None) -> list[dict]:
    collection = collection or default_collection(client)
    return client.get(f"/api/collections/{collection}/projects").json()


_ids = itertools.count(1)


def new_node(
    client: TestClient,
    project_id: str,
    kind: str = "image",
    prompt: str = "a fox",
    name: str | None = "auto",
):
    """A node with a fresh unique ID (n1, n2...) unless `name` says otherwise:
    nothing can link out of a node without an ID."""
    if name == "auto":
        name = f"n{next(_ids)}"
    response = client.post(
        f"/api/projects/{project_id}/nodes",
        json={"kind": kind, "position": {"x": 10, "y": 20}, "prompt": prompt, "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def connect(client: TestClient, project_id: str, source: str, target: str):
    return client.post(
        f"/api/projects/{project_id}/edges",
        json={"source_node_id": source, "target_node_id": target},
    )


def generate(client: TestClient, node_id: str):
    return client.post(f"/api/nodes/{node_id}/generate")


# --- basics ----------------------------------------------------------------------


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_unknown_route_is_not_found(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert error_code(response) == "not_found"


def test_malformed_id_is_a_validation_error(client):
    response = client.get("/api/projects/not-a-project-id")
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_committed_openapi_matches_code():
    """contract/openapi.json is generated; run `make contract` after changing models."""
    if not OPENAPI_JSON.exists():
        pytest.skip("contract/openapi.json is not mounted here")
    committed = json.loads(OPENAPI_JSON.read_text())
    assert committed == create_app().openapi(), "contract is stale: run `make contract`"


# --- projects ----------------------------------------------------------------------


def test_project_list_summaries(client):
    empty = new_project(client, "Empty")
    busy = new_project(client, "Busy")
    still = new_node(client, busy)["id"]
    new_node(client, busy, kind="video")
    wait_for_job(client, generate(client, still).json()["id"])
    take = wait_for_job(client, generate(client, still).json()["id"])["output_id"]

    listed = {p["id"]: p for p in list_projects(client)}
    assert (listed[empty]["node_count"], listed[empty]["cover"]) == (0, None)
    summary = listed[busy]
    assert (summary["node_count"], summary["image_count"], summary["video_count"]) == (2, 2, 0)
    assert summary["running_count"] == 0
    newest = client.get(f"/api/nodes/{still}/outputs").json()[0]
    assert newest["id"] == take
    assert summary["cover"]["id"] == newest["asset"]["id"]


def test_project_lifecycle(client):
    first = new_project(client, "First")
    second = new_project(client, "Second")
    assert [p["id"] for p in list_projects(client)] == [second, first]

    response = client.patch(
        f"/api/projects/{first}",
        json={"name": "Renamed", "viewport": {"x": 5, "y": 6, "zoom": 2}},
    )
    assert response.json()["name"] == "Renamed"
    assert response.json()["viewport"] == {"x": 5, "y": 6, "zoom": 2}
    # Updating bumps it to the top.
    assert list_projects(client)[0]["id"] == first

    graph = client.get(f"/api/projects/{first}").json()
    assert graph["project"]["name"] == "Renamed"
    assert graph["nodes"] == graph["edges"] == graph["outputs"] == graph["active_jobs"] == []

    assert client.delete(f"/api/projects/{first}").status_code == 204
    response = client.get(f"/api/projects/{first}")
    assert response.status_code == 404
    assert error_code(response) == "not_found"


# --- nodes -------------------------------------------------------------------------


def test_node_create_and_update(client):
    project = new_project(client)
    node = new_node(client, project, kind="video")
    assert node["params"]["kind"] == "video"
    assert node["params"]["duration_s"] == 4
    assert node["selected_output_id"] is None

    updated = client.patch(
        f"/api/nodes/{node['id']}",
        json={
            "prompt": "new",
            "position": {"x": 1, "y": 2},
            "size": {"width": 300, "height": 200},
        },
    ).json()
    assert updated["prompt"] == "new"
    assert updated["position"] == {"x": 1, "y": 2}
    assert updated["size"] == {"width": 300, "height": 200}

    # Changing kind without params resets params to the new kind's defaults.
    switched = client.patch(f"/api/nodes/{node['id']}", json={"kind": "image"}).json()
    assert switched["params"] == {"kind": "image", "size": "auto", "quality": "auto"}
    assert switched["size"] == {"width": 300, "height": 200}

    # Explicit null clears the size back to auto.
    cleared = client.patch(f"/api/nodes/{node['id']}", json={"size": None}).json()
    assert cleared["size"] is None


def test_node_params_must_match_kind_on_update(client):
    project = new_project(client)
    node = new_node(client, project, kind="image")
    response = client.patch(f"/api/nodes/{node['id']}", json={"params": {"kind": "video"}})
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_selected_output_must_belong_to_node(client):
    project = new_project(client)
    a, b = new_node(client, project), new_node(client, project)
    take = wait_for_job(client, generate(client, a["id"]).json()["id"])["output_id"]
    response = client.patch(f"/api/nodes/{b['id']}", json={"selected_output_id": take})
    assert response.status_code == 422


def test_create_node_in_missing_project(client):
    response = client.post(
        "/api/projects/prj_missing/nodes", json={"kind": "image", "position": {"x": 0, "y": 0}}
    )
    assert response.status_code == 404


# --- edges ---------------------------------------------------------------------------


def test_edge_rules(client):
    project = new_project(client)
    a, b, c = (new_node(client, project)["id"] for _ in range(3))

    assert connect(client, project, a, b).status_code == 201
    assert connect(client, project, b, c).status_code == 201

    for source, target, code in [
        (a, a, "self_reference"),
        (a, b, "duplicate_edge"),
        (c, a, "cycle"),
        (b, a, "cycle"),
    ]:
        response = connect(client, project, source, target)
        assert response.status_code == 409, (source, target)
        assert error_code(response) == code

    # Diamond shapes are fine: a -> c as well as a -> b -> c.
    assert connect(client, project, a, c).status_code == 201


def test_edge_nodes_must_be_in_the_project(client):
    p1, p2 = new_project(client), new_project(client)
    a, b = new_node(client, p1)["id"], new_node(client, p2)["id"]
    response = connect(client, p1, a, b)
    assert response.status_code == 404


def test_deleting_a_node_removes_its_edges(client):
    project = new_project(client)
    a, b = new_node(client, project)["id"], new_node(client, project)["id"]
    edge = connect(client, project, a, b).json()
    assert client.delete(f"/api/nodes/{a}").status_code == 204
    graph = client.get(f"/api/projects/{project}").json()
    assert [n["id"] for n in graph["nodes"]] == [b]
    assert graph["edges"] == []
    assert client.delete(f"/api/edges/{edge['id']}").status_code == 404


# --- generation --------------------------------------------------------------------


def test_generate_image_end_to_end(client, fake_image):
    project = new_project(client)
    node = new_node(client, project, prompt="  a red fox  ")

    response = generate(client, node["id"])
    assert response.status_code == 202
    job = response.json()
    assert job["status"] in ("queued", "running", "succeeded")
    assert job["provider"] == "openai"
    assert job["operation"] == "image_generate"
    assert job["input"]["prompt"] == "a red fox"

    job = wait_for_job(client, job["id"])
    assert job["status"] == "succeeded", job
    assert job["progress"] == 1
    assert job["finished_at"] is not None
    assert fake_image.requests[0].prompt == "a red fox"

    node = client.get(f"/api/projects/{project}").json()["nodes"][0]
    assert node["selected_output_id"] == job["output_id"]

    outputs = client.get(f"/api/nodes/{node['id']}/outputs").json()
    assert [o["id"] for o in outputs] == [job["output_id"]]
    asset = outputs[0]["asset"]
    assert (asset["mime"], asset["width"], asset["height"]) == ("image/png", 2, 3)

    content = client.get(asset["url"])
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.content == PNG


def test_each_generate_adds_a_take_and_selects_it(client):
    project = new_project(client)
    node = new_node(client, project)["id"]
    first = wait_for_job(client, generate(client, node).json()["id"])["output_id"]
    second = wait_for_job(client, generate(client, node).json()["id"])["output_id"]

    outputs = client.get(f"/api/nodes/{node}/outputs").json()
    assert [o["id"] for o in outputs] == [second, first]  # newest first
    assert (
        client.get(f"/api/projects/{project}").json()["nodes"][0]["selected_output_id"]
        == second
    )

    # Pick the older take again.
    picked = client.patch(f"/api/nodes/{node}", json={"selected_output_id": first}).json()
    assert picked["selected_output_id"] == first


def test_asset_supports_range_requests(client):
    project = new_project(client)
    node = new_node(client, project)["id"]
    wait_for_job(client, generate(client, node).json()["id"])
    url = client.get(f"/api/nodes/{node}/outputs").json()[0]["asset"]["url"]
    response = client.get(url, headers={"Range": "bytes=0-7"})
    assert response.status_code == 206
    assert response.content == PNG[:8]


def test_generate_empty_prompt(client):
    project = new_project(client)
    node = new_node(client, project, prompt="   ")["id"]
    response = generate(client, node)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_generate_text(client, fake_text):
    project = new_project(client)
    node = new_node(client, project, kind="text", prompt="a haiku about snow")["id"]
    response = generate(client, node)
    assert response.status_code == 202, response.text
    job = wait_for_job(client, response.json()["id"])
    assert job["status"] == "succeeded", job
    outputs = client.get(f"/api/nodes/{node}/outputs").json()
    assert outputs[0]["text"] == "[fake text] a haiku about snow"
    assert fake_text.calls[-1]["spec"] is None


def test_generate_video_with_image_and_video_references(client, fake_video):
    project = new_project(client)
    still = new_node(client, project, prompt="a fox")["id"]
    clip = new_node(client, project, kind="video", prompt="a fox walking")["id"]
    final = new_node(client, project, kind="video", prompt="combine")["id"]
    connect(client, project, still, final)
    connect(client, project, clip, final)
    wait_for_job(client, generate(client, still).json()["id"])

    clip_job = wait_for_job(client, generate(client, clip).json()["id"])
    assert clip_job["status"] == "succeeded"
    assert clip_job["provider"] == "seedance"
    assert clip_job["provider_task_id"] == "cgt-1"
    asset = client.get(f"/api/nodes/{clip}/outputs").json()[0]["asset"]
    assert (asset["kind"], asset["mime"], asset["duration_s"]) == ("video", "video/mp4", 4)
    assert client.get(asset["url"]).content == b"MP4"

    job = wait_for_job(client, generate(client, final).json()["id"])
    assert job["operation"] == "video_generate"
    assert [r["kind"] for r in job["input"]["refs"]] == ["image", "video"]
    assert [f.kind for f in fake_video.requests[-1].files] == ["image", "video"]


def test_video_cannot_feed_an_image_node(client):
    project = new_project(client)
    clip = new_node(client, project, kind="video")["id"]
    still = new_node(client, project)["id"]
    connect(client, project, clip, still)
    wait_for_job(client, generate(client, clip).json()["id"])
    response = generate(client, still)
    assert response.status_code == 409
    assert error_code(response) == "unsupported_ref"


def test_generate_requires_referenced_outputs(client):
    project = new_project(client)
    a, b = new_node(client, project)["id"], new_node(client, project)["id"]
    connect(client, project, a, b)
    response = generate(client, b)
    assert response.status_code == 409
    assert error_code(response) == "missing_ref_output"
    assert response.json()["error"]["context"] == {"node_id": a}


def test_generate_with_image_references(client, fake_image, data_dir):
    project = new_project(client)
    fox = new_node(client, project, prompt="a fox", name="fox")["id"]
    snow = new_node(client, project, prompt="a snowy field", name="snow")["id"]
    # Mentions make the links; they are listed snow first, but the prompt
    # mentions the fox first, and that is the order the inputs go in.
    scene = new_node(client, project, prompt="behind SNOW: fox in snow")["id"]
    edges = client.get(f"/api/projects/{project}").json()["edges"]
    assert sorted((e["source_node_id"], e["target_node_id"]) for e in edges) == sorted(
        [(fox, scene), (snow, scene)]
    )
    fox_take = wait_for_job(client, generate(client, fox).json()["id"])["output_id"]
    snow_take = wait_for_job(client, generate(client, snow).json()["id"])["output_id"]

    job = generate(client, scene).json()
    assert job["operation"] == "image_edit"
    # References resolve to each source's selected take, in mention order.
    assert [(r["node_id"], r["output_id"], r["kind"]) for r in job["input"]["refs"]] == [
        (snow, snow_take, "image"),
        (fox, fox_take, "image"),
    ]
    # "@ID" mentions become tokens in the job; the provider labels them.
    assert job["input"]["prompt"] == f"behind @{{{snow}}}: @{{{fox}}} in @{{{snow}}}"
    # (@{...} are internal tokens; the provider turns them into "image 1"...)

    assert wait_for_job(client, job["id"])["status"] == "succeeded"
    request = fake_image.requests[-1]
    assert [f.node_id for f in request.files] == [snow, fox]
    assert all(f.name.startswith("ast_") and f.read() == PNG for f in request.files)


def test_reference_uses_the_selected_take(client, fake_image):
    project = new_project(client)
    source = new_node(client, project)["id"]
    target = new_node(client, project, prompt="variation")["id"]
    connect(client, project, source, target)
    first = wait_for_job(client, generate(client, source).json()["id"])["output_id"]
    wait_for_job(client, generate(client, source).json()["id"])
    client.patch(f"/api/nodes/{source}", json={"selected_output_id": first})

    job = generate(client, target).json()
    assert job["input"]["refs"][0]["output_id"] == first


def test_generate_after_reference_removed(client):
    project = new_project(client)
    a, b = new_node(client, project)["id"], new_node(client, project)["id"]
    edge = connect(client, project, a, b).json()["id"]
    wait_for_job(client, generate(client, a).json()["id"])
    client.delete(f"/api/edges/{edge}")
    assert generate(client, b).json()["operation"] == "image_generate"


def test_unknown_mentions_are_just_text(client):
    project = new_project(client)
    node = new_node(client, project, prompt="a fox, like nobody and @{nod_x}")["id"]
    job = generate(client, node).json()
    assert job["operation"] == "image_generate"
    assert job["input"]["prompt"] == "a fox, like nobody and @{nod_x}"


def test_generate_missing_node(client):
    assert generate(client, "nod_missing").status_code == 404


def test_provider_failure_marks_job_failed(client, fake_image):
    fake_image.fail_with = "OpenAI 400: prompt rejected"
    project = new_project(client)
    node = new_node(client, project)["id"]
    job = wait_for_job(client, generate(client, node).json()["id"])
    assert job["status"] == "failed"
    assert job["error"] == "OpenAI 400: prompt rejected"
    assert job["output_id"] is None
    assert client.get(f"/api/nodes/{node}/outputs").json() == []


# --- jobs: one at a time, cancel -------------------------------------------------------


def test_one_job_per_node_and_cancel(client, fake_image):
    fake_image.gate.clear()
    project = new_project(client)
    node = new_node(client, project)["id"]
    job = generate(client, node).json()
    wait_for_status(client, job["id"], "running")

    busy = generate(client, node)
    assert busy.status_code == 409
    assert error_code(busy) == "job_in_progress"

    graph = client.get(f"/api/projects/{project}").json()
    assert [j["id"] for j in graph["active_jobs"]] == [job["id"]]

    canceled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"

    fake_image.gate.set()
    again = client.post(f"/api/jobs/{job['id']}/cancel")
    assert again.status_code == 409
    assert error_code(again) == "job_finished"

    assert client.get(f"/api/nodes/{node}/outputs").json() == []
    # The node is free again.
    assert wait_for_job(client, generate(client, node).json()["id"])["status"] == "succeeded"


def test_deleting_node_with_running_job(client, fake_image):
    fake_image.gate.clear()
    project = new_project(client)
    node = new_node(client, project)["id"]
    job = generate(client, node).json()
    wait_for_status(client, job["id"], "running")
    assert client.delete(f"/api/nodes/{node}").status_code == 204
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert (job["status"], job["error"]) == ("canceled", "the node was deleted")
    fake_image.gate.set()


def test_deleting_project_removes_asset_files(client, data_dir):
    project = new_project(client)
    node = new_node(client, project)["id"]
    wait_for_job(client, generate(client, node).json()["id"])
    assert list((data_dir / "assets").iterdir())
    client.delete(f"/api/projects/{project}")
    assert list((data_dir / "assets").iterdir()) == []


def test_restart_requeues_queued_and_fails_running(settings, fake_image):
    """Jobs survive a restart: queued ones run, running ones are marked failed."""
    from canvas_api.contract import JobStatus

    generators = {Operation.image_generate: fake_image}

    fake_image.gate.clear()
    with signed_in(create_app(settings, generators)) as client:
        project = new_project(client)
        running_node = new_node(client, project)["id"]
        queued_node = new_node(client, project)["id"]
        running = generate(client, running_node).json()["id"]
        wait_for_status(client, running, "running")
    # Simulate a job that was queued when the process died.
    store = open_store(settings)
    queued = store.create_job(
        store.get_node(queued_node),
        provider=store.get_job(running).provider,
        operation=Operation.image_generate,
        job_input=store.get_job(running).input,
    ).id
    store.close()

    fake_image.gate.set()
    with signed_in(create_app(settings, generators)) as client:
        assert client.get(f"/api/jobs/{running}").json()["status"] == "failed"
        assert "restart" in client.get(f"/api/jobs/{running}").json()["error"]
        assert wait_for_job(client, queued)["status"] == JobStatus.succeeded


def test_restart_resumes_a_submitted_video_job(settings, fake_image, fake_video):
    """A video job that reached Seedance is resumed, not resubmitted."""
    generators = {Operation.image_generate: fake_image, Operation.video_generate: fake_video}

    fake_video.gate.clear()
    with signed_in(create_app(settings, generators)) as client:
        project = new_project(client)
        node = new_node(client, project, kind="video")["id"]
        job = generate(client, node).json()["id"]
        wait_for_status(client, job, "running")
        assert client.get(f"/api/jobs/{job}").json()["provider_task_id"] == "cgt-1"

    fake_video.gate.set()
    with signed_in(create_app(settings, generators)) as client:
        finished = wait_for_job(client, job)
        assert finished["status"] == "succeeded"
        assert fake_video.requests[-1].resume_task_id == "cgt-1"
        assert finished["started_at"] is not None


class SendingVideo:
    """A video provider stopped mid-send: it saves its seed, then hangs
    before Ark answers (no task id yet)."""

    resumable = True

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []
        self.gate = threading.Event()

    async def run(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if request.resume_seed is None and request.on_sending:
            request.on_sending(1234, 1_700_000_000.0)
            while not self.gate.is_set():
                await asyncio.sleep(0.01)
        return GenerationResult(
            kind=MediaKind.video, data=b"MP4", mime="video/mp4", ext="mp4", duration_s=4
        )


def test_restart_mid_send_looks_the_task_up_by_seed(settings, fake_image):
    """A video job stopped while its create request was going out is resumed
    with the seed saved before sending, not failed (and not resent)."""
    video = SendingVideo()
    generators = {Operation.image_generate: fake_image, Operation.video_generate: video}
    with signed_in(create_app(settings, generators)) as client:
        project = new_project(client)
        node = new_node(client, project, kind="video")["id"]
        job = generate(client, node).json()["id"]
        wait_for_status(client, job, "running")
        deadline = time.monotonic() + 5
        while client.get(f"/api/jobs/{job}").json()["provider_seed"] != 1234:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert client.get(f"/api/jobs/{job}").json()["provider_task_id"] is None

    video.gate.set()
    with signed_in(create_app(settings, generators)) as client:
        assert wait_for_job(client, job)["status"] == "succeeded"
        resumed = video.requests[-1]
        assert (resumed.resume_seed, resumed.resume_since) == (1234, 1_700_000_000.0)
        assert resumed.resume_task_id is None


# --- soft delete and restore (undo) ------------------------------------------------


def restore(client: TestClient, project: str, nodes=(), edges=()):
    response = client.post(
        f"/api/projects/{project}/restore",
        json={"node_ids": list(nodes), "edge_ids": list(edges)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_delete_then_restore_brings_back_takes_and_connections(client, data_dir):
    project = new_project(client)
    a, b, c = (new_node(client, project)["id"] for _ in range(3))
    ab = connect(client, project, a, b).json()["id"]
    bc = connect(client, project, b, c).json()["id"]
    wait_for_job(client, generate(client, a).json()["id"])
    take = wait_for_job(client, generate(client, b).json()["id"])["output_id"]

    assert client.delete(f"/api/nodes/{b}").status_code == 204
    graph = client.get(f"/api/projects/{project}").json()
    assert sorted(n["id"] for n in graph["nodes"]) == sorted([a, c])
    assert graph["edges"] == []
    assert [o["node_id"] for o in graph["outputs"]] == [a]  # none of b's takes
    assert client.get(f"/api/nodes/{b}/outputs").status_code == 404
    assert client.patch(f"/api/nodes/{b}", json={"prompt": "x"}).status_code == 404
    # Files stay on disk until purged, so the take can come back.
    assert len(list((data_dir / "assets").iterdir())) == 2

    result = restore(client, project, nodes=[b], edges=[ab, bc])
    assert [n["id"] for n in result["nodes"]] == [b]
    assert result["nodes"][0]["selected_output_id"] == take
    assert sorted(e["id"] for e in result["edges"]) == sorted([ab, bc])
    assert [o["id"] for o in result["outputs"]] == [take]
    graph = client.get(f"/api/projects/{project}").json()
    assert len(graph["nodes"]) == 3 and len(graph["edges"]) == 2


def test_delete_and_restore_a_single_edge(client):
    project = new_project(client)
    a, b = new_node(client, project)["id"], new_node(client, project)["id"]
    edge = connect(client, project, a, b).json()["id"]
    prompt = client.get(f"/api/projects/{project}").json()["nodes"][1]["prompt"]
    assert client.delete(f"/api/edges/{edge}").status_code == 204
    assert client.delete(f"/api/edges/{edge}").status_code == 404
    # A main-input link follows the prompt: restoring the edge alone can't
    # bring it back, restoring the mention does (and keeps its id).
    assert restore(client, project, edges=[edge])["edges"] == []
    client.patch(f"/api/nodes/{b}", json={"prompt": prompt})
    assert [e["id"] for e in client.get(f"/api/projects/{project}").json()["edges"]] == [edge]


def test_reconnecting_after_a_delete_supersedes_the_deleted_edge(client):
    project = new_project(client)
    a, b = new_node(client, project)["id"], new_node(client, project)["id"]
    old = connect(client, project, a, b).json()["id"]
    client.delete(f"/api/edges/{old}")
    again = connect(client, project, a, b)
    assert again.status_code == 201
    # Links are revived rather than re-created, so undo/redo keep their ids.
    assert again.json()["id"] == old


def test_restore_skips_edges_that_would_loop_or_dangle(client):
    project = new_project(client)
    a, b, c = (new_node(client, project)["id"] for _ in range(3))
    ab = connect(client, project, a, b).json()["id"]
    bc = connect(client, project, b, c).json()["id"]
    client.delete(f"/api/edges/{ab}")
    assert connect(client, project, b, a).status_code == 201  # now b -> a
    client.delete(f"/api/nodes/{c}")  # takes bc with it

    result = restore(client, project, edges=[ab, bc])
    assert result["edges"] == []  # ab would loop, bc's target is still deleted


def test_deleted_nodes_leave_the_project_summary(client):
    project = new_project(client)
    node = new_node(client, project)["id"]
    wait_for_job(client, generate(client, node).json()["id"])
    client.delete(f"/api/nodes/{node}")
    summary = next(p for p in list_projects(client) if p["id"] == project)
    assert (summary["node_count"], summary["image_count"], summary["cover"]) == (0, 0, None)


def test_purge_erases_old_deletes_and_their_files(settings, fake_image):
    from datetime import timedelta

    with signed_in(create_app(settings, {Operation.image_generate: fake_image})) as client:
        project = new_project(client)
        node = new_node(client, project)["id"]
        wait_for_job(client, generate(client, node).json()["id"])
        client.delete(f"/api/nodes/{node}")

    store = open_store(settings)
    assert store.purge_deleted(older_than=timedelta(days=1)) == []  # too recent
    files = store.purge_deleted(older_than=timedelta(0))
    store.close()
    assert len(files) == 1 and files[0].startswith("assets/ast_")

    with signed_in(create_app(settings, {Operation.image_generate: fake_image})) as client:
        assert restore(client, project, nodes=[node])["nodes"] == []
