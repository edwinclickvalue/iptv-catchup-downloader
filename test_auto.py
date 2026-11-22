"""With AUTO_RACE=1 the app queues every live race broadcast by itself."""
import importlib
import json
import os
import sys
import time

import pytest

import f1


def program(title, session, live, end_ts, start="2026-11-22 04:55:00", end="2026-11-22 07:00:00"):
    return {"title": title, "description": "", "session": session, "live": live,
            "start": start, "end": end, "end_ts": end_ts}


def test_races_due_takes_only_the_live_race_after_the_margin():
    now = 1_000_000
    programs = [
        program("Live Las Vegas F1 Grand Prix", "Race", True, now - 3600),
        program("Las Vegas F1 Grand Prix", "Race", False, now - 3600),        # repeat
        program("Live Grand Prix Sunday", None, True, now - 9000),            # build-up
        program("Live Las Vegas F1 GP", "Kwalificatie", True, now - 90000),   # other session
        program("Live Qatar F1 Grand Prix", "Race", True, now - 600),         # margin not over
    ]
    assert [p["title"] for p in f1.races_due(programs, now, extra_min=30)] == ["Live Las Vegas F1 Grand Prix"]


def test_padded_end_adds_the_margin_also_past_midnight():
    assert f1.padded_end("2026-11-22 07:00:00", 30) == "07:30"
    assert f1.padded_end("2026-11-22 23:50:00", 30) == "00:20"


@pytest.fixture
def app(monkeypatch, tmp_path):
    for key, value in {"XTREAM_SERVER": "http://x", "XTREAM_USER": "u", "XTREAM_PASS": "p",
                       "DOWNLOAD_DIR": str(tmp_path / "dl"), "CACHE_DIR": str(tmp_path / "cache"),
                       "AUTO_RACE": "1"}.items():
        monkeypatch.setenv(key, value)
    os.makedirs(tmp_path / "dl")
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    race = program("Live Las Vegas F1 Grand Prix", "Race", True, time.time() - 3600)
    monkeypatch.setattr(module, "best_f1_channel", lambda: {"id": 7, "days": 3})
    monkeypatch.setattr(module, "epg_listings", lambda channel: [])
    monkeypatch.setattr(module.f1, "archived_programs", lambda listings: [race])
    module.results = []          # what each fake download ends with

    def fake(dl_id):
        module._active_downloads[dl_id].update(returncode=0, complete=module.results.pop(0))

    monkeypatch.setattr(module, "_run_download", fake)
    yield module
    sys.modules.pop("app", None)


def settle(app):
    end = time.time() + 3
    while time.time() < end and any(not d["done"] for d in app._active_downloads.values()):
        time.sleep(0.01)


RACE_ID = "7_20261122_0455"


def test_race_is_queued_once_with_margin_and_remembered_over_a_restart(app):
    app.results = [True]
    assert app.auto_check() == [RACE_ID]
    job = app._active_downloads[RACE_ID]
    assert job["duration"] == 155                      # 04:55-07:00 plus 30 min
    assert job["out"].endswith("F1_Live_Las_Vegas_F1_Grand_Prix_Race_20261122_0455.ts")
    settle(app)
    assert app.auto_check() == []                      # done: not again
    app._active_downloads.clear()                      # restart: jobs gone, auto.json stays
    assert app.auto_check() == []
    assert json.load(open(app.AUTO_FILE))[RACE_ID]["ok"] is True


def test_incomplete_race_is_tried_again_up_to_three_times(app):
    app.results = [False, False, False]
    for _ in range(3):
        assert app.auto_check() == [RACE_ID]
        settle(app)
    assert app.auto_check() == []


def test_race_fetched_by_hand_is_left_alone(app):
    open(app.job_names(7, "F1 Live Las Vegas F1 Grand Prix Race", "2026-11-22", "04:55")[1], "w").close()
    assert app.auto_check() == []


def test_nothing_is_checked_while_a_download_uses_the_connection(app, monkeypatch):
    app._active_downloads["x"] = {"done": False}
    monkeypatch.setattr(app, "best_f1_channel", lambda: pytest.fail("provider called"))
    assert app.auto_check() == []


def test_page_is_told_that_auto_is_on(app):
    assert app.app.test_client().get("/api/f1").get_json()["auto"] is True
