"""Moving many nodes at once (the canvas's Clean up): one request, one
transaction."""

from __future__ import annotations

from .test_api import error_code, new_node, new_project


def positions(client, project: str) -> dict[str, dict]:
    graph = client.get(f"/api/projects/{project}").json()
    return {n["id"]: n["position"] for n in graph["nodes"]}


def test_nodes_move_together(client):
    project = new_project(client)
    a, b = new_node(client, project)["id"], new_node(client, project)["id"]
    moved = client.patch(
        f"/api/projects/{project}/positions",
        json={
            "moves": [
                {"node_id": a, "position": {"x": 560, "y": 0}},
                {"node_id": b, "position": {"x": 0, "y": 600}},
            ]
        },
    )
    assert moved.status_code == 200, moved.text
    assert [n["id"] for n in moved.json()] == [a, b]
    assert positions(client, project)[a] == {"x": 560, "y": 0}
    assert positions(client, project)[b] == {"x": 0, "y": 600}


def test_all_or_nothing(client):
    project, other = new_project(client), new_project(client, "Other")
    mine, theirs = new_node(client, project)["id"], new_node(client, other)["id"]
    before = positions(client, project)[mine]
    refused = client.patch(
        f"/api/projects/{project}/positions",
        json={
            "moves": [
                {"node_id": mine, "position": {"x": 999, "y": 999}},
                {"node_id": theirs, "position": {"x": 0, "y": 0}},
            ]
        },
    )
    assert (refused.status_code, error_code(refused)) == (404, "not_found")
    assert positions(client, project)[mine] == before
    empty = client.patch(f"/api/projects/{project}/positions", json={"moves": []})
    assert empty.status_code == 422
