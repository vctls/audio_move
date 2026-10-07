"""foobar2000's "Guess values from file name"."""

from __future__ import annotations

import os
import re

_FIELD_RE = re.compile(r"(%[^%]+%)")
_ALIASES = {"track number": "TRACKNUMBER", "track": "TRACKNUMBER"}
_IGNORED = {"", "DUMMY", "_", "IGNORE"}


def _field_name(token: str) -> str:
    name = token[1:-1].strip()
    return _ALIASES.get(name.lower(), name.upper())


def compile_pattern(pattern: str) -> tuple[re.Pattern[str], list[str], int]:
    pattern = pattern.replace("\\", "/").strip("/")
    names: list[str] = []
    regex = []
    for token in _FIELD_RE.split(pattern):
        if len(token) > 2 and token.startswith("%") and token.endswith("%"):
            regex.append(f"(?P<g{len(names)}>.+?)")
            names.append(_field_name(token))
        else:
            regex.append(re.escape(token))
    return re.compile("".join(regex), re.DOTALL), names, pattern.count("/") + 1


def guess(pattern: str, path: str) -> dict[str, str] | None:
    """Match the pattern against the end of the path, without extension.

    Each "/" in the pattern consumes one more parent directory.
    """
    rx, names, depth = compile_pattern(pattern)
    stem = os.path.splitext(path)[0]
    target = "/".join(stem.split("/")[-depth:])
    m = rx.fullmatch(target)
    if not m:
        return None
    out: dict[str, str] = {}
    for i, name in enumerate(names):
        if name in _IGNORED:
            continue
        value = m.group(f"g{i}").strip()
        if value:
            out[name] = value
    return out
