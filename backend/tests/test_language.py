"""The language setting is the UI's only: what the model is told is the
same English wording whatever it is, with the user's own words tagged, and
the model writes in the language of those words."""

from __future__ import annotations

from canvas_api.domain.workflow import image_label

from .helpers import run_step
from .test_api import new_project


def set_language(client, language: str):
    response = client.put("/api/settings", json={"language": language})
    assert response.status_code == 200, response.text
    return response.json()


def test_language_defaults_to_english_and_is_remembered(client):
    assert client.get("/api/settings").json() == {"language": "en"}
    assert set_language(client, "zh") == {"language": "zh"}
    assert client.get("/api/settings").json() == {"language": "zh"}
    assert client.put("/api/settings", json={"language": "fr"}).status_code == 422


def test_the_setting_does_not_change_what_the_model_is_told(client, fake_text):
    project = new_project(client)
    run_step(client, project, "dishes", "冬天的汤", 2)
    english = fake_text.calls[-1]
    set_language(client, "zh")
    run_step(client, project, "dishes", "冬天的汤", 2)
    chinese = fake_text.calls[-1]
    assert english["system"] == chinese["system"]
    assert english["messages"] == chinese["messages"]

    system = chinese["system"]
    # The user's words are tagged, and the model writes in their language.
    assert "write every result, and every `id`, in the language and script" in system
    # The step's name is the user's text: never translated.
    assert "This step is called “Dish brainstorming” and makes texts." in system
    assert chinese["messages"][0]["content"] == "<request>\n冬天的汤\n</request>"


def test_image_labels_follow_the_prompts_script():
    assert image_label(1, "把 雪地 变成夜晚") == "图片1"
    assert image_label(2, "turn the snow to night") == "image 2"
    assert image_label(3) == "image 3"
