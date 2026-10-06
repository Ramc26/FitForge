"""FitForge API and the static app. Run this from the backend directory."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from api import router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fitforge")

app = FastAPI(title="FitForge", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.middleware("http")
async def revalidate_assets(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/css/", "/js/")):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def unhandled(_request, exc):
    if isinstance(exc, HTTPException):
        raise exc
    log.exception("request failed")
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong. Try again."},
    )


_FILES = {
    "index.html": "text/html",
    "manifest.json": "application/manifest+json",
    "sw.js": "application/javascript",
    "data.json": "application/json",
}


def _file(name: str):
    path = config.ROOT / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file is missing.")
    headers = {"Cache-Control": "no-cache"} if name in {"index.html", "sw.js", "data.json"} else None
    return FileResponse(path, media_type=_FILES[name], headers=headers)


@app.get("/")
def root():
    return _file("index.html")


for _name in _FILES:
    def _bind(filename: str):
        def endpoint():
            return _file(filename)

        return endpoint

    app.add_api_route(
        f"/{_name}",
        _bind(_name),
        methods=["GET"],
        include_in_schema=False,
        name=f"static_{_name.replace('.', '_')}",
    )


for _folder in ("css", "js", "images"):
    _directory = config.ROOT / _folder
    _directory.mkdir(exist_ok=True)
    app.mount(f"/{_folder}", StaticFiles(directory=_directory), name=_folder)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    icon = config.ROOT / "images" / "forge-icon.svg"
    if icon.is_file():
        return FileResponse(icon, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="No icon.")
