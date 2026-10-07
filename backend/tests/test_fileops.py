import os
from pathlib import Path

from app.config import Roots
from app.fileops import Journal, clean_component, destination_parts, execute_plan, plan_operation
from app.guess import guess
from app.tags import WriteOptions, write_track

PATTERN = (
    "%album artist% - %year% - %album% '['$caps(%codec%)']'/%track number% - %artist% - %title%"
)


def tag(path, n, title, artist="AC/DC", album="Back in Black"):
    write_track(
        path,
        {
            "ARTIST": [artist],
            "ALBUM": [album],
            "DATE": ["1980"],
            "TRACKNUMBER": [f"{n:02d}"],
            "TITLE": [title],
        },
        [],
        WriteOptions(),
    )


def test_clean_component():
    assert clean_component('What? "Now": <x>|*', "_") == "What_ _Now__ _x___"
    assert clean_component("Trailing dots...", "_") == "Trailing dots"
    assert clean_component("..", "_") == ""


def test_destination_parts_extension_and_slashes():
    track = {"path": "/m/a.flac", "tags": {"ARTIST": ["AC/DC"], "TITLE": ["T"]}, "info": {}}
    assert destination_parts("%artist%/%title%", track, "_") == ["AC_DC", "T.flac"]
    assert destination_parts("%artist%\\%title%.flac", track, "_") == ["AC_DC", "T.flac"]


def test_move_with_other_files_and_cleanup(make_audio, tmp_path):
    root = os.path.realpath(tmp_path)
    roots = Roots((root,))
    src_dir = os.path.join(root, "incoming", "acdc bib")
    a = make_audio("flac", "incoming/acdc bib/CD1/01.flac")
    b = make_audio("flac", "incoming/acdc bib/CD1/02.flac")
    tag(a, 1, "Hells Bells")
    tag(b, 2, "Shoot to Thrill")
    Path(src_dir, "cover.jpg").write_bytes(b"jpg")
    Path(src_dir, "CD1", "rip.log").write_text("log")
    os.makedirs(os.path.join(src_dir, "Scans"))
    Path(src_dir, "Scans", "back.png").write_bytes(b"png")
    unrelated = make_audio("mp3", "incoming/acdc bib/bonus.mp3")

    dest = os.path.join(root, "library")
    plan = plan_operation(roots, [a, b], PATTERN, "move", dest, True, src_dir, "_")
    album_dir = os.path.join(dest, "AC_DC - 1980 - Back in Black [Flac]")
    by_src = {os.path.relpath(i.src, src_dir): i for i in plan.items}
    assert by_src["CD1/01.flac"].dst == os.path.join(album_dir, "01 - AC_DC - Hells Bells.flac")
    assert by_src["cover.jpg"].dst == os.path.join(album_dir, "cover.jpg")
    assert by_src["Scans"].dst == os.path.join(album_dir, "Scans")
    assert by_src["CD1/rip.log"].dst == os.path.join(album_dir, "rip.log")
    assert "bonus.mp3" not in by_src
    assert all(i.status == "ok" for i in plan.items)

    result = execute_plan(plan, roots, True, src_dir)
    assert os.path.isfile(os.path.join(album_dir, "02 - AC_DC - Shoot to Thrill.flac"))
    assert os.path.isfile(os.path.join(album_dir, "Scans", "back.png"))
    assert os.path.join(src_dir, "CD1") in result["removed_dirs"]
    # The unselected bonus track keeps the source folder alive.
    assert os.path.isfile(unrelated)

    journal = Journal(str(tmp_path / "config"))
    jid = journal.add("move", result["done"], result["removed_dirs"], result["created_dirs"])
    undo = journal.undo(jid, roots)
    assert not undo["errors"]
    assert os.path.isfile(a) and os.path.isfile(os.path.join(src_dir, "Scans", "back.png"))
    assert not os.path.exists(os.path.join(dest))


def test_conflicts(make_audio, tmp_path):
    root = os.path.realpath(tmp_path)
    roots = Roots((root,))
    a = make_audio("flac", "in/a.flac")
    b = make_audio("flac", "in/b.flac")
    tag(a, 1, "Same")
    tag(b, 1, "Same")
    plan = plan_operation(roots, [a, b], "%title%", "rename", "", False, None, "_")
    assert [i.status for i in plan.items] == ["ok", "duplicate"]

    c = make_audio("flac", "in/c.flac")
    tag(c, 1, "a")
    plan = plan_operation(roots, [c], "%title%", "rename", "", False, None, "_")
    assert plan.items[0].status == "exists"

    plan = plan_operation(roots, [a], "a", "rename", "", False, None, "_")
    assert plan.items[0].status == "unchanged"


def test_destination_outside_roots_rejected(make_audio, tmp_path):
    import pytest

    from app.config import PathError

    root = os.path.realpath(tmp_path / "music")
    os.makedirs(root)
    roots = Roots((root,))
    a = make_audio("flac", "music/a.flac")
    with pytest.raises(PathError):
        plan_operation(roots, [a], "%title%", "move", "/tmp", False, None, "_")
    plan = plan_operation(roots, [a], "../../%title%", "rename", "", False, None, "_")
    assert plan.items[0].dst.startswith(root)


def test_guess():
    assert guess(
        "%tracknumber% - %artist% - %title%", "/m/x/03 - Daft Punk - One More Time.flac"
    ) == {
        "TRACKNUMBER": "03",
        "ARTIST": "Daft Punk",
        "TITLE": "One More Time",
    }
    assert guess(
        "%album artist% - %album%/%track number%. %title%", "/m/Air - Moon Safari/01. La Femme.mp3"
    ) == {
        "ALBUM ARTIST": "Air",
        "ALBUM": "Moon Safari",
        "TRACKNUMBER": "01",
        "TITLE": "La Femme",
    }
    assert guess("%tracknumber% - %title%", "/m/no separator.flac") is None
