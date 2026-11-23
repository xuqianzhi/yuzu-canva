"""Sharing a collection: invites, what editors may do, one tab per project
at a time, the owner paying (with editors' own limits), and deleting."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from canvas_api.app import create_app
from canvas_api.config import Limits
from canvas_api.contract import Operation

from .conftest import ALICE, BOB, PNG, auth, signed_in, wait_for_job
from .test_api import error_code, generate, list_projects, new_collection, new_node, new_project
from .test_collection_assets import add_asset

CAROL = "carol@example.com"


class Person:
    """Requests as someone else, from their own browser tab, through the
    same test client (one app)."""

    def __init__(self, client, email: str, tab: str) -> None:
        self.client = client
        self.headers = {**auth(email), "X-Edit-Session": tab}

    def request(self, method: str, url: str, **kwargs):
        return self.client.request(method, url, headers=self.headers, **kwargs)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)


def invite(owner, collection: str, email: str, **limits):
    return owner.post(
        f"/api/collections/{collection}/invites", json={"email": email, "limits": limits}
    )


def join(owner, person: Person, collection: str, email: str, **limits) -> None:
    """Invite `email` and accept as them."""
    assert invite(owner, collection, email, **limits).status_code == 201
    [invitation] = [
        i for i in person.get("/api/invitations").json() if i["collection_id"] == collection
    ]
    assert person.post(f"/api/invitations/{invitation['id']}/accept").status_code == 200


def members(client, collection: str) -> dict[str, dict]:
    return {m["email"]: m for m in client.get(f"/api/collections/{collection}/members").json()}


@pytest.fixture
def bob(client) -> Person:
    return Person(client, BOB, "bob-tab")


@pytest.fixture
def carol(client) -> Person:
    return Person(client, CAROL, "carol-tab")


# --- invites ---------------------------------------------------------------------------


def test_invites_wait_to_be_accepted(client, bob, carol):
    bob.get("/api/me")  # Bob has signed in before; Carol hasn't
    collection = new_collection(client, "Anime")
    made = invite(client, collection, " Bob@Example.com ", image=5)
    assert made.status_code == 201, made.text
    assert made.json()["email"] == BOB and made.json()["invited_by_email"] == ALICE
    invite(client, collection, CAROL)
    assert [
        i["email"] for i in client.get(f"/api/collections/{collection}/invites").json()
    ] == [
        CAROL,
        BOB,
    ]

    # Until Bob accepts, the collection isn't his.
    assert bob.get("/api/collections").json() == []
    assert bob.get(f"/api/collections/{collection}").status_code == 404
    [invitation] = bob.get("/api/invitations").json()
    assert invitation["collection_name"] == "Anime"
    # Nobody else can accept it for him.
    assert carol.post(f"/api/invitations/{invitation['id']}/accept").status_code == 404
    accepted = bob.post(f"/api/invitations/{invitation['id']}/accept")
    assert accepted.status_code == 200 and accepted.json()["your_role"] == "editor"
    [listed] = bob.get("/api/collections").json()
    assert (listed["id"], listed["owner_email"], listed["member_count"]) == (
        collection,
        ALICE,
        2,
    )
    assert bob.get("/api/invitations").json() == []
    people = members(client, collection)
    assert list(people) == [ALICE, BOB]  # the owner first
    assert people[ALICE]["role"] == "owner" and people[BOB]["role"] == "editor"
    assert people[BOB]["limits"] == {"text": None, "image": 5, "video": None}
    again = invite(client, collection, BOB)
    assert (again.status_code, error_code(again)) == (409, "validation_error")

    # Carol declines; a cancelled invite is gone too.
    [for_carol] = carol.get("/api/invitations").json()
    assert carol.post(f"/api/invitations/{for_carol['id']}/decline").status_code == 204
    assert carol.get("/api/collections").json() == []
    dave = invite(client, collection, "dave@example.com").json()
    assert (
        client.delete(f"/api/collections/{collection}/invites/{dave['id']}").status_code == 204
    )
    assert client.get(f"/api/collections/{collection}/invites").json() == []


def test_expired_invites_cant_be_accepted(client, bob, settings):
    collection = new_collection(client)
    invite(client, collection, BOB)
    with psycopg.connect(settings.database_url, autocommit=True) as db:
        past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        db.execute("UPDATE collection_invites SET expires_at = %s", (past,))
    assert bob.get("/api/invitations").json() == []
    assert client.get(f"/api/collections/{collection}/invites").json() == []


# --- what editors may do ---------------------------------------------------------------


def test_editors_do_everything_but_delete_and_manage_people(client, bob, carol):
    collection = new_collection(client)
    join(client, bob, collection, BOB)
    project = new_project(bob, "Bob's", collection)
    node = new_node(bob, project)["id"]
    assert bob.patch(f"/api/nodes/{node}", json={"prompt": "a cat"}).status_code == 200
    version = bob.get(f"/api/collections/{collection}").json()["version"]
    renamed = bob.patch(
        f"/api/collections/{collection}", json={"version": version, "name": "B"}
    )
    assert renamed.status_code == 200
    made = bob.post(
        f"/api/collections/{collection}/workflows",
        json={
            "definition": {
                "id": "x",
                "name": "W",
                "steps": [{"key": "a", "name": "A", "kind": "text"}],
            }
        },
    ).json()
    assert bob.post(f"/api/workflows/{made['id']}/activate").status_code == 200
    assert add_asset(bob, "Logo", collection=collection).status_code == 201
    bob.delete(f"/api/projects/{project}/lock")

    alice_id = members(client, collection)[ALICE]["user_id"]
    bob_id = members(client, collection)[BOB]["user_id"]
    for method, path, body in [
        ("DELETE", f"/api/projects/{project}", None),
        ("DELETE", f"/api/collections/{collection}", None),
        ("POST", f"/api/collections/{collection}/invites", {"email": CAROL}),
        ("PATCH", f"/api/collections/{collection}/members/{bob_id}", {"limits": {}}),
        ("DELETE", f"/api/collections/{collection}/members/{alice_id}", None),
    ]:
        response = bob.request(method, path, json=body)
        assert (response.status_code, error_code(response)) == (403, "forbidden"), path
    assert client.get(f"/api/projects/{project}").status_code == 200

    # The owner can't leave; an editor can, and their work stays.
    owner_leaves = client.delete(f"/api/collections/{collection}/members/{alice_id}")
    assert owner_leaves.status_code == 409
    assert bob.delete(f"/api/collections/{collection}/members/{bob_id}").status_code == 204
    assert bob.get(f"/api/collections/{collection}").status_code == 404
    assert [p["id"] for p in list_projects(client, collection)] == [project]


def test_the_owner_removes_an_editor(client, bob):
    collection = new_collection(client)
    join(client, bob, collection, BOB)
    project = new_project(bob, "P", collection)
    assert bob.post(f"/api/projects/{project}/lock").json()["held"]
    bob_id = members(client, collection)[BOB]["user_id"]
    assert client.delete(f"/api/collections/{collection}/members/{bob_id}").status_code == 204
    assert bob.get(f"/api/projects/{project}").status_code == 404
    # Their lock went with them.
    assert client.patch(f"/api/projects/{project}", json={"name": "Q"}).status_code == 200


# --- one tab per project ---------------------------------------------------------------


def test_one_tab_edits_a_project_at_a_time(client, bob):
    collection = new_collection(client)
    join(client, bob, collection, BOB)
    project = new_project(client, "P", collection)
    lock = client.post(f"/api/projects/{project}/lock").json()
    assert lock["held"] and lock["holder_email"] == ALICE

    # Bob can look, not change anything.
    assert bob.get(f"/api/projects/{project}").status_code == 200
    seen = bob.get(f"/api/projects/{project}/lock").json()
    assert (seen["held"], seen["holder_email"], seen["holder_is_you"]) == (False, ALICE, False)
    for method, path, body in [
        ("PATCH", f"/api/projects/{project}", {"name": "Bob's"}),
        ("POST", f"/api/projects/{project}/nodes", {"kind": "text"}),
        ("POST", f"/api/projects/{project}/lock", None),
    ]:
        response = bob.request(method, path, json=body)
        assert (response.status_code, error_code(response)) == (409, "project_locked"), path
        context = response.json()["error"]["context"]
        assert context == {"holder_email": ALICE, "holder_is_you": "false"}
    # Not even to take it over.
    taken = bob.post(f"/api/projects/{project}/lock", json={"take_over": True})
    assert taken.status_code == 409
    assert bob.get("/api/collections").json()[0]["id"] == collection
    summary = list_projects(bob, collection)[0]
    assert summary["editing_by"] == ALICE
    assert list_projects(client, collection)[0]["editing_by"] is None  # that's you

    # Alice's other tab can take it over; her first tab then can't change it.
    other_tab = Person(client, ALICE, "tab-2")
    refused = other_tab.post(f"/api/projects/{project}/lock")
    assert refused.json()["error"]["context"]["holder_is_you"] == "true"
    assert other_tab.post(f"/api/projects/{project}/lock", json={"take_over": True}).json()[
        "held"
    ]
    stale = client.patch(f"/api/projects/{project}", json={"name": "Q"})
    assert (stale.status_code, error_code(stale)) == (409, "project_locked")

    # Once released, Bob's change takes the lock.
    assert other_tab.delete(f"/api/projects/{project}/lock").status_code == 204
    assert bob.patch(f"/api/projects/{project}", json={"name": "Bob's"}).status_code == 200
    assert bob.get(f"/api/projects/{project}/lock").json()["held"]
    # No edit session at all: refused.
    headless = client.patch(
        f"/api/projects/{project}", json={"name": "x"}, headers={"X-Edit-Session": ""}
    )
    assert headless.status_code == 409


def test_a_lock_expires_when_its_tab_stops_renewing(client, bob, settings):
    collection = new_collection(client)
    join(client, bob, collection, BOB)
    project = new_project(client, "P", collection)
    client.post(f"/api/projects/{project}/lock")
    assert bob.post(f"/api/projects/{project}/lock").status_code == 409
    with psycopg.connect(settings.database_url, autocommit=True) as db:
        past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        db.execute("UPDATE project_locks SET expires_at = %s", (past,))
    assert bob.get(f"/api/projects/{project}/lock").json()["holder_email"] is None
    assert bob.post(f"/api/projects/{project}/lock").json()["held"]


def test_the_owner_can_delete_a_project_someone_is_editing(client, bob):
    collection = new_collection(client)
    join(client, bob, collection, BOB)
    project = new_project(client, "P", collection)
    assert bob.post(f"/api/projects/{project}/lock").json()["held"]
    assert list_projects(client, collection)[0]["editing_by"] == BOB
    assert client.delete(f"/api/projects/{project}").status_code == 204
    assert bob.get(f"/api/projects/{project}").status_code == 404


# --- the owner pays --------------------------------------------------------------------


@pytest.fixture
def team(settings, fake_image):
    """Alice, with at most 3 images a day, and Bob in her collection with
    his own limit of 1."""
    tight = replace(settings, limits=replace(Limits(), images_per_day=3, active_jobs=0))
    with signed_in(create_app(tight, {Operation.image_generate: fake_image})) as alice:
        bob = Person(alice, BOB, "bob-tab")
        collection = new_collection(alice, "Anime")
        join(alice, bob, collection, BOB, image=1)
        yield alice, bob, collection


def test_the_owner_pays_for_what_editors_make(team):
    alice, bob, collection = team
    project = new_project(bob, "P", collection)
    first, second = new_node(bob, project)["id"], new_node(bob, project)["id"]
    wait_for_job(bob, generate(bob, first).json()["id"])
    over = generate(bob, second)
    assert (over.status_code, error_code(over)) == (429, "quota_exceeded")
    assert over.json()["error"]["context"]["scope"] == "editor"
    assert "1 of 1 images" in over.json()["error"]["message"]

    me = alice.get("/api/me").json()
    assert me["used_today"]["image"] == 1  # Alice pays for Bob's image
    assert me["breakdown"] == [
        {
            "collection_id": collection,
            "collection_name": "Anime",
            "email": BOB,
            "used": {"text": 0, "image": 1, "video": 0},
        }
    ]
    assert bob.get("/api/me").json()["used_today"]["image"] == 0
    assert members(alice, collection)[BOB]["used_today"]["image"] == 1

    # Alice's own daily limit covers everything together.
    bob.delete(f"/api/projects/{project}/lock")
    for node in (new_node(alice, project)["id"], new_node(alice, project)["id"]):
        wait_for_job(alice, generate(alice, node).json()["id"])
    bob_id = members(alice, collection)[BOB]["user_id"]
    raised = alice.patch(
        f"/api/collections/{collection}/members/{bob_id}", json={"limits": {"image": None}}
    )
    assert raised.json()["limits"]["image"] is None
    alice.delete(f"/api/projects/{project}/lock")
    owners_limit = generate(bob, second)
    assert (owners_limit.status_code, error_code(owners_limit)) == (429, "quota_exceeded")
    assert (
        "3 of 3 images used today by this collection's owner"
        in (owners_limit.json()["error"]["message"])
    )


def test_an_editor_with_a_zero_limit_cant_generate_that_kind(team):
    alice, bob, collection = team
    bob_id = members(alice, collection)[BOB]["user_id"]
    alice.patch(
        f"/api/collections/{collection}/members/{bob_id}", json={"limits": {"image": 0}}
    )
    project = new_project(bob, "P", collection)
    response = generate(bob, new_node(bob, project)["id"])
    assert response.status_code == 429
    assert "can't generate images in this collection" in response.json()["error"]["message"]


# --- deleting --------------------------------------------------------------------------


def test_deleting_a_collection_deletes_everything_in_it(client, bob, carol, data_dir):
    collection = new_collection(client)
    keep = new_collection(client, "Keep")
    join(client, bob, collection, BOB)
    invite(client, collection, CAROL)
    add_asset(client, "Logo", collection=collection)
    project = new_project(client, "P", collection)
    node = new_node(client, project)["id"]
    wait_for_job(client, generate(client, node).json()["id"])
    [take] = client.get(f"/api/nodes/{node}/outputs").json()
    assert client.get(take["asset"]["url"]).content == PNG
    files = lambda: sorted(p.name for p in data_dir.rglob("*") if p.is_file())  # noqa: E731
    assert len(files()) == 3  # the asset, its copy in the project, the image

    # Only the owner, and then it's gone for everyone.
    assert bob.delete(f"/api/collections/{collection}").status_code == 403
    assert client.delete(f"/api/collections/{collection}").status_code == 204
    assert [c["id"] for c in client.get("/api/collections").json()] == [keep]
    assert bob.get("/api/collections").json() == []
    assert carol.get("/api/invitations").json() == []
    assert client.get(f"/api/projects/{project}").status_code == 404
    assert client.get(take["asset"]["url"]).status_code == 404
    assert files() == []
    # What it cost still counts today.
    me = client.get("/api/me").json()
    assert me["used_today"]["image"] == 1
    assert me["breakdown"][0]["collection_id"] is None
