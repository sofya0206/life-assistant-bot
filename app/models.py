"""Структура ответа LLM. Плоские модели без dict-полей — так схема
гарантированно проходит через structured outputs и у Claude, и у Gemini.

Правило: записи (entries) применяются сразу, а calendar/task/goal-действия
ждут подтверждения кнопкой — они трогают внешние сервисы.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntryKind = Literal["sleep", "meal", "workout", "mood", "weight", "water", "steps", "symptom", "note"]


class LogEntry(BaseModel):
    kind: EntryKind
    time: str | None = Field(default=None, description="ISO 8601 с оффсетом; для сна — время пробуждения")
    sleep_start: str | None = None
    sleep_end: str | None = None
    hours: float | None = None
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    description: str | None = None
    minutes: int | None = None
    intensity: Literal["low", "medium", "high"] | None = None
    score: int | None = Field(default=None, description="настроение 1–10, качество сна 1–5, полезность еды 1–5")
    value: float | None = None
    unit: str | None = None


class CalendarAction(BaseModel):
    op: Literal["create", "move", "delete"]
    source: Literal["google", "calcom"] = "google"
    title: str
    start: str | None = Field(default=None, description="ISO 8601 с оффсетом")
    end: str | None = None
    event_id: str | None = Field(default=None, description="id из контекста для move/delete")
    note: str | None = None
    why: str | None = Field(default=None, description="одна фраза: почему именно это время")


class TaskAction(BaseModel):
    op: Literal["create", "complete"]
    content: str
    due: str | None = Field(default=None, description="срок: 'завтра', 'в среду 15:00' или YYYY-MM-DD")
    priority: int | None = Field(default=None, description="1 обычный … 4 срочный")
    task_id: str | None = None


class SmartGoal(BaseModel):
    title: str
    specific: str
    measurable: str
    achievable: str
    relevant: str
    time_bound: str
    deadline: str | None = Field(default=None, description="YYYY-MM-DD")
    milestones: list[str] = Field(default_factory=list)
    weekly_actions: list[str] = Field(default_factory=list)


class GoalProgress(BaseModel):
    goal_id: int
    note: str
    value: float | None = None


class Question(BaseModel):
    text: str = Field(description="один короткий вопрос с рекомендацией внутри")
    options: list[str] = Field(default_factory=list, description="2–3 варианта ответа, первый — рекомендуемый")


class AssistantOutput(BaseModel):
    reply: str = Field(description="короткий ответ пользователю на русском")
    entries: list[LogEntry] = Field(default_factory=list)
    calendar_actions: list[CalendarAction] = Field(default_factory=list)
    task_actions: list[TaskAction] = Field(default_factory=list)
    goals: list[SmartGoal] = Field(default_factory=list)
    goal_progress: list[GoalProgress] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    mits: list[str] = Field(default_factory=list, description="до 3 главных дел дня, если запрос про план дня")
    weekly_focus: str | None = Field(default=None, description="главный приоритет недели, только если Соня его явно выбрала")

    @property
    def has_external_actions(self) -> bool:
        return bool(self.calendar_actions or self.task_actions or self.goals or self.goal_progress)
