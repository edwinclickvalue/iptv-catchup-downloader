"""A log of finished downloads says who fetched what, so nothing is done twice."""
import importlib
import json
import os
import sys
import time

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    for key, value in {"XTREAM_SERVER": "http://x", "XTREAM_USER": "u", "XTREAM_PASS": "p",
                       "DOWNLOAD_DIR": str(tmp_path / "dl"), "CACHE_DIR": str(tmp_path / "cache"),
                       "AUTO_RACE": "1"}.items():
        monkeypatch.setenv(key, value)
    os.makedirs(tmp_path / "dl")
    sys.modules.pop("app", None)
    module = importlib.import_module("app")

    def fake(dl_id):                      # a download that leaves a file behind
        dl = module._active_downloads[dl_id]
        with open(dl["out"], "wb") as fh:
            fh.write(b"x" * 10)
        dl.update(returncode=0, complete=True, got_min=dl["duration"])

    monkeypatch.setattr(module, "_run_download", fake)
    yield module
    sys.modules.pop("app", None)


def settle(app):
    end = time.time() + 3
    while time.time() < end and any(not d["done"] for d in app._active_downloads.values()):
        time.sleep(0.01)


RACE = {"title": "Live Las Vegas F1 Grand Prix", "description": "", "session": "Race", "live": True,
        "start": "2026-11-22 04:55:00", "end": "2026-11-22 07:00:00"}
RACE_FILE = "F1_Live_Las_Vegas_F1_Grand_Prix_Race_20261122_0455.ts"


def watch_race(app, monkeypatch):
    monkeypatch.setattr(app, "best_f1_channel", lambda: {"id": 7, "days": 3})
    monkeypatch.setattr(app, "epg_listings", lambda channel: [])
    monkeypatch.setattr(app.f1, "archived_programs",
                        lambda listings: [dict(RACE, end_ts=time.time() - 3600)])


def by_hand(app):
    app.app.test_client().post("/api/download", json={
        "stream_id": 7, "name": "F1 Live Las Vegas F1 Grand Prix Race",
        "date": "2026-11-22", "start_time": "04:55", "end_time": "07:00"})
    settle(app)


def test_race_fetched_by_hand_is_not_fetched_again_even_when_the_file_is_gone(app, monkeypatch, tmp_path):
    watch_race(app, monkeypatch)
    by_hand(app)
    [entry] = json.load(open(app.LOG_FILE))
    assert (entry["source"], entry["ok"], entry["file"], entry["size"]) == ("handmatig", True, RACE_FILE, 10)

    os.remove(tmp_path / "dl" / RACE_FILE)     # watched and thrown away
    app._active_downloads.clear()              # and the container restarted
    assert app.auto_check() == []

    [row] = app.app.test_client().get("/api/files").get_json()["files"]
    assert (row["name"], row["source"], row["missing"]) == (RACE_FILE, "handmatig", True)


def test_automatic_download_is_logged_as_automatic_and_shown_on_the_page(app, monkeypatch):
    watch_race(app, monkeypatch)
    assert app.auto_check() == ["7_20261122_0455"]
    settle(app)
    client = app.app.test_client()
    [row] = client.get("/api/files").get_json()["files"]
    assert (row["source"], row["missing"], row["incomplete"]) == ("automatisch", False, False)
    assert client.get("/api/f1").get_json()["programs"][0]["downloaded"] == "automatisch"
    assert client.get("/api/downloads").get_json()[0]["source"] == "automatisch"


def test_programmes_are_marked_from_the_log_or_from_a_file_that_predates_it(app, tmp_path):
    (tmp_path / "dl" / "F1_Live_Chequered_Flag_20261122_0700.ts").write_bytes(b"x")
    by_hand(app)
    programs = [{"start": "2026-11-22 04:55:00"}, {"start": "2026-11-22 07:00:00"}, {"start": "2026-11-22 08:00:00"}]
    app.mark_downloaded(7, programs)
    assert [p["downloaded"] for p in programs] == ["handmatig", "op schijf", ""]


def test_incomplete_download_is_logged_as_such_and_a_retry_replaces_it(app, monkeypatch):
    results = [False, True]
    monkeypatch.setattr(app, "_run_download", lambda dl_id: app._active_downloads[dl_id].update(
        returncode=0, complete=results.pop(0), got_min=3))
    by_hand(app)
    assert [e["ok"] for e in json.load(open(app.LOG_FILE))] == [False]
    by_hand(app)
    assert [e["ok"] for e in json.load(open(app.LOG_FILE))] == [True]
