"""MusicBrainz web service client and release-to-tags mapping."""

from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import httpx

API_ROOT = "https://musicbrainz.org/ws/2"
CAA_ROOT = "https://coverartarchive.org"
RELEASE_INC = "recordings+artist-credits+labels+release-groups+media+isrcs"
SEARCH_INC = "artist-credits+labels+media+release-groups"

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


class MusicBrainzError(Exception):
    pass


def lucene_escape(s: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", s)


def build_query(artist: str, album: str) -> str:
    parts = []
    if album.strip():
        parts.append(f"release:({lucene_escape(album.strip())})")
    if artist.strip():
        parts.append(f"artist:({lucene_escape(artist.strip())})")
    return " AND ".join(parts)


def parse_mbid(text: str) -> tuple[str, str] | None:
    """Extract (entity, mbid) from a bare MBID or a musicbrainz.org URL."""
    m = _UUID_RE.search(text)
    if not m:
        return None
    entity = "release-group" if "release-group/" in text else "release"
    return entity, m.group(0).lower()


def artist_credit(credits: list[dict] | None) -> str:
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in credits or [])


def artist_ids(credits: list[dict] | None) -> list[str]:
    return [c["artist"]["id"] for c in credits or [] if c.get("artist", {}).get("id")]


def _format_summary(media: list[dict]) -> str:
    counts: OrderedDict[str, int] = OrderedDict()
    for m in media:
        fmt = m.get("format") or "(unknown)"
        counts[fmt] = counts.get(fmt, 0) + 1
    return " + ".join(f"{n}×{fmt}" if n > 1 else fmt for fmt, n in counts.items())


def summarize_release(r: dict) -> dict[str, Any]:
    media = r.get("media") or []
    rg = r.get("release-group") or {}
    labels = r.get("label-info") or []
    track_count = r.get("track-count")
    if track_count is None:
        track_count = sum(m.get("track-count") or 0 for m in media)
    return {
        "id": r["id"],
        "score": r.get("score"),
        "title": r.get("title", ""),
        "disambiguation": r.get("disambiguation", ""),
        "artist": artist_credit(r.get("artist-credit")),
        "date": r.get("date", ""),
        "country": r.get("country", ""),
        "status": r.get("status", ""),
        "barcode": r.get("barcode") or "",
        "labels": [
            {
                "name": (li.get("label") or {}).get("name", ""),
                "catno": li.get("catalog-number") or "",
            }
            for li in labels
        ],
        "format": _format_summary(media),
        "media": [
            {"format": m.get("format") or "", "track_count": m.get("track-count") or 0}
            for m in media
        ],
        "track_count": track_count,
        "type": rg.get("primary-type") or "",
        "secondary_types": rg.get("secondary-types") or [],
    }


def summarize_release_detail(r: dict) -> dict[str, Any]:
    base = summarize_release(r)
    rg = r.get("release-group") or {}
    text = r.get("text-representation") or {}
    base.update(
        {
            "artist_ids": artist_ids(r.get("artist-credit")),
            "asin": r.get("asin") or "",
            "script": text.get("script") or "",
            "language": text.get("language") or "",
            "release_group": {
                "id": rg.get("id", ""),
                "type": rg.get("primary-type") or "",
                "secondary_types": rg.get("secondary-types") or [],
                "first_release_date": rg.get("first-release-date") or "",
            },
            "cover_art": bool((r.get("cover-art-archive") or {}).get("front")),
            "media": [
                {
                    "position": m.get("position") or i + 1,
                    "format": m.get("format") or "",
                    "title": m.get("title") or "",
                    "track_count": m.get("track-count") or len(m.get("tracks") or []),
                    "tracks": [
                        {
                            "id": t.get("id", ""),
                            "recording_id": (t.get("recording") or {}).get("id", ""),
                            "position": t.get("position") or j + 1,
                            "number": t.get("number") or str(j + 1),
                            "title": t.get("title", ""),
                            "artist": artist_credit(
                                t.get("artist-credit")
                                or (t.get("recording") or {}).get("artist-credit")
                            ),
                            "artist_ids": artist_ids(
                                t.get("artist-credit")
                                or (t.get("recording") or {}).get("artist-credit")
                            ),
                            "length": (
                                t.get("length") or (t.get("recording") or {}).get("length") or 0
                            )
                            / 1000,
                            "isrcs": (t.get("recording") or {}).get("isrcs") or [],
                        }
                        for j, t in enumerate(m.get("tracks") or [])
                    ],
                }
                for i, m in enumerate(r.get("media") or [])
            ],
        }
    )
    return base


@dataclass
class TagOptions:
    date: str = "year"  # "year" or "full"
    groups: set[str] = field(default_factory=lambda: {"basic", "release", "ids"})
    disc_for_single: bool = False
    padding: int = 2


def _pad(n: int | str, width: int) -> str:
    s = str(n)
    return s.zfill(width) if width > 0 and s.isdigit() else s


def track_tags(release: dict, medium: dict, track: dict, opts: TagOptions) -> dict[str, list[str]]:
    """Tags for one track of a release produced by summarize_release_detail."""
    out: dict[str, list[str]] = {}

    def put(key: str, *values: str) -> None:
        vals = [v for v in values if v]
        if vals:
            out[key] = vals

    total_discs = len(release["media"])
    if "basic" in opts.groups:
        put("TITLE", track["title"])
        put("ARTIST", track["artist"])
        put("ALBUM", release["title"])
        put("ALBUM ARTIST", release["artist"])
        date = release["date"]
        put("DATE", date[:4] if opts.date == "year" else date)
        put("TRACKNUMBER", _pad(track["position"], opts.padding))
        put("TOTALTRACKS", _pad(medium["track_count"], opts.padding))
        if total_discs > 1 or opts.disc_for_single:
            put("DISCNUMBER", str(medium["position"]))
            put("TOTALDISCS", str(total_discs))
        put("DISCSUBTITLE", medium["title"])
    if "release" in opts.groups:
        put("LABEL", *dict.fromkeys(li["name"] for li in release["labels"] if li["name"]))
        put("CATALOGNUMBER", *dict.fromkeys(li["catno"] for li in release["labels"] if li["catno"]))
        put("BARCODE", release["barcode"])
        put("MEDIA", medium["format"])
        put("RELEASECOUNTRY", release["country"])
        put("RELEASESTATUS", release["status"].lower())
        rg = release["release_group"]
        put("RELEASETYPE", *(t.lower() for t in [rg["type"], *rg["secondary_types"]] if t))
        orig = rg["first_release_date"]
        put("ORIGINALDATE", orig[:4] if opts.date == "year" else orig)
        put("ISRC", *track["isrcs"])
    if "ids" in opts.groups:
        put("MUSICBRAINZ_ALBUMID", release["id"])
        put("MUSICBRAINZ_RELEASEGROUPID", release["release_group"]["id"])
        put("MUSICBRAINZ_ALBUMARTISTID", *release["artist_ids"])
        put("MUSICBRAINZ_ARTISTID", *track["artist_ids"])
        put("MUSICBRAINZ_TRACKID", track["recording_id"])
        put("MUSICBRAINZ_RELEASETRACKID", track["id"])
    return out


def release_with_tags(release: dict, opts: TagOptions) -> dict:
    out = dict(release)
    out["media"] = [
        {**m, "tracks": [{**t, "tags": track_tags(release, m, t, opts)} for t in m["tracks"]]}
        for m in release["media"]
    ]
    return out


class MusicBrainzClient:
    """Async client honouring the MusicBrainz limit of one request per second."""

    def __init__(self, user_agent: str, min_interval: float = 1.1):
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
        )
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._min_interval = min_interval
        self._cache: OrderedDict[str, Any] = OrderedDict()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        params = {**params, "fmt": "json"}
        for attempt in range(4):
            async with self._lock:
                wait = self._last + self._min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self._client.get(f"{API_ROOT}/{path}", params=params)
                except httpx.HTTPError as e:
                    raise MusicBrainzError(f"MusicBrainz request failed: {e}") from e
                finally:
                    self._last = time.monotonic()
            if resp.status_code == 503 and attempt < 3:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 404:
                raise MusicBrainzError("Not found on MusicBrainz")
            if resp.status_code >= 400:
                raise MusicBrainzError(f"MusicBrainz returned HTTP {resp.status_code}")
            data = resp.json()
            self._cache[key] = data
            if len(self._cache) > 200:
                self._cache.popitem(last=False)
            return data
        raise MusicBrainzError("MusicBrainz is rate limiting requests, try again shortly")

    async def search(self, query: str, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        data = await self._get("release", {"query": query, "limit": limit, "offset": offset})
        return {
            "count": data.get("count", 0),
            "offset": data.get("offset", 0),
            "releases": [summarize_release(r) for r in data.get("releases", [])],
        }

    async def releases_of_group(self, rgid: str) -> dict[str, Any]:
        data = await self._get("release", {"release-group": rgid, "inc": SEARCH_INC, "limit": 100})
        releases = [summarize_release(r) for r in data.get("releases", [])]
        releases.sort(key=lambda r: (r["date"] or "9999", r["country"]))
        return {"count": len(releases), "offset": 0, "releases": releases}

    async def release(self, mbid: str) -> dict[str, Any]:
        data = await self._get(f"release/{mbid}", {"inc": RELEASE_INC})
        return summarize_release_detail(data)

    async def lookup(self, text: str) -> dict[str, Any]:
        parsed = parse_mbid(text)
        if not parsed:
            raise MusicBrainzError("No MusicBrainz ID found in input")
        entity, mbid = parsed
        if entity == "release":
            try:
                rel = await self.release(mbid)
                return {"count": 1, "offset": 0, "releases": [rel]}
            except MusicBrainzError:
                if "release/" in text:
                    raise
        return await self.releases_of_group(mbid)

    async def cover(self, mbid: str, size: str) -> bytes:
        suffix = "front" if size == "original" else f"front-{size}"
        try:
            resp = await self._client.get(f"{CAA_ROOT}/release/{mbid}/{suffix}")
        except httpx.HTTPError as e:
            raise MusicBrainzError(f"Cover Art Archive request failed: {e}") from e
        if resp.status_code == 404:
            raise MusicBrainzError("This release has no front cover on the Cover Art Archive")
        if resp.status_code >= 400:
            raise MusicBrainzError(f"Cover Art Archive returned HTTP {resp.status_code}")
        return resp.content
