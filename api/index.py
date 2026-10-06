"""Vercel entrypoint. The app itself still lives in backend/."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# This file lives in a folder named api/. Drop that package so `import api`
# loads backend/api.py, which is what the FastAPI app imports.
_running = __name__
for _name in list(sys.modules):
    if _name != _running and (_name == "api" or _name.startswith("api.")):
        sys.modules.pop(_name, None)

from main import app  # noqa: E402

__all__ = ["app"]
