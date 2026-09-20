from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.alerts import (
    Event,
    breakfast_alert,
    calendar_flags,
    goal_stale_alerts,
    sleep_alert,
    sleep_baseline,
    workout_gap_alert,
)

TZ = ZoneInfo("Europe/Moscow")
TODAY = date(2026, 9, 20)


def dt(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)


def sleep_entry(day: date, hours: float) -> dict:
    wake = dt(day, 8)
    return {"kind": "sleep", "ts": wake.isoformat(), "data": {"hours": hours, "sleep_end": wake.isoformat()}}


def test_sleep_alert_needs_history():
    entries = [sleep_entry(TODAY, 5.5)]
    assert sleep_alert(entries, TODAY) is not None  # short night rule
    assert sleep_baseline(entries, TODAY) is None


def test_sleep_alert_below_baseline():
    entries = [sleep_entry(TODAY - timedelta(days=i), 7.5) for i in range(1, 8)]
    entries.append(sleep_entry(TODAY, 6.2))
    msg = sleep_alert(entries, TODAY)
    assert msg and "норм" in msg


def test_sleep_ok():
    entries = [sleep_entry(TODAY - timedelta(days=i), 7.5) for i in range(1, 8)]
    entries.append(sleep_entry(TODAY, 7.3))
    assert sleep_alert(entries, TODAY) is None


def test_workout_gap():
    now = dt(TODAY, 12)
    entries = [
        {"kind": "workout", "ts": dt(TODAY - timedelta(days=4), 18).isoformat(), "data": {}},
        {"kind": "meal", "ts": dt(TODAY, 9).isoformat(), "data": {"meal_type": "breakfast"}},
    ]
    assert workout_gap_alert(entries, now) is not None
    entries.append({"kind": "workout", "ts": dt(TODAY - timedelta(days=1), 18).isoformat(), "data": {}})
    assert workout_gap_alert(entries, now) is None


def test_workout_gap_silent_for_new_user():
    now = dt(TODAY, 12)
    entries = [{"kind": "meal", "ts": dt(TODAY, 9).isoformat(), "data": {"meal_type": "breakfast"}}]
    assert workout_gap_alert(entries, now) is None


def test_breakfast_alert_window():
    entries: list[dict] = []
    assert breakfast_alert(entries, dt(TODAY, 9)) is None
    assert breakfast_alert(entries, dt(TODAY, 11, 5)) is not None
    entries.append({"kind": "meal", "ts": dt(TODAY, 8, 30).isoformat(), "data": {"meal_type": "breakfast"}})
    assert breakfast_alert(entries, dt(TODAY, 11, 5)) is None


def test_calendar_overlap_and_late():
    events = [
        Event("a", "Созвон", dt(TODAY, 10), dt(TODAY, 11)),
        Event("b", "Встреча", dt(TODAY, 10, 30), dt(TODAY, 11, 30)),
        Event("c", "Ужин с клиентом", dt(TODAY, 20, 30), dt(TODAY, 22)),
    ]
    flags = calendar_flags(events, TODAY)
    assert any("Пересечение" in f for f in flags)
    assert any("поздно" in f for f in flags)


def test_calendar_chain_and_no_deep_work():
    events = [
        Event(str(i), f"Встреча {i}", dt(TODAY, 9 + i), dt(TODAY, 10 + i)) for i in range(0, 10)
    ]
    flags = calendar_flags(events, TODAY)
    assert any("подряд" in f for f in flags)
    assert any("свободного окна" in f for f in flags)
    assert any("перегруз" in f for f in flags)


def test_calendar_quiet_day():
    events = [Event("a", "Кофе", dt(TODAY, 10), dt(TODAY, 10, 30))]
    assert calendar_flags(events, TODAY) == []


def test_goal_stale():
    now = dt(TODAY, 12)
    goals = [{"id": 1, "title": "Английский B2", "status": "active",
              "created_at": dt(TODAY - timedelta(days=10), 12).isoformat()}]
    assert goal_stale_alerts(goals, [], now)
    progress = [{"goal_id": 1, "ts": dt(TODAY - timedelta(days=1), 12).isoformat()}]
    assert goal_stale_alerts(goals, progress, now) == []


@pytest.mark.parametrize("hours", [7.0, 8.0])
def test_sleep_baseline_median(hours):
    entries = [sleep_entry(TODAY - timedelta(days=i), hours) for i in range(1, 6)]
    assert sleep_baseline(entries, TODAY) == hours
