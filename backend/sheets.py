"""Google Sheets access. Nothing else in the app should call the Sheets API.

Auth matches the working service-account client from the original test script.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

TABS: dict[str, list[str]] = {
    "Users": [
        "user_id",
        "name",
        "age",
        "height_cm",
        "weight_kg",
        "goal",
        "created_at",
        "updated_at",
    ],
    "WorkoutLogs": [
        "log_id",
        "user_id",
        "date",
        "day_of_week",
        "exercise_name",
        "set_number",
        "weight_kg",
        "reps",
        "rpe",
        "notes",
        "created_at",
    ],
    "Progress": [
        "progress_id",
        "user_id",
        "date",
        "weight_kg",
        "waist_cm",
        "notes",
    ],
    "CoachConversations": [
        "message_id",
        "user_id",
        "conversation_id",
        "role",
        "message",
        "created_at",
    ],
    "CoachMemory": [
        "memory_id",
        "user_id",
        "category",
        "memory",
        "importance",
        "created_at",
        "updated_at",
    ],
}

_CACHE_TTL = 15
_cache: dict[str, tuple[float, list[dict]]] = {}
_sheet_ids: dict[str, int] = {}
_ready = False
# googleapiclient's HTTP transport is not thread-safe, and FastAPI runs sync routes in a thread pool.
_local = threading.local()
_lock = threading.Lock()


class SheetsError(RuntimeError):
    """Raised when Sheets cannot be read or written. Callers map this to a friendly HTTP error."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _account_info(raw: str) -> dict:
    info = json.loads(raw.strip())
    if isinstance(info, str):
        info = json.loads(info)
    key = info.get("private_key") or ""
    if "\\n" in key:
        info["private_key"] = key.replace("\\n", "\n")
    return info


def _credentials() -> Credentials:
    if config.GOOGLE_SERVICE_ACCOUNT_JSON.strip():
        info = _account_info(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )


def service():
    client = getattr(_local, "service", None)
    if client is None:
        try:
            client = build(
                "sheets",
                "v4",
                credentials=_credentials(),
                cache_discovery=False,
            )
        except Exception as exc:
            raise SheetsError("Google Sheets credentials are missing or invalid") from exc
        _local.service = client
    return client


def _execute(request):
    try:
        return request.execute(num_retries=2)
    except HttpError as exc:
        raise SheetsError("Google Sheets request failed") from exc
    except SheetsError:
        raise
    except Exception:
        # A broken connection poisons this thread's client; rebuild it and try once more.
        _local.service = None
        try:
            request.http = service()._http
            return request.execute(num_retries=1)
        except Exception as exc:
            raise SheetsError("Google Sheets request failed") from exc


def _invalidate() -> None:
    _cache.clear()


def _as_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _public(row: dict) -> dict:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _parse_rows(headers: list[str], values: list[list]) -> list[dict]:
    if not values:
        return []
    first = [str(cell).strip() for cell in values[0]]
    start = 1 if first[: len(headers)] == headers else 0
    header_row = headers if start == 1 else first
    records = []
    for offset, raw in enumerate(values[start:], start=start + 1):
        if not any(str(cell).strip() for cell in raw):
            continue
        padded = list(raw) + [""] * (len(header_row) - len(raw))
        item = {header_row[index]: padded[index] for index in range(len(header_row))}
        item["_row"] = offset
        records.append(item)
    return records


def _coerce(tab: str, row: dict) -> dict:
    item = _public(row)
    if tab == "Users":
        item["age"] = _as_int(item.get("age"))
        item["height_cm"] = _as_float(item.get("height_cm"))
        item["weight_kg"] = _as_float(item.get("weight_kg"))
    elif tab == "WorkoutLogs":
        item["set_number"] = _as_int(item.get("set_number")) or 0
        item["weight_kg"] = _as_float(item.get("weight_kg"))
        item["reps"] = _as_int(item.get("reps"))
        item["rpe"] = _as_float(item.get("rpe"))
        item["notes"] = item.get("notes") or ""
    elif tab == "Progress":
        item["weight_kg"] = _as_float(item.get("weight_kg"))
        item["waist_cm"] = _as_float(item.get("waist_cm"))
        item["notes"] = item.get("notes") or ""
    elif tab == "CoachMemory":
        item["importance"] = _as_int(item.get("importance")) or 1
    return item


def ensure_ready() -> None:
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        meta = _execute(
            service().spreadsheets().get(spreadsheetId=config.SPREADSHEET_ID)
        )
        titles = {
            sheet["properties"]["title"]: sheet["properties"]["sheetId"]
            for sheet in meta.get("sheets", [])
        }
        requests = [
            {"addSheet": {"properties": {"title": title}}}
            for title in TABS
            if title not in titles
        ]
        if requests:
            _execute(
                service()
                .spreadsheets()
                .batchUpdate(
                    spreadsheetId=config.SPREADSHEET_ID,
                    body={"requests": requests},
                )
            )
            meta = _execute(
                service().spreadsheets().get(spreadsheetId=config.SPREADSHEET_ID)
            )
            titles = {
                sheet["properties"]["title"]: sheet["properties"]["sheetId"]
                for sheet in meta.get("sheets", [])
            }
        _sheet_ids.clear()
        _sheet_ids.update(titles)
        for title, headers in TABS.items():
            current = _execute(
                service()
                .spreadsheets()
                .values()
                .get(
                    spreadsheetId=config.SPREADSHEET_ID,
                    range=f"{title}!A1:Z1",
                )
            )
            row = (current.get("values") or [[]])[0] if current.get("values") else []
            if [str(cell).strip() for cell in row] != headers:
                if row:
                    continue
                _execute(
                    service()
                    .spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=config.SPREADSHEET_ID,
                        range=f"{title}!A1",
                        valueInputOption="RAW",
                        body={"values": [headers]},
                    )
                )
        _ready = True


def _read_tab(tab: str, use_cache: bool = True) -> list[dict]:
    ensure_ready()
    now = time.time()
    cached = _cache.get(tab)
    if use_cache and cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    result = _execute(
        service()
        .spreadsheets()
        .values()
        .get(spreadsheetId=config.SPREADSHEET_ID, range=f"{tab}!A:Z")
    )
    records = _parse_rows(TABS[tab], result.get("values", []))
    _cache[tab] = (time.time(), records)
    return records


def batch_read(tabs: list[str]) -> dict[str, list[dict]]:
    """Read several tabs in one Sheets call. Used so Hanu does not fan out."""
    ensure_ready()
    now = time.time()
    found: dict[str, list[dict]] = {}
    missing: list[str] = []
    for tab in tabs:
        cached = _cache.get(tab)
        if cached and now - cached[0] < _CACHE_TTL:
            found[tab] = cached[1]
        else:
            missing.append(tab)
    if not missing:
        return found
    result = _execute(
        service()
        .spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=config.SPREADSHEET_ID,
            ranges=[f"{tab}!A:Z" for tab in missing],
        )
    )
    blocks = {}
    for block in result.get("valueRanges", []):
        label = str(block.get("range", "")).split("!")[0].strip("'")
        blocks[label] = block
    for index, tab in enumerate(missing):
        block = blocks.get(tab)
        if block is None and index < len(result.get("valueRanges", [])):
            block = result["valueRanges"][index]
        records = _parse_rows(TABS[tab], (block or {}).get("values", []))
        _cache[tab] = (time.time(), records)
        found[tab] = records
    return found


def _row_values(tab: str, record: dict) -> list:
    values = []
    for header in TABS[tab]:
        value = record.get(header, "")
        values.append("" if value is None else value)
    return values


def _append(tab: str, record: dict) -> None:
    ensure_ready()
    _execute(
        service()
        .spreadsheets()
        .values()
        .append(
            spreadsheetId=config.SPREADSHEET_ID,
            range=f"{tab}!A:Z",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [_row_values(tab, record)]},
        )
    )
    _invalidate()


def _update_row(tab: str, row_number: int, record: dict) -> None:
    ensure_ready()
    _execute(
        service()
        .spreadsheets()
        .values()
        .update(
            spreadsheetId=config.SPREADSHEET_ID,
            range=f"{tab}!A{row_number}",
            valueInputOption="RAW",
            body={"values": [_row_values(tab, record)]},
        )
    )
    _invalidate()


def _delete_row(tab: str, row_number: int) -> None:
    ensure_ready()
    sheet_id = _sheet_ids.get(tab)
    if sheet_id is None:
        raise SheetsError(f"Sheet '{tab}' was not found")
    _execute(
        service()
        .spreadsheets()
        .batchUpdate(
            spreadsheetId=config.SPREADSHEET_ID,
            body={
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": row_number - 1,
                                "endIndex": row_number,
                            }
                        }
                    }
                ]
            },
        )
    )


def _match(tab: str, field: str, value: str) -> list[dict]:
    return [row for row in _read_tab(tab) if str(row.get(field)) == str(value)]


def load_user_context(user_id: str) -> dict:
    tabs = batch_read(
        ["Users", "WorkoutLogs", "Progress", "CoachMemory", "CoachConversations"]
    )
    return {
        "user": next(
            (_coerce("Users", row) for row in tabs["Users"] if row.get("user_id") == user_id),
            None,
        ),
        "logs": [
            _coerce("WorkoutLogs", row)
            for row in tabs["WorkoutLogs"]
            if row.get("user_id") == user_id
        ],
        "progress": [
            _coerce("Progress", row)
            for row in tabs["Progress"]
            if row.get("user_id") == user_id
        ],
        "memory": [
            _coerce("CoachMemory", row)
            for row in tabs["CoachMemory"]
            if row.get("user_id") == user_id
        ],
        "messages": [
            _coerce("CoachConversations", row)
            for row in tabs["CoachConversations"]
            if row.get("user_id") == user_id
        ],
    }


def get_user(user_id: str) -> dict | None:
    rows = _match("Users", "user_id", user_id)
    if not rows:
        return None
    return _coerce("Users", rows[-1])


def save_user(record: dict) -> dict:
    now = _now()
    existing = _match("Users", "user_id", record["user_id"])
    stored = {
        "user_id": record["user_id"],
        "name": record.get("name") or "",
        "age": record.get("age") if record.get("age") is not None else "",
        "height_cm": record.get("height_cm") if record.get("height_cm") is not None else "",
        "weight_kg": record.get("weight_kg") if record.get("weight_kg") is not None else "",
        "goal": record.get("goal") or "",
        "created_at": (existing[-1].get("created_at") if existing else None) or now,
        "updated_at": now,
    }
    if existing:
        _update_row("Users", existing[-1]["_row"], stored)
    else:
        _append("Users", stored)
    return _coerce("Users", stored)


def get_workout_logs(user_id: str, exercise_name: str | None = None) -> list[dict]:
    rows = [_coerce("WorkoutLogs", row) for row in _match("WorkoutLogs", "user_id", user_id)]
    if exercise_name:
        wanted = " ".join(exercise_name.casefold().split())
        rows = [
            row
            for row in rows
            if " ".join(str(row.get("exercise_name", "")).casefold().split()) == wanted
        ]
    rows.sort(key=lambda row: (row.get("date") or "", row.get("created_at") or "", row.get("set_number") or 0))
    return rows


def save_workout_log(record: dict) -> dict:
    stored = {
        "log_id": record.get("log_id") or uuid.uuid4().hex,
        "user_id": record["user_id"],
        "date": record.get("date") or "",
        "day_of_week": record.get("day_of_week") or "",
        "exercise_name": record.get("exercise_name") or "",
        "set_number": record.get("set_number") or 1,
        "weight_kg": "" if record.get("weight_kg") is None else record.get("weight_kg"),
        "reps": "" if record.get("reps") is None else record.get("reps"),
        "rpe": "" if record.get("rpe") is None else record.get("rpe"),
        "notes": record.get("notes") or "",
        "created_at": record.get("created_at") or _now(),
    }
    _append("WorkoutLogs", stored)
    return _coerce("WorkoutLogs", stored)


def get_progress(user_id: str) -> list[dict]:
    rows = [_coerce("Progress", row) for row in _match("Progress", "user_id", user_id)]
    rows.sort(key=lambda row: row.get("date") or "")
    return rows


def save_progress(record: dict) -> dict:
    stored = {
        "progress_id": record.get("progress_id") or uuid.uuid4().hex,
        "user_id": record["user_id"],
        "date": record.get("date") or "",
        "weight_kg": "" if record.get("weight_kg") is None else record.get("weight_kg"),
        "waist_cm": "" if record.get("waist_cm") is None else record.get("waist_cm"),
        "notes": record.get("notes") or "",
    }
    _append("Progress", stored)
    return _coerce("Progress", stored)


def get_conversation(user_id: str, conversation_id: str | None = None) -> list[dict]:
    rows = [
        _coerce("CoachConversations", row)
        for row in _match("CoachConversations", "user_id", user_id)
    ]
    rows.sort(key=lambda row: row.get("created_at") or "")
    if conversation_id:
        return [row for row in rows if row.get("conversation_id") == conversation_id]
    if not rows:
        return []
    latest = rows[-1]["conversation_id"]
    return [row for row in rows if row.get("conversation_id") == latest]


def save_conversation_message(record: dict) -> dict:
    stored = {
        "message_id": record.get("message_id") or uuid.uuid4().hex,
        "user_id": record["user_id"],
        "conversation_id": record["conversation_id"],
        "role": record.get("role") or "user",
        "message": record.get("message") or "",
        "created_at": record.get("created_at") or _now(),
    }
    _append("CoachConversations", stored)
    return _coerce("CoachConversations", stored)


def get_coach_memory(user_id: str) -> list[dict]:
    rows = [_coerce("CoachMemory", row) for row in _match("CoachMemory", "user_id", user_id)]
    rows.sort(key=lambda row: row.get("updated_at") or row.get("created_at") or "")
    return rows


def save_coach_memory(record: dict) -> dict:
    now = _now()
    text = (record.get("memory") or "").strip()
    category = record.get("category") or "note"
    existing = [
        row
        for row in _match("CoachMemory", "user_id", record["user_id"])
        if (row.get("category") == category and category == "equipment")
        or (row.get("category") == category and str(row.get("memory")).strip() == text)
    ]
    stored = {
        "memory_id": (existing[-1].get("memory_id") if existing else None) or uuid.uuid4().hex,
        "user_id": record["user_id"],
        "category": category,
        "memory": text,
        "importance": record.get("importance") or 2,
        "created_at": (existing[-1].get("created_at") if existing else None) or now,
        "updated_at": now,
    }
    if existing:
        _update_row("CoachMemory", existing[-1]["_row"], stored)
    else:
        _append("CoachMemory", stored)
    return _coerce("CoachMemory", stored)


def delete_user_data(user_id: str) -> None:
    """Remove every row for one user. Tests use this so demo data does not stick."""
    ensure_ready()
    _invalidate()
    for tab in TABS:
        rows = [row for row in _read_tab(tab, use_cache=False) if str(row.get("user_id")) == str(user_id)]
        for row in sorted(rows, key=lambda item: item["_row"], reverse=True):
            _delete_row(tab, row["_row"])
        _invalidate()
