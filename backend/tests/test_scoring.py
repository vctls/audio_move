from app.cues import collect_cues
from app.musicbrainz import rank_releases
from app.scoring import format_family


def release(id_: str, *formats: str, score: int | None = 100, tracks: int = 10) -> dict:
    media = [{"format": f, "track_count": tracks} for f in formats]
    return {"id": id_, "score": score, "media": media, "track_count": tracks * len(media)}


def track(path, tags=None, **info) -> dict:
    return {
        "path": str(path),
        "tags": tags or {},
        "info": {"encoding": "lossless", "samplerate": 44100, "bitspersample": 16, **info},
    }


def album(tmp_path, name: str, *extra: str, count: int = 10) -> list[dict]:
    folder = tmp_path / name
    folder.mkdir(parents=True)
    for f in extra:
        (folder / f).touch()
    return [track(folder / f"{n:02d}.flac") for n in range(count)]


def ranked(releases, tracks) -> list[str]:
    return [r["id"] for r in rank_releases(releases, collect_cues(tracks))]


CANDIDATES = [
    release("web", "Digital Media"),
    release("vinyl", '12" Vinyl'),
    release("cd", "CD"),
]


def test_format_family():
    assert format_family("Enhanced CD") == "cd"
    assert format_family("Hybrid SACD") == "cd"
    assert format_family('7" Vinyl') == "vinyl"
    assert format_family("Digital Media") == "digital"
    assert format_family("DVD-Video") == "other"


def test_rip_log_favours_cd(tmp_path):
    tracks = album(tmp_path, "Artist - Album", "Artist - Album.log")
    ranked_releases = rank_releases(CANDIDATES, collect_cues(tracks))
    assert ranked_releases[0]["id"] == "cd"
    assert "Ripping log in the folder" in [
        r["reason"] for r in ranked_releases[0]["match"]["reasons"]
    ]


def test_log_next_to_disc_folders(tmp_path):
    tracks = album(tmp_path, "Album/CD1")
    (tmp_path / "Album" / "rip.log").touch()
    assert ranked(CANDIDATES, tracks)[0] == "cd"


def test_explicit_cues_outweigh_rip_log(tmp_path):
    tracks = album(tmp_path, "Album [Vinyl]", "rip.log")
    assert ranked(CANDIDATES, tracks)[0] == "vinyl"
    tracks = album(tmp_path, "Other", "rip.log")
    for t in tracks:
        t["tags"]["MEDIA"] = ["Digital Media"]
    assert ranked(CANDIDATES, tracks)[0] == "web"


def test_scene_style_folder_name(tmp_path):
    tracks = album(tmp_path, "Artist-Album-WEB-2020-GRP")
    assert ranked(CANDIDATES, tracks)[0] == "web"
    tracks = album(tmp_path, "Artist_-_Album-2CD-2020")
    assert ranked(CANDIDATES, tracks)[0] == "cd"


def test_hires_audio_is_not_from_cd(tmp_path):
    tracks = [
        {**t, "info": {**t["info"], "bitspersample": 24, "samplerate": 96000}}
        for t in album(tmp_path, "Album", "rip.log")
    ]
    assert ranked(CANDIDATES, tracks)[-1] == "cd"


def test_track_count_and_relevance(tmp_path):
    tracks = album(tmp_path, "Album", count=12)
    releases = [
        release("other", "CD", score=100, tracks=10),
        release("match", "CD", score=95, tracks=12),
        release("unrelated", "CD", score=60, tracks=12),
    ]
    assert ranked(releases, tracks) == ["match", "other", "unrelated"]


def test_no_cues_keeps_order():
    releases = [release("a", "CD", score=None), release("b", "Vinyl", score=None)]
    assert ranked(releases, []) == ["a", "b"]
    assert all(r["match"] == {"points": 0, "reasons": []} for r in releases)
