from pathlib import Path

from app.models import AssistantOutput, CalendarAction, Question
from app.prompts import BASE_PROMPT, build_system_prompt, load_knowledge
from app.render import render_output, split_message


def test_knowledge_is_loaded_into_prompt():
    prompt = build_system_prompt()
    assert prompt.startswith(BASE_PROMPT)
    assert "planning.md" in prompt
    assert "about_me.md" in prompt
    assert "Метод Айви Ли" in prompt


def test_knowledge_missing_dir_falls_back(tmp_path: Path):
    assert load_knowledge(tmp_path / "nope") == ""
    assert build_system_prompt(tmp_path / "nope") == BASE_PROMPT


def test_render_questions_mits_and_why():
    out = AssistantOutput(
        reply="Ок",
        mits=["Эссе", "Созвон", "Зал"],
        calendar_actions=[CalendarAction(op="create", title="Эссе <черновик>",
                                         start="2026-09-21T09:00:00+03:00", end="2026-09-21T10:30:00+03:00",
                                         why="первый блок глубокой работы")],
        questions=[Question(text="Что важнее: эссе или созвон?", options=["Эссе", "Созвон"])],
        weekly_focus="Эссе к среде",
    )
    text = render_output(out, [])
    assert "Главное на день" in text and "1. Эссе" in text
    assert "&lt;черновик&gt;" in text
    assert "первый блок глубокой работы" in text
    assert "❓ Что важнее" in text
    assert "Фокус недели" in text


def test_split_message_respects_limit():
    text = "\n\n".join("абзац " * 200 for _ in range(10))
    chunks = split_message(text, limit=3000)
    assert len(chunks) > 1
    assert all(len(c) <= 3000 for c in chunks)
