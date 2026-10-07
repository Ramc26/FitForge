"""HTTP API. Every endpoint lives in this file."""

from __future__ import annotations

import logging
import re
from datetime import date

from fastapi import APIRouter, Header, HTTPException, Query

import config
import hanu
import sheets
from models import (
    CoachMessage,
    CoachRequest,
    CoachResponse,
    ExerciseHistory,
    HistoryResponse,
    ProgressCreate,
    ProgressEntry,
    ProgressOverview,
    ScheduleResponse,
    UserProfile,
    UserUpdate,
    WorkoutDay,
    WorkoutLog,
    WorkoutLogCreate,
)

log = logging.getLogger("fitforge.api")
router = APIRouter()

_USER_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _user_id(header: str | None) -> str:
    raw = (header or config.DEFAULT_USER_ID).strip()
    if not _USER_ID.fullmatch(raw):
        raise HTTPException(status_code=400, detail="That user id isn't valid.")
    return raw


def _on_date(header: str | None, explicit: str | None) -> date:
    return hanu.parse_date(explicit or header)


def _plan(plan: str | None) -> str:
    chosen = plan or config.DEFAULT_PLAN
    if chosen not in hanu.PLAN_LABELS:
        raise HTTPException(status_code=400, detail="That workout plan doesn't exist.")
    return chosen


def _sheets(action):
    try:
        return action()
    except sheets.SheetsError:
        log.warning("Sheets request failed", exc_info=True)
        return None


def _require_sheets(action, detail: str):
    try:
        return action()
    except sheets.SheetsError as exc:
        log.warning("Sheets request failed", exc_info=True)
        reason = str(exc).strip()
        raise HTTPException(status_code=503, detail=reason or detail) from None


def _equipment(user_id: str) -> list[str]:
    try:
        memory = sheets.get_coach_memory(user_id)
    except sheets.SheetsError:
        return list(hanu.DEFAULT_EQUIPMENT)
    for item in reversed(memory):
        if item.get("category") != "equipment":
            continue
        try:
            import json

            parsed = json.loads(item.get("memory") or "")
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list) and parsed:
            return [str(piece) for piece in parsed]
    return list(hanu.DEFAULT_EQUIPMENT)


def _preferences(user_id: str) -> str:
    try:
        memory = sheets.get_coach_memory(user_id)
    except sheets.SheetsError:
        return ""
    notes = [item.get("memory") or "" for item in memory if item.get("category") == "preference"]
    return notes[-1] if notes else ""


def _profile(user_id: str, row: dict | None) -> UserProfile:
    base = row or {
        "user_id": user_id,
        "name": "Ram",
        "age": None,
        "height_cm": None,
        "weight_kg": None,
        "goal": "Build a V-shaped body",
        "created_at": None,
        "updated_at": None,
    }
    return UserProfile(
        user_id=user_id,
        name=base.get("name") or "Ram",
        age=base.get("age"),
        height_cm=base.get("height_cm"),
        weight_kg=base.get("weight_kg"),
        goal=base.get("goal") or "Build a V-shaped body",
        created_at=base.get("created_at") or None,
        updated_at=base.get("updated_at") or None,
        saved=row is not None,
        equipment=_equipment(user_id),
        equipment_rules=list(hanu.EQUIPMENT_RULES),
        preferences=_preferences(user_id),
    )


@router.get("/health")
def health():
    return {"status": "ok", "app": "fitforge"}


@router.get("/user", response_model=UserProfile)
def get_user(x_user_id: str | None = Header(default=None)):
    user_id = _user_id(x_user_id)
    row = _sheets(lambda: sheets.get_user(user_id))
    return _profile(user_id, row)


@router.put("/user", response_model=UserProfile)
def put_user(body: UserUpdate, x_user_id: str | None = Header(default=None)):
    user_id = _user_id(x_user_id)
    current = _require_sheets(
        lambda: sheets.get_user(user_id),
        "FitForge couldn't load your profile. Try again.",
    ) or {
        "user_id": user_id,
        "name": "Ram",
        "goal": "Build a V-shaped body",
    }
    updates = body.model_dump(exclude_unset=True)
    for field in ("name", "age", "height_cm", "weight_kg", "goal"):
        if field in updates and updates[field] is not None:
            current[field] = updates[field]
    current["user_id"] = user_id
    saved = _require_sheets(
        lambda: sheets.save_user(current),
        "FitForge couldn't save your profile. Try again.",
    )
    if "equipment" in updates and updates["equipment"] is not None:
        import json

        _require_sheets(
            lambda: sheets.save_coach_memory(
                {
                    "user_id": user_id,
                    "category": "equipment",
                    "memory": json.dumps(updates["equipment"]),
                    "importance": 3,
                }
            ),
            "FitForge couldn't save your profile. Try again.",
        )
    if updates.get("preferences"):
        _require_sheets(
            lambda: sheets.save_coach_memory(
                {
                    "user_id": user_id,
                    "category": "preference",
                    "memory": updates["preferences"].strip(),
                    "importance": 2,
                }
            ),
            "FitForge couldn't save your profile. Try again.",
        )
    return _profile(user_id, saved)


@router.get("/workouts/today", response_model=WorkoutDay)
def workout_today(
    plan: str | None = None,
    on: str | None = None,
    x_client_date: str | None = Header(default=None),
):
    chosen = _plan(plan)
    today = _on_date(x_client_date, on)
    payload = hanu.get_today_workout(chosen, today)
    if payload is None:
        raise HTTPException(status_code=404, detail="No workout is scheduled for that day.")
    return payload


@router.get("/workouts/schedule", response_model=ScheduleResponse)
def workout_schedule(
    plan: str | None = None,
    on: str | None = None,
    x_client_date: str | None = Header(default=None),
):
    chosen = _plan(plan)
    today = _on_date(x_client_date, on)
    days = []
    for name in hanu.DAY_NAMES:
        # Date of that weekday in the same Monday-Sunday week as `today`.
        delta = hanu.DAY_NAMES.index(name) - today.weekday()
        payload = hanu.get_workout(chosen, name, today.fromordinal(today.toordinal() + delta))
        if payload:
            days.append(payload)
    return {
        "plan": chosen,
        "plan_label": hanu.PLAN_LABELS[chosen],
        "plans": [{"key": key, "label": label} for key, label in hanu.PLAN_LABELS.items()],
        "days": days,
    }


@router.get("/workouts/history", response_model=HistoryResponse)
def workout_history(x_user_id: str | None = Header(default=None)):
    user_id = _user_id(x_user_id)
    logs = _require_sheets(
        lambda: sheets.get_workout_logs(user_id),
        "FitForge couldn't load your history. Try again.",
    )
    return {"logs": logs[-200:], "recent_sessions": hanu.recent_sessions(logs)}


@router.get("/workouts/history/{exercise_name}", response_model=ExerciseHistory)
def exercise_history(
    exercise_name: str,
    plan: str | None = None,
    x_user_id: str | None = Header(default=None),
):
    user_id = _user_id(x_user_id)
    chosen = _plan(plan)
    logs = _require_sheets(
        lambda: sheets.get_workout_logs(user_id),
        "FitForge couldn't load your history. Try again.",
    )
    return hanu.exercise_history(exercise_name, logs, chosen)


@router.get("/workouts/{day}", response_model=WorkoutDay)
def workout_day(
    day: str,
    plan: str | None = None,
    on: str | None = None,
    x_client_date: str | None = Header(default=None),
):
    chosen = _plan(plan)
    today = _on_date(x_client_date, on)
    name = day.strip().capitalize()
    if name not in hanu.DAY_NAMES:
        raise HTTPException(status_code=404, detail="That isn't a day in the program.")
    payload = hanu.get_workout(chosen, name, today)
    if payload is None:
        raise HTTPException(status_code=404, detail="No workout is scheduled for that day.")
    return payload


@router.post("/workouts/log", response_model=WorkoutLog)
def log_workout(
    body: WorkoutLogCreate,
    x_user_id: str | None = Header(default=None),
    x_client_date: str | None = Header(default=None),
):
    user_id = _user_id(x_user_id)
    logged_on = hanu.parse_date(body.date or x_client_date)
    record = body.model_dump()
    record["user_id"] = user_id
    record["date"] = logged_on.isoformat()
    record["day_of_week"] = body.day_of_week or hanu.weekday_name(logged_on)
    saved = _require_sheets(
        lambda: sheets.save_workout_log(record),
        "FitForge couldn't save your workout. Try again.",
    )
    return saved


@router.get("/progress", response_model=ProgressOverview)
def get_progress(
    plan: str | None = None,
    on: str | None = None,
    x_user_id: str | None = Header(default=None),
    x_client_date: str | None = Header(default=None),
):
    user_id = _user_id(x_user_id)
    chosen = _plan(plan)
    today = _on_date(x_client_date, on)

    def load():
        return sheets.load_user_context(user_id)

    remote = _require_sheets(load, "FitForge couldn't load your progress. Try again.")
    return hanu.build_progress_overview(
        remote.get("user"),
        remote.get("logs") or [],
        remote.get("progress") or [],
        chosen,
        today,
    )


@router.post("/progress", response_model=ProgressEntry)
def add_progress(
    body: ProgressCreate,
    x_user_id: str | None = Header(default=None),
    x_client_date: str | None = Header(default=None),
):
    user_id = _user_id(x_user_id)
    if body.weight_kg is None and body.waist_cm is None:
        raise HTTPException(status_code=400, detail="Add a weight or a waist measurement.")
    record = body.model_dump()
    record["user_id"] = user_id
    record["date"] = hanu.parse_date(body.date or x_client_date).isoformat()
    saved = _require_sheets(
        lambda: sheets.save_progress(record),
        "FitForge couldn't save your progress. Try again.",
    )
    return saved


@router.post("/coach/chat", response_model=CoachResponse)
def coach_chat(
    body: CoachRequest,
    x_user_id: str | None = Header(default=None),
    x_client_date: str | None = Header(default=None),
):
    user_id = _user_id(x_user_id)
    context = body.context.model_dump() if body.context else {}
    try:
        result = hanu.chat(
            user_id=user_id,
            message=body.message,
            conversation_id=body.conversation_id,
            context=context,
            on_date=_on_date(x_client_date, None),
            persist=True,
            recent_messages=[item.model_dump() for item in body.recent_messages],
            recent_logs=[item.model_dump() for item in body.recent_logs],
        )
    except Exception:
        log.warning("Hanu failed", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Hanu is taking a break. Try again in a moment.",
        ) from None
    return result


@router.get("/coach/history", response_model=list[CoachMessage])
def coach_history(
    conversation_id: str | None = Query(default=None),
    x_user_id: str | None = Header(default=None),
):
    user_id = _user_id(x_user_id)
    rows = _require_sheets(
        lambda: sheets.get_conversation(user_id, conversation_id),
        "FitForge couldn't load that conversation. Try again.",
    )
    return rows[-100:]
