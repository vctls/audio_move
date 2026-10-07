"""foobar2000 title formatting: parser and evaluator.

Every evaluation yields a (text, truth) pair, as in foobar2000. Truth drives
[...] sections and $if(). Fields are true when present, literals are false.
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class Lit:
    text: str


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Cond:
    body: tuple


@dataclass(frozen=True)
class Func:
    name: str
    args: tuple


Node = Lit | Field | Cond | Func
Result = tuple[str, bool]

_FUNC_RE = re.compile(r"\$([A-Za-z0-9_]+)\(")


def _strip_comments(src: str) -> str:
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("//")]
    return "".join(lines)


class _Parser:
    def __init__(self, src: str):
        self.s = _strip_comments(src)
        self.i = 0

    def parse(self) -> tuple:
        return self._seq("")

    def _seq(self, stop: str) -> tuple:
        nodes: list[Node] = []
        buf: list[str] = []
        s = self.s

        def flush():
            if buf:
                nodes.append(Lit("".join(buf)))
                buf.clear()

        while self.i < len(s):
            c = s[self.i]
            if c in stop:
                break
            if c == "'":
                end = s.find("'", self.i + 1)
                if end == -1:
                    buf.append(s[self.i + 1 :])
                    self.i = len(s)
                elif end == self.i + 1:
                    buf.append("'")
                    self.i = end + 1
                else:
                    buf.append(s[self.i + 1 : end])
                    self.i = end + 1
            elif c == "%":
                end = s.find("%", self.i + 1)
                if end == -1:
                    buf.append(s[self.i :])
                    self.i = len(s)
                else:
                    flush()
                    nodes.append(Field(s[self.i + 1 : end]))
                    self.i = end + 1
            elif c == "[":
                flush()
                self.i += 1
                body = self._seq("]")
                if self.i < len(s):
                    self.i += 1
                nodes.append(Cond(body))
            elif c == "$" and (m := _FUNC_RE.match(s, self.i)):
                flush()
                self.i = m.end()
                args: list[tuple] = []
                while True:
                    args.append(self._seq(",)"))
                    if self.i >= len(s):
                        break
                    sep = s[self.i]
                    self.i += 1
                    if sep == ")":
                        break
                if args == [()]:
                    args = []
                nodes.append(Func(m.group(1).lower(), tuple(args)))
            else:
                buf.append(c)
                self.i += 1
        flush()
        return tuple(nodes)


@lru_cache(maxsize=256)
def compile_format(src: str) -> tuple:
    return _Parser(src).parse()


# --- helpers -----------------------------------------------------------------

_INT_RE = re.compile(r"\s*(-?\d+)")


def to_int(s: str) -> int:
    m = _INT_RE.match(s)
    return int(m.group(1)) if m else 0


_WORD_START_AFTER = set(' \t\r\n([{"/')


def _caps(s: str, lower_rest: bool) -> str:
    out = []
    prev = " "
    for ch in s:
        if prev in _WORD_START_AFTER:
            out.append(ch.upper())
        else:
            out.append(ch.lower() if lower_rest else ch)
        prev = ch
    return "".join(out)


def _ascii(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c if ord(c) < 128 else "?" for c in stripped)


def _abbr(s: str) -> str:
    out = []
    for word in s.split(" "):
        word = word.replace("(", "").replace(")", "")
        if not word:
            continue
        out.append(word[0] if word[0].isalnum() else word)
    return "".join(out)


def _roman(n: int) -> str:
    if n <= 0 or n >= 100000:
        return ""
    table = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    out = []
    for value, sym in table:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def _rot13(s: str) -> str:
    out = []
    for c in s:
        if "a" <= c <= "z":
            out.append(chr((ord(c) - 97 + 13) % 26 + 97))
        elif "A" <= c <= "Z":
            out.append(chr((ord(c) - 65 + 13) % 26 + 65))
        else:
            out.append(c)
    return "".join(out)


def _replace_multi(s: str, pairs: list[tuple[str, str]]) -> str:
    pairs = [(a, b) for a, b in pairs if a]
    if not pairs:
        return s
    out = []
    i = 0
    while i < len(s):
        for search, repl in pairs:
            if s.startswith(search, i):
                out.append(repl)
                i += len(search)
                break
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _split_path(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]", path)]


def _width2(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def format_length(seconds: float, ms: bool = False) -> str:
    if ms:
        total_ms = round(seconds * 1000)
        secs, milli = divmod(total_ms, 1000)
    else:
        secs, milli = round(seconds), 0
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    base = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return f"{base}.{milli:03d}" if ms else base


def _natural_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n} B" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return str(n)


def _channels_text(n: int) -> str:
    return {1: "mono", 2: "stereo"}.get(n, f"{n}ch")


_YEAR_RE = re.compile(r"\s*(\d{4})")


# --- evaluation context --------------------------------------------------------


@dataclass
class Context:
    """Data for one track. Tag keys are matched case-insensitively."""

    tags: Mapping[str, Sequence[str]]
    info: Mapping[str, object] = field(default_factory=dict)
    path: str = ""
    # File operations use this to keep a "/" inside a tag value from becoming a
    # directory separator.
    field_filter: Callable[[str], str] | None = None
    variables: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self._tags = {k.upper(): [str(v) for v in vals] for k, vals in self.tags.items() if vals}

    def values(self, name: str) -> list[str] | None:
        return self._tags.get(name.upper())

    def meta(self, name: str, sep: str = ", ") -> str | None:
        vals = self.values(name)
        return sep.join(vals) if vals else None

    def first_meta(self, *names: str) -> str | None:
        for n in names:
            v = self.meta(n)
            if v is not None:
                return v
        return None

    def filtered(self, value: str) -> str:
        return self.field_filter(value) if self.field_filter else value

    def info_value(self, name: str) -> str | None:
        v = self.info.get(name.lower())
        if v is None or v == "":
            return None
        return str(v)


def _filename_parts(path: str) -> tuple[str, str, str]:
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    return base, stem, ext[1:]


def lookup_field(ctx: Context, name: str) -> str | None:
    key = name.lower()
    if key.startswith("__"):
        return ctx.info_value(key[2:])
    if key == "album artist":
        return ctx.first_meta("ALBUM ARTIST", "ARTIST", "COMPOSER", "PERFORMER")
    if key == "artist":
        return ctx.first_meta("ARTIST", "ALBUM ARTIST", "COMPOSER", "PERFORMER")
    if key == "album":
        return ctx.first_meta("ALBUM", "VENUE")
    if key == "track artist":
        artist = lookup_field(ctx, "artist")
        album_artist = lookup_field(ctx, "album artist")
        return artist if artist is not None and artist != album_artist else None
    if key == "title":
        return ctx.first_meta("TITLE") or _filename_parts(ctx.path)[1] or None
    if key in ("tracknumber", "track number"):
        v = ctx.first_meta("TRACKNUMBER", "TRACK")
        if v is not None and key == "tracknumber" and len(v) == 1 and v.isdigit():
            v = "0" + v
        return v
    if key == "discnumber":
        return ctx.first_meta("DISCNUMBER", "DISC")
    if key == "totaldiscs":
        return ctx.first_meta("TOTALDISCS", "DISCTOTAL")
    if key == "totaltracks":
        return ctx.first_meta("TOTALTRACKS", "TRACKTOTAL")
    if key == "year":
        # foobar2000 has no %year% remapping. This one falls back to the year of DATE.
        v = ctx.meta("YEAR")
        if v is None and (date := ctx.meta("DATE")) and (m := _YEAR_RE.match(date)):
            v = m.group(1)
        return v
    if key in ("filename", "filename_ext", "directoryname", "path"):
        base, stem, _ext = _filename_parts(ctx.path)
        if key == "filename":
            return stem
        if key == "filename_ext":
            return base
        if key == "directoryname":
            return os.path.basename(os.path.dirname(ctx.path))
        return ctx.path
    if key in ("codec", "bitrate", "samplerate", "codec_profile"):
        return ctx.info_value(key)
    if key == "channels":
        n = ctx.info.get("channels")
        return _channels_text(int(n)) if n else None
    if key in ("filesize", "_filesize"):
        return ctx.info_value("filesize")
    if key == "filesize_natural":
        n = ctx.info.get("filesize")
        return _natural_size(int(n)) if n else None
    if key in (
        "length",
        "_time_total",
        "length_ex",
        "length_seconds",
        "_time_total_seconds",
        "length_seconds_fp",
        "length_samples",
    ):
        secs = ctx.info.get("length")
        if secs is None:
            return None
        secs = float(secs)
        if key in ("length", "_time_total"):
            return format_length(secs)
        if key == "length_ex":
            return format_length(secs, ms=True)
        if key in ("length_seconds", "_time_total_seconds"):
            return str(round(secs))
        if key == "length_seconds_fp":
            return f"{secs:.6f}"
        rate = ctx.info.get("samplerate") or 0
        return str(round(secs * int(rate)))
    if key == "last_modified":
        return ctx.info_value("last_modified")
    return ctx.meta(name)


# --- evaluator -----------------------------------------------------------------


class _Args:
    __slots__ = ("_cache", "ctx", "raw")

    def __init__(self, ctx: Context, raw: tuple):
        self.ctx = ctx
        self.raw = raw
        self._cache: dict[int, Result] = {}

    def __len__(self) -> int:
        return len(self.raw)

    def __call__(self, i: int) -> Result:
        if i not in self._cache:
            self._cache[i] = evaluate_nodes(self.raw[i], self.ctx)
        return self._cache[i]

    def s(self, i: int) -> str:
        return self(i)[0]

    def t(self, i: int) -> bool:
        return self(i)[1]

    def n(self, i: int) -> int:
        return to_int(self.s(i))

    def any_true(self) -> bool:
        return any(self.t(i) for i in range(len(self)))


class _ArityError(Exception):
    pass


def _need(a: _Args, *counts: int) -> None:
    if len(a) not in counts:
        raise _ArityError


def _need_min(a: _Args, n: int) -> None:
    if len(a) < n:
        raise _ArityError


def _fold(op):
    def fn(a: _Args) -> Result:
        _need_min(a, 1)
        acc = a.n(0)
        for i in range(1, len(a)):
            acc = op(acc, a.n(i))
        return str(acc), a.any_true()

    return fn


def _idiv(x: int, y: int) -> int:
    return x if y == 0 else int(x / y)


def _imod(x: int, y: int) -> int:
    return x if y == 0 else int(math.fmod(x, y))


def _f_muldiv(a: _Args) -> Result:
    _need(a, 3)
    c = a.n(2)
    if c == 0:
        return "-1", a.any_true()
    return str(math.floor(a.n(0) * a.n(1) / c + 0.5)), a.any_true()


def _f_if(a: _Args) -> Result:
    _need(a, 2, 3)
    if a.t(0):
        return a(1)
    return a(2) if len(a) == 3 else ("", False)


def _f_if2(a: _Args) -> Result:
    _need(a, 2)
    return a(0) if a.t(0) else a(1)


def _f_if3(a: _Args) -> Result:
    _need_min(a, 2)
    for i in range(len(a) - 1):
        if a.t(i):
            return a(i)
    return a(len(a) - 1)


def _f_ifequal(a: _Args) -> Result:
    _need(a, 4)
    return a(2) if a.n(0) == a.n(1) else a(3)


def _f_ifgreater(a: _Args) -> Result:
    _need(a, 4)
    return a(2) if a.n(0) > a.n(1) else a(3)


def _f_iflonger(a: _Args) -> Result:
    _need(a, 4)
    return a(2) if len(a.s(0)) > a.n(1) else a(3)


def _f_select(a: _Args) -> Result:
    _need_min(a, 2)
    n = a.n(0)
    if 1 <= n < len(a):
        return a(n)
    return "", False


def _bool(v: bool) -> Result:
    return "", v


def _str_fn(fn: Callable[..., str], *counts: int):
    def wrapped(a: _Args) -> Result:
        _need(a, *counts)
        return fn(a), a.t(0)

    return wrapped


def _pad(a: _Args, right_align: bool, cut: bool) -> str:
    _need(a, 2, 3)
    s, n = a.s(0), a.n(1)
    ch = (a.s(2) or " ")[0] if len(a) == 3 else " "
    if cut and len(s) > n:
        return s[: max(n, 0)]
    if len(s) >= n:
        return s
    fill = ch * (n - len(s))
    return fill + s if right_align else s + fill


def _num(a: _Args) -> str:
    n, width = a.n(0), a.n(1)
    if n < 0:
        return "-" + str(-n).zfill(max(width - 1, 0))
    return str(n).zfill(max(width, 0))


def _left(a: _Args) -> str:
    n = a.n(1)
    return a.s(0) if n < 0 else a.s(0)[:n]


def _right(a: _Args) -> str:
    n = a.n(1)
    s = a.s(0)
    if n < 0:
        return s
    return s[len(s) - n :] if n else ""


def _substr(a: _Args) -> str:
    s, start, end = a.s(0), a.n(1), a.n(2)
    return s[max(start - 1, 0) : max(end, 0)]


def _insert(a: _Args) -> str:
    s, ins, n = a.s(0), a.s(1), a.n(2)
    n = max(0, min(n, len(s)))
    return s[:n] + ins + s[n:]


def _f_replace(a: _Args) -> Result:
    if len(a) < 3 or len(a) % 2 == 0:
        raise _ArityError
    pairs = [(a.s(i), a.s(i + 1)) for i in range(1, len(a), 2)]
    return _replace_multi(a.s(0), pairs), a.t(0)


def _abbr_fn(a: _Args) -> str:
    s = a.s(0)
    if len(a) == 2 and len(s) <= a.n(1):
        return s
    return _abbr(s)


_DEFAULT_PREFIXES = ("A", "The")


def _prefixes(a: _Args) -> list[str]:
    return [a.s(i) for i in range(1, len(a))] or list(_DEFAULT_PREFIXES)


def _stripprefix(a: _Args) -> str:
    s = a.s(0)
    for p in _prefixes(a):
        if s.lower().startswith(p.lower() + " "):
            return s[len(p) + 1 :]
    return s


def _swapprefix(a: _Args) -> str:
    s = a.s(0)
    for p in _prefixes(a):
        if s.lower().startswith(p.lower() + " "):
            return f"{s[len(p) + 1 :]}, {s[: len(p)]}"
    return s


def _directory(a: _Args) -> str:
    parts = _split_path(a.s(0))
    level = a.n(1) if len(a) == 2 else 1
    idx = len(parts) - 1 - level
    return parts[idx] if 0 <= idx < len(parts) - 1 else ""


def _directory_path(a: _Args) -> str:
    s = a.s(0)
    cut = max(s.rfind("/"), s.rfind("\\"))
    return s[:cut] if cut >= 0 else ""


def _ext(a: _Args) -> str:
    name = _split_path(a.s(0))[-1]
    return name.rsplit(".", 1)[1] if "." in name else ""


def _filename(a: _Args) -> str:
    name = _split_path(a.s(0))[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _fix_eol(a: _Args) -> str:
    s = a.s(0)
    indicator = a.s(1) if len(a) == 2 else " (...)"
    idx = s.find("\r\n")
    if idx == -1:
        idx = s.find("\n")
    return s if idx == -1 else s[:idx] + indicator


def _hex(a: _Args) -> str:
    n = a.n(0)
    width = a.n(1) if len(a) == 2 else 0
    return format(n & 0xFFFFFFFF if n < 0 else n, "X").zfill(width)


def _date_part(start: int, end: int, pattern: str):
    rx = re.compile(pattern)

    def fn(a: _Args) -> Result:
        _need(a, 1)
        s = a.s(0)
        if not rx.match(s):
            return "", False
        return s[start:end], a.t(0)

    return fn


def _f_meta(ctx: Context, a: _Args) -> Result:
    _need(a, 1, 2)
    vals = ctx.values(a.s(0))
    if not vals:
        return "", False
    if len(a) == 2:
        idx = a.n(1)
        if not 0 <= idx < len(vals):
            return "", False
        return ctx.filtered(vals[idx]), True
    return ctx.filtered(", ".join(vals)), True


def _f_meta_sep(ctx: Context, a: _Args) -> Result:
    _need(a, 2, 3)
    vals = ctx.values(a.s(0))
    if not vals:
        return "", False
    sep = a.s(1)
    if len(a) == 3 and len(vals) > 1:
        joined = sep.join(vals[:-1]) + a.s(2) + vals[-1]
    else:
        joined = sep.join(vals)
    return ctx.filtered(joined), True


def _f_meta_test(ctx: Context, a: _Args) -> Result:
    _need_min(a, 1)
    ok = all(ctx.values(a.s(i)) for i in range(len(a)))
    return ("1", True) if ok else ("", False)


def _f_meta_num(ctx: Context, a: _Args) -> Result:
    _need(a, 1)
    vals = ctx.values(a.s(0)) or []
    return str(len(vals)), bool(vals)


def _f_info(ctx: Context, a: _Args) -> Result:
    _need(a, 1)
    v = ctx.info_value(a.s(0))
    return (v, True) if v is not None else ("", False)


def _f_channels(ctx: Context, a: _Args) -> Result:
    n = ctx.info.get("channels")
    return (_channels_text(int(n)), True) if n else ("", False)


def _f_get(ctx: Context, a: _Args) -> Result:
    _need(a, 1)
    v = ctx.variables.get(a.s(0).lower())
    return (v, True) if v else (v or "", False)


def _f_put(ctx: Context, a: _Args) -> Result:
    _need(a, 2)
    ctx.variables[a.s(0).lower()] = a.s(1)
    return a(1)


def _f_puts(ctx: Context, a: _Args) -> Result:
    _need(a, 2)
    ctx.variables[a.s(0).lower()] = a.s(1)
    return "", a.t(1)


def _strpos(a: _Args, last: bool) -> Result:
    _need(a, 2)
    s, needle = a.s(0), a.s(1)[:1]
    if not needle:
        return "0", False
    idx = s.rfind(needle) if last else s.find(needle)
    return str(idx + 1), idx >= 0


def _f_strstr(a: _Args) -> Result:
    _need(a, 2)
    idx = a.s(0).find(a.s(1)) if a.s(1) else -1
    return str(idx + 1), idx >= 0


def _f_longest(a: _Args) -> Result:
    _need_min(a, 1)
    best = max(range(len(a)), key=lambda i: (len(a.s(i)), -i))
    return a(best)


def _f_shortest(a: _Args) -> Result:
    _need_min(a, 1)
    best = min(range(len(a)), key=lambda i: (len(a.s(i)), i))
    return a(best)


def _f_char(a: _Args) -> Result:
    _need(a, 1)
    n = a.n(0)
    try:
        return (chr(n) if n > 0 else ""), False
    except (ValueError, OverflowError):
        return "", False


def _f_tab(a: _Args) -> Result:
    _need(a, 0, 1)
    return "\t" * (a.n(0) if len(a) else 1), False


def _f_repeat(a: _Args) -> Result:
    _need(a, 2)
    return a.s(0) * max(a.n(1), 0), a.t(0)


_FUNCS: dict[str, Callable[[_Args], Result]] = {
    "add": _fold(lambda x, y: x + y),
    "sub": _fold(lambda x, y: x - y),
    "mul": _fold(lambda x, y: x * y),
    "div": _fold(_idiv),
    "mod": _fold(_imod),
    "min": _fold(min),
    "max": _fold(max),
    "muldiv": _f_muldiv,
    "greater": lambda a: (_need(a, 2), _bool(a.n(0) > a.n(1)))[1],
    "and": lambda a: _bool(all(a.t(i) for i in range(len(a)))),
    "or": lambda a: _bool(any(a.t(i) for i in range(len(a)))),
    "not": lambda a: (_need(a, 1), _bool(not a.t(0)))[1],
    "xor": lambda a: _bool(sum(a.t(i) for i in range(len(a))) % 2 == 1),
    "if": _f_if,
    "if2": _f_if2,
    "if3": _f_if3,
    "ifequal": _f_ifequal,
    "ifgreater": _f_ifgreater,
    "iflonger": _f_iflonger,
    "select": _f_select,
    "abbr": _str_fn(_abbr_fn, 1, 2),
    "ansi": _str_fn(lambda a: a.s(0), 1),
    "ascii": _str_fn(lambda a: _ascii(a.s(0)), 1),
    "caps": _str_fn(lambda a: _caps(a.s(0), True), 1),
    "caps2": _str_fn(lambda a: _caps(a.s(0), False), 1),
    "char": _f_char,
    "crc32": _str_fn(lambda a: str(zlib.crc32(a.s(0).encode("utf-8"))), 1),
    "crlf": lambda a: ("\r\n", False),
    "cut": _str_fn(_left, 2),
    "left": _str_fn(_left, 2),
    "right": _str_fn(_right, 2),
    "directory": _str_fn(_directory, 1, 2),
    "directory_path": _str_fn(_directory_path, 1),
    "ext": _str_fn(_ext, 1),
    "filename": _str_fn(_filename, 1),
    "fix_eol": _str_fn(_fix_eol, 1, 2),
    "hex": _str_fn(_hex, 1, 2),
    "insert": _str_fn(_insert, 3),
    "len": _str_fn(lambda a: str(len(a.s(0))), 1),
    "len2": _str_fn(lambda a: str(_width2(a.s(0))), 1),
    "longer": lambda a: (_need(a, 2), _bool(len(a.s(0)) > len(a.s(1))))[1],
    "longest": _f_longest,
    "shortest": _f_shortest,
    "lower": _str_fn(lambda a: a.s(0).lower(), 1),
    "upper": _str_fn(lambda a: a.s(0).upper(), 1),
    "num": _str_fn(_num, 2),
    "pad": _str_fn(lambda a: _pad(a, False, False), 2, 3),
    "pad_right": _str_fn(lambda a: _pad(a, True, False), 2, 3),
    "padcut": _str_fn(lambda a: _pad(a, False, True), 2, 3),
    "padcut_right": _str_fn(lambda a: _pad(a, True, True), 2, 3),
    "repeat": _f_repeat,
    "replace": _f_replace,
    "roman": _str_fn(lambda a: _roman(a.n(0)), 1),
    "rot13": _str_fn(lambda a: _rot13(a.s(0)), 1),
    "strchr": lambda a: _strpos(a, last=False),
    "strrchr": lambda a: _strpos(a, last=True),
    "strstr": _f_strstr,
    "strcmp": lambda a: (_need(a, 2), _bool(a.s(0) == a.s(1)))[1],
    "stricmp": lambda a: (_need(a, 2), _bool(a.s(0).lower() == a.s(1).lower()))[1],
    "stripprefix": _str_fn(_stripprefix, *range(1, 32)),
    "swapprefix": _str_fn(_swapprefix, *range(1, 32)),
    "substr": _str_fn(_substr, 3),
    "trim": _str_fn(lambda a: a.s(0).strip(" "), 1),
    "tab": _f_tab,
    "year": _date_part(0, 4, r"\d{4}"),
    "month": _date_part(5, 7, r"\d{4}-\d{2}"),
    "day_of_month": _date_part(8, 10, r"\d{4}-\d{2}-\d{2}"),
    "date": _date_part(0, 10, r"\d{4}-\d{2}-\d{2}"),
    "time": _date_part(11, 19, r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"),
}

_CTX_FUNCS: dict[str, Callable[[Context, _Args], Result]] = {
    "meta": _f_meta,
    "meta_sep": _f_meta_sep,
    "meta_test": _f_meta_test,
    "meta_num": _f_meta_num,
    "info": _f_info,
    "channels": _f_channels,
    "get": _f_get,
    "put": _f_put,
    "puts": _f_puts,
}


def _eval_node(node: Node, ctx: Context) -> Result:
    if isinstance(node, Lit):
        return node.text, False
    if isinstance(node, Field):
        v = lookup_field(ctx, node.name)
        return ("?", False) if v is None else (ctx.filtered(v), True)
    if isinstance(node, Cond):
        s, t = evaluate_nodes(node.body, ctx)
        return (s, True) if t else ("", False)
    args = _Args(ctx, node.args)
    try:
        if (fn := _FUNCS.get(node.name)) is not None:
            return fn(args)
        if (cfn := _CTX_FUNCS.get(node.name)) is not None:
            return cfn(ctx, args)
    except _ArityError:
        return f"[INVALID ${node.name.upper()} SYNTAX]", False
    return "[UNKNOWN FUNCTION]", False


def evaluate_nodes(nodes: tuple, ctx: Context) -> Result:
    out: list[str] = []
    truth = False
    for node in nodes:
        s, t = _eval_node(node, ctx)
        out.append(s)
        truth = truth or t
    return "".join(out), truth


def format_track(template: str, ctx: Context) -> str:
    return evaluate_nodes(compile_format(template), ctx)[0]
