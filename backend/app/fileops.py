"""Planning and running foobar2000-style move/copy/rename operations."""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from .config import PathError, Roots
from .tags import TagError, is_audio, read_track
from .titleformat import Context, compile_format, evaluate_nodes

Operation = Literal["move", "copy", "rename"]
Status = Literal["ok", "unchanged", "exists", "duplicate", "error"]

# Characters Windows refuses in file names. Replacing them keeps the library
# usable over SMB, as foobar2000 does.
_ILLEGAL = set('<>:"|?*')
_MAX_NAME_BYTES = 255


@dataclass
class PlanItem:
    src: str
    dst: str
    kind: Literal["track", "other"]
    status: Status = "ok"
    message: str = ""


@dataclass
class Plan:
    operation: Operation
    items: list[PlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "items": [asdict(i) for i in self.items],
            "warnings": self.warnings,
        }


def _truncate_bytes(s: str, limit: int) -> str:
    encoded = s.encode("utf-8")
    if len(encoded) <= limit:
        return s
    return encoded[:limit].decode("utf-8", "ignore").rstrip()


def clean_component(part: str, replacement: str) -> str:
    part = "".join(replacement if ch in _ILLEGAL or ord(ch) < 32 else ch for ch in part)
    # Windows strips trailing dots and spaces, which would break SMB clients.
    part = part.strip().rstrip(". ")
    return "" if part in ("", ".", "..") else part


def destination_parts(template: str, track: dict[str, Any], replacement: str) -> list[str]:
    """Evaluate a file name pattern into cleaned path components, extension included."""
    src = track["path"]

    def field_filter(v: str) -> str:
        return v.replace("/", replacement).replace("\\", replacement)

    ctx = Context(track["tags"], track["info"], src, field_filter=field_filter)
    text, _ = evaluate_nodes(compile_format(template), ctx)
    parts = [clean_component(p, replacement) for p in text.replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("The pattern produced an empty file name")
    ext = os.path.splitext(src)[1]
    stem = parts[-1]
    # foobar2000 appends the extension itself, but tolerate patterns that add it.
    if ext and stem.lower().endswith(ext.lower()):
        stem = stem[: -len(ext)].rstrip(". ") or stem
    stem = _truncate_bytes(stem, _MAX_NAME_BYTES - len(ext.encode("utf-8")))
    parts = [_truncate_bytes(p, _MAX_NAME_BYTES) for p in parts[:-1]] + [stem + ext]
    return parts


def _samefile(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _mark_conflicts(items: list[PlanItem]) -> None:
    seen: set[str] = set()
    for item in items:
        if item.status not in ("ok", "unchanged"):
            continue
        if item.dst == item.src:
            item.status = "unchanged"
        elif os.path.lexists(item.dst) and not _samefile(item.src, item.dst):
            item.status = "exists"
            item.message = "Destination already exists"
        if item.dst in seen and item.status in ("ok", "exists"):
            item.status = "duplicate"
            item.message = "Another file in this batch has the same destination"
        seen.add(item.dst)


def _contains_audio(path: str) -> bool:
    for _dirpath, _dirnames, filenames in os.walk(path):
        if any(is_audio(f) for f in filenames):
            return True
    return False


def _is_within(path: str, ancestor: str) -> bool:
    return path == ancestor or path.startswith(ancestor.rstrip("/") + "/")


def _other_files(
    tracks: list[PlanItem], base_dir: str | None, roots: Roots, dest_root: str | None
) -> tuple[list[PlanItem], list[str]]:
    items: list[PlanItem] = []
    warnings: list[str] = []
    track_dirs = {os.path.dirname(t.src) for t in tracks}
    source_dirs = set(track_dirs)
    if base_dir and all(_is_within(d, base_dir) for d in track_dirs):
        for d in track_dirs:
            while d != base_dir and _is_within(d, base_dir):
                source_dirs.add(d)
                d = os.path.dirname(d)
        source_dirs.add(base_dir)

    for src_dir in sorted(source_dirs):
        dst_dirs = sorted(
            {os.path.dirname(t.dst) for t in tracks if _is_within(os.path.dirname(t.src), src_dir)}
        )
        if len(dst_dirs) == 1:
            target = dst_dirs[0]
        else:
            target = os.path.commonpath(dst_dirs)
            if (
                roots.is_root(target)
                or target == dest_root
                or (dest_root and not _is_within(target, dest_root))
            ):
                warnings.append(
                    f"Other files in {src_dir} were left in place: its tracks go to unrelated folders"
                )
                continue
        if target == src_dir:
            continue
        try:
            entries = sorted(os.scandir(src_dir), key=lambda e: e.name)
        except OSError as e:
            warnings.append(f"Cannot list {src_dir}: {e}")
            continue
        for entry in entries:
            path = entry.path
            if entry.is_dir(follow_symlinks=False):
                if path in source_dirs or _is_within(target, path) or _contains_audio(path):
                    continue
            elif is_audio(entry.name):
                continue
            items.append(PlanItem(path, os.path.join(target, entry.name), "other"))
    return items, warnings


def plan_operation(
    roots: Roots,
    paths: Iterable[str],
    template: str,
    operation: Operation,
    destination: str,
    move_other_files: bool,
    base_dir: str | None,
    replacement: str,
    reader: Callable[[str], dict[str, Any]] = read_track,
) -> Plan:
    plan = Plan(operation)
    dest_root = None if operation == "rename" else roots.resolve(destination)
    base = roots.resolve(base_dir) if base_dir else None
    for p in paths:
        src = roots.resolve(p)
        try:
            parts = destination_parts(template, reader(src), replacement)
        except (TagError, ValueError) as e:
            plan.items.append(PlanItem(src, "", "track", "error", str(e)))
            continue
        dst = os.path.join(dest_root or os.path.dirname(src), *parts)
        if not roots.contains(os.path.dirname(dst)) and not roots.contains(dst):
            plan.items.append(
                PlanItem(src, dst, "track", "error", "Destination is outside the music folders")
            )
            continue
        plan.items.append(PlanItem(src, dst, "track"))
    _mark_conflicts(plan.items)
    if move_other_files:
        tracks = [i for i in plan.items if i.status in ("ok", "unchanged")]
        if tracks:
            others, warnings = _other_files(tracks, base, roots, dest_root)
            plan.items.extend(others)
            plan.warnings.extend(warnings)
            _mark_conflicts(plan.items)
    return plan


def _move(src: str, dst: str) -> None:
    try:
        os.rename(src, dst)
    except OSError:
        shutil.move(src, dst)


def _remove_empty_dirs(
    candidates: set[str], base_dir: str | None, roots: Roots, protected: list[str]
) -> list[str]:
    dirs: set[str] = set()
    for d in candidates:
        dirs.add(d)
        if base_dir and _is_within(d, base_dir):
            while d != base_dir:
                d = os.path.dirname(d)
                dirs.add(d)
    removed: list[str] = []
    for d in sorted(dirs, key=lambda x: x.count("/"), reverse=True):
        if roots.is_root(d) or not roots.contains(d):
            continue
        if any(_is_within(p, d) for p in protected):
            continue
        try:
            os.rmdir(d)
            removed.append(d)
        except OSError:
            pass
    return removed


def _makedirs(path: str, created: list[str]) -> None:
    missing = []
    d = path
    while d and d != "/" and not os.path.isdir(d):
        missing.append(d)
        d = os.path.dirname(d)
    os.makedirs(path, exist_ok=True)
    created.extend(reversed(missing))


def execute_plan(
    plan: Plan, roots: Roots, remove_empty: bool, base_dir: str | None
) -> dict[str, Any]:
    done: list[PlanItem] = []
    created: list[str] = []
    for item in plan.items:
        if item.status != "ok":
            continue
        try:
            if os.path.lexists(item.dst) and not _samefile(item.src, item.dst):
                raise FileExistsError("Destination already exists")
            _makedirs(os.path.dirname(item.dst), created)
            if plan.operation == "copy":
                if os.path.isdir(item.src) and not os.path.islink(item.src):
                    shutil.copytree(item.src, item.dst, symlinks=True)
                else:
                    shutil.copy2(item.src, item.dst)
            else:
                _move(item.src, item.dst)
            done.append(item)
        except OSError as e:
            item.status = "error"
            item.message = e.strerror or str(e)
    removed: list[str] = []
    if plan.operation != "copy" and remove_empty and done:
        base = roots.resolve(base_dir) if base_dir else None
        removed = _remove_empty_dirs(
            {os.path.dirname(i.src) for i in done}, base, roots, [i.dst for i in done]
        )
    return {
        "plan": plan.to_dict(),
        "done": [asdict(i) for i in done],
        "removed_dirs": removed,
        "created_dirs": created,
    }


class Journal:
    """History of move/rename batches so the last ones can be undone."""

    def __init__(self, config_dir: str, keep: int = 50):
        self.path = os.path.join(config_dir, "journal.json")
        self.keep = keep
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries[-self.keep :], f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def add(
        self,
        operation: str,
        done: list[dict[str, Any]],
        removed_dirs: list[str],
        created_dirs: list[str],
    ) -> str:
        entry = {
            "id": uuid.uuid4().hex,
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "operation": operation,
            "moves": [{"src": d["src"], "dst": d["dst"], "kind": d["kind"]} for d in done],
            "removed_dirs": removed_dirs,
            "created_dirs": created_dirs,
            "undone": False,
        }
        with self._lock:
            entries = self._load()
            entries.append(entry)
            self._save(entries)
        return entry["id"]

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._load()))

    def undo(self, entry_id: str, roots: Roots) -> dict[str, Any]:
        with self._lock:
            entries = self._load()
            entry = next((e for e in entries if e["id"] == entry_id), None)
            if entry is None:
                raise KeyError(entry_id)
            if entry["undone"]:
                raise ValueError("This operation was already undone")
            restored, errors = [], []
            for m in reversed(entry["moves"]):
                src, dst = m["src"], m["dst"]
                try:
                    roots.resolve(src)
                    roots.resolve(dst)
                    if not os.path.lexists(dst):
                        raise FileNotFoundError(f"{dst} no longer exists")
                    if os.path.lexists(src):
                        raise FileExistsError(f"{src} already exists")
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    _move(dst, src)
                    restored.append(m)
                except (OSError, PathError) as e:
                    errors.append({"src": src, "dst": dst, "error": str(e)})
            removed = []
            for d in sorted(
                entry.get("created_dirs", []), key=lambda x: x.count("/"), reverse=True
            ):
                if roots.contains(d) and not roots.is_root(d):
                    try:
                        os.rmdir(d)
                        removed.append(d)
                    except OSError:
                        pass
            entry["undone"] = True
            self._save(entries)
        return {"restored": restored, "errors": errors, "removed_dirs": removed}
