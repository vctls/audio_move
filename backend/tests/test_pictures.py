import base64
import os
from pathlib import Path

import mutagen
import pytest
from mutagen.apev2 import BINARY, APEValue
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4Cover

from app.pictures import (
    extract_folder_images,
    folder_image_info,
    image_size,
    save_folder_image,
    sniff_mime,
)
from app.tags import WriteOptions, read_track, write_track


def embed(path: str, data: bytes, mime: str = "image/jpeg", ptype: int = 3) -> None:
    audio = mutagen.File(path)
    if isinstance(audio, FLAC):
        pic = Picture()
        pic.type, pic.mime, pic.data = ptype, mime, data
        audio.add_picture(pic)
    else:
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        name = type(audio).__name__
        if name in ("MP3", "WAVE", "AIFF"):
            tags.add(APIC(encoding=3, mime=mime, type=ptype, desc=str(len(tags)), data=data))
        elif name == "MP4":
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            tags["covr"] = [*tags.get("covr", []), MP4Cover(data, imageformat=fmt)]
        elif name == "WavPack":
            label = "Front" if ptype == 3 else "Back"
            tags[f"Cover Art ({label})"] = APEValue(b"cover.jpg\x00" + data, BINARY)
        else:
            pic = Picture()
            pic.type, pic.mime, pic.data = ptype, mime, data
            existing = list(tags.get("METADATA_BLOCK_PICTURE", []))
            tags["METADATA_BLOCK_PICTURE"] = [*existing, base64.b64encode(pic.write()).decode()]
    audio.save()


def test_image_helpers(images):
    assert sniff_mime(images["small.jpg"]) == "image/jpeg"
    assert sniff_mime(images["small.png"]) == "image/png"
    assert image_size(images["small.jpg"]) == (40, 30)
    assert image_size(images["small.png"]) == (64, 48)
    assert image_size(images["large.jpg"]) == (900, 900)
    assert image_size(b"nope") == (0, 0)


@pytest.mark.parametrize("fmt", ["flac", "mp3", "m4a", "ogg", "opus", "wav", "aiff", "wv"])
def test_list_and_remove(make_audio, images, fmt):
    path = make_audio(fmt, f"album/track.{fmt}")
    write_track(path, {"TITLE": ["Kept"]}, [], WriteOptions())
    embed(path, images["large.jpg"])
    pictures = read_track(path)["pictures"]
    assert pictures == [
        {
            "type": "front",
            "mime": "image/jpeg",
            "width": 900,
            "height": 900,
            "size": len(images["large.jpg"]),
        }
    ]

    before = os.path.getsize(path)
    track = write_track(path, {}, [], WriteOptions(), drop_pictures=True)
    assert track["pictures"] == []
    assert track["tags"]["TITLE"] == ["Kept"]
    assert os.path.getsize(path) < before - len(images["large.jpg"]) // 2


def test_remove_without_pictures_leaves_file_alone(make_audio):
    path = make_audio("flac", "a.flac")
    before = Path(path).read_bytes()
    write_track(path, {}, [], WriteOptions(), drop_pictures=True)
    assert Path(path).read_bytes() == before


def test_extract_prefers_front_cover(make_audio, images, tmp_path):
    a = make_audio("mp3", "album/01.mp3")
    b = make_audio("mp3", "album/02.mp3")
    embed(a, images["large.jpg"], ptype=4)
    embed(b, images["small.png"], mime="image/png")
    results = extract_folder_images([a, b], "folder")
    assert results == [
        {"dir": str(tmp_path / "album"), "ok": True, "path": str(tmp_path / "album/folder.png")}
    ]
    assert (tmp_path / "album/folder.png").read_bytes() == images["small.png"]
    info = folder_image_info(str(tmp_path / "album"), "folder")
    assert info == {
        "names": ["folder.png"],
        "width": 64,
        "height": 48,
        "size": len(images["small.png"]),
    }

    again = extract_folder_images([a, b], "folder")
    assert again[0]["skipped"] and "folder.png" in again[0]["message"]


def test_extract_without_usable_picture(make_audio, tmp_path):
    a = make_audio("flac", "album/01.flac")
    assert extract_folder_images([a], "folder")[0]["ok"] is False
    assert not list((tmp_path / "album").glob("folder.*"))


def test_save_folder_image_keeps_a_single_file(tmp_path, images):
    d = str(tmp_path)
    assert save_folder_image(d, "folder", images["small.png"], overwrite=False)["ok"]
    refused = save_folder_image(d, "folder", images["small.jpg"], overwrite=False)
    assert not refused["ok"] and "folder.png" in refused["error"]
    assert save_folder_image(d, "folder", images["small.jpg"], overwrite=True)["ok"]
    assert sorted(os.listdir(d)) == ["folder.jpg"]
    assert not save_folder_image(d, "folder", b"GIF89a....", overwrite=True)["ok"]
