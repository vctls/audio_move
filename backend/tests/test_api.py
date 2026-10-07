import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch, make_audio):
    monkeypatch.setenv("MUSIC_ROOTS", str(tmp_path))
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / ".config"))
    monkeypatch.setenv("LARGE_FOLDER_TRACKS", "3")
    monkeypatch.setenv("MAX_TRACKS", "10")
    for artist in range(3):
        for n in range(2):
            make_audio("flac", f"lib/Artist {artist}/Album/{n:02d}.flac")
    import app.main

    with TestClient(importlib.reload(app.main).app) as c:
        yield c


def test_browse_lists_names_only(client, tmp_path):
    res = client.get("/api/browse", params={"path": str(tmp_path / "lib")}).json()
    assert [d["name"] for d in res["dirs"]] == ["Artist 0", "Artist 1", "Artist 2"]
    assert set(res["dirs"][0]) == {"name", "path"}


def test_summary(client, tmp_path):
    album = str(tmp_path / "lib/Artist 0/Album")
    artist = str(tmp_path / "lib/Artist 0")
    res = client.post("/api/browse/summary", json={"paths": [artist, album, "/etc"]}).json()
    assert res["summaries"] == {
        artist: {"has_children": True, "audio": 0},
        album: {"has_children": False, "audio": 2},
    }


def test_large_folder_needs_force(client, tmp_path):
    lib = str(tmp_path / "lib")
    res = client.get("/api/tracks", params={"path": lib}).json()
    assert res["too_many"] and res["limit"] == 3 and res["tracks"] == []
    res = client.get("/api/tracks", params={"path": lib, "force": True}).json()
    assert not res["too_many"] and len(res["tracks"]) == 6

    album = str(tmp_path / "lib/Artist 1/Album")
    res = client.get("/api/tracks", params={"path": album}).json()
    assert len(res["tracks"]) == 2
