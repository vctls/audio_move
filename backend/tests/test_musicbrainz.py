import json
import os

from app.musicbrainz import (
    TagOptions,
    build_query,
    parse_mbid,
    release_with_tags,
    summarize_release_detail,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "release_2x_vinyl.json")


def load():
    with open(FIXTURE, encoding="utf-8") as f:
        return summarize_release_detail(json.load(f))


def test_summary():
    r = load()
    assert r["title"] == "Discovery"
    assert r["artist"] == "Daft Punk"
    assert r["format"] == '2×12" Vinyl'
    assert r["track_count"] == 14
    assert [m["position"] for m in r["media"]] == [1, 2]
    assert r["media"][1]["tracks"][0]["number"] == "C1"
    assert r["media"][1]["tracks"][0]["position"] == 1


def test_track_tags_default():
    r = release_with_tags(load(), TagOptions())
    tags = r["media"][1]["tracks"][0]["tags"]
    assert tags["TITLE"] == ["High Life"]
    assert tags["ALBUM"] == ["Discovery"]
    assert tags["ALBUM ARTIST"] == ["Daft Punk"]
    assert tags["DATE"] == ["2021"]
    assert tags["ORIGINALDATE"] == ["2001"]
    assert tags["TRACKNUMBER"] == ["01"]
    assert tags["TOTALTRACKS"] == ["07"]
    assert tags["DISCNUMBER"] == ["2"]
    assert tags["TOTALDISCS"] == ["2"]
    assert tags["MEDIA"] == ['12" Vinyl']
    assert tags["RELEASETYPE"] == ["album"]
    assert tags["ISRC"] == ["GBDUW0000063"]
    assert tags["MUSICBRAINZ_ALBUMID"] == ["b078d70c-d2eb-489a-a8f8-e322af35dedf"]
    assert len(tags["MUSICBRAINZ_TRACKID"][0]) == 36


def test_track_tags_options():
    r = release_with_tags(load(), TagOptions(date="full", groups={"basic"}, padding=0))
    tags = r["media"][0]["tracks"][2]["tags"]
    assert tags["DATE"] == ["2021-12-17"]
    assert tags["TRACKNUMBER"] == ["3"]
    assert "MUSICBRAINZ_ALBUMID" not in tags
    assert "LABEL" not in tags


def test_single_disc_omits_disc_number():
    rel = load()
    rel["media"] = rel["media"][:1]
    tags = release_with_tags(rel, TagOptions())["media"][0]["tracks"][0]["tags"]
    assert "DISCNUMBER" not in tags
    tags = release_with_tags(rel, TagOptions(disc_for_single=True))["media"][0]["tracks"][0]["tags"]
    assert tags["DISCNUMBER"] == ["1"] and tags["TOTALDISCS"] == ["1"]


def test_query_and_mbid_parsing():
    assert build_query("AC/DC", "Back in Black") == r"release:(Back in Black) AND artist:(AC\/DC)"
    mbid = "b078d70c-d2eb-489a-a8f8-e322af35dedf"
    assert parse_mbid(mbid) == ("release", mbid)
    assert parse_mbid(f"https://musicbrainz.org/release-group/{mbid}") == ("release-group", mbid)
    assert parse_mbid("nothing here") is None
