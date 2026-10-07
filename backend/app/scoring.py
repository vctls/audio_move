"""Heuristic ranking of release candidates against cues gathered from local files.

Cue sources and candidate sources only meet through Cue and Candidate, so either side can
grow without knowing about the other.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


def format_family(name: str) -> str:
    """Map a media format name such as 'Enhanced CD' or '12" Vinyl' to a broad family."""
    n = name.lower()
    if "vinyl" in n:
        return "vinyl"
    if "digital" in n:
        return "digital"
    if "cassette" in n:
        return "cassette"
    if re.search(r"cd(?![a-z])", n):
        return "cd"
    return "other"


@dataclass(frozen=True)
class Candidate:
    """What the scorer may look at on a release, independent of where it came from."""

    formats: frozenset[str] = frozenset()
    # The total and each medium's count, so a single disc of a set can match too.
    track_counts: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Cue:
    """A hint about the release the local files come from.

    A matching candidate gains `points`, which are negative for evidence against it.
    """

    points: float
    reason: str
    test: Callable[[Candidate], bool]


def format_cue(family: str, points: float, reason: str) -> Cue:
    return Cue(points, reason, lambda c: family in c.formats)


def tracks_cue(count: int, points: float, reason: str) -> Cue:
    return Cue(points, reason, lambda c: count in c.track_counts)


@dataclass
class Score:
    points: float = 0
    reasons: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"points": self.points, "reasons": self.reasons}


def score(candidate: Candidate, cues: Iterable[Cue]) -> Score:
    s = Score()
    for cue in cues:
        if cue.test(candidate):
            s.points += cue.points
            s.reasons.append({"points": cue.points, "reason": cue.reason})
    return s
