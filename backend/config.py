"""Environment configuration. Secrets stay here and never go to the browser."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(__file__).resolve().parent

load_dotenv(ROOT / ".env")
load_dotenv(BACKEND / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _key_file(value: str) -> Path:
    path = Path(value)
    if path.is_file():
        return path
    for base in (ROOT, BACKEND, Path.cwd()):
        candidate = (base / value).resolve()
        if candidate.is_file():
            return candidate
    return path


SPREADSHEET_ID = _env("GOOGLE_SPREADSHEET_ID", "SPREADSHEET_ID") or (
    "1OgPkbTnC1NninCscb8pDaTNTaw8D9TzCic5e72ad95w"
)

# Service-account auth is what actually works today (see sheets.py).
# The OAuth client vars are accepted so a later login flow has a place to live.
# Vercel must get the raw key JSON. A filename in SERVICE_ACCOUNT_FILE is not deployed.
_account_json = _env("GOOGLE_SERVICE_ACCOUNT_JSON", "SERVICE_ACCOUNT_JSON")
_account_file = _env("GOOGLE_SERVICE_ACCOUNT_FILE", "SERVICE_ACCOUNT_FILE")
if _account_file.startswith("{"):
    _account_json = _account_json or _account_file
    _account_file = ""
GOOGLE_SERVICE_ACCOUNT_JSON = _account_json
GOOGLE_SERVICE_ACCOUNT_FILE = str(
    _key_file(_account_file or "sam-agent-506413-b67261b92c1c.json")
)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")

_DEFAULT_ORIGINS = ",".join(
    [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "https://fitforgeweb.vercel.app",
    ]
)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]

DATA_JSON = ROOT / "data.json"
DEFAULT_USER_ID = os.getenv("FITFORGE_USER_ID", "ram")
DEFAULT_PLAN = "schedule_3"
