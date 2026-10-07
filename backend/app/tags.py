"""Reading and writing tags through mutagen, using foobar2000-style field names.

Every format is exposed as a dict of UPPERCASE field name -> list of values.
Track and disc numbers are always split into TRACKNUMBER/TOTALTRACKS and
DISCNUMBER/TOTALDISCS, whatever the storage format.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import mutagen
from mutagen.aiff import AIFF
from mutagen.apev2 import APEBinaryValue, APEv2File
from mutagen.dsf import DSF
from mutagen.flac import FLAC
from mutagen.id3 import COMM, ID3, TXXX, UFID, USLT, Frames
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggflac import OggFLAC
from mutagen.oggopus import OggOpus
from mutagen.oggspeex import OggSpeex
from mutagen.oggvorbis import OggVorbis
from mutagen.trueaudio import TrueAudio
from mutagen.wave import WAVE

from .pictures import compact_padding, embedded_pictures, remove_pictures

AUDIO_EXTENSIONS = {
    ".flac",
    ".mp3",
    ".m4a",
    ".m4b",
    ".mp4",
    ".ogg",
    ".oga",
    ".opus",
    ".spx",
    ".ape",
    ".wv",
    ".mpc",
    ".wav",
    ".aif",
    ".aiff",
    ".aifc",
    ".dsf",
    ".tta",
}

LOSSLESS_CODECS = {"FLAC", "ALAC", "PCM", "Monkey's Audio", "WavPack", "DSD", "TTA"}

NUMBER_PAIRS = {
    "TRACKNUMBER": "TOTALTRACKS",
    "TOTALTRACKS": "TRACKNUMBER",
    "DISCNUMBER": "TOTALDISCS",
    "TOTALDISCS": "DISCNUMBER",
}

_FIELD_NAME_RE = re.compile(r"^[\x20-\x3C\x3E-\x7D]+$")


class TagError(Exception):
    pass


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def valid_field_name(name: str) -> bool:
    return bool(name.strip()) and bool(_FIELD_NAME_RE.match(name))


@dataclass
class WriteOptions:
    id3_version: int = 4
    vorbis_albumartist_key: str = "ALBUMARTIST"


def _add(out: dict[str, list[str]], key: str, values) -> None:
    vals = [str(v) for v in values if v is not None and str(v) != ""]
    if vals:
        out.setdefault(key, []).extend(vals)


def _split_numbers(tags: dict[str, list[str]]) -> dict[str, list[str]]:
    for num, total in (("TRACKNUMBER", "TOTALTRACKS"), ("DISCNUMBER", "TOTALDISCS")):
        vals = tags.get(num)
        if vals and "/" in vals[0]:
            n, _, t = vals[0].partition("/")
            n, t = n.strip(), t.strip()
            if n:
                tags[num] = [n]
            else:
                del tags[num]
            if t and not tags.get(total):
                tags[total] = [t]
    return tags


def _first(tags: dict[str, list[str]], key: str) -> str:
    vals = tags.get(key)
    return vals[0].strip() if vals else ""


def _int_or_zero(s: str) -> int:
    m = re.match(r"\s*(\d+)", s)
    return int(m.group(1)) if m else 0


# --- Vorbis comments (FLAC, Ogg) -------------------------------------------------


VORBIS_ALIASES = {
    "ALBUMARTIST": "ALBUM ARTIST",
    "TRACKTOTAL": "TOTALTRACKS",
    "DISCTOTAL": "TOTALDISCS",
}
VORBIS_SKIP = {"METADATA_BLOCK_PICTURE", "COVERART", "COVERARTMIME"}


class VorbisHandler:
    def read(self, audio) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, value in audio.tags or []:
            k = key.upper()
            if k in VORBIS_SKIP:
                continue
            _add(out, VORBIS_ALIASES.get(k, k), [value])
        return out

    def _stored_keys(self, field: str) -> list[str]:
        return [field] + [alias for alias, canon in VORBIS_ALIASES.items() if canon == field]

    def write(self, audio, tags, fields, opts: WriteOptions) -> None:
        if audio.tags is None:
            audio.add_tags()
        vc = audio.tags
        for f in fields:
            for k in self._stored_keys(f):
                if k in vc:
                    del vc[k]
            vals = tags.get(f)
            if vals:
                key = opts.vorbis_albumartist_key if f == "ALBUM ARTIST" else f
                vc[key] = vals


# --- ID3 (MP3, WAV, AIFF, DSF, TTA) ------------------------------------------------

ID3_TEXT = {
    "TITLE": "TIT2",
    "ARTIST": "TPE1",
    "ALBUM": "TALB",
    "ALBUM ARTIST": "TPE2",
    "CONDUCTOR": "TPE3",
    "REMIXER": "TPE4",
    "COMPOSER": "TCOM",
    "LYRICIST": "TEXT",
    "GENRE": "TCON",
    "DATE": "TDRC",
    "ORIGINALDATE": "TDOR",
    "BPM": "TBPM",
    "COPYRIGHT": "TCOP",
    "ENCODEDBY": "TENC",
    "ENCODERSETTINGS": "TSSE",
    "LABEL": "TPUB",
    "ISRC": "TSRC",
    "MEDIA": "TMED",
    "MOOD": "TMOO",
    "LANGUAGE": "TLAN",
    "DISCSUBTITLE": "TSST",
    "GROUPING": "TIT1",
    "SUBTITLE": "TIT3",
    "ALBUMSORT": "TSOA",
    "ARTISTSORT": "TSOP",
    "TITLESORT": "TSOT",
    "ALBUMARTISTSORT": "TSO2",
    "COMPOSERSORT": "TSOC",
    "COMPILATION": "TCMP",
    "KEY": "TKEY",
    "ORIGINALARTIST": "TOPE",
    "ORIGINALALBUM": "TOAL",
}
ID3_TEXT_REV = {v: k for k, v in ID3_TEXT.items()}

# MusicBrainz Picard's TXXX descriptions, shared with MP4 freeform atoms.
PICARD_NAMES = {
    "MUSICBRAINZ_ALBUMID": "MusicBrainz Album Id",
    "MUSICBRAINZ_ARTISTID": "MusicBrainz Artist Id",
    "MUSICBRAINZ_ALBUMARTISTID": "MusicBrainz Album Artist Id",
    "MUSICBRAINZ_RELEASEGROUPID": "MusicBrainz Release Group Id",
    "MUSICBRAINZ_RELEASETRACKID": "MusicBrainz Release Track Id",
    "MUSICBRAINZ_WORKID": "MusicBrainz Work Id",
    "MUSICBRAINZ_DISCID": "MusicBrainz Disc Id",
    "RELEASETYPE": "MusicBrainz Album Type",
    "RELEASESTATUS": "MusicBrainz Album Status",
    "RELEASECOUNTRY": "MusicBrainz Album Release Country",
    "ACOUSTID_ID": "Acoustid Id",
}
PICARD_NAMES_REV = {v.lower(): k for k, v in PICARD_NAMES.items()}

MB_UFID_OWNER = "http://musicbrainz.org"


class ID3Handler:
    def read(self, audio) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        tags = audio.tags
        if tags is None:
            return out
        for frame in tags.values():
            fid = frame.FrameID
            if fid == "TXXX":
                _add(out, PICARD_NAMES_REV.get(frame.desc.lower(), frame.desc.upper()), frame.text)
            elif fid == "TRCK":
                _add(out, "TRACKNUMBER", [str(frame.text[0])] if frame.text else [])
            elif fid == "TPOS":
                _add(out, "DISCNUMBER", [str(frame.text[0])] if frame.text else [])
            elif fid == "TCON":
                _add(out, "GENRE", frame.genres)
            elif fid in ID3_TEXT_REV:
                _add(out, ID3_TEXT_REV[fid], [str(t) for t in frame.text])
            elif fid == "COMM" and frame.desc == "":
                _add(out, "COMMENT", frame.text)
            elif fid == "USLT" and frame.desc == "":
                _add(out, "LYRICS", [frame.text])
            elif fid == "UFID" and frame.owner == MB_UFID_OWNER:
                _add(out, "MUSICBRAINZ_TRACKID", [frame.data.decode("ascii", "replace")])
        return out

    @staticmethod
    def _delete_where(tags, pred) -> None:
        for key in list(tags.keys()):
            if pred(tags[key]):
                del tags[key]

    def write(self, audio, tags, fields, opts: WriteOptions) -> None:
        if audio.tags is None:
            audio.add_tags()
        id3 = audio.tags
        done: set[str] = set()
        for f in fields:
            if f in ("TRACKNUMBER", "TOTALTRACKS", "DISCNUMBER", "TOTALDISCS"):
                fid = "TRCK" if f in ("TRACKNUMBER", "TOTALTRACKS") else "TPOS"
                if fid in done:
                    continue
                done.add(fid)
                num, total = (
                    ("TRACKNUMBER", "TOTALTRACKS")
                    if fid == "TRCK"
                    else ("DISCNUMBER", "TOTALDISCS")
                )
                id3.delall(fid)
                n, t = _first(tags, num), _first(tags, total)
                text = f"{n}/{t}" if n and t else n
                if text:
                    id3.add(Frames[fid](encoding=3, text=[text]))
            elif f in ID3_TEXT:
                fid = ID3_TEXT[f]
                id3.delall(fid)
                if vals := tags.get(f):
                    id3.add(Frames[fid](encoding=3, text=vals))
            elif f == "COMMENT":
                self._delete_where(id3, lambda fr: fr.FrameID == "COMM" and fr.desc == "")
                if vals := tags.get(f):
                    id3.add(COMM(encoding=3, lang="eng", desc="", text=vals))
            elif f == "LYRICS":
                self._delete_where(id3, lambda fr: fr.FrameID == "USLT" and fr.desc == "")
                if vals := tags.get(f):
                    id3.add(USLT(encoding=3, lang="eng", desc="", text="\n".join(vals)))
            elif f == "MUSICBRAINZ_TRACKID":
                self._delete_where(
                    id3, lambda fr: fr.FrameID == "UFID" and fr.owner == MB_UFID_OWNER
                )
                if vals := tags.get(f):
                    id3.add(UFID(owner=MB_UFID_OWNER, data=vals[0].encode("ascii", "replace")))
            else:
                desc = PICARD_NAMES.get(f, f)
                self._delete_where(
                    id3,
                    lambda fr, desc=desc, f=f: (
                        fr.FrameID == "TXXX"
                        and (fr.desc.lower() == desc.lower() or fr.desc.upper() == f)
                    ),
                )
                if vals := tags.get(f):
                    id3.add(TXXX(encoding=3, desc=desc, text=vals))


# --- MP4 ---------------------------------------------------------------------------

MP4_TEXT = {
    "TITLE": "\xa9nam",
    "ARTIST": "\xa9ART",
    "ALBUM": "\xa9alb",
    "ALBUM ARTIST": "aART",
    "DATE": "\xa9day",
    "GENRE": "\xa9gen",
    "COMPOSER": "\xa9wrt",
    "COMMENT": "\xa9cmt",
    "LYRICS": "\xa9lyr",
    "GROUPING": "\xa9grp",
    "COPYRIGHT": "cprt",
    "ENCODEDBY": "\xa9too",
    "DESCRIPTION": "desc",
    "ALBUMSORT": "soal",
    "ARTISTSORT": "soar",
    "TITLESORT": "sonm",
    "ALBUMARTISTSORT": "soaa",
    "COMPOSERSORT": "soco",
    "WORK": "\xa9wrk",
    "MOVEMENT": "\xa9mvn",
}
MP4_TEXT_REV = {v: k for k, v in MP4_TEXT.items()}
MP4_FREEFORM_PREFIX = "----:com.apple.iTunes:"
MP4_FREEFORM_NAMES = {**PICARD_NAMES, "MUSICBRAINZ_TRACKID": "MusicBrainz Track Id"}
MP4_FREEFORM_REV = {v.lower(): k for k, v in MP4_FREEFORM_NAMES.items()}


class MP4Handler:
    def read(self, audio) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        tags = audio.tags
        if tags is None:
            return out
        for key, value in tags.items():
            if key in MP4_TEXT_REV:
                _add(out, MP4_TEXT_REV[key], value)
            elif key in ("trkn", "disk"):
                n, t = (value[0] + (0, 0))[:2] if value else (0, 0)
                num, total = (
                    ("TRACKNUMBER", "TOTALTRACKS")
                    if key == "trkn"
                    else ("DISCNUMBER", "TOTALDISCS")
                )
                if n:
                    _add(out, num, [n])
                if t:
                    _add(out, total, [t])
            elif key == "tmpo":
                _add(out, "BPM", value)
            elif key == "cpil":
                _add(out, "COMPILATION", ["1" if value else "0"])
            elif key.startswith(MP4_FREEFORM_PREFIX):
                name = key[len(MP4_FREEFORM_PREFIX) :]
                if name.lower().startswith("itun"):
                    continue
                canon = MP4_FREEFORM_REV.get(name.lower(), name.upper())
                _add(out, canon, [bytes(v).decode("utf-8", "replace") for v in value])
        return out

    def write(self, audio, tags, fields, opts: WriteOptions) -> None:
        if audio.tags is None:
            audio.add_tags()
        mp4 = audio.tags
        for f in fields:
            if f in MP4_TEXT:
                key = MP4_TEXT[f]
                mp4.pop(key, None)
                if vals := tags.get(f):
                    mp4[key] = vals
            elif f in NUMBER_PAIRS:
                key = "trkn" if f in ("TRACKNUMBER", "TOTALTRACKS") else "disk"
                num, total = (
                    ("TRACKNUMBER", "TOTALTRACKS")
                    if key == "trkn"
                    else ("DISCNUMBER", "TOTALDISCS")
                )
                n, t = _int_or_zero(_first(tags, num)), _int_or_zero(_first(tags, total))
                mp4.pop(key, None)
                if n or t:
                    mp4[key] = [(n, t)]
            elif f == "BPM":
                mp4.pop("tmpo", None)
                if bpm := _int_or_zero(_first(tags, f)):
                    mp4["tmpo"] = [bpm]
            elif f == "COMPILATION":
                mp4.pop("cpil", None)
                if _first(tags, f):
                    mp4["cpil"] = _int_or_zero(_first(tags, f)) != 0
            else:
                name = MP4_FREEFORM_NAMES.get(f, f)
                for key in list(mp4.keys()):
                    if key.startswith(MP4_FREEFORM_PREFIX):
                        existing = key[len(MP4_FREEFORM_PREFIX) :]
                        if existing.lower() == name.lower() or existing.upper() == f:
                            del mp4[key]
                if vals := tags.get(f):
                    mp4[MP4_FREEFORM_PREFIX + name] = [MP4FreeForm(v.encode("utf-8")) for v in vals]


# --- APEv2 (Monkey's Audio, WavPack, Musepack) ----------------------------------------

APE_READ = {
    "YEAR": "DATE",
    "TRACK": "TRACKNUMBER",
    "DISC": "DISCNUMBER",
    "ALBUMARTIST": "ALBUM ARTIST",
}
APE_WRITE = {
    "TITLE": "Title",
    "ARTIST": "Artist",
    "ALBUM": "Album",
    "ALBUM ARTIST": "Album Artist",
    "DATE": "Year",
    "GENRE": "Genre",
    "COMPOSER": "Composer",
    "COMMENT": "Comment",
    "PERFORMER": "Performer",
    "COPYRIGHT": "Copyright",
    "PUBLISHER": "Publisher",
}


class APEHandler:
    def read(self, audio) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, value in (audio.tags or {}).items():
            if isinstance(value, APEBinaryValue) or value.kind != 0:
                continue
            k = key.upper()
            _add(out, APE_READ.get(k, k), list(value))
        return out

    def write(self, audio, tags, fields, opts: WriteOptions) -> None:
        if audio.tags is None:
            audio.add_tags()
        ape = audio.tags
        done: set[str] = set()
        for f in fields:
            if f in NUMBER_PAIRS:
                key = "Track" if f in ("TRACKNUMBER", "TOTALTRACKS") else "Disc"
                if key in done:
                    continue
                done.add(key)
                num, total = (
                    ("TRACKNUMBER", "TOTALTRACKS")
                    if key == "Track"
                    else ("DISCNUMBER", "TOTALDISCS")
                )
                for k in (key, num, total):
                    ape.pop(k, None)
                n, t = _first(tags, num), _first(tags, total)
                text = f"{n}/{t}" if n and t else n
                if text:
                    ape[key] = text
                continue
            stored = [f] + [k for k, canon in APE_READ.items() if canon == f]
            for k in stored:
                ape.pop(k, None)
            if vals := tags.get(f):
                ape[APE_WRITE.get(f, f)] = vals


# --- dispatch ----------------------------------------------------------------------


def _handler(audio):
    if isinstance(audio, MP4):
        return MP4Handler()
    if isinstance(audio, (FLAC, OggVorbis, OggOpus, OggFLAC, OggSpeex)):
        return VorbisHandler()
    if isinstance(audio, APEv2File):
        return APEHandler()
    if isinstance(audio, (MP3, WAVE, AIFF, DSF, TrueAudio)) or isinstance(audio.tags, ID3):
        return ID3Handler()
    raise TagError(f"Unsupported tag format: {type(audio).__name__}")


def _codec(audio, path: str) -> tuple[str, str]:
    name = type(audio).__name__
    info = audio.info
    if isinstance(audio, MP4):
        codec = getattr(info, "codec", "") or ""
        desc = getattr(info, "codec_description", "") or ""
        if codec.startswith("alac"):
            return "ALAC", ""
        if codec.startswith("mp4a"):
            return "AAC", desc.replace("AAC", "").strip()
        return (desc or codec or "MP4").upper(), ""
    simple = {
        "FLAC": "FLAC",
        "OggFLAC": "FLAC",
        "OggVorbis": "Vorbis",
        "OggOpus": "Opus",
        "OggSpeex": "Speex",
        "MonkeysAudio": "Monkey's Audio",
        "WavPack": "WavPack",
        "Musepack": "Musepack",
        "WAVE": "PCM",
        "AIFF": "PCM",
        "DSF": "DSD",
        "TrueAudio": "TTA",
    }
    if name in simple:
        return simple[name], ""
    if name in ("MP3", "EasyMP3"):
        mode = getattr(info, "bitrate_mode", None)
        profile = {1: "CBR", 2: "VBR", 3: "ABR"}.get(int(mode) if mode is not None else 0, "")
        return "MP3", profile
    return os.path.splitext(path)[1][1:].upper(), ""


def _tech_info(audio, path: str, st: os.stat_result) -> dict[str, Any]:
    info = audio.info
    codec, profile = _codec(audio, path)
    length = float(getattr(info, "length", 0) or 0)
    bitrate = int(getattr(info, "bitrate", 0) or 0)
    if not bitrate and length:
        bitrate = int(st.st_size * 8 / length)
    return {
        "codec": codec,
        "codec_profile": profile,
        "length": round(length, 3),
        "bitrate": round(bitrate / 1000) if bitrate else 0,
        "samplerate": int(getattr(info, "sample_rate", 0) or 0),
        "channels": int(getattr(info, "channels", 0) or 0),
        "bitspersample": int(getattr(info, "bits_per_sample", 0) or 0),
        "encoding": "lossless" if codec in LOSSLESS_CODECS else "lossy",
        "filesize": st.st_size,
        "last_modified": datetime.fromtimestamp(st.st_mtime, tz=UTC)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S"),
    }


def _open(path: str):
    try:
        audio = mutagen.File(path)
    except Exception as e:  # mutagen raises a variety of format-specific errors
        raise TagError(f"Cannot read {os.path.basename(path)}: {e}") from e
    if audio is None:
        raise TagError(f"Unrecognized audio file: {os.path.basename(path)}")
    return audio


def read_track(path: str) -> dict[str, Any]:
    audio = _open(path)
    st = os.stat(path)
    tags = _split_numbers(_handler(audio).read(audio))
    return {
        "path": path,
        "tags": tags,
        "info": _tech_info(audio, path, st),
        "pictures": [p.summary() for p in embedded_pictures(audio)],
        "mtime": st.st_mtime,
    }


def apply_changes(
    current: dict[str, list[str]], set_fields: dict[str, list[str]], remove: list[str]
) -> tuple[dict[str, list[str]], set[str]]:
    new = {k: list(v) for k, v in current.items()}
    touched: set[str] = set()
    for name in remove:
        key = name.upper()
        if not valid_field_name(key):
            raise TagError(f"Invalid field name: {name!r}")
        new.pop(key, None)
        touched.add(key)
    for name, values in set_fields.items():
        key = name.upper().strip()
        if not valid_field_name(key):
            raise TagError(f"Invalid field name: {name!r}")
        vals = [v.strip() for v in values if v is not None and v.strip() != ""]
        if vals:
            new[key] = vals
        else:
            new.pop(key, None)
        touched.add(key)
    changed = {k for k in touched if current.get(k) != new.get(k)}
    changed |= {NUMBER_PAIRS[k] for k in changed if k in NUMBER_PAIRS}
    return new, changed


def _save(audio, handler, opts: WriteOptions, shrink: bool) -> None:
    kwargs: dict[str, Any] = {}
    if isinstance(handler, ID3Handler):
        kwargs["v2_version"] = opts.id3_version
    if shrink and not isinstance(handler, APEHandler):
        kwargs["padding"] = compact_padding
    try:
        audio.save(**kwargs)
    except TypeError:
        audio.save()


def write_track(
    path: str,
    set_fields: dict[str, list[str]],
    remove: list[str],
    opts: WriteOptions,
    drop_pictures: bool = False,
) -> dict[str, Any]:
    audio = _open(path)
    handler = _handler(audio)
    current = _split_numbers(handler.read(audio))
    new, changed = apply_changes(current, set_fields, remove)
    pictures_removed = drop_pictures and remove_pictures(audio)
    if changed:
        handler.write(audio, new, sorted(changed), opts)
    if changed or pictures_removed:
        _save(audio, handler, opts, shrink=pictures_removed)
    return read_track(path)
