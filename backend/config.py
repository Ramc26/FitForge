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

SPREADSHEET_ID = os.getenv(
    "GOOGLE_SPREADSHEET_ID",
    "1OgPkbTnC1NninCscb8pDaTNTaw8D9TzCic5e72ad95w",
)

# Service-account auth is what actually works today (see sheets.py).
# The OAuth client vars are accepted so a later login flow has a place to live.
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    str(ROOT / "sam-agent-506413-b67261b92c1c.json"),
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
