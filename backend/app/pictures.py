"""Embedded pictures: listing, removal, and extraction to a folder image."""

from __future__ import annotations

import base64
import logging
import os
import struct
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import mutagen
from mutagen.apev2 import APEBinaryValue, APEv2File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4, MP4Cover

logger = logging.getLogger(__name__)

# ID3 APIC and FLAC share this numbering.
PICTURE_TYPES = {
    0: "other",
    1: "icon",
    2: "icon",
    3: "front",
    4: "back",
    5: "leaflet",
    6: "media",
    7: "lead artist",
    8: "artist",
    9: "conductor",
    10: "band",
    11: "composer",
    12: "lyricist",
    13: "location",
    14: "recording",
    15: "performance",
    16: "screen capture",
    18: "illustration",
    19: "band logo",
    20: "publisher logo",
}
FOLDER_IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png"}
_FOLDER_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
_VORBIS_PICTURE_KEYS = ("METADATA_BLOCK_PICTURE", "COVERART", "COVERARTMIME")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass
class EmbeddedPicture:
    type: str
    mime: str
    data: bytes

    def summary(self) -> dict[str, Any]:
        width, height = image_size(self.data)
        return {
            "type": self.type,
            "mime": self.mime,
            "width": width,
            "height": height,
            "size": len(self.data),
        }


def sniff_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == _PNG_SIGNATURE:
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return ""


def image_size(data: bytes) -> tuple[int, int]:
    """Return (width, height) from a PNG, JPEG or GIF header, or (0, 0)."""
    if data[:8] == _PNG_SIGNATURE and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:2] != b"\xff\xd8":
        return 0, 0
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return 0, 0


def _picture(type_id: int, declared_mime: str, data: bytes) -> EmbeddedPicture:
    return EmbeddedPicture(
        PICTURE_TYPES.get(int(type_id), f"type {int(type_id)}"),
        sniff_mime(data) or declared_mime or "application/octet-stream",
        data,
    )


def _vorbis_pictures(tags) -> list[EmbeddedPicture]:
    out = []
    for b64 in tags.get("METADATA_BLOCK_PICTURE", []):
        try:
            pic = Picture(base64.b64decode(b64))
        except (ValueError, TypeError, mutagen.MutagenError):
            continue
        out.append(_picture(pic.type, pic.mime, pic.data))
    mimes = tags.get("COVERARTMIME", [])
    for i, b64 in enumerate(tags.get("COVERART", [])):
        try:
            data = base64.b64decode(b64)
        except ValueError:
            continue
        out.append(_picture(3, mimes[i] if i < len(mimes) else "", data))
    return out


def _ape_cover_type(key: str) -> int:
    k = key.lower()
    return 4 if "back" in k else 3 if "front" in k else 0


def embedded_pictures(audio) -> list[EmbeddedPicture]:
    out: list[EmbeddedPicture] = []
    if isinstance(audio, FLAC):
        out += [_picture(p.type, p.mime, p.data) for p in audio.pictures]
    tags = audio.tags
    if tags is None:
        return out
    if isinstance(audio, MP4):
        for cover in tags.get("covr", []):
            declared = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
            out.append(_picture(3, declared, bytes(cover)))
    elif isinstance(tags, ID3):
        out += [_picture(f.type, f.mime, f.data) for f in tags.getall("APIC")]
    elif isinstance(audio, APEv2File):
        for key, value in tags.items():
            if isinstance(value, APEBinaryValue) and key.lower().startswith("cover art"):
                # APEv2 stores "<file name>\0<image bytes>".
                data = bytes(value.value).partition(b"\x00")[2]
                out.append(_picture(_ape_cover_type(key), "", data))
    elif hasattr(tags, "get"):
        out += _vorbis_pictures(tags)
    return out


def remove_pictures(audio) -> bool:
    """Drop every embedded picture. Return True when something was removed."""
    removed = False
    if isinstance(audio, FLAC) and audio.pictures:
        audio.clear_pictures()
        removed = True
    tags = audio.tags
    if tags is None:
        return removed
    if isinstance(audio, MP4):
        removed |= tags.pop("covr", None) is not None
    elif isinstance(tags, ID3):
        if tags.getall("APIC"):
            tags.delall("APIC")
            removed = True
    elif isinstance(audio, APEv2File):
        for key in [k for k, v in tags.items() if isinstance(v, APEBinaryValue)]:
            if key.lower().startswith("cover art"):
                del tags[key]
                removed = True
    else:
        for key in _VORBIS_PICTURE_KEYS:
            if key in tags:
                del tags[key]
                removed = True
    return removed


def compact_padding(info) -> int:
    """mutagen padding callback that gives back the space freed by removed pictures."""
    return info.padding if 0 <= info.padding <= 8192 else 1024


# --- folder images ---------------------------------------------------------------


def find_folder_images(directory: str, stem: str) -> list[str]:
    wanted = {stem.lower() + suffix for suffix in _FOLDER_IMAGE_SUFFIXES}
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    return [os.path.join(directory, n) for n in names if n.lower() in wanted]


def folder_image_info(directory: str, stem: str) -> dict[str, Any] | None:
    found = find_folder_images(directory, stem)
    if not found:
        return None
    path = found[0]
    try:
        with open(path, "rb") as f:
            head = f.read(1 << 20)
        size = os.path.getsize(path)
    except OSError:
        return None
    width, height = image_size(head)
    return {
        "names": [os.path.basename(p) for p in found],
        "width": width,
        "height": height,
        "size": size,
    }


def extract_folder_images(paths: list[str], stem: str) -> list[dict[str, Any]]:
    """Write the best embedded front cover of each folder as <stem>.jpg or .png.

    Folders that already have a folder image are skipped. Nothing is overwritten.
    """
    by_dir: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        by_dir[os.path.dirname(p)].append(p)
    results: list[dict[str, Any]] = []
    for directory, files in sorted(by_dir.items()):
        existing = find_folder_images(directory, stem)
        if existing:
            results.append(
                {
                    "dir": directory,
                    "ok": False,
                    "skipped": True,
                    "message": f"{os.path.basename(existing[0])} already exists",
                }
            )
            continue
        best: tuple[tuple[bool, int], EmbeddedPicture] | None = None
        for path in files:
            try:
                audio = mutagen.File(path)
            except (mutagen.MutagenError, OSError) as e:
                logger.warning("Cannot read pictures from %s: %s", path, e)
                continue
            for pic in embedded_pictures(audio) if audio else []:
                if pic.mime not in FOLDER_IMAGE_EXTENSIONS:
                    continue
                score = (pic.type == "front", len(pic.data))
                if best is None or score > best[0]:
                    best = (score, pic)
        if best is None:
            results.append(
                {"dir": directory, "ok": False, "message": "No embedded JPEG or PNG picture"}
            )
            continue
        pic = best[1]
        target = os.path.join(directory, stem + FOLDER_IMAGE_EXTENSIONS[pic.mime])
        try:
            with open(target, "xb") as f:
                f.write(pic.data)
            results.append({"dir": directory, "ok": True, "path": target})
        except OSError as e:
            logger.warning("Cannot write %s: %s", target, e)
            results.append({"dir": directory, "ok": False, "message": e.strerror or str(e)})
    return results


def save_folder_image(directory: str, stem: str, data: bytes, overwrite: bool) -> dict[str, Any]:
    """Store downloaded cover art as <stem>.jpg or .png, keeping a single folder image."""
    ext = FOLDER_IMAGE_EXTENSIONS.get(sniff_mime(data))
    if not ext:
        return {"path": directory, "ok": False, "error": "The image is neither JPEG nor PNG"}
    target = os.path.join(directory, stem + ext)
    existing = find_folder_images(directory, stem)
    if existing and not overwrite:
        name = os.path.basename(existing[0])
        return {"path": target, "ok": False, "error": f"{name} already exists"}
    try:
        with open(target, "wb") as f:
            f.write(data)
        for other in existing:
            if other != target:
                os.remove(other)
    except OSError as e:
        logger.warning("Cannot save cover art to %s: %s", target, e)
        return {"path": target, "ok": False, "error": e.strerror or str(e)}
    return {"path": target, "ok": True}
