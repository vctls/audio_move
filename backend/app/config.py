from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_PATTERN = (
    "%album artist% - %year% - %album% '['$caps(%codec%)']'/%track number% - %artist% - %title%"
)


class Settings(BaseModel):
    patterns: list[str] = Field(default_factory=lambda: [DEFAULT_PATTERN])
    pattern: str = DEFAULT_PATTERN
    operation: Literal["move", "copy", "rename"] = "move"
    destination: str = ""
    move_other_files: bool = True
    remove_empty_dirs: bool = True
    replacement: str = "_"
    # Folder images are <cover_name>.jpg or <cover_name>.png.
    cover_name: str = "folder"
    multivalue_fields: list[str] = Field(
        default_factory=lambda: [
            "ARTIST",
            "ALBUM ARTIST",
            "PRODUCER",
            "COMPOSER",
            "PERFORMER",
            "GENRE",
        ]
    )
    id3_version: Literal[3, 4] = 4
    vorbis_albumartist_key: Literal["ALBUMARTIST", "ALBUM ARTIST"] = "ALBUMARTIST"
    track_padding: int = Field(2, ge=0, le=4)
    autonumber_total: bool = True
    autonumber_per_disc: bool = True
    mb_date: Literal["year", "full"] = "year"
    mb_groups: list[str] = Field(default_factory=lambda: ["basic", "release", "ids"])
    mb_disc_for_single: bool = False
    mb_cover: bool = False
    mb_cover_size: Literal["500", "1200", "original"] = "1200"
    mb_cover_overwrite: bool = False
    guess_patterns: list[str] = Field(
        default_factory=lambda: [
            "%tracknumber% - %artist% - %title%",
            "%tracknumber% - %title%",
            "%tracknumber%. %title%",
            "%album artist% - %album%/%tracknumber% - %title%",
        ]
    )
    format_presets: list[str] = Field(
        default_factory=lambda: ["$caps2(%title%)", "$trim(%title%)", "%artist%"]
    )

    @field_validator("cover_name")
    @classmethod
    def _plain_cover_name(cls, v: str) -> str:
        v = v.strip()
        for suffix in (".jpg", ".jpeg", ".png"):
            if v.lower().endswith(suffix):
                v = v[: -len(suffix)]
        if not v or any(c in v for c in '/\\<>:"|?*') or v in (".", ".."):
            raise ValueError("Invalid cover file name")
        return v

    @field_validator("replacement")
    @classmethod
    def _safe_replacement(cls, v: str) -> str:
        if any(c in v for c in '/\\<>:"|?*') or any(ord(c) < 32 for c in v):
            raise ValueError(
                "The replacement cannot contain characters that are illegal in file names"
            )
        return v


@dataclass(frozen=True)
class AppConfig:
    roots: tuple[str, ...]
    config_dir: str
    static_dir: str
    user_agent: str
    max_tracks: int

    @classmethod
    def from_env(cls) -> AppConfig:
        raw = os.environ.get("MUSIC_ROOTS", "/music")
        roots = tuple(
            os.path.realpath(p.strip()) for p in raw.replace(";", ",").split(",") if p.strip()
        )
        contact = os.environ.get("MB_CONTACT", "https://github.com/").strip()
        return cls(
            roots=roots,
            config_dir=os.environ.get("CONFIG_DIR", "/config"),
            static_dir=os.environ.get(
                "STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static")
            ),
            user_agent=f"audio-move/0.1 ( {contact} )",
            max_tracks=int(os.environ.get("MAX_TRACKS", "5000")),
        )


class SettingsStore:
    def __init__(self, config_dir: str):
        self.path = os.path.join(config_dir, "settings.json")
        self._lock = threading.Lock()

    def load(self) -> Settings:
        with self._lock:
            try:
                with open(self.path, encoding="utf-8") as f:
                    return Settings.model_validate(json.load(f))
            except FileNotFoundError:
                return Settings()
            except (OSError, ValueError) as e:
                logger.error("Cannot load %s, using default settings: %s", self.path, e)
                return Settings()

    def save(self, settings: Settings) -> Settings:
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(settings.model_dump(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        return settings


class PathError(Exception):
    pass


class Roots:
    def __init__(self, roots: tuple[str, ...]):
        self.roots = roots

    def resolve(self, path: str) -> str:
        """Return the real path, refusing anything outside the configured roots."""
        if not path or not os.path.isabs(path):
            raise PathError(f"Not an absolute path: {path!r}")
        real = os.path.realpath(path)
        for root in self.roots:
            if real == root or real.startswith(root.rstrip("/") + "/"):
                return real
        raise PathError(f"Path is outside the music folders: {path}")

    def is_root(self, path: str) -> bool:
        return os.path.realpath(path) in self.roots

    def contains(self, path: str) -> bool:
        try:
            self.resolve(path)
            return True
        except PathError:
            return False
