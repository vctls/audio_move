from pathlib import Path

import mutagen
import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from app.tags import WriteOptions, read_track, write_track
from tests.conftest import FORMATS

FIELDS = {
    "TITLE": ["Digital Love"],
    "ARTIST": ["Daft Punk", "Guest"],
    "ALBUM": ["Discovery"],
    "ALBUM ARTIST": ["Daft Punk"],
    "DATE": ["2001"],
    "GENRE": ["House"],
    "TRACKNUMBER": ["03"],
    "TOTALTRACKS": ["14"],
    "DISCNUMBER": ["1"],
    "TOTALDISCS": ["2"],
    "COMMENT": ["hello"],
    "LABEL": ["Virgin"],
    "MUSICBRAINZ_ALBUMID": ["48117b82-8ea6-4b1a-b0f4-35a0a2c5b9a7"],
    "MUSICBRAINZ_TRACKID": ["0a0a0a0a-0000-0000-0000-000000000000"],
    "MY CUSTOM FIELD": ["custom"],
}

EXPECTED_CODEC = {
    "flac": "FLAC",
    "mp3": "MP3",
    "m4a": "AAC",
    "alac.m4a": "ALAC",
    "ogg": "Vorbis",
    "opus": "Opus",
    "wav": "PCM",
    "aiff": "PCM",
    "wv": "WavPack",
}


@pytest.mark.parametrize("fmt", list(FORMATS))
def test_roundtrip(make_audio, fmt):
    path = make_audio(fmt, f"a/track.{fmt}")
    track = write_track(path, FIELDS, [], WriteOptions())
    tags = track["tags"]
    for key, values in FIELDS.items():
        if fmt.endswith("m4a") and key in (
            "TRACKNUMBER",
            "TOTALTRACKS",
            "DISCNUMBER",
            "TOTALDISCS",
        ):
            assert tags[key] == [str(int(values[0]))]
        else:
            assert tags[key] == values, (fmt, key)
    assert track["info"]["codec"] == EXPECTED_CODEC[fmt]
    assert 0.9 < track["info"]["length"] < 1.2

    track = write_track(path, {"TITLE": ["New"]}, ["COMMENT", "MY CUSTOM FIELD"], WriteOptions())
    assert track["tags"]["TITLE"] == ["New"]
    assert "COMMENT" not in track["tags"]
    assert "MY CUSTOM FIELD" not in track["tags"]
    assert track["tags"]["ARTIST"] == ["Daft Punk", "Guest"]


def test_vorbis_album_artist_key(make_audio):
    path = make_audio("flac", "a.flac")
    write_track(
        path, {"ALBUM ARTIST": ["X"]}, [], WriteOptions(vorbis_albumartist_key="ALBUMARTIST")
    )
    assert FLAC(path).tags["ALBUMARTIST"] == ["X"]
    write_track(
        path, {"ALBUM ARTIST": ["Y"]}, [], WriteOptions(vorbis_albumartist_key="ALBUM ARTIST")
    )
    vc = FLAC(path).tags
    assert vc["ALBUM ARTIST"] == ["Y"] and "ALBUMARTIST" not in vc


def test_vorbis_slash_track_number_is_split_and_normalized(make_audio):
    path = make_audio("flac", "a.flac")
    f = FLAC(path)
    if f.tags is None:
        f.add_tags()
    f.tags["TRACKNUMBER"] = "4/12"
    f.tags["TRACKTOTAL"] = "12"
    f.save()
    assert read_track(path)["tags"]["TRACKNUMBER"] == ["4"]
    assert read_track(path)["tags"]["TOTALTRACKS"] == ["12"]
    write_track(path, {"TOTALTRACKS": ["13"]}, [], WriteOptions())
    vc = FLAC(path).tags
    assert vc["TRACKNUMBER"] == ["4"] and vc["TOTALTRACKS"] == ["13"] and "TRACKTOTAL" not in vc


def test_id3_frames(make_audio):
    path = make_audio("mp3", "a.mp3")
    write_track(path, FIELDS, [], WriteOptions())
    id3 = ID3(path)
    assert id3.version == (2, 4, 0)
    assert id3["TRCK"].text == ["03/14"]
    assert id3["TPOS"].text == ["1/2"]
    assert id3["TPE2"].text == ["Daft Punk"]
    assert id3["TXXX:MusicBrainz Album Id"].text == [FIELDS["MUSICBRAINZ_ALBUMID"][0]]
    assert id3["UFID:http://musicbrainz.org"].data == FIELDS["MUSICBRAINZ_TRACKID"][0].encode()


def test_id3v23(make_audio):
    path = make_audio("mp3", "a.mp3")
    write_track(path, {"DATE": ["2001"], "TITLE": ["x"]}, [], WriteOptions(id3_version=3))
    id3 = ID3(path)
    assert id3.version == (2, 3, 0)
    assert read_track(path)["tags"]["DATE"] == ["2001"]


def test_mp4_atoms(make_audio):
    path = make_audio("m4a", "a.m4a")
    write_track(path, FIELDS, [], WriteOptions())
    tags = MP4(path).tags
    assert tags["trkn"] == [(3, 14)]
    assert tags["aART"] == ["Daft Punk"]
    assert (
        bytes(tags["----:com.apple.iTunes:MusicBrainz Track Id"][0]).decode()
        == (FIELDS["MUSICBRAINZ_TRACKID"][0])
    )


def test_unchanged_write_does_not_touch_file(make_audio):
    path = make_audio("flac", "a.flac")
    write_track(path, {"TITLE": ["x"]}, [], WriteOptions())
    before = Path(path).read_bytes()
    write_track(path, {"TITLE": ["x"]}, [], WriteOptions())
    assert Path(path).read_bytes() == before


def test_invalid_field_name(make_audio):
    from app.tags import TagError

    path = make_audio("flac", "a.flac")
    with pytest.raises(TagError):
        write_track(path, {"BAD=NAME": ["x"]}, [], WriteOptions())
    assert mutagen.File(path) is not None
