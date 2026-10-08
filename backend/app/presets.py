"""Tag presets: named lists of actions applied in order, like foobar2000 Masstagger scripts."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from fnmatch import fnmatchcase
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from .titleformat import Context, format_track


class FormatAction(BaseModel):
    """Set a field from a title formatting template. An empty result removes the field."""

    type: Literal["format"] = "format"
    field: str
    template: str


class RemoveAction(BaseModel):
    """Remove fields by name. Shell-style wildcards such as MUSICBRAINZ_* are allowed."""

    type: Literal["remove"] = "remove"
    fields: list[str]


class PicturesToFolderAction(BaseModel):
    """Save embedded pictures as the folder image, then remove them from the files.

    It only touches files, so apply_actions leaves the tags alone and the client runs it.
    """

    type: Literal["pictures_to_folder"] = "pictures_to_folder"


TagAction = Annotated[
    FormatAction | RemoveAction | PicturesToFolderAction, Field(discriminator="type")
]


class TagPreset(BaseModel):
    name: str
    actions: list[TagAction] = Field(default_factory=list)


def default_presets() -> list[TagPreset]:
    return [
        TagPreset(
            name="Tidy after MusicBrainz",
            actions=[
                FormatAction(field="TRACKNUMBER", template="[$num(%track number%,0)]"),
                FormatAction(field="TOTALTRACKS", template="[$num(%totaltracks%,0)]"),
                # DISCNUMBER first, because it reads TOTALDISCS.
                FormatAction(
                    field="DISCNUMBER", template="$ifgreater(%totaldiscs%,1,%discnumber%,)"
                ),
                FormatAction(
                    field="TOTALDISCS", template="$ifgreater(%totaldiscs%,1,%totaldiscs%,)"
                ),
                PicturesToFolderAction(),
            ],
        )
    ]


def _without(tags: dict[str, list[str]], patterns: list[str]) -> dict[str, list[str]]:
    upper = [p.strip().upper() for p in patterns if p.strip()]
    return {k: v for k, v in tags.items() if not any(fnmatchcase(k.upper(), p) for p in upper)}


def apply_actions(
    actions: list[TagAction],
    tags: Mapping[str, list[str]],
    info: Mapping[str, Any],
    path: str,
    multivalue: Collection[str],
) -> dict[str, list[str]]:
    """Return the tags of one track after the actions, each seeing the previous one's result."""
    out = {k: list(v) for k, v in tags.items()}
    multi = {f.upper() for f in multivalue}
    for action in actions:
        if isinstance(action, FormatAction):
            name = action.field.strip().upper()
            if not name:
                continue
            text = format_track(action.template, Context(out, info, path))
            parts = text.split(";") if name in multi else [text]
            values = [v.strip() for v in parts if v.strip()]
            out = _without(out, [name])
            if values:
                out[name] = values
        elif isinstance(action, RemoveAction):
            out = _without(out, action.fields)
    return out
