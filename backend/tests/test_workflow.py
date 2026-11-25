"""Workflows: several per collection, one active (steps are a name and a
kind), and running a step with a prompt and a count."""

from __future__ import annotations

import io
import json
import zipfile
from urllib.parse import unquote

from fastapi.testclient import TestClient

from canvas_api.domain.workflow import (
    Piece,
    RunItem,
    builtin_workflow,
    name_images,
    parse_run,
)

from .conftest import signed_in, wait_for_job
from .helpers import graph_of, pipeline_template, run_step, step_nodes, wait_for_outputs
from .test_api import error_code, new_collection, new_node, new_project, patch_collection


def mini() -> dict:
    return {
        "id": "ignored",
        "name": "Mini",
        "steps": [
            {"key": "brief", "name": "Brief", "kind": "text"},
            {"key": "posters", "name": "Posters", "kind": "image"},
        ],
    }


def workflows(client: TestClient, collection: str) -> list[dict]:
    return client.get(f"/api/collections/{collection}/workflows").json()


def add_workflow(client: TestClient, collection: str, definition: dict):
    return client.post(
        f"/api/collections/{collection}/workflows", json={"definition": definition}
    )


def test_a_collection_starts_with_the_builtin_workflow_active(client):
    collection = new_collection(client)
    [builtin] = workflows(client, collection)
    assert builtin["id"].startswith("wfl_") and builtin["active"]
    assert (
        client.get(f"/api/collections/{collection}").json()["active_workflow_id"]
        == (builtin["id"])
    )
    steps = builtin["definition"]["steps"]
    assert [(s["name"], s["kind"]) for s in steps] == [
        ("Character", "image"),
        ("Dish brainstorming", "text"),
        ("Dish image", "image"),
        ("Script overview", "text"),
        ("Video per scene", "video"),
    ]
    assert all("output" not in s for s in steps)
    assert all(s["description"] for s in steps)
    project = graph_of(client, new_project(client, collection=collection))["project"]
    expected = builtin_workflow().model_copy(update={"id": builtin["id"]})
    assert project["workflow"] == expected.model_dump(mode="json")
    # Or start it with a copy of another workflow.
    copied = new_collection(client, "Copy", workflow=mini())
    [only] = workflows(client, copied)
    assert only["definition"]["name"] == "Mini" and only["id"] != "ignored"


def test_projects_run_on_the_active_workflow(client):
    collection = new_collection(client)
    [builtin] = workflows(client, collection)
    project = new_project(client, collection=collection)
    made = add_workflow(client, collection, mini())
    assert made.status_code == 201, made.text
    other = made.json()
    assert not other["active"]
    assert graph_of(client, project)["project"]["workflow"]["name"] != "Mini"

    activated = client.post(f"/api/workflows/{other['id']}/activate")
    assert activated.status_code == 200 and activated.json()["active"]
    assert graph_of(client, project)["project"]["workflow"]["name"] == "Mini"
    # Editing the active one changes it for every project too.
    edited = client.put(
        f"/api/workflows/{other['id']}",
        json={"definition": {**mini(), "name": "Mini 2"}, "base_version": 1},
    )
    assert edited.json()["definition"]["version"] == 2
    assert graph_of(client, project)["project"]["workflow"]["name"] == "Mini 2"
    # Someone else's newer save isn't overwritten.
    stale = client.put(
        f"/api/workflows/{other['id']}", json={"definition": mini(), "base_version": 1}
    )
    assert (stale.status_code, error_code(stale)) == (409, "edit_conflict")

    twice = {**mini(), "steps": [mini()["steps"][0], mini()["steps"][0]]}
    assert add_workflow(client, collection, twice).status_code == 422
    active = client.delete(f"/api/workflows/{other['id']}")
    assert (active.status_code, error_code(active)) == (409, "validation_error")
    client.post(f"/api/workflows/{builtin['id']}/activate")
    assert client.delete(f"/api/workflows/{other['id']}").status_code == 204
    assert [w["id"] for w in workflows(client, collection)] == [builtin["id"]]


def test_a_step_can_have_a_default_count(client):
    collection = new_collection(client)
    steps = [
        {"key": "a", "name": "A", "kind": "text", "count": 4},
        {"key": "b", "name": "B", "kind": "image"},
    ]
    made = add_workflow(client, collection, {**mini(), "steps": steps}).json()
    assert [s["count"] for s in made["definition"]["steps"]] == [4, None]
    for bad in (0, 21):
        wrong = [{**steps[0], "count": bad}, steps[1]]
        assert add_workflow(client, collection, {**mini(), "steps": wrong}).status_code == 422
    [builtin] = [w for w in workflows(client, collection) if w["active"]]
    assert [s["count"] for s in builtin["definition"]["steps"]] == [None, None, None, 1, None]


def test_a_steps_description_goes_to_the_ai(client, fake_text):
    described = "Two-line dish ideas a five-year-old could draw."
    steps = [
        {"key": "dishes", "name": "Dishes", "kind": "text", "description": f"  {described} "},
        {"key": "posters", "name": "Posters", "kind": "image"},
    ]
    collection = new_collection(
        client, "Kids", instruction="Cozy.", workflow={**mini(), "steps": steps}
    )
    [workflow] = workflows(client, collection)
    assert workflow["definition"]["steps"][0]["description"] == f"  {described} "
    assert workflow["definition"]["steps"][1]["description"] == ""
    project = new_project(client, collection=collection)

    graph = run_step(client, project, "dishes", "soups", 1).json()
    system = fake_text.calls[-1]["system"]
    step = "This step is called “Dishes” and makes texts."
    assert f"{step}\n<step_description>\n{described}\n</step_description>\n" in system
    assert system.index("Cozy.") < system.index(described)
    node = step_nodes(graph, "dishes")[0]["id"]
    client.post(f"/api/nodes/{node}/chat", json={"text": "shorter please"})
    assert f"{step}\n<step_description>\n{described}" in fake_text.calls[-1]["system"]

    too_long = [{**steps[0], "description": "x" * 4001}, steps[1]]
    assert add_workflow(client, collection, {**mini(), "steps": too_long}).status_code == 422


def test_switching_workflows_hides_steps_without_deleting_them(client):
    collection = new_collection(client)
    [builtin] = workflows(client, collection)
    project = new_project(client, collection=collection)
    graph = run_step(client, project, "dishes", "soups", 2).json()
    dishes = [n["id"] for n in step_nodes(graph, "dishes")]
    other = add_workflow(client, collection, mini()).json()

    client.post(f"/api/workflows/{other['id']}/activate")
    graph = graph_of(client, project)
    assert step_nodes(graph, "dishes") == [] and graph["runs"] == []
    client.post(f"/api/workflows/{builtin['id']}/activate")
    graph = graph_of(client, project)
    assert [n["id"] for n in step_nodes(graph, "dishes")] == dishes
    assert [r["step"] for r in graph["runs"]] == ["dishes"]


def test_the_active_workflow_cant_change_while_a_step_runs(settings, fake_image):
    from canvas_api.app import create_app
    from canvas_api.contract import Operation
    from canvas_api.providers.fake import FakeTextModel

    from .conftest import signed_in

    slow = FakeTextModel(delay_s=0.5)
    with signed_in(
        create_app(settings, {Operation.image_generate: fake_image}, slow)
    ) as client:
        collection = new_collection(client)
        [builtin] = workflows(client, collection)
        other = add_workflow(client, collection, mini()).json()
        project = new_project(client, collection=collection)
        started = client.post(
            f"/api/projects/{project}/workflow/steps/dishes/run",
            json={"prompt": "soups", "count": 1},
        )
        assert started.status_code == 202
        busy = client.post(f"/api/workflows/{other['id']}/activate")
        assert (busy.status_code, error_code(busy)) == (409, "workflow_locked")
        edit = client.put(
            f"/api/workflows/{builtin['id']}", json={"definition": builtin["definition"]}
        )
        assert edit.status_code == 409
        # An inactive one can be edited meanwhile.
        assert (
            client.put(f"/api/workflows/{other['id']}", json={"definition": mini()}).status_code
            == 200
        )


def test_a_text_step_makes_one_node_per_result(client, fake_text):
    collection = new_collection(client, "Kids", instruction="Cozy, for kids.")
    project = new_project(client, collection=collection)
    response = run_step(client, project, "dishes", "winter soups", 3)
    assert response.status_code == 200, response.text
    graph = response.json()
    nodes = step_nodes(graph, "dishes")
    assert [(n["name"], n["kind"], n["workflow_item"]) for n in nodes] == [
        ("dishes_1", "text", 1),
        ("dishes_2", "text", 2),
        ("dishes_3", "text", 3),
    ]
    outputs = {o["id"]: o for o in graph["outputs"]}
    assert outputs[nodes[0]["selected_output_id"]]["text"].startswith("Result 1:")
    assert graph["runs"][0] | {"updated_at": None} == {
        "step": "dishes",
        "prompt": "winter soups",
        "count": 3,
        "status": "done",
        "error": None,
        "updated_at": None,
        "manual": False,
    }
    call = fake_text.calls[-1]
    assert (
        "Cozy, for kids." in call["system"]
        and "<collection_instruction>\nCozy, for kids.\n</collection_instruction>"
        in call["system"]
        and "This step is called “Dish brainstorming”" in call["system"]
    )
    assert "exactly 3" in call["system"]
    assert call["messages"][0]["content"] == "<request>\nwinter soups\n</request>"
    schema = call["spec"].schema["properties"]["items"]
    assert (schema["minItems"], schema["maxItems"]) == (3, 3)

    # Running again replaces the step's nodes.
    again = run_step(client, project, "dishes", "summer salads", 2).json()
    assert [n["name"] for n in step_nodes(again, "dishes")] == ["dishes_1", "dishes_2"]
    assert all(n["id"] not in {m["id"] for m in nodes} for n in step_nodes(again, "dishes"))


def test_independent_results_are_used_by_mentioning_their_ids(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "dishes", "winter soups", 2)
    # Nothing flows to the next step by itself.
    run_step(client, project, "characters", "a mascot", 1)
    assert fake_text.calls[-1]["messages"][0]["content"] == "<request>\na mascot\n</request>"

    fake_image.gate.clear()  # keep the new image jobs running while we look
    graph = run_step(client, project, "characters", "a mascot for dishes_2", 2).json()
    call = fake_text.calls[-1]
    sent = call["messages"][0]["content"]
    assert sent.startswith('<reference id="dishes_2">\nResult 2:')
    assert sent.endswith("<request>\na mascot for dishes_2\n</request>")
    assert "write that id exactly as it is" in call["system"]
    nodes = step_nodes(graph, "characters")
    assert [n["name"] for n in nodes] == ["characters_1", "characters_2"]
    # Each prompt keeps the mention, so the dish is linked as an input.
    assert all("dishes_2" in n["prompt"] for n in nodes)
    dish = step_nodes(graph, "dishes")[1]
    into = [e for e in graph["edges"] if e["target_node_id"] == nodes[0]["id"]]
    assert [(e["source_node_id"], e["workflow"]) for e in into] == [(dish["id"], False)]
    # Each image is generated right away.
    assert len(graph["active_jobs"]) == 2
    fake_image.gate.set()
    for job in graph["active_jobs"]:
        assert wait_for_job(client, job["id"])["status"] == "succeeded"


def test_mentioned_images_are_shown_to_the_model(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "characters", "a fox", 1)
    wait_for_outputs(client, project, "characters")
    run_step(client, project, "dishes", "a soup for characters_1", 2)
    call = fake_text.calls[-1]
    assert call["messages"][0]["content"].startswith(
        '<reference id="characters_1">\n(an image, attached as image 1. In what you '
        "write, call it characters_1, never image 1.)\n</reference>"
    )
    assert len(call["images"]) == 1


def test_image_labels_in_written_prompts_become_ids(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "characters", "a fox", 1)
    wait_for_outputs(client, project, "characters")
    # The fake model echoes the request: as if it wrote "image 1" itself.
    graph = run_step(
        client, project, "dishes", "a soup for characters_1, in the style of image 1", 1
    ).json()
    text = next(
        o for o in graph["outputs"] if o["node_id"] == step_nodes(graph, "dishes")[0]["id"]
    )
    assert "for characters_1, in the style of characters_1" in text["text"]
    assert "image 1" not in text["text"]


def test_name_images_replaces_only_mentioned_labels():
    refs = [
        Piece(kind="image", label="image 1", name="小獭女仆"),
        Piece(kind="text", text="a story", name="script"),
        Piece(kind="image", label="image 2", name="fox"),
    ]
    items = [
        "参照图片 image 1 画风，和图片2一起",
        "Image 2 and image 3 and image 12; myimage 1 stays",
        "参照图片1的配色",
    ]
    assert name_images(items, refs) == [
        "参照图片 小獭女仆 画风，和fox一起",
        "fox and image 3 and image 12; myimage 1 stays",
        "参照小獭女仆的配色",
    ]
    assert name_images(["image 1"], []) == ["image 1"]


def download(client: TestClient, project: str, step: str):
    return client.get(f"/api/projects/{project}/workflow/steps/{step}/download")


def test_download_a_step_as_a_zip_in_order(client, fake_text, fake_image):
    project = new_project(client, "Winter / menu")
    # Nothing yet.
    assert download(client, project, "dishes").status_code == 404
    assert download(client, project, "nope").status_code == 404

    run_step(client, project, "dishes", "winter soups", 3)
    response = download(client, project, "dishes")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = unquote(response.headers["content-disposition"])
    assert disposition.endswith("Winter-menu_step2_Dish-brainstorming.zip")
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.namelist() == ["dishes_01.txt", "dishes_02.txt", "dishes_03.txt"]
    graph = graph_of(client, project)
    outputs = {o["id"]: o for o in graph["outputs"]}
    for node in step_nodes(graph, "dishes"):
        text = outputs[node["selected_output_id"]]["text"]
        assert archive.read(f"dishes_0{node['workflow_item']}.txt").decode() == text

    run_step(client, project, "characters", "a fox", 2)
    wait_for_outputs(client, project, "characters")
    archive = zipfile.ZipFile(io.BytesIO(download(client, project, "characters").content))
    names = archive.namelist()
    assert [n.rsplit(".", 1)[0] for n in names] == ["characters_01", "characters_02"]
    assert all(archive.read(n) for n in names)


def test_editors_can_download_but_outsiders_cannot(client, fake_text, fake_image):
    project = new_project(client)
    run_step(client, project, "dishes", "soups", 1)
    stranger = signed_in(client.app, "stranger@example.com")
    assert download(stranger, project, "dishes").status_code == 404


def test_old_one_to_one_steps_read_as_plain_steps(client):
    # Definitions saved with the removed `output` setting still load.
    definition = {
        "id": "x",
        "name": "Old",
        "steps": [
            {"key": "a", "name": "A", "kind": "text", "output": "one_to_one", "carry": "none"},
            {"key": "b", "name": "B", "kind": "text", "output": "independent", "carry": "used"},
            {"key": "c", "name": "C", "kind": "text", "output": "one_to_one"},
        ],
    }
    collection = new_collection(client, "Old", workflow=definition)
    saved = client.get(f"/api/collections/{collection}/workflows").json()[0]["definition"]
    assert [s["carry"] for s in saved["steps"]] == ["none", "used", "all"]
    assert all("output" not in s for s in saved["steps"])


def test_runs_are_checked(client):
    project = new_project(client)
    assert run_step(client, project, "dishes", "x", None).status_code == 422  # how many?
    assert run_step(client, project, "dishes", "x", 0).status_code == 422
    assert run_step(client, project, "dishes", "x", 21).status_code == 422
    assert run_step(client, project, "nope", "x", 1).status_code == 404
    assert parse_run('{"items": [" a ", "", "b", "c"]}', 2) == [RunItem("a"), RunItem("b")]
    named = '{"items": [{"id": " 怪人 ", "content": " x "}, {"id": "", "content": "y"}, "z"]}'
    assert parse_run(named, 3) == [RunItem("x", "怪人"), RunItem("y"), RunItem("z")]


# --- node IDs given by the model -----------------------------------------------------


def answer_with(fake_text, *named: tuple[str | None, str]) -> None:
    """Make the fake model answer the next runs with these (id, content) items."""
    complete = fake_text.complete

    async def scripted(system, messages, spec=None, images=None):
        if spec is None or spec.name != "run":
            return await complete(system, messages, spec, images)
        await complete(system, messages, spec, images)  # recorded
        items = [{"id": i, "content": c} if i is not None else c for i, c in named]
        return json.dumps({"items": items})

    fake_text.complete = scripted


def test_the_model_names_a_steps_nodes(client, fake_text, fake_image):
    project = new_project(client)
    new_node(client, project, name="小獭女仆")
    answer_with(fake_text, ("怪人", "角色名：怪人，狂野"), ("帅气科学家", "角色名：帅气科学家"))
    graph = run_step(client, project, "characters", "怪人和帅气科学家", 2).json()
    assert [n["name"] for n in step_nodes(graph, "characters")] == ["怪人", "帅气科学家"]
    call = fake_text.calls[-1]
    assert call["spec"].schema["properties"]["items"]["items"]["required"] == ["id", "content"]
    assert "IDs already in the project (小獭女仆)" in call["system"]

    wait_for_outputs(client, project, "characters")

    # A node generated on its own keeps its ID.
    first = step_nodes(graph_of(client, project), "characters")[0]
    job = client.post(f"/api/nodes/{first['id']}/generate").json()
    assert wait_for_job(client, job["id"])["status"] == "succeeded"
    assert step_nodes(graph_of(client, project), "characters")[0]["name"] == "怪人"

    # Run again: named afresh. The step's own IDs aren't "taken" (they're
    # being replaced), and the model isn't asked to keep them.
    answer_with(fake_text, ("狂野怪人", "a"), ("老科学家", "b"))
    graph = run_step(client, project, "characters", "怪人和帅气科学家", 2).json()
    assert [n["name"] for n in step_nodes(graph, "characters")] == ["狂野怪人", "老科学家"]
    call = fake_text.calls[-1]
    assert "IDs already in the project (小獭女仆)" in call["system"]
    assert "帅气科学家" not in call["system"]
    wait_for_outputs(client, project, "characters")


def test_given_names_are_cleaned_and_made_unique(client, fake_text):
    project = new_project(client)
    new_node(client, project, kind="text", name="怪人")
    answer_with(
        fake_text,
        ("怪人", "a"),  # taken by another node
        ("狂野 怪人!", "b"),  # not a valid ID
        (None, "c"),  # none given
        ("!!!", "d"),  # nothing usable
        ("A-very-long-name-that-goes-on-and-on", "e"),
        ("dish", "f"),
        ("DISH", "g"),  # the same ignoring case
    )
    graph = run_step(client, project, "dishes", "soups", 7).json()
    assert [n["name"] for n in step_nodes(graph, "dishes")] == [
        "怪人_2",
        "狂野_怪人",
        "dishes_3",
        "dishes_4",
        "A-very-long-name-that-go",
        "dish",
        "DISH_2",
    ]


def test_a_name_in_a_siblings_prompt_gets_its_number(client, fake_text, fake_image):
    # 怪人 is in the scientist's prompt: as is, it would be the scientist's
    # input before it has an image, and that generation would fail.
    project = new_project(client)
    answer_with(fake_text, ("怪人", "a wild man"), ("科学家", "怪人 turned scientist"))
    graph = run_step(client, project, "characters", "two looks", 2).json()
    nodes = step_nodes(graph, "characters")
    assert [n["name"] for n in nodes] == ["怪人_1", "科学家"]
    assert not [e for e in graph["edges"] if e["target_node_id"] == nodes[1]["id"]]
    wait_for_outputs(client, project, "characters")
    assert all(
        n["selected_output_id"] for n in step_nodes(graph_of(client, project), "characters")
    )


def test_the_prompt_is_optional_when_the_model_writes(client, fake_text):
    project = new_project(client)
    graph = run_step(client, project, "dishes", "  ", 2).json()
    assert len(step_nodes(graph, "dishes")) == 2
    call = fake_text.calls[-1]
    assert "There's no <request> this time" in call["system"]
    assert "<request>" not in call["messages"][0]["content"]


def test_media_steps_are_filled_in_then_generated(client, fake_text, fake_image):
    project = new_project(client)
    url = f"/api/projects/{project}/workflow/steps/characters"
    early = client.post(f"{url}/generate")
    assert (early.status_code, error_code(early)) == (409, "workflow_blocked")
    graph = run_step(client, project, "characters", "a fox", 2, generate=False).json()
    nodes = step_nodes(graph, "characters")
    assert [bool(n["prompt"]) for n in nodes] == [True, True]
    assert graph["active_jobs"] == [] and not any(n["selected_output_id"] for n in nodes)
    # A blank prompt holds the step back.
    client.patch(f"/api/nodes/{nodes[1]['id']}", json={"prompt": " "})
    blank = client.post(f"{url}/generate")
    assert (blank.status_code, error_code(blank)) == (409, "workflow_blocked")
    client.patch(f"/api/nodes/{nodes[1]['id']}", json={"prompt": "a grey fox"})
    graph = client.post(f"{url}/generate").json()
    assert len(graph["active_jobs"]) == 2
    text = client.post(f"/api/projects/{project}/workflow/steps/dishes/generate")
    assert (text.status_code, error_code(text)) == (409, "not_generatable")
    wait_for_outputs(client, project, "characters")


def test_video_lengths_come_from_the_model(client, fake_text, fake_video):
    project = pipeline_template(client, "text", "video")
    run_step(client, project, "prompts", "two scenes, 8 s and 12 s", 2)
    graph = run_step(client, project, "scenes", "", 2, generate=False).json()
    call = fake_text.calls[-1]
    assert "length in whole `seconds`, from 4 to 15" in call["system"]
    item = call["spec"].schema["properties"]["items"]["items"]
    assert item["required"] == ["id", "content", "seconds"]
    assert [n["params"]["duration_s"] for n in step_nodes(graph, "scenes")] == [5, 6]
    # Out of range or not a number: kept to what Seedance takes, or left out.
    raw = '{"items": [{"content": "a", "seconds": 40}, {"content": "b", "seconds": 2.6},'
    raw += ' {"content": "c", "seconds": "x"}]}'
    assert [i.seconds for i in parse_run(raw, 3)] == [15, 4, None]


def test_workflow_nodes_are_locked_but_editable(client):
    project = new_project(client)
    node = step_nodes(run_step(client, project, "characters", "a fox", 1).json(), "characters")[
        0
    ]
    deleted = client.delete(f"/api/nodes/{node['id']}")
    assert (deleted.status_code, error_code(deleted)) == (409, "workflow_locked")
    retyped = client.patch(f"/api/nodes/{node['id']}", json={"kind": "text"})
    assert (retyped.status_code, error_code(retyped)) == (409, "workflow_locked")
    assert (
        client.patch(f"/api/nodes/{node['id']}", json={"prompt": "a red fox"}).status_code
        == 200
    )


def test_chat_and_takes_on_text_nodes(client, fake_text):
    project = new_project(client)
    node = step_nodes(run_step(client, project, "dishes", "soups", 1).json(), "dishes")[0]
    sent = client.post(f"/api/nodes/{node['id']}/chat", json={"text": "make it spicier"})
    assert sent.status_code == 200, sent.text
    _, answer = sent.json()
    chat = fake_text.calls[-1]
    assert "This step is called “Dish brainstorming”" in chat["system"]
    assert "reply, and write any new version, in the language and script" in chat["system"]
    assert chat["messages"][0]["content"].startswith("<current_version>\nResult 1:")
    applied = client.post(f"/api/chat/{answer['id']}/apply").json()
    take = client.post(f"/api/nodes/{node['id']}/takes", json={"text": "my own"}).json()
    outputs = client.get(f"/api/nodes/{node['id']}/outputs").json()
    assert [o["id"] for o in outputs][:2] == [take["id"], applied["id"]]
    image = new_node(client, project)["id"]
    assert client.post(f"/api/nodes/{image}/chat", json={"text": "hi"}).status_code == 409


def test_a_collection_can_generate_images_or_videos_directly(client, fake_text, fake_image):
    collection = new_collection(client, "Direct")
    saved = client.get(f"/api/collections/{collection}").json()
    assert (saved["direct_image"], saved["direct_video"]) == (False, False)  # off by default
    project = new_project(client, "P", collection)
    graph = run_step(client, project, "characters", "a fox", 2, generate=False).json()
    assert graph["active_jobs"] == []  # only filled in

    changed = patch_collection(client, collection, direct_image=True).json()
    assert (changed["direct_image"], changed["direct_video"]) == (True, False)
    assert graph_of(client, project)["project"]["direct_image"] is True  # read live
    fake_image.gate.clear()  # keep the jobs running while we look
    graph = run_step(client, project, "characters", "a fox", 2, generate=False).json()
    nodes = step_nodes(graph, "characters")
    assert {j["node_id"] for j in graph["active_jobs"]} == {n["id"] for n in nodes}
    assert next(r for r in graph["runs"] if r["step"] == "characters")["status"] == "done"
    fake_image.gate.set()
    wait_for_outputs(client, project, "characters")


def test_direct_video_is_its_own_setting(client, fake_text, fake_video):
    project = pipeline_template(client, "text", "video")
    collection = graph_of(client, project)["project"]["collection_id"]
    patch_collection(client, collection, direct_image=True)
    run_step(client, project, "prompts", "two scenes", 2)
    graph = run_step(client, project, "scenes", "", 2, generate=False).json()
    assert graph["active_jobs"] == []  # images go directly, videos don't
    patch_collection(client, collection, direct_video=True)
    fake_video.gate.clear()
    graph = run_step(client, project, "scenes", "", 2, generate=False).json()
    assert len(graph["active_jobs"]) == 2
    fake_video.gate.set()
    for job in graph["active_jobs"]:
        assert wait_for_job(client, job["id"])["status"] == "succeeded"
