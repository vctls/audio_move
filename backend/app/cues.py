"""Cues about the original release, read from local tracks and the folders holding them."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .scoring import Cue, format_cue, format_family, tracks_cue

# Points are on the same scale as MusicBrainz search scores (0-100), so a cue reorders
# releases of the same album without lifting an unrelated one above them.
MEDIA_TAG_POINTS = 20
FOLDER_NAME_POINTS = 12
TRACK_COUNT_POINTS = 10
RIP_LOG_POINTS = 6
CUE_SHEET_POINTS = 3
NOT_CD_POINTS = -8

_DISC_FOLDER = re.compile(r"^(?:cd|dis[ck])\s*\d+", re.IGNORECASE)
# Underscores separate words in scene-style names, so \b would not do.
_FOLDER_TOKENS = {
    "cd": re.compile(r"(?<![a-z0-9])(?:\d*cd[sm]?\d*|sacd|cdda)(?![a-z0-9])", re.IGNORECASE),
    "vinyl": re.compile(r"(?<![a-z0-9])(?:vinyl|lp|vls)(?![a-z0-9])", re.IGNORECASE),
    "digital": re.compile(r"(?<![a-z0-9])web(?![a-z0-9])", re.IGNORECASE),
    "cassette": re.compile(r"(?<![a-z0-9])cassette(?![a-z0-9])", re.IGNORECASE),
}


def _album_folder(track_dir: str) -> str:
    """The folder named after the album, which is the parent of a 'CD1' or 'Disc 2' folder."""
    return (
        os.path.dirname(track_dir) if _DISC_FOLDER.match(os.path.basename(track_dir)) else track_dir
    )


def _list(folder: str) -> list[str]:
    try:
        return os.listdir(folder)
    except OSError:
        return []


def folder_cues(track_dirs: Iterable[str]) -> list[Cue]:
    track_dirs = set(track_dirs)
    albums = {_album_folder(d) for d in track_dirs}
    cues = []

    names = [os.path.basename(a) for a in albums]
    for family, pattern in _FOLDER_TOKENS.items():
        hit = next((n for n in names if pattern.search(n)), None)
        if hit:
            cues.append(format_cue(family, FOLDER_NAME_POINTS, f'Folder name "{hit}"'))

    files = [f.lower() for d in track_dirs | albums for f in _list(d)]
    if any(f.endswith(".log") for f in files):
        cues.append(format_cue("cd", RIP_LOG_POINTS, "Ripping log in the folder"))
    elif any(f.endswith(".cue") for f in files):
        cues.append(format_cue("cd", CUE_SHEET_POINTS, "Cue sheet in the folder"))
    return cues


def media_tag_cues(tracks: list[Mapping[str, Any]]) -> list[Cue]:
    values = {v for t in tracks for v in (t.get("tags") or {}).get("MEDIA", []) if v}
    by_family = {format_family(v): v for v in values}
    return [
        format_cue(family, MEDIA_TAG_POINTS, f'MEDIA tag is "{value}"')
        for family, value in by_family.items()
        if family != "other"
    ]


def audio_cues(tracks: list[Mapping[str, Any]]) -> list[Cue]:
    lossless = [t.get("info") or {} for t in tracks]
    lossless = [i for i in lossless if i.get("encoding") == "lossless" and i.get("samplerate")]
    if not lossless:
        return []
    # Lossless files keep the source resolution, unlike lossy ones resampled by the encoder.
    if all(i.get("bitspersample", 0) > 16 or i["samplerate"] != 44100 for i in lossless):
        i = lossless[0]
        desc = f"{i.get('bitspersample') or '?'}-bit/{i['samplerate'] / 1000:g} kHz"
        return [format_cue("cd", NOT_CD_POINTS, f"{desc} audio cannot come from a CD")]
    return []


def collect_cues(tracks: list[Mapping[str, Any]]) -> list[Cue]:
    """Cues from tracks given as {path, tags, info}, whose paths must already be trusted."""
    if not tracks:
        return []
    return [
        *media_tag_cues(tracks),
        *folder_cues(os.path.dirname(t["path"]) for t in tracks),
        *audio_cues(tracks),
        tracks_cue(len(tracks), TRACK_COUNT_POINTS, f"{len(tracks)} tracks, like the local files"),
    ]
