"""The page lists what is already in the download folder."""
import importlib
import os
import sys

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    for key, value in {"XTREAM_SERVER": "http://x", "XTREAM_USER": "u", "XTREAM_PASS": "p",
                       "DOWNLOAD_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("app", None)
    yield importlib.import_module("app")
    sys.modules.pop("app", None)


def test_lists_recordings_newest_first_and_marks_the_running_one(app, tmp_path):
    for name, size, mtime in [("F1_Old_20261101_2055.ts", 10, 1000), ("F1_New_20261122_0455.ts", 20, 3000),
                              ("F1_Now_20261122_0700.ts", 5, 2000), ("notes.txt", 1, 4000),
                              ("F1_Now_20261122_0700.ts.part", 1, 4000)]:
        path = tmp_path / name
        path.write_bytes(b"x" * size)
        os.utime(path, (mtime, mtime))
    (tmp_path / "map.ts").mkdir()
    app._active_downloads["j"] = {"out": f"{tmp_path}/F1_Now_20261122_0700.ts", "done": False}

    data = app.app.test_client().get("/api/files").get_json()
    assert data["folder"] == str(tmp_path)
    assert [(f["name"], f["size"], f["busy"]) for f in data["files"]] == [
        ("F1_New_20261122_0455.ts", 20, False),
        ("F1_Now_20261122_0700.ts", 5, True),
        ("F1_Old_20261101_2055.ts", 10, False),
    ]


def test_missing_folder_gives_an_empty_list(app, monkeypatch):
    monkeypatch.setattr(app, "DOWNLOAD_DIR", "/bestaat/niet")
    assert app.app.test_client().get("/api/files").get_json()["files"] == []
