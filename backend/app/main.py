from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .config import AppConfig, PathError, Roots, Settings, SettingsStore
from .fileops import Journal, execute_plan, plan_operation
from .guess import guess
from .musicbrainz import (
    MusicBrainzClient,
    MusicBrainzError,
    TagOptions,
    build_query,
    parse_mbid,
    release_with_tags,
)
from .pictures import extract_folder_images, folder_image_info, save_folder_image
from .tags import TagError, WriteOptions, is_audio, read_track, write_track
from .titleformat import Context, format_track

# uvicorn only configures its own loggers, so app.* messages need a root handler.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

cfg = AppConfig.from_env()
roots = Roots(cfg.roots)
settings_store = SettingsStore(cfg.config_dir)
journal = Journal(cfg.config_dir)
io_pool = ThreadPoolExecutor(max_workers=8)
state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state["mb"] = MusicBrainzClient(cfg.user_agent)
    yield
    await state["mb"].close()


app = FastAPI(title="audio-move", lifespan=lifespan)


@app.exception_handler(PathError)
async def _path_error(req: Request, exc: PathError):
    logger.warning("%s %s: %s", req.method, req.url, exc)
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(MusicBrainzError)
async def _mb_error(req: Request, exc: MusicBrainzError):
    logger.warning("%s %s: %s", req.method, req.url, exc)
    return JSONResponse({"detail": str(exc)}, status_code=502)


def _natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _root_name(root: str) -> str:
    return os.path.basename(root.rstrip("/")) or root


# --- browsing ----------------------------------------------------------------------


class PathsBody(BaseModel):
    paths: list[str]


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "roots": [{"name": _root_name(r), "path": r} for r in cfg.roots],
        "max_tracks": cfg.max_tracks,
    }


@app.get("/api/browse")
def browse(path: str = "") -> dict[str, Any]:
    """List subfolder names only.

    On a NAS every scandir is a round trip, so the client asks for summaries of
    the folders it actually shows.
    """
    if not path:
        return {"path": "", "dirs": [{"name": _root_name(r), "path": r} for r in cfg.roots]}
    real = roots.resolve(path)
    try:
        with os.scandir(real) as it:
            names = [e.name for e in it if not e.name.startswith(".") and e.is_dir()]
    except OSError as e:
        logger.warning("Cannot open folder %s: %s", real, e)
        raise HTTPException(400, f"Cannot open folder: {e.strerror}") from e
    names.sort(key=_natural_key)
    return {"path": real, "dirs": [{"name": n, "path": os.path.join(real, n)} for n in names]}


def _dir_summary(path: str) -> dict[str, Any]:
    has_children = False
    audio = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if e.is_dir():
                    has_children = True
                elif is_audio(e.name):
                    audio += 1
    except OSError as e:
        logger.warning("Cannot list %s: %s", path, e)
    return {"has_children": has_children, "audio": audio}


@app.post("/api/browse/summary")
def browse_summary(body: PathsBody) -> dict[str, Any]:
    paths = [p for p in body.paths[:200] if roots.contains(p)]
    summaries = io_pool.map(lambda p: _dir_summary(roots.resolve(p)), paths)
    return {"summaries": dict(zip(paths, summaries, strict=True))}


class TooManyTracks(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _collect_audio(path: str, recursive: bool, limit: int) -> list[str]:
    """List audio files in path, raising TooManyTracks as soon as the limit is passed.

    Stopping early keeps an accidental click on a whole library cheap.
    """
    found: list[str] = []
    if not recursive:
        names = sorted(os.listdir(path), key=_natural_key)
        found = [
            os.path.join(path, n)
            for n in names
            if is_audio(n) and os.path.isfile(os.path.join(path, n))
        ]
        if len(found) > limit:
            raise TooManyTracks("tracks")
        return found
    for visited, (dirpath, dirnames, filenames) in enumerate(os.walk(path)):
        if visited > 2 * limit:
            raise TooManyTracks("folders")
        dirnames[:] = sorted((d for d in dirnames if not d.startswith(".")), key=_natural_key)
        for n in sorted(filenames, key=_natural_key):
            if is_audio(n):
                found.append(os.path.join(dirpath, n))
                if len(found) > limit:
                    raise TooManyTracks("tracks")
    return found


def _read_many(paths: list[str]) -> tuple[list[dict], list[dict]]:
    def safe_read(p: str):
        try:
            return read_track(p), None
        except (TagError, OSError) as e:
            logger.warning("Cannot read %s: %s", p, e)
            return None, {"path": p, "error": str(e)}

    tracks, errors = [], []
    for track, err in io_pool.map(safe_read, paths):
        if track:
            tracks.append(track)
        else:
            errors.append(err)
    return tracks, errors


def _with_folder_images(tracks: list[dict]) -> list[dict]:
    stem = settings_store.load().cover_name
    cache: dict[str, dict | None] = {}
    for t in tracks:
        d = os.path.dirname(t["path"])
        if d not in cache:
            cache[d] = folder_image_info(d, stem)
        t["folder_image"] = cache[d]
    return tracks


@app.get("/api/tracks")
def list_tracks(path: str, recursive: bool = True, force: bool = False) -> dict[str, Any]:
    real = roots.resolve(path)
    limit = cfg.max_tracks if force else cfg.large_folder_tracks
    try:
        paths = [real] if os.path.isfile(real) else _collect_audio(real, recursive, limit)
    except TooManyTracks as e:
        return {
            "tracks": [],
            "errors": [],
            "too_many": True,
            "reason": e.reason,
            "limit": limit,
            "forced": force,
        }
    tracks, errors = _read_many(paths)
    return {"tracks": _with_folder_images(tracks), "errors": errors, "too_many": False}


@app.post("/api/tracks/read")
def read_tracks(body: PathsBody) -> dict[str, Any]:
    tracks, errors = _read_many([roots.resolve(p) for p in body.paths])
    return {"tracks": _with_folder_images(tracks), "errors": errors}


# --- tags ----------------------------------------------------------------------------


class TagChange(BaseModel):
    path: str
    set: dict[str, list[str]] = Field(default_factory=dict)
    remove: list[str] = Field(default_factory=list)
    remove_pictures: bool = False


class SaveBody(BaseModel):
    items: list[TagChange]


@app.post("/api/tags")
def save_tags(body: SaveBody) -> dict[str, Any]:
    s = settings_store.load()
    opts = WriteOptions(id3_version=s.id3_version, vorbis_albumartist_key=s.vorbis_albumartist_key)

    def save_one(item: TagChange) -> dict[str, Any]:
        try:
            path = roots.resolve(item.path)
            return {
                "path": item.path,
                "ok": True,
                "track": write_track(path, item.set, item.remove, opts, item.remove_pictures),
            }
        except (TagError, OSError, PathError) as e:
            logger.warning("Cannot save tags to %s: %s", item.path, e)
            return {"path": item.path, "ok": False, "error": str(e)}

    results = list(io_pool.map(save_one, body.items))
    _with_folder_images([r["track"] for r in results if r["ok"]])
    return {"results": results}


@app.post("/api/pictures/extract")
def extract_pictures(body: PathsBody) -> dict[str, Any]:
    paths = [roots.resolve(p) for p in body.paths]
    return {"results": extract_folder_images(paths, settings_store.load().cover_name)}


class FormatItem(BaseModel):
    path: str
    tags: dict[str, list[str]]
    info: dict[str, Any] = Field(default_factory=dict)


class FormatBody(BaseModel):
    template: str
    items: list[FormatItem]


@app.post("/api/format")
def format_values(body: FormatBody) -> dict[str, Any]:
    return {
        "results": [
            format_track(body.template, Context(i.tags, i.info, i.path)) for i in body.items
        ]
    }


class GuessBody(BaseModel):
    pattern: str
    paths: list[str]


@app.post("/api/guess")
def guess_values(body: GuessBody) -> dict[str, Any]:
    return {"results": [guess(body.pattern, p) for p in body.paths]}


# --- file operations -------------------------------------------------------------------


class FileOpBody(BaseModel):
    paths: list[str]
    pattern: str
    operation: Literal["move", "copy", "rename"]
    destination: str = ""
    move_other_files: bool = True
    remove_empty_dirs: bool = True
    base_dir: str | None = None


def _plan(body: FileOpBody):
    if not body.pattern.strip():
        raise HTTPException(400, "The file name pattern is empty")
    if body.operation != "rename" and not body.destination:
        raise HTTPException(400, "Choose a destination folder")
    s = settings_store.load()
    return plan_operation(
        roots,
        body.paths,
        body.pattern,
        body.operation,
        body.destination,
        body.move_other_files,
        body.base_dir,
        s.replacement,
    )


@app.post("/api/fileops/preview")
def fileops_preview(body: FileOpBody) -> dict[str, Any]:
    return _plan(body).to_dict()


@app.post("/api/fileops/execute")
def fileops_execute(body: FileOpBody) -> dict[str, Any]:
    plan = _plan(body)
    result = execute_plan(plan, roots, body.remove_empty_dirs, body.base_dir)
    if body.operation != "copy" and result["done"]:
        result["journal_id"] = journal.add(
            body.operation, result["done"], result["removed_dirs"], result["created_dirs"]
        )
    return result


@app.get("/api/fileops/history")
def fileops_history() -> list[dict[str, Any]]:
    return [
        {
            "id": e["id"],
            "time": e["time"],
            "operation": e["operation"],
            "count": len(e["moves"]),
            "undone": e["undone"],
            "sample": e["moves"][0] if e["moves"] else None,
        }
        for e in journal.list()
    ]


class UndoBody(BaseModel):
    id: str


@app.post("/api/fileops/undo")
def fileops_undo(body: UndoBody) -> dict[str, Any]:
    try:
        return journal.undo(body.id, roots)
    except KeyError as e:
        raise HTTPException(404, "Unknown operation") from e
    except ValueError as e:
        logger.warning("Cannot undo %s: %s", body.id, e)
        raise HTTPException(400, str(e)) from e


# --- settings ---------------------------------------------------------------------------


@app.get("/api/settings")
def get_settings() -> Settings:
    s = settings_store.load()
    if not s.destination and cfg.roots:
        s.destination = cfg.roots[0]
    return s


@app.put("/api/settings")
def put_settings(s: Settings) -> Settings:
    return settings_store.save(s)


# --- MusicBrainz ----------------------------------------------------------------------------


@app.get("/api/mb/search")
async def mb_search(
    artist: str = "", album: str = "", query: str = "", offset: int = 0
) -> dict[str, Any]:
    mb: MusicBrainzClient = state["mb"]
    text = query.strip()
    if text and parse_mbid(text):
        return await mb.lookup(text)
    q = text or build_query(artist, album)
    if not q:
        raise HTTPException(400, "Enter an artist, an album or a query")
    return {**(await mb.search(q, offset=offset)), "query": q}


@app.get("/api/mb/release/{mbid}")
async def mb_release(
    mbid: str,
    date: Literal["year", "full"] = "year",
    groups: str = "basic,release,ids",
    disc_for_single: bool = False,
    padding: int = 2,
) -> dict[str, Any]:
    mb: MusicBrainzClient = state["mb"]
    release = await mb.release(mbid)
    opts = TagOptions(
        date=date,
        groups={g for g in groups.split(",") if g},
        disc_for_single=disc_for_single,
        padding=max(0, min(padding, 4)),
    )
    return release_with_tags(release, opts)


class CoverBody(BaseModel):
    release_id: str
    dirs: list[str]
    size: Literal["500", "1200", "original"] = "1200"
    overwrite: bool = False


@app.post("/api/mb/cover")
async def mb_cover(body: CoverBody) -> dict[str, Any]:
    stem = settings_store.load().cover_name
    dirs = [roots.resolve(d) for d in dict.fromkeys(body.dirs)]
    data = await state["mb"].cover(body.release_id, body.size)

    def save_all() -> list[dict[str, Any]]:
        return [save_folder_image(d, stem, data, body.overwrite) for d in dirs]

    return {"results": await run_in_threadpool(save_all)}


if os.path.isdir(cfg.static_dir):
    app.mount("/", StaticFiles(directory=cfg.static_dir, html=True), name="static")
