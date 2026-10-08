"""Hanu, FitForge's coach. One graph, one file.

Deterministic questions (today's workout, weights, swaps, equipment) are answered
in Python. OpenAI is only used when the reply actually needs conversation.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import config
import sheets

log = logging.getLogger("fitforge.hanu")

PLAN_LABELS = {
    "schedule": "Classic Split",
    "schedule_2": "Enhanced Split",
    "schedule_3": "V-Tapper",
}

DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

DEFAULT_EQUIPMENT = [
    "dumbbells",
    "bench",
    "lat_machine",
    "barbell",
    "cable",
    "pec_deck",
    "seated_row",
    "pullup_machine",
]

EQUIPMENT_RULES = [
    "Lat machine: lat and back-width work only.",
    "Barbell: bench press only.",
    "Cable machine: triceps only.",
]

SYSTEM_PROMPT = """You are Hanu, the user's personal gym coach inside FitForge.

Help them follow their program, progress, and make practical training calls.
Use the facts in the user message. Never invent a weight, a session, or a set.
Never say an exercise was done if no log is included.
Do not add random exercises. Prefer the program as written.
The user's look is a V-taper: wider lats, bigger side and rear delts, stronger upper chest, bigger arms, smaller waist.
Do not claim an exercise burns belly fat.
Do not diagnose pain. For sharp, persistent, worsening, or worrying pain, tell them to get a medical opinion.
Ask a question only when you truly cannot answer without it.
Talk like a coach on the gym floor: short, casual, confident, a little witty. No corporate tone. No essay.

Equipment that must be respected:
- Dumbbells, bench, lat machine, barbell, cable machine, pec deck, seated row machine, pull-up machine.
- Lat machine is only for lat and back-width work.
- Barbell is only for bench press.
- Cable machine is only for triceps.
Never recommend barbell rows, barbell squats, barbell RDLs, cable rows, cable curls, cable laterals, or cable lat pulldowns.

Return JSON with message, intent, clarification_needed, suggested_actions, and memory.
memory must be empty unless there is a lasting training preference. If you store one, start it with "User ".
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "message": {"type": "string"},
        "intent": {"type": "string"},
        "clarification_needed": {"type": "boolean"},
        "suggested_actions": {"type": "array", "items": {"type": "string"}},
        "memory": {"type": "string"},
    },
    "required": ["message", "intent", "clarification_needed", "suggested_actions", "memory"],
}

_program_cache: dict = {"mtime": None, "data": None}
_graph = None


class HanuState(TypedDict, total=False):
    user_id: str
    conversation_id: str
    user_message: str
    intent: str
    context: dict
    on_date: str
    persist: bool
    user_profile: dict
    today_workout: dict
    recent_workouts: list
    exercise_history: list
    all_logs: list
    progress: list
    memory: list
    history_messages: list
    client_history: list
    client_logs: list
    target_exercise: str
    equipment: list
    clarification_needed: bool
    clarification_question: str
    response: str
    suggested_actions: list
    new_memory: str


def norm(name: str) -> str:
    return " ".join(str(name or "").casefold().replace("-", " ").split())


def compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(name))


def load_program() -> dict:
    path = config.DATA_JSON
    mtime = path.stat().st_mtime
    if _program_cache["data"] is not None and _program_cache["mtime"] == mtime:
        return _program_cache["data"]
    data = json.loads(path.read_text())
    _program_cache["mtime"] = mtime
    _program_cache["data"] = data
    return data


def weekday_name(day: date) -> str:
    return DAY_NAMES[day.weekday()]


def parse_date(value: str | None, fallback: date | None = None) -> date:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return fallback or date.today()


def _schedule(program: dict, plan: str) -> list[dict]:
    days = program.get(plan) or program.get(config.DEFAULT_PLAN) or []
    return days if isinstance(days, list) else []


def _day_dict(plan: str, day_name: str) -> dict | None:
    for day in _schedule(load_program(), plan):
        if day.get("day_of_week") == day_name:
            return day
    return None


def estimate_minutes(day: dict) -> int:
    if day.get("is_rest_day"):
        return 0
    total = 5 * 60
    blocks = list(day.get("exercises") or [])
    if day.get("finisher"):
        blocks.append(day["finisher"])
    for exercise in blocks:
        reps = str(exercise.get("reps") or "")
        if "minute" in reps.lower():
            nums = [int(item) for item in re.findall(r"\d+", reps)]
            total += (max(nums) if nums else 20) * 60
            continue
        if exercise.get("duration_minutes"):
            total += int(exercise["duration_minutes"]) * 60
            continue
        sets = int(exercise.get("sets") or 1)
        rest = int(exercise.get("rest_seconds") or 60)
        total += sets * (45 + rest) + 60
    return max(1, round(total / 60))


def coach_nudge(day: dict) -> str:
    if day.get("is_rest_day"):
        return "Rest is part of the program. Walk if you want, then leave the gym alone."
    focus = (day.get("focus") or "").lower()
    if "pull" in focus or "back" in focus:
        return "Let's make your back wider today."
    if "push" in focus or "chest" in focus:
        return "Upper chest and shoulders today. Build the shelf."
    if "leg" in focus:
        return "Leg day. Smooth reps, full range."
    if "v-taper" in focus or "upper" in focus:
        return "Width day. Lats and side delts come first."
    if "cardio" in focus:
        return "Optional work. Walk, brace the core, or take the rest if you're cooked."
    return "Train what's on the card. Leave a little in the tank."


def _exercise_payload(raw: dict | None) -> dict | None:
    if not raw:
        return None
    payload = {
        "name": raw.get("name") or "Exercise",
        "sets": raw.get("sets"),
        "reps": raw.get("reps"),
        "log": raw.get("log"),
        "rest_seconds": raw.get("rest_seconds"),
        "anatomy_pov": raw.get("anatomy_pov"),
        "form": raw.get("form"),
        "machine_alternative": raw.get("machine_alternative"),
        "duration_minutes": raw.get("duration_minutes"),
    }
    if payload["sets"] is not None:
        payload["sets"] = int(payload["sets"])
    if payload["rest_seconds"] is not None:
        payload["rest_seconds"] = int(payload["rest_seconds"])
    if payload["duration_minutes"] is not None:
        payload["duration_minutes"] = int(payload["duration_minutes"])
    return payload


def build_workout(plan: str, day_name: str, on: date) -> dict | None:
    raw = _day_dict(plan, day_name)
    if raw is None:
        return None
    exercises = [_exercise_payload(item) for item in raw.get("exercises") or []]
    optional = [_exercise_payload(item) for item in raw.get("optional_exercises") or []]
    return {
        "plan": plan,
        "plan_label": PLAN_LABELS.get(plan, plan),
        "day": day_name,
        "date": on.isoformat(),
        "focus": raw.get("focus") or "",
        "is_rest_day": bool(raw.get("is_rest_day")),
        "notes": raw.get("notes") or "",
        "exercises": exercises,
        "optional_exercises": optional,
        "finisher": _exercise_payload(raw.get("finisher")),
        "exercise_count": len(exercises),
        "estimated_minutes": estimate_minutes(raw),
        "coach_nudge": coach_nudge(raw),
    }


def get_today_workout(plan: str, on: date) -> dict | None:
    return build_workout(plan, weekday_name(on), on)


def get_workout(plan: str, day_name: str, on: date) -> dict | None:
    return build_workout(plan, day_name, on)


def iter_exercises(day: dict) -> list[dict]:
    items = list(day.get("exercises") or [])
    items.extend(day.get("optional_exercises") or [])
    if day.get("finisher"):
        items.append(day["finisher"])
    return items


def find_exercise(name: str | None, plan: str) -> dict | None:
    if not name:
        return None
    wanted = norm(name)
    program = load_program()
    plans = [plan] + [key for key in PLAN_LABELS if key != plan]

    def search(days: list[dict]) -> dict | None:
        catalog = []
        for day in days:
            catalog.extend(iter_exercises(day))
        exact = [item for item in catalog if norm(item.get("name")) == wanted]
        if exact:
            return exact[0]
        wanted_compact = compact(name)
        if len(wanted_compact) >= 5:
            same = [item for item in catalog if compact(item.get("name")) == wanted_compact]
            if same:
                return same[0]
            partial = [
                item
                for item in catalog
                if wanted_compact in compact(item.get("name"))
            ]
            if partial:
                partial.sort(key=lambda item: len(item.get("name") or ""), reverse=True)
                return partial[0]
        hits = [
            item
            for item in catalog
            if wanted in norm(item.get("name")) or norm(item.get("name")) in wanted
        ]
        if not hits:
            return None
        hits.sort(key=lambda item: len(item.get("name") or ""), reverse=True)
        return hits[0]

    for key in plans:
        found = search(_schedule(program, key))
        if found:
            return found
    return None


def parse_rep_range(reps: str | None) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*-\s*(\d+)", reps or "")
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)", reps or "")
    if match:
        number = int(match.group(1))
        return number, number
    return None, None


def _sessions(exercise: str, logs: list[dict]) -> list[dict]:
    wanted = norm(exercise)
    grouped: dict[str, dict] = {}
    for row in logs:
        if norm(row.get("exercise_name")) != wanted:
            continue
        bucket = grouped.setdefault(
            row.get("date") or "",
            {"date": row.get("date") or "", "day_of_week": row.get("day_of_week") or "", "sets": {}},
        )
        set_number = int(row.get("set_number") or 0)
        current = bucket["sets"].get(set_number)
        if current is None or (row.get("created_at") or "") >= (current.get("created_at") or ""):
            bucket["sets"][set_number] = row
    sessions = []
    for day in sorted(grouped):
        sets = [grouped[day]["sets"][key] for key in sorted(grouped[day]["sets"])]
        sessions.append(
            {
                "date": grouped[day]["date"],
                "day_of_week": grouped[day]["day_of_week"],
                "sets": sets,
            }
        )
    return sessions


def progression_advice(exercise: str, logs: list[dict], reps_text: str | None = None) -> str:
    sessions = _sessions(exercise, logs)
    if not sessions:
        return (
            f"There's no previous weight recorded yet for {exercise}. "
            "Start with a weight you can control for 8-12 clean reps."
        )
    last = sessions[-1]
    sets = last["sets"]
    weights = [set_row.get("weight_kg") for set_row in sets if set_row.get("weight_kg") not in (None, "")]
    reps = [int(set_row.get("reps") or 0) for set_row in sets]
    if not weights:
        return (
            f"Last time on {exercise} didn't have a weight logged. "
            "Start with a weight you can control for 8-12 clean reps."
        )
    weight = weights[0]
    total = sum(reps)
    low, high = parse_rep_range(reps_text)
    high = high or 12
    low = low or 8
    rep_text = " / ".join(str(rep) for rep in reps) if reps else "no reps"
    top = "/".join([str(high)] * max(len(reps), 1))
    weight_text = f"{weight:g}"
    if reps and all(rep >= high for rep in reps):
        return (
            f"You earned a bump on {exercise}. Last time was {weight_text}kg for {rep_text}. "
            f"Add a little weight today and work back through {low}-{high}."
        )
    return (
        f"Stay at {weight_text}kg today on {exercise}. "
        f"Last time you got {rep_text}. Try to beat {total} total reps. "
        f"If you hit {top} cleanly, move up next session."
    )


def equipment_block_reason(name: str, equipment: list[str] | None = None) -> str | None:
    owned = set(equipment or DEFAULT_EQUIPMENT)
    text = norm(name)
    if "cable" in text:
        if "cable" not in owned:
            return "The cable machine isn't on your equipment list."
        if any(token in text for token in ("tricep", "pushdown", "push down")):
            return None
        return (
            "Your cable machine is only for triceps work, like pushdowns. "
            "Skip cable rows, curls, laterals, and cable lat pulldowns."
        )
    if text in {"bench press", "flat bench press"} or ("barbell" in text) or text.startswith("bb "):
        if "barbell" not in owned or "bench" not in owned:
            return "Barbell bench isn't on your equipment list."
        if "bench" in text:
            return None
        return "Your barbell is only for bench press. No barbell rows, squats, or RDLs."
    if "pulldown" in text or "lat machine" in text:
        if "lat_machine" not in owned:
            return "The lat machine isn't on your equipment list."
        if any(token in text for token in ("curl", "row", "squat", "press", "raise", "extension", "fly")):
            return "The lat machine is only for lat and back-width work."
        return None
    if "pec deck" in text or "reverse pec" in text:
        if "pec_deck" not in owned:
            return "The pec deck isn't on your equipment list."
        return None
    if "seated row" in text:
        if "seated_row" not in owned:
            return "The seated row machine isn't on your equipment list."
        return None
    if "pull up" in text or "pullup" in text:
        if "pullup_machine" not in owned:
            return "The pull-up machine isn't on your equipment list."
        return None
    if "dumbbell" in text or text.startswith("db "):
        if "dumbbells" not in owned:
            return "Dumbbells aren't on your equipment list."
        return None
    banned = ("leg press", "smith", "hack squat", "leg curl", "leg extension", "chest press machine")
    if any(token in text for token in banned):
        return (
            "That machine isn't in your gym. Stay with dumbbells, the bench, the lat machine, "
            "barbell bench press, cable triceps, the pec deck, seated row, and the pull-up machine."
        )
    return None


def _proposal(message: str) -> str | None:
    text = message.strip().rstrip("?.!")
    patterns = [
        r"(?:use|try|do)\s+(.+?)\s+instead\b",
        r"replace\s+.+?\s+with\s+(.+)$",
        r"swap\s+.+?\s+(?:for|with)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        proposal = match.group(1).strip(" ?.!")
        if proposal and proposal.casefold() not in {"it", "this", "that"}:
            return proposal
    return None


def _target(message: str) -> str | None:
    proposal = _proposal(message)
    if proposal:
        match = re.search(r"replace\s+(.+?)\s+with\s+", message, flags=re.I)
        if match:
            return match.group(1).strip(" ?.!")
        return None
    match = re.search(r"(?:replace|swap|substitute)\s+(?:the\s+)?(.+?)(?:\?|$)", message, flags=re.I)
    if not match:
        return None
    target = match.group(1).strip(" ?.!")
    if target.casefold() in {"this", "this exercise", "it", "that", "this one", "the exercise"}:
        return None
    return target


def _set_text(exercise: dict) -> str:
    sets = exercise.get("sets")
    reps = exercise.get("reps")
    if sets and reps:
        return f"{sets} × {reps}"
    if exercise.get("duration_minutes"):
        return f"{exercise['duration_minutes']} min"
    return reps or "the same work"


def substitution_reply(message: str, plan: str, context: dict, equipment: list[str]) -> str:
    proposal = _proposal(message)
    if proposal:
        reason = equipment_block_reason(proposal, equipment)
        if reason:
            return f"No. {reason}"
        return f"Yes. {proposal} fits your gym. Keep the same sets and reps as the exercise you're replacing."

    target_name = _target(message) or (context or {}).get("current_exercise")
    exercise = find_exercise(target_name, plan) if target_name else None
    if exercise is None:
        return "Which exercise do you want to replace?"
    alternative = exercise.get("machine_alternative")
    if not alternative:
        return f"Keep {exercise['name']}. I don't have a swap for it that fits your gym."
    reason = equipment_block_reason(alternative, equipment)
    if reason:
        return (
            f"The usual swap for {exercise['name']} is {alternative}, but that doesn't fit your gym. {reason} "
            f"Stay with {exercise['name']}."
        )
    return (
        f"Yes. Swap {exercise['name']} for {alternative}. "
        f"Same {_set_text(exercise)}."
    )


def format_today(day: dict, logs: list[dict]) -> str:
    if day.get("is_rest_day"):
        note = day.get("notes") or "Take the day off."
        return f"{day.get('focus') or 'Rest'}.\n\n{note}\n\nCatch up a missed day if you still want to train."
    focus = (day.get("focus") or "").lower()
    if "pull" in focus:
        opener = "Pull day. We're chasing width today 💪"
    else:
        opener = coach_nudge(day)
    lines = [opener, ""]
    items = list(day.get("exercises") or [])
    if day.get("finisher"):
        items.append(day["finisher"])
    for index, exercise in enumerate(items, start=1):
        lines.append(f"{index}. {exercise['name']} — {_set_text(exercise)}")
    main = (day.get("exercises") or [None])[0]
    if main:
        sessions = _sessions(main["name"], logs)
        if sessions:
            sets = sessions[-1]["sets"]
            reps = "/".join(str(item.get("reps")) for item in sets)
            weight = sets[0].get("weight_kg")
            weight_bit = f"{weight:g}kg, " if isinstance(weight, (int, float)) else ""
            lines.append("")
            lines.append(f"Your main target: beat last session on {main['name']} ({weight_bit}{reps}).")
        else:
            lines.append("")
            lines.append(f"Your main target: own {main['name']}. No previous weight is logged yet.")
    return "\n".join(lines)


def history_reply(message: str, logs: list[dict], exercise: str | None) -> str:
    text = message.casefold()
    if "pr" in text:
        if not exercise:
            return "Which exercise? I'll pull the best logged set, not a guess."
        sessions = _sessions(exercise, logs)
        best = None
        for session in sessions:
            for item in session["sets"]:
                weight = item.get("weight_kg") or 0
                reps = item.get("reps") or 0
                if best is None or weight > best[0] or (weight == best[0] and reps > best[1]):
                    best = (weight, reps, session["date"])
        if not best or not best[0]:
            return f"There's no weighed set logged for {exercise} yet, so there's no PR to report."
        return f"Best logged {exercise} is {best[0]:g}kg × {best[1]} on {best[2]}."
    if "volume" in text and exercise:
        sessions = _sessions(exercise, logs)
        if not sessions:
            return f"There's no log for {exercise} yet, so volume is zero."
        sets = sessions[-1]["sets"]
        volume = sum((item.get("weight_kg") or 0) * (item.get("reps") or 0) for item in sets)
        return (
            f"Last session on {exercise} ({sessions[-1]['date']}) was {volume:g} kg of volume "
            f"across {len(sets)} sets."
        )
    if "last week" in text:
        if not logs:
            return "Nothing is logged for last week yet."
        today = date.today()
        start = today - timedelta(days=7)
        recent = [row for row in logs if start.isoformat() <= (row.get("date") or "") < today.isoformat()]
        if not recent:
            return "I don't have any sets logged in the last 7 days."
        by_date: dict[str, list[str]] = {}
        for row in recent:
            by_date.setdefault(row.get("date") or "", []).append(row.get("exercise_name") or "Exercise")
        lines = ["Here's what is actually logged from the last 7 days:"]
        for day in sorted(by_date):
            names = []
            for name in by_date[day]:
                if name not in names:
                    names.append(name)
            lines.append(f"{day}: {', '.join(names)}")
        return "\n".join(lines)
    if not exercise:
        if not logs:
            return "There's no workout history yet. Finish a set and I'll remember it."
        last_date = sorted({row.get("date") or "" for row in logs})[-1]
        names = []
        for row in logs:
            if row.get("date") == last_date and row.get("exercise_name") not in names:
                names.append(row.get("exercise_name"))
        return f"Last logged day was {last_date}: {', '.join(names)}."
    sessions = _sessions(exercise, logs)
    if not sessions:
        return f"There's no previous {exercise} session in the log."
    last = sessions[-1]
    bits = []
    for item in last["sets"]:
        weight = item.get("weight_kg")
        reps = item.get("reps")
        if weight is None:
            bits.append(f"set {item.get('set_number')}: {reps} reps")
        else:
            bits.append(f"{weight:g}kg × {reps}")
    improved = ""
    if len(sessions) >= 2:
        previous = sessions[-2]["sets"]
        prev_weight = max((item.get("weight_kg") or 0) for item in previous)
        last_weight = max((item.get("weight_kg") or 0) for item in last["sets"])
        if last_weight > prev_weight:
            improved = f" That's up from {prev_weight:g}kg on {sessions[-2]['date']}."
        elif last_weight == prev_weight:
            improved = " Weight is the same as the session before. Reps are the thing to beat."
        else:
            improved = f" That's lighter than {prev_weight:g}kg on {sessions[-2]['date']}."
    return f"Last {exercise} was {last['date']}: {', '.join(bits)}.{improved}"


def progress_reply(logs: list[dict], progress_rows: list[dict]) -> str:
    if not logs and not progress_rows:
        return (
            "There's no training history yet, so I can't call a trend. "
            "Log a few sessions and I'll tell you if the weights are moving."
        )
    names = []
    for row in logs:
        if row.get("exercise_name") and row["exercise_name"] not in names:
            names.append(row["exercise_name"])
    lines = []
    for name in names:
        sessions = _sessions(name, logs)
        if len(sessions) < 2:
            continue
        before = max((item.get("weight_kg") or 0) for item in sessions[-2]["sets"])
        after = max((item.get("weight_kg") or 0) for item in sessions[-1]["sets"])
        if not before and not after:
            continue
        if after > before:
            lines.append(f"{name}: {before:g}kg → {after:g}kg")
        elif after == before:
            lines.append(f"{name}: holding {after:g}kg")
        else:
            lines.append(f"{name}: {before:g}kg → {after:g}kg")
    weight_line = ""
    weights = [row.get("weight_kg") for row in progress_rows if row.get("weight_kg")]
    if len(weights) >= 2:
        delta = weights[-1] - weights[0]
        weight_line = f"Body weight went from {weights[0]:g}kg to {weights[-1]:g}kg ({delta:+.1f}kg)."
    if not lines and not weight_line:
        return "You've got a thin log so far. That's the baseline. Next session we can see if you beat it."
    reply = ["Here's the real trend:"]
    reply.extend(lines[:6])
    if weight_line:
        reply.append(weight_line)
    return "\n".join(reply)


def shorten_reply(day: dict) -> str:
    if day.get("is_rest_day"):
        return "Today is already a rest day. If you're short on time, a walk is enough."
    exercises = list(day.get("exercises") or [])
    keep = exercises[:3] if len(exercises) > 3 else exercises
    if not keep:
        return "There's nothing to shorten. Take the rest."
    names = ", ".join(item["name"] for item in keep)
    return (
        f"Short version: do {names}. Skip the rest and the finisher. "
        "That keeps the session useful without dragging it out."
    )


def needs_pain_clarification(message: str, history: list[dict]) -> bool:
    text = message.casefold()
    quality = any(word in text for word in ("sharp", "dull", "fatigue", "soreness", "ache", "sore"))
    timing = any(word in text for word in ("during", "after", "while", "next day"))
    followup = bool(history) and "sharp pain" in (history[-1].get("message") or "").casefold()
    if followup and (quality or timing):
        return False
    if quality and timing:
        return False
    return True


def pain_reply(message: str, history: list[dict]) -> str:
    blob = " ".join([message] + [item.get("message") or "" for item in history]).casefold()
    serious = any(word in blob for word in ("sharp", "numb", "swelling", "swollen", "worse", "weeks", "weak"))
    if serious:
        return (
            "That sounds like more than normal training fatigue. I'm not a doctor, so get it checked "
            "if it's sharp, persistent, or getting worse. Skip the painful lift today. Don't grind through it."
        )
    return (
        "If it's just muscle fatigue and it eases off, keep the exercise but drop the weight and clean up the reps. "
        "If it turns sharp or it's still there tomorrow, stop that lift and get it looked at."
    )


def _merge_history(stored: list[dict], client: list[dict]) -> list[dict]:
    combined = []
    for item in list(stored) + list(client):
        text = str(item.get("message") or "").strip()
        if not text:
            continue
        role = "assistant" if (item.get("role") or "") in {"assistant", "hanu"} else "user"
        row = {"role": role, "message": text}
        if combined and combined[-1] == row:
            continue
        combined.append(row)
    return combined[-5:]


def _merge_logs(stored: list[dict], client: list[dict]) -> list[dict]:
    merged = list(stored)
    seen = {
        (norm(row.get("exercise_name")), str(row.get("date") or ""), int(row.get("set_number") or 0))
        for row in merged
    }
    for row in client:
        key = (norm(row.get("exercise_name")), str(row.get("date") or ""), int(row.get("set_number") or 0))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _followup_intent(history: list[dict]) -> str | None:
    if not history:
        return None
    last = history[-1]
    if last.get("role") != "assistant":
        return None
    text = (last.get("message") or "").casefold()
    if "which exercise" not in text:
        return None
    if "replace" in text:
        return "substitution"
    return "progression"


def _names_the_exercise(message: str, exercise: str) -> bool:
    if not exercise:
        return False
    if compact(message) == compact(exercise):
        return True
    return len(message.split()) <= 5 and compact(exercise) in compact(message)


def classify_intent(message: str) -> str:
    text = " ".join(message.casefold().split())
    if any(word in text for word in ("hurt", "hurts", "pain", "injury", "injured", "tweaked")):
        return "pain"
    if any(word in text for word in ("replace", "instead", "swap", "substitute", "alternative")):
        return "substitution"
    if any(word in text for word in ("volume", "my pr", "what's my pr", "whats my pr", "last time", "last week", "last session", "did i improve", "what did i")):
        return "history"
    if any(word in text for word in ("what weight", "how heavy", "how much", "what should i use", "which weight")):
        return "progression"
    if any(word in text for word in ("progressing", "my progress", "how am i doing", "am i getting")):
        return "progress_check"
    if any(word in text for word in ("shorter", "less time", "quick workout", "shorten", "in a hurry", "short on time")):
        return "shorten"
    named_day = next((day for day in DAY_NAMES if day.casefold() in text), None)
    if named_day and "today" not in text:
        return "day_workout"
    if any(word in text for word in ("today", "what should i do", "what am i training", "what's my workout", "whats my workout", "this workout")):
        return "today"
    return "general"


def _empty_remote() -> dict:
    return {"user": None, "logs": [], "progress": [], "memory": [], "messages": []}


def _equipment_from(state: HanuState) -> list[str]:
    context = state.get("context") or {}
    if context.get("equipment"):
        return list(context["equipment"])
    for item in state.get("memory") or []:
        if item.get("category") != "equipment":
            continue
        try:
            parsed = json.loads(item.get("memory") or "")
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list) and parsed:
            return [str(piece) for piece in parsed]
    return list(DEFAULT_EQUIPMENT)


def _resolve_exercise(state: HanuState) -> str | None:
    message = state.get("user_message") or ""
    plan = (state.get("context") or {}).get("plan") or config.DEFAULT_PLAN
    named = _target(message) or _proposal(message)
    # A named program exercise beats a loose proposal like "cable rows".
    found = find_exercise(named, plan) if named else None
    if found and norm(found.get("name")) == norm(named):
        return found["name"]
    context_name = (state.get("context") or {}).get("current_exercise")
    if context_name:
        return context_name
    if found:
        return found["name"]
    program = load_program()
    catalog = []
    for key in PLAN_LABELS:
        for day in _schedule(program, key):
            catalog.extend(iter_exercises(day))
    text = norm(message)
    text_compact = compact(message)
    hits = [
        item
        for item in catalog
        if norm(item.get("name")) in text
        or (len(compact(item.get("name"))) >= 6 and compact(item.get("name")) in text_compact)
    ]
    if not hits:
        return None
    hits.sort(key=lambda item: len(item.get("name") or ""), reverse=True)
    return hits[0]["name"]


def consistency(logs: list[dict], plan: str, today: date) -> dict:
    training = {
        day["day_of_week"]
        for day in _schedule(load_program(), plan)
        if not day.get("is_rest_day")
    }
    start = today - timedelta(days=6)
    expected = 0
    done = set()
    logged_days = {row.get("date") for row in logs}
    for offset in range(7):
        current = start + timedelta(days=offset)
        name = weekday_name(current)
        if name in training:
            expected += 1
            if current.isoformat() in logged_days:
                done.add(current.isoformat())
    percent = round(100 * len(done) / expected) if expected else 0
    return {"completed": len(done), "expected": expected, "percent": percent}


def personal_records(logs: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for row in logs:
        weight = row.get("weight_kg") or 0
        if weight <= 0:
            continue
        name = row.get("exercise_name") or "Exercise"
        reps = row.get("reps") or 0
        current = best.get(name)
        if current is None or weight > current["weight_kg"] or (
            weight == current["weight_kg"] and reps > current["reps"]
        ):
            best[name] = {
                "exercise_name": name,
                "weight_kg": weight,
                "reps": reps,
                "date": row.get("date"),
            }
    return sorted(best.values(), key=lambda item: item["weight_kg"], reverse=True)[:8]


def recent_sessions(logs: list[dict], limit: int = 6) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in logs:
        day = row.get("date") or ""
        bucket = grouped.setdefault(
            day,
            {"date": day, "day_of_week": row.get("day_of_week") or "", "exercises": {}},
        )
        name = row.get("exercise_name") or "Exercise"
        exercise = bucket["exercises"].setdefault(name, [])
        exercise.append(row)
    sessions = []
    for day in sorted(grouped, reverse=True)[:limit]:
        exercises = []
        for name, rows in grouped[day]["exercises"].items():
            rows.sort(key=lambda item: item.get("set_number") or 0)
            exercises.append(
                {
                    "exercise_name": name,
                    "sets": [
                        {
                            "set_number": row.get("set_number"),
                            "weight_kg": row.get("weight_kg"),
                            "reps": row.get("reps"),
                        }
                        for row in rows
                    ],
                }
            )
        sessions.append(
            {
                "date": day,
                "day_of_week": grouped[day]["day_of_week"],
                "exercises": exercises,
            }
        )
    return sessions


def strength_trend(logs: list[dict]) -> list[dict]:
    trends = []
    names = []
    for row in logs:
        if row.get("exercise_name") and row["exercise_name"] not in names:
            names.append(row["exercise_name"])
    for name in names:
        sessions = _sessions(name, logs)
        if len(sessions) < 2:
            continue
        previous = max((item.get("weight_kg") or 0) for item in sessions[-2]["sets"])
        latest = max((item.get("weight_kg") or 0) for item in sessions[-1]["sets"])
        if not previous and not latest:
            continue
        trends.append(
            {
                "exercise_name": name,
                "previous_kg": previous,
                "latest_kg": latest,
                "latest_date": sessions[-1]["date"],
            }
        )
    return trends[:8]


def build_progress_overview(user: dict | None, logs: list[dict], entries: list[dict], plan: str, today: date) -> dict:
    weights = [row.get("weight_kg") for row in entries if row.get("weight_kg")]
    current = weights[-1] if weights else (user or {}).get("weight_kg")
    delta = round(weights[-1] - weights[0], 1) if len(weights) >= 2 else None
    return {
        "entries": entries,
        "current_weight_kg": current,
        "weight_delta_kg": delta,
        "consistency": consistency(logs, plan, today),
        "prs": personal_records(logs),
        "recent_sessions": recent_sessions(logs),
        "strength": strength_trend(logs),
    }


def exercise_history(name: str, logs: list[dict], plan: str) -> dict:
    exercise = find_exercise(name, plan)
    reps_text = (exercise or {}).get("reps")
    sessions = []
    for session in _sessions(name, logs):
        sessions.append(
            {
                "date": session["date"],
                "day_of_week": session["day_of_week"],
                "sets": [
                    {
                        "set_number": item.get("set_number") or 0,
                        "weight_kg": item.get("weight_kg"),
                        "reps": item.get("reps"),
                        "rpe": item.get("rpe"),
                        "notes": item.get("notes") or "",
                    }
                    for item in session["sets"]
                ],
            }
        )
    record = None
    for item in personal_records(logs):
        if norm(item["exercise_name"]) == norm(name):
            record = item
            break
    return {
        "exercise_name": (exercise or {}).get("name") or name,
        "sessions": sessions,
        "pr": record,
        "suggestion": progression_advice((exercise or {}).get("name") or name, logs, reps_text),
    }


def _focus_line(day_name: str, plan: str, on: date) -> dict:
    workout = get_workout(plan, day_name, on) or {}
    return workout


def understand(state: HanuState) -> dict:
    return {"intent": classify_intent(state.get("user_message") or "")}


def load_context(state: HanuState) -> dict:
    remote = _empty_remote()
    try:
        remote = sheets.load_user_context(state["user_id"])
    except Exception:
        log.warning("Hanu context load failed", exc_info=True)
    context = dict(state.get("context") or {})
    plan = context.get("plan") or config.DEFAULT_PLAN
    if plan not in PLAN_LABELS:
        plan = config.DEFAULT_PLAN
    on = parse_date(state.get("on_date"))
    day_name = context.get("current_day") or weekday_name(on)
    if state.get("intent") == "day_workout":
        for name in DAY_NAMES:
            if name.casefold() in (state.get("user_message") or "").casefold():
                day_name = name
                break
    workout = get_workout(plan, day_name, on) or {}
    logs = _merge_logs(remote["logs"], state.get("client_logs") or [])
    target = _resolve_exercise({**state, "context": context, "today_workout": workout, "all_logs": logs})
    relevant = logs
    if target:
        relevant = [row for row in logs if norm(row.get("exercise_name")) == norm(target)]
    messages = remote["messages"]
    conversation_id = state.get("conversation_id")
    if conversation_id:
        scoped = [row for row in messages if row.get("conversation_id") == conversation_id]
        if scoped:
            messages = scoped
    messages = _merge_history(messages, state.get("client_history") or [])
    return {
        "context": context,
        "user_profile": remote["user"],
        "today_workout": workout,
        "recent_workouts": recent_sessions(logs, limit=5),
        "exercise_history": relevant[-12:],
        "all_logs": logs,
        "progress": remote["progress"][-8:],
        "memory": remote["memory"][-8:],
        "history_messages": messages,
        "target_exercise": target or "",
        "equipment": _equipment_from({**state, "memory": remote["memory"], "context": context}),
    }


def clarify(state: HanuState) -> dict:
    history = state.get("history_messages") or []
    intent = state.get("intent") or "general"
    follow = _followup_intent(history)
    if follow and intent == "general":
        intent = follow
    if history and "sharp pain" in (history[-1].get("message") or "").casefold():
        intent = "pain"
    message = state.get("user_message") or ""
    if intent == "pain" and needs_pain_clarification(message, history):
        question = (
            "Is it a sharp pain or more like normal muscle fatigue? "
            "And does it happen during the movement or after?"
        )
        return {
            "intent": "pain",
            "clarification_needed": True,
            "clarification_question": question,
            "response": question,
            "suggested_actions": [],
        }
    if intent == "progression" and not state.get("target_exercise"):
        question = "Which exercise? I'll use your log if it's there."
        return {
            "intent": intent,
            "clarification_needed": True,
            "clarification_question": question,
            "response": question,
            "suggested_actions": [],
        }
    if intent == "substitution" and not _proposal(message) and not state.get("target_exercise"):
        question = "Which exercise do you want to replace?"
        return {
            "intent": intent,
            "clarification_needed": True,
            "clarification_question": question,
            "response": question,
            "suggested_actions": [],
        }
    return {"intent": intent, "clarification_needed": False, "response": ""}


def _route(state: HanuState) -> str:
    return "persist" if state.get("clarification_needed") else "answer"


def _llm(state: HanuState) -> dict:
    if not config.OPENAI_API_KEY:
        return {
            "message": (
                "I can run today's workout, your logged weights, and equipment swaps without a cloud model. "
                "Add an OpenAI key when you want open-ended coaching."
            ),
            "intent": state.get("intent") or "general",
            "clarification_needed": False,
            "suggested_actions": [],
            "memory": "",
        }
    profile = state.get("user_profile") or {}
    day = state.get("today_workout") or {}
    today_names = ", ".join(item["name"] for item in (day.get("exercises") or []))
    memories = " | ".join(item.get("memory") or "" for item in (state.get("memory") or [])[:6])
    history = "\n".join(
        f"{item.get('role')}: {(item.get('message') or '')[:400]}"
        for item in (state.get("history_messages") or [])[-5:]
    )
    sessions = []
    for item in (state.get("recent_workouts") or [])[:5]:
        lifted = ", ".join(block.get("exercise_name") or "" for block in (item.get("exercises") or [])[:6])
        sessions.append(f"{item.get('date')} {item.get('day_of_week')}: {lifted}")
    logs = json.dumps(state.get("exercise_history") or [], default=str)[:1800]
    prompt = "\n\n".join(
        [
            f"User: {profile.get('name') or 'Athlete'}; goal: {profile.get('goal') or 'V-taper'}; weight: {profile.get('weight_kg')}",
            f"Today: {day.get('day')} {day.get('focus')} — {today_names}",
            f"On screen: {(state.get('context') or {}).get('current_exercise') or 'none'}",
            f"Equipment ids: {', '.join(state.get('equipment') or DEFAULT_EQUIPMENT)}",
            f"Memory: {memories or 'none'}",
            f"Last sessions: {'; '.join(sessions) or 'none'}",
            f"Relevant logs: {logs or 'none'}",
            f"Recent chat:\n{history or 'none'}",
            f"User message: {(state.get('user_message') or '')[:1000]}",
        ]
    )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=30)
        model = config.OPENAI_MODEL
        text = {
            "format": {
                "type": "json_schema",
                "name": "hanu_response",
                "strict": True,
                "schema": _RESPONSE_SCHEMA,
            },
        }
        # Reasoning models (gpt-5, o-series) reject temperature; older models reject low verbosity.
        reasoning = model.startswith(("gpt-5", "o1", "o3", "o4"))
        extra = {"reasoning": {"effort": "low"}} if reasoning else {"temperature": 0.4}
        if reasoning:
            text["verbosity"] = "low"
        response = client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT,
            input=prompt,
            max_output_tokens=800 if reasoning else 400,
            store=False,
            text=text,
            **extra,
        )
        raw = getattr(response, "output_text", "") or ""
        data = json.loads(raw)
        message = _scrub(data.get("message") or "")
        return {
            "message": message or "Ask me about today's session, a weight, or a swap.",
            "intent": data.get("intent") or state.get("intent") or "general",
            "clarification_needed": bool(data.get("clarification_needed")),
            "suggested_actions": list(data.get("suggested_actions") or [])[:4],
            "memory": data.get("memory") or "",
        }
    except Exception:
        log.warning("OpenAI request failed", exc_info=True)
        return {
            "message": "Hanu is taking a break. Try again in a moment.",
            "intent": state.get("intent") or "general",
            "clarification_needed": False,
            "suggested_actions": [],
            "memory": "",
        }


def _scrub(message: str) -> str:
    lowered = message.casefold()
    banned = ("cable row", "barbell squat", "barbell row", "barbell rdl", "cable curl", "cable lateral")
    if any(phrase in lowered for phrase in banned):
        return (
            "I'm not putting that in the session. The cable machine is only for triceps, "
            "and the barbell is only for bench press."
        )
    return message


def answer(state: HanuState) -> dict:
    intent = state.get("intent") or "general"
    day = state.get("today_workout") or {}
    scoped = state.get("exercise_history") or []
    logs = state.get("all_logs") or scoped
    message = state.get("user_message") or ""
    plan = (state.get("context") or {}).get("plan") or config.DEFAULT_PLAN
    equipment = state.get("equipment") or DEFAULT_EQUIPMENT
    target = state.get("target_exercise") or ""
    actions: list[str] = []
    new_memory = ""

    if intent == "today":
        text = format_today(day, logs)
        actions = [] if day.get("is_rest_day") else ["Start workout"]
    elif intent == "day_workout":
        text = format_today(day, logs)
    elif intent == "progression":
        exercise = find_exercise(target, plan) or {"name": target, "reps": "8-12"}
        text = progression_advice(exercise.get("name") or target, scoped or logs, exercise.get("reps"))
    elif intent == "history":
        text = history_reply(message, logs, target or None)
    elif intent == "progress_check":
        text = progress_reply(logs, state.get("progress") or [])
    elif intent == "shorten":
        text = shorten_reply(day)
    elif intent == "substitution":
        text = substitution_reply(message, plan, state.get("context") or {}, equipment)
        if text.startswith("Which exercise"):
            return {
                "intent": intent,
                "clarification_needed": True,
                "response": text,
                "suggested_actions": [],
            }
    elif intent == "pain":
        text = pain_reply(message, state.get("history_messages") or [])
    else:
        named = state.get("target_exercise") or ""
        if named and _names_the_exercise(message, named):
            exercise = find_exercise(named, plan) or {"name": named, "reps": "8-12"}
            text = progression_advice(exercise.get("name") or named, scoped or logs, exercise.get("reps"))
            intent = "progression"
        else:
            greeting = re.fullmatch(r"(hi|hey|hello|yo|sup|hii+|good (morning|afternoon|evening))[!. ]*", message.strip(), re.I)
            if greeting or (not config.OPENAI_API_KEY and len(message.split()) <= 3):
                name = (state.get("user_profile") or {}).get("name") or "Ram"
                if day and not day.get("is_rest_day"):
                    first = (day.get("exercises") or [{}])[0].get("name") or "the first lift"
                    text = f"Hey {name}. {day.get('focus')} today, starting with {first}. Ask me for a weight, a swap, or form tips."
                else:
                    text = f"Hey {name}. Rest day today. Ask me about the program, your numbers, or recovery."
            else:
                generated = _llm(state)
                text = generated["message"]
                intent = generated.get("intent") or intent
                new_memory = generated.get("memory") or ""
                actions = generated.get("suggested_actions") or []
                if generated.get("clarification_needed"):
                    return {
                        "intent": intent,
                        "clarification_needed": True,
                        "response": text,
                        "suggested_actions": actions,
                        "new_memory": new_memory if new_memory.startswith("User ") else "",
                    }
    return {
        "intent": intent,
        "clarification_needed": False,
        "response": text,
        "suggested_actions": actions,
        "new_memory": new_memory if str(new_memory).startswith("User ") else "",
    }


def _remember(state: HanuState) -> None:
    if not state.get("persist", True):
        return
    patterns = [
        (re.compile(r"i (?:don't|do not|dont) like ([^.!\n]{3,80})", re.I), "User dislikes {0}"),
        (re.compile(r"i (?:hate|dislike) ([^.!\n]{3,80})", re.I), "User dislikes {0}"),
        (re.compile(r"i prefer ([^.!\n]{3,80})", re.I), "User prefers {0}"),
    ]
    found = []
    for pattern, template in patterns:
        match = pattern.search(state.get("user_message") or "")
        if match:
            found.append(template.format(match.group(1).strip()))
    extra = state.get("new_memory") or ""
    if extra.startswith("User "):
        found.append(extra[:160])
    for memory in found:
        try:
            sheets.save_coach_memory(
                {
                    "user_id": state["user_id"],
                    "category": "preference",
                    "memory": memory,
                    "importance": 2,
                }
            )
        except Exception:
            log.warning("Could not store coach memory", exc_info=True)


def persist(state: HanuState) -> dict:
    if state.get("persist", True):
        try:
            sheets.save_conversation_message(
                {
                    "user_id": state["user_id"],
                    "conversation_id": state["conversation_id"],
                    "role": "user",
                    "message": state.get("user_message") or "",
                }
            )
            sheets.save_conversation_message(
                {
                    "user_id": state["user_id"],
                    "conversation_id": state["conversation_id"],
                    "role": "assistant",
                    "message": state.get("response") or "",
                }
            )
        except Exception:
            log.warning("Could not store coach conversation", exc_info=True)
        _remember(state)
    return {}


def build_graph():
    graph = StateGraph(HanuState)
    graph.add_node("understand", understand)
    graph.add_node("load_context", load_context)
    graph.add_node("clarify", clarify)
    graph.add_node("answer", answer)
    graph.add_node("persist", persist)
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "load_context")
    graph.add_edge("load_context", "clarify")
    graph.add_conditional_edges("clarify", _route, {"persist": "persist", "answer": "answer"})
    graph.add_edge("answer", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def chat(
    user_id: str,
    message: str,
    conversation_id: str | None = None,
    context: dict | None = None,
    on_date: date | None = None,
    persist: bool = True,
    recent_messages: list[dict] | None = None,
    recent_logs: list[dict] | None = None,
) -> dict:
    conversation = conversation_id or uuid.uuid4().hex
    history = []
    for item in (recent_messages or [])[-5:]:
        text = str(item.get("message") or "").strip()
        if text:
            role = "assistant" if item.get("role") == "assistant" else "user"
            history.append({"role": role, "message": text[:500]})
    result = get_graph().invoke(
        {
            "user_id": user_id,
            "conversation_id": conversation,
            "user_message": message.strip(),
            "context": context or {},
            "on_date": (on_date or date.today()).isoformat(),
            "persist": persist,
            "client_history": history,
            "client_logs": list(recent_logs or [])[-40:],
            "clarification_needed": False,
            "suggested_actions": [],
            "equipment": list((context or {}).get("equipment") or []),
        }
    )
    return {
        "message": result.get("response") or "Ask me about today's session, a weight, or a swap.",
        "intent": result.get("intent") or "general",
        "clarification_needed": bool(result.get("clarification_needed")),
        "suggested_actions": result.get("suggested_actions") or [],
        "conversation_id": conversation,
    }
