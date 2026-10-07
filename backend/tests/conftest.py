import os
import shutil
import subprocess

import pytest

FORMATS = {
    "flac": ["-c:a", "flac"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"],
    "m4a": ["-c:a", "aac", "-b:a", "96k"],
    "alac.m4a": ["-c:a", "alac"],
    "ogg": ["-c:a", "libvorbis"],
    "opus": ["-c:a", "libopus"],
    "wav": ["-c:a", "pcm_s16le"],
    "aiff": ["-c:a", "pcm_s16be"],
    "wv": ["-c:a", "wavpack"],
}


@pytest.fixture(scope="session")
def audio_templates(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required to generate audio fixtures")
    out = tmp_path_factory.mktemp("templates")
    files = {}
    for name, codec in FORMATS.items():
        path = out / f"sample.{name}"
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-map_metadata",
                "-1",
                *codec,
                str(path),
            ],
            check=True,
        )
        files[name] = str(path)
    return files


@pytest.fixture
def make_audio(audio_templates, tmp_path):
    def make(fmt: str, rel: str) -> str:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(audio_templates[fmt], dst)
        return str(dst)

    return make


@pytest.fixture
def music_root(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setenv("MUSIC_ROOTS", str(root))
    return os.path.realpath(root)


@pytest.fixture(scope="session")
def images(tmp_path_factory):
    """A small JPEG, a PNG and a large noisy JPEG generated with ffmpeg."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required to generate image fixtures")
    out = tmp_path_factory.mktemp("images")
    specs = {
        "small.jpg": "color=red:s=40x30",
        "small.png": "color=blue:s=64x48",
        "large.jpg": "nullsrc=s=900x900,geq=random(1)*255:128:128",
    }
    data = {}
    for name, source in specs.items():
        path = out / name
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                source,
                "-frames:v",
                "1",
                str(path),
            ],
            check=True,
        )
        data[name] = path.read_bytes()
    return data
