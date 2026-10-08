from pydantic import TypeAdapter

from app.config import Settings
from app.presets import FormatAction, RemoveAction, TagAction, apply_actions, default_presets

MB_TAGS = {
    "TITLE": ["One"],
    "TRACKNUMBER": ["03"],
    "TOTALTRACKS": ["09"],
    "DISCNUMBER": ["1"],
    "TOTALDISCS": ["1"],
    "MUSICBRAINZ_ALBUMID": ["x"],
    "MUSICBRAINZ_TRACKID": ["y"],
}


def run(actions, tags, multivalue=()):
    return apply_actions(actions, tags, {}, "/music/a.flac", multivalue)


def test_default_preset_tidies_single_disc():
    out = run(default_presets()[0].actions, MB_TAGS)
    assert out["TRACKNUMBER"] == ["3"]
    assert out["TOTALTRACKS"] == ["9"]
    assert "DISCNUMBER" not in out and "TOTALDISCS" not in out
    assert out["TITLE"] == ["One"]


def test_default_preset_keeps_disc_of_a_set():
    out = run(default_presets()[0].actions, {**MB_TAGS, "DISCNUMBER": ["2"], "TOTALDISCS": ["2"]})
    assert out["DISCNUMBER"] == ["2"] and out["TOTALDISCS"] == ["2"]


def test_default_preset_does_not_invent_numbers():
    assert run(default_presets()[0].actions, {"TITLE": ["One"]}) == {"TITLE": ["One"]}


def test_actions_see_previous_results():
    actions = [
        FormatAction(field="comment", template="%title%!"),
        FormatAction(field="TITLE", template="%comment%?"),
    ]
    out = run(actions, {"TITLE": ["Hi"]})
    assert out == {"TITLE": ["Hi!?"], "COMMENT": ["Hi!"]}


def test_format_replaces_differently_cased_key_and_splits_multivalue():
    out = run([FormatAction(field="ARTIST", template="A; B")], {"Artist": ["Old"]}, ["ARTIST"])
    assert out == {"ARTIST": ["A", "B"]}


def test_remove_with_wildcards():
    out = run([RemoveAction(fields=["musicbrainz_*", " title "])], MB_TAGS)
    assert set(out) == {"TRACKNUMBER", "TOTALTRACKS", "DISCNUMBER", "TOTALDISCS"}


def test_actions_parse_from_settings_json():
    actions = TypeAdapter(list[TagAction]).validate_python(
        [{"type": "remove", "fields": ["X"]}, {"type": "pictures_to_folder"}]
    )
    assert run(actions, {"X": ["1"], "Y": ["2"]}) == {"Y": ["2"]}
    s = Settings.model_validate_json(Settings().model_dump_json())
    assert s.tag_presets == default_presets()
