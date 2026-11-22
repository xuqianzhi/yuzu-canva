"""IDs mentioned in prompts (plain text, no "@"), and links that exist
exactly when a prompt mentions them."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from canvas_api.app import create_app
from canvas_api.contract import Operation
from canvas_api.domain.mentions import find_mentions, mentioned, remove_mentions

from .conftest import make_settings
from .test_api import connect, error_code, new_node, new_project

IDS = {"fox": "nod_f", "fox_2": "nod_f2", "兔子老板": "nod_r", "Snow-Field": "nod_s"}


def test_parser_rules():
    assert mentioned("the fox and fox_2", IDS) == ["nod_f", "nod_f2"]  # longest wins
    assert mentioned("兔子老板走进办公室", IDS) == ["nod_r"]  # Chinese needs no spaces
    assert mentioned("redfox and foxes", IDS) == []  # Latin IDs are whole words
    assert mentioned("FOX, then snow-field.", IDS) == ["nod_f", "nod_s"]  # any case
    assert mentioned("@fox still counts", IDS) == ["nod_f"]
    assert mentioned("nothing here", IDS) == []
    assert [m[:2] for m in find_mentions("a fox b", IDS)] == [(2, 5)]
    assert remove_mentions("put fox in  兔子老板 now", IDS, "nod_f") == "put in 兔子老板 now"
    assert remove_mentions("a field fox, and fox again", IDS, "nod_f") == "a field, and again"


def prompt_of(client, project, node):
    nodes = client.get(f"/api/projects/{project}").json()["nodes"]
    return next(n["prompt"] for n in nodes if n["id"] == node)


def links(client, project):
    edges = client.get(f"/api/projects/{project}").json()["edges"]
    return sorted((e["source_node_id"], e["target_node_id"]) for e in edges)


def test_typing_an_id_links_and_deleting_it_unlinks(client):
    project = new_project(client)
    fox = new_node(client, project, name="fox", prompt="")["id"]
    rabbit = new_node(client, project, name="兔子老板", prompt="")["id"]
    scene = new_node(client, project, prompt="empty")["id"]

    client.patch(f"/api/nodes/{scene}", json={"prompt": "the fox meets 兔子老板在雪地里"})
    assert links(client, project) == sorted([(fox, scene), (rabbit, scene)])
    client.patch(f"/api/nodes/{scene}", json={"prompt": "兔子老板 alone, no foxes"})
    assert links(client, project) == [(rabbit, scene)]
    client.patch(f"/api/nodes/{scene}", json={"prompt": "nobody"})
    assert links(client, project) == []


def test_linking_and_unlinking_edit_the_prompt(client):
    project = new_project(client)
    fox = new_node(client, project, name="fox", prompt="")["id"]
    scene = new_node(client, project, prompt="a field")["id"]
    edge = connect(client, project, fox, scene).json()["id"]
    assert prompt_of(client, project, scene) == "a field fox"
    client.patch(f"/api/nodes/{scene}", json={"prompt": "a field fox, and fox again"})
    client.delete(f"/api/edges/{edge}")
    assert prompt_of(client, project, scene) == "a field, and again"
    assert links(client, project) == []


def test_renaming_rewrites_mentions_and_removing_the_id_unlinks(client):
    project = new_project(client)
    fox = new_node(client, project, name="fox", prompt="")["id"]
    scene = new_node(client, project, prompt="fox in snow, foxes are many")["id"]
    assert links(client, project) == [(fox, scene)]

    client.patch(f"/api/nodes/{fox}", json={"name": "Red_fox"})
    assert prompt_of(client, project, scene) == "Red_fox in snow, foxes are many"
    assert links(client, project) == [(fox, scene)]

    # No ID: nothing can link out of it; the words stay as plain text.
    client.patch(f"/api/nodes/{fox}", json={"name": None})
    assert links(client, project) == []
    assert prompt_of(client, project, scene) == "Red_fox in snow, foxes are many"
    # Giving it that ID again links the words already there.
    client.patch(f"/api/nodes/{fox}", json={"name": "red_FOX"})
    assert links(client, project) == [(fox, scene)]


def test_nodes_without_an_id_cannot_link_out(client):
    project = new_project(client)
    anon = new_node(client, project, name=None)["id"]
    target = new_node(client, project)["id"]
    response = connect(client, project, anon, target)
    assert (response.status_code, error_code(response)) == (409, "no_id")


def test_a_mention_that_would_loop_stays_unlinked(client):
    project = new_project(client)
    a = new_node(client, project, name="a1", prompt="first")["id"]
    b = new_node(client, project, name="b1", prompt="after a1")["id"]
    assert links(client, project) == [(a, b)]
    client.patch(f"/api/nodes/{a}", json={"prompt": "before b1"})  # b1 -> a1 would loop
    assert links(client, project) == [(a, b)]


def test_deleting_and_restoring_a_source_relinks(client):
    project = new_project(client)
    fox = new_node(client, project, name="fox", prompt="")["id"]
    scene = new_node(client, project, prompt="a fox")["id"]
    (edge,) = client.get(f"/api/projects/{project}").json()["edges"]
    client.delete(f"/api/nodes/{fox}")
    assert links(client, project) == []
    assert prompt_of(client, project, scene) == "a fox"  # the text stays
    client.post(f"/api/projects/{project}/restore", json={"node_ids": [fox]})
    assert [e["id"] for e in client.get(f"/api/projects/{project}").json()["edges"]] == [
        edge["id"]
    ]


def test_old_at_mentions_and_characters_are_migrated(data_dir, fake_image):
    """Before: "@ID" in prompts, and character nodes (a subtype of image)
    with a sheet of traits, some given by an image linked to the trait."""
    settings = make_settings(data_dir)
    generators = {Operation.image_generate: fake_image}
    with TestClient(create_app(settings, generators)) as client:
        project = new_project(client)
        parrot = new_node(client, project, name="鹦鹉员工")["id"]
        scene = new_node(client, project, prompt="x")["id"]
        hero = new_node(client, project, prompt="")["id"]
    db = sqlite3.connect(settings.db_path)
    db.execute(
        "UPDATE nodes SET prompt = 'meet @鹦鹉员工 at noon, mail a@b.com' WHERE id = ?",
        (scene,),
    )
    db.execute(
        "UPDATE nodes SET prompt = '', role = 'character', character = ? WHERE id = ?",
        (
            '{"style": "anime", "color": "", "body_shape": "", "age": "", '
            '"description": "brave"}',
            hero,
        ),
    )
    db.execute(
        "INSERT INTO edges (id, project_id, source_node_id, target_node_id, created_at, "
        "target_handle) VALUES ('edg_trait', ?, ?, ?, '2026-01-01T00:00:00Z', 'color')",
        (project, parrot, hero),
    )
    db.execute("PRAGMA user_version = 0")
    db.commit()
    db.close()
    with TestClient(create_app(settings, generators)) as client:
        graph = client.get(f"/api/projects/{project}").json()
        nodes = {n["id"]: n for n in graph["nodes"]}
        assert nodes[scene]["prompt"] == "meet 鹦鹉员工 at noon, mail a@b.com"
        # The character is a plain image whose prompt kept everything.
        assert nodes[hero]["prompt"] == "brave\nStyle: anime\nColor: 鹦鹉员工"
        assert "role" not in nodes[hero] and "character" not in nodes[hero]
        # Links are re-synced on startup: both mentions link, the trait link is gone.
        pairs = sorted((e["source_node_id"], e["target_node_id"]) for e in graph["edges"])
        assert pairs == sorted([(parrot, scene), (parrot, hero)])
        assert all(e["id"] != "edg_trait" for e in graph["edges"])
