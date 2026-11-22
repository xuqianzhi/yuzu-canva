"""The language setting: it picks the wording of every prompt the backend
writes (the user's own text is sent as written)."""

from __future__ import annotations

from .conftest import wait_for_job
from .test_api import generate, new_node, new_project
from .test_workflow import run_step


def set_language(client, language: str):
    response = client.put("/api/settings", json={"language": language})
    assert response.status_code == 200, response.text
    return response.json()


def test_language_defaults_to_english_and_is_remembered(client):
    assert client.get("/api/settings").json() == {"language": "en"}
    assert set_language(client, "zh") == {"language": "zh"}
    assert client.get("/api/settings").json() == {"language": "zh"}
    assert client.put("/api/settings", json={"language": "fr"}).status_code == 422


def test_run_wording_follows_the_language_but_names_do_not(client, fake_text):
    set_language(client, "zh")
    project = new_project(client)
    run_step(client, project, "dishes", "冬天的汤", 2)
    call = fake_text.calls[-1]
    assert "请用中文写作" in call["system"]
    # The step's name is the user's text: never translated.
    assert "## 这一步：Dish brainstorming" in call["system"]
    assert call["messages"][0]["content"] == "## 要求\n冬天的汤"
    set_language(client, "en")
    run_step(client, project, "dishes", "soups", 1)
    assert fake_text.calls[-1]["messages"][0]["content"] == "## Request\nsoups"


def test_image_labels_follow_the_language(client, fake_image):
    set_language(client, "zh")
    project = new_project(client)
    source = new_node(client, project, prompt="雪地")
    wait_for_job(client, generate(client, source["id"]).json()["id"])
    edit = new_node(client, project, prompt=f"把 {source['name']} 变成夜晚")
    job = wait_for_job(client, generate(client, edit["id"]).json()["id"])
    assert job["operation"] == "image_edit"
    assert job["input"]["language"] == "zh"
    assert fake_image.requests[-1].language == "zh"
