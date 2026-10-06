"""Focused tests for the program, equipment rules, Hanu, and Sheets CRUD."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import hanu
import sheets
from main import app

ROOT = Path(__file__).resolve().parents[1]
CREDS = ROOT / "sam-agent-506413-b67261b92c1c.json"
client = TestClient(app)

LAT_LOGS = [
    {
        "date": "2026-09-29",
        "day_of_week": "Tuesday",
        "exercise_name": "Lat Pulldown",
        "set_number": 1,
        "weight_kg": 45,
        "reps": 12,
        "created_at": "2026-09-29T10:00:00+00:00",
    },
    {
        "date": "2026-09-29",
        "day_of_week": "Tuesday",
        "exercise_name": "Lat Pulldown",
        "set_number": 2,
        "weight_kg": 45,
        "reps": 11,
        "created_at": "2026-09-29T10:02:00+00:00",
    },
    {
        "date": "2026-09-29",
        "day_of_week": "Tuesday",
        "exercise_name": "Lat Pulldown",
        "set_number": 3,
        "weight_kg": 45,
        "reps": 10,
        "created_at": "2026-09-29T10:04:00+00:00",
    },
]


def _silence_sheets(monkeypatch, remote=None):
    payload = remote or {
        "user": {"user_id": "ram", "name": "Ram", "goal": "Build a V-shaped body"},
        "logs": [],
        "progress": [],
        "memory": [],
        "messages": [],
    }
    monkeypatch.setattr("hanu.sheets.load_user_context", lambda user_id: payload)
    monkeypatch.setattr("hanu.sheets.save_conversation_message", lambda record: record)
    monkeypatch.setattr("hanu.sheets.save_coach_memory", lambda record: record)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_today_is_the_program():
    response = client.get("/api/workouts/today", params={"plan": "schedule_3", "on": "2026-10-06"})
    assert response.status_code == 200
    body = response.json()
    assert body["day"] == "Tuesday"
    assert body["focus"] == "Pull + Core"
    assert [item["name"] for item in body["exercises"]] == [
        "Lat Pulldown",
        "Seated Row Machine",
        "Pull-Up Machine",
        "Dumbbell Bicep Curls",
    ]
    assert body["finisher"]["name"] == "Russian Twists"


def test_schedule_has_seven_days():
    response = client.get("/api/workouts/schedule", params={"plan": "schedule_3", "on": "2026-10-06"})
    assert response.status_code == 200
    body = response.json()
    assert body["plan_label"] == "V-Tapper"
    assert len(body["days"]) == 7
    assert body["days"][0]["focus"] == "Push + Core"


def test_named_day_and_rest_day():
    monday = client.get("/api/workouts/Monday", params={"plan": "schedule_3", "on": "2026-10-06"})
    assert monday.status_code == 200
    assert monday.json()["focus"] == "Push + Core"
    wednesday = client.get("/api/workouts/Wednesday", params={"plan": "schedule_3", "on": "2026-10-07"})
    assert wednesday.json()["is_rest_day"] is True
    missing = client.get("/api/workouts/notaday")
    assert missing.status_code == 404


def test_log_endpoint_contract(monkeypatch):
    captured = {}

    def fake_save(record):
        captured.update(record)
        return {
            **record,
            "log_id": "log1",
            "created_at": "2026-10-06T12:00:00+00:00",
            "notes": record.get("notes") or "",
        }

    monkeypatch.setattr("api.sheets.save_workout_log", fake_save)
    response = client.post(
        "/api/workouts/log",
        headers={"X-User-Id": "ram", "X-Client-Date": "2026-10-06"},
        json={"exercise_name": "Lat Pulldown", "set_number": 1, "weight_kg": 45, "reps": 12},
    )
    assert response.status_code == 200
    assert captured["exercise_name"] == "Lat Pulldown"
    assert captured["weight_kg"] == 45
    assert captured["date"] == "2026-10-06"
    assert captured["day_of_week"] == "Tuesday"


def test_log_validation_is_not_a_server_error():
    response = client.post("/api/workouts/log", json={"exercise_name": "", "set_number": 0})
    assert response.status_code == 422


def test_today_chat_uses_the_real_schedule(monkeypatch):
    _silence_sheets(monkeypatch)
    result = hanu.chat(
        user_id="ram",
        message="What should I do today?",
        context={"plan": "schedule_3"},
        on_date=date(2026, 10, 6),
        persist=False,
    )
    assert result["clarification_needed"] is False
    assert result["intent"] == "today"
    text = result["message"]
    assert "Lat Pulldown" in text
    assert "Seated Row Machine" in text
    assert "Pull" in text
    assert "Russian Twists" in text


def test_cable_rows_are_rejected(monkeypatch):
    _silence_sheets(monkeypatch)
    result = hanu.chat(
        user_id="ram",
        message="Can I use cable rows instead?",
        context={"plan": "schedule_3", "current_exercise": "Seated Row Machine"},
        on_date=date(2026, 10, 6),
        persist=False,
    )
    text = result["message"].lower()
    assert result["clarification_needed"] is False
    assert "cable" in text
    assert "tricep" in text
    assert "row" in text
    assert "yes" not in text.split(".")[0]


def test_barbell_squat_is_rejected():
    reason = hanu.equipment_block_reason("barbell squats")
    assert reason
    assert "bench press" in reason.lower()


def test_replace_incline_uses_the_program_alternative(monkeypatch):
    _silence_sheets(monkeypatch)
    result = hanu.chat(
        user_id="ram",
        message="Can I replace incline dumbbell press?",
        context={"plan": "schedule_3", "current_day": "Monday"},
        on_date=date(2026, 10, 5),
        persist=False,
    )
    assert result["clarification_needed"] is False
    assert "pec deck" in result["message"].lower()


def test_weight_uses_logged_sets(monkeypatch):
    _silence_sheets(
        monkeypatch,
        {
            "user": {"user_id": "ram", "name": "Ram", "goal": "Build a V-shaped body"},
            "logs": LAT_LOGS,
            "progress": [],
            "memory": [],
            "messages": [],
        },
    )
    result = hanu.chat(
        user_id="ram",
        message="What weight should I use?",
        context={"plan": "schedule_3", "current_exercise": "Lat Pulldown"},
        on_date=date(2026, 10, 6),
        persist=False,
    )
    text = result["message"]
    assert result["intent"] == "progression"
    assert "45" in text
    assert "33" in text
    assert "12/12/12" in text or "12/12/12" in text.replace(" ", "")


def test_weight_without_history_does_not_invent_one(monkeypatch):
    _silence_sheets(monkeypatch)
    result = hanu.chat(
        user_id="ram",
        message="What weight should I use for lat pulldown?",
        context={"plan": "schedule_3"},
        on_date=date(2026, 10, 6),
        persist=False,
    )
    assert "no previous weight" in result["message"].lower()


def test_exercise_name_continues_the_weight_question(monkeypatch):
    _silence_sheets(
        monkeypatch,
        {
            "user": {"user_id": "ram", "name": "Ram", "goal": "Build a V-shaped body"},
            "logs": LAT_LOGS,
            "progress": [],
            "memory": [],
            "messages": [],
        },
    )
    result = hanu.chat(
        user_id="ram",
        message="Latpull down",
        context={"plan": "schedule_3", "current_day": "Tuesday"},
        on_date=date(2026, 10, 6),
        persist=False,
        recent_messages=[
            {"role": "user", "message": "What weight should I use?"},
            {"role": "assistant", "message": "Which exercise? I'll use your log if it's there."},
        ],
    )
    text = result["message"].lower()
    assert result["intent"] == "progression"
    assert "what's up" not in text
    assert "lat pulldown" in text
    assert "45" in result["message"]


def test_pain_asks_a_useful_question(monkeypatch):
    _silence_sheets(monkeypatch)
    result = hanu.chat(
        user_id="ram",
        message="My shoulder hurts during shoulder press.",
        context={"plan": "schedule_3", "current_exercise": "Dumbbell Shoulder Press"},
        on_date=date(2026, 10, 5),
        persist=False,
    )
    assert result["clarification_needed"] is True
    assert result["intent"] == "pain"
    assert "sharp" in result["message"].lower()


def test_shorten_does_not_need_a_model(monkeypatch):
    _silence_sheets(monkeypatch)
    result = hanu.chat(
        user_id="ram",
        message="Make today's workout shorter",
        context={"plan": "schedule_3"},
        on_date=date(2026, 10, 6),
        persist=False,
    )
    assert "Lat Pulldown" in result["message"]
    assert "finisher" in result["message"].lower()


@pytest.mark.skipif(not CREDS.exists(), reason="Google service account file is not on disk")
def test_sheets_crud_roundtrip():
    user_id = "fftest_crud"
    try:
        sheets.delete_user_data(user_id)
        created = sheets.save_user(
            {
                "user_id": user_id,
                "name": "Test User",
                "age": 30,
                "height_cm": 180,
                "weight_kg": 75,
                "goal": "Lose weight",
            }
        )
        assert created["name"] == "Test User"
        loaded = sheets.get_user(user_id)
        assert loaded["goal"] == "Lose weight"
        assert loaded["age"] == 30

        updated = sheets.save_user({**loaded, "goal": "Build a V-shaped body"})
        assert updated["goal"] == "Build a V-shaped body"
        assert sheets.get_user(user_id)["name"] == "Test User"

        log_row = sheets.save_workout_log(
            {
                "user_id": user_id,
                "date": "2026-10-06",
                "day_of_week": "Tuesday",
                "exercise_name": "Lat Pulldown",
                "set_number": 1,
                "weight_kg": 45,
                "reps": 12,
            }
        )
        history = sheets.get_workout_logs(user_id, "Lat Pulldown")
        assert len(history) == 1
        assert history[0]["weight_kg"] == 45
        assert history[0]["log_id"] == log_row["log_id"]

        progress = sheets.save_progress(
            {"user_id": user_id, "date": "2026-10-06", "weight_kg": 75, "waist_cm": 80, "notes": ""}
        )
        assert sheets.get_progress(user_id)[0]["progress_id"] == progress["progress_id"]

        message = sheets.save_conversation_message(
            {
                "user_id": user_id,
                "conversation_id": "conv1",
                "role": "user",
                "message": "What should I do today?",
            }
        )
        convo = sheets.get_conversation(user_id, "conv1")
        assert convo[0]["message_id"] == message["message_id"]

        memory = sheets.save_coach_memory(
            {
                "user_id": user_id,
                "category": "preference",
                "memory": "User prefers shorter workouts.",
                "importance": 2,
            }
        )
        assert sheets.get_coach_memory(user_id)[0]["memory_id"] == memory["memory_id"]
    finally:
        sheets.delete_user_data(user_id)

    assert sheets.get_user(user_id) is None
    assert sheets.get_workout_logs(user_id) == []


@pytest.mark.skipif(not CREDS.exists(), reason="Google service account file is not on disk")
def test_log_and_history_endpoints():
    user_id = "fftest_api"
    headers = {"X-User-Id": user_id, "X-Client-Date": "2026-10-06"}
    try:
        sheets.delete_user_data(user_id)
        saved = client.put(
            "/api/user",
            headers=headers,
            json={"name": "API User", "age": 28, "goal": "Build a V-shaped body"},
        )
        assert saved.status_code == 200
        assert saved.json()["saved"] is True

        logged = client.post(
            "/api/workouts/log",
            headers=headers,
            json={"exercise_name": "Lat Pulldown", "set_number": 1, "weight_kg": 40, "reps": 10},
        )
        assert logged.status_code == 200, logged.text

        history = client.get("/api/workouts/history/Lat Pulldown", headers=headers, params={"plan": "schedule_3"})
        assert history.status_code == 200, history.text
        body = history.json()
        assert body["sessions"][0]["sets"][0]["weight_kg"] == 40
        assert "no previous weight" not in body["suggestion"].lower()

        overview = client.get("/api/progress", headers=headers, params={"plan": "schedule_3", "on": "2026-10-06"})
        assert overview.status_code == 200
        assert overview.json()["consistency"]["expected"] >= 1
    finally:
        sheets.delete_user_data(user_id)
