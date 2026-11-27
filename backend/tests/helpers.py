"""Helpers the test modules share: running workflow steps, uploading
materials, completing steps by hand."""

from __future__ import annotations

import io
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from .test_api import new_collection, new_project

VIDEO = (
    Path(__file__).resolve().parents[1] / "src/canvas_api/providers/fake_assets/landscape.mp4"
).read_bytes()


def upload(
    client: TestClient, project: str, name: str, data: bytes, mime="application/octet-stream"
):
    return client.post(f"/api/projects/{project}/materials", files={"file": (name, data, mime)})


def jpeg(size=(40, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, "JPEG")
    return out.getvalue()


class Finished:
    """A finished run, shaped like a response: 200 with the graph, or 502
    with the run's error."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code, self._body = status_code, body
        self.text = str(body)

    def json(self) -> dict:
        return self._body


def run_step(
    client: TestClient,
    project: str,
    step: str,
    prompt: str,
    count: int | None,
    generate: bool = True,
):
    """Start a run and wait for it (it finishes in the background). An image
    or video step's run only fills in its nodes: with `generate`, they're
    then generated (generateStep)."""
    response = client.post(
        f"/api/projects/{project}/workflow/steps/{step}/run",
        json={"prompt": prompt, "count": count},
    )
    if response.status_code != 202:
        return response
    started = next(r for r in response.json()["runs"] if r["step"] == step)
    assert started["status"] in ("running", "done", "failed")  # may already be over
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        graph = graph_of(client, project)
        run = next(r for r in graph["runs"] if r["step"] == step)
        if run["status"] == "done":
            media = [n for n in step_nodes(graph, step) if n["kind"] != "text"]
            if generate and media:
                url = f"/api/projects/{project}/workflow/steps/{step}/generate"
                response = client.post(url)
                assert response.status_code == 200, response.text
                graph = response.json()
            return Finished(200, graph)
        if run["status"] == "failed":
            return Finished(502, {"error": {"code": "provider_error", "message": run["error"]}})
        time.sleep(0.02)
    raise AssertionError(f"step {step} still running")


def step_nodes(graph: dict, step: str) -> list[dict]:
    nodes = [n for n in graph["nodes"] if n["workflow_step"] == step]
    return sorted(nodes, key=lambda n: n["workflow_item"])


def graph_of(client: TestClient, project: str) -> dict:
    return client.get(f"/api/projects/{project}").json()


def wait_for_outputs(client: TestClient, project: str, step: str) -> None:
    """Until every node of the step has an output."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        nodes = step_nodes(graph_of(client, project), step)
        if nodes and all(n["selected_output_id"] for n in nodes):
            return
        time.sleep(0.02)
    raise AssertionError(f"{step} nodes still have no output")


def pipeline_template(client, first: str = "text", second: str = "image") -> str:
    definition = {
        "id": "x",
        "name": "Pipeline",
        "steps": [
            {"key": "prompts", "name": "Prompts", "kind": first, "carry": "all"},
            {"key": "scenes", "name": "Scenes", "kind": second},
        ],
    }
    collection = new_collection(client, "Pipeline", workflow=definition)
    return new_project(client, "P", collection)


def complete(client: TestClient, project: str, step: str, *entries: dict):
    return client.post(
        f"/api/projects/{project}/workflow/steps/{step}/complete",
        json={"entries": list(entries)},
    )


def material(client: TestClient, project: str, name: str, data: bytes) -> str:
    response = upload(client, project, name, data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def run_of(graph: dict, step: str) -> dict:
    return next(r for r in graph["runs"] if r["step"] == step)
