"""Downloads wait in a queue on the server and run one at a time."""
import importlib
import sys
import threading
import time

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    for key, value in {"XTREAM_SERVER": "http://x", "XTREAM_USER": "u", "XTREAM_PASS": "p",
                       "DOWNLOAD_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("app", None)
    yield importlib.import_module("app")
    sys.modules.pop("app", None)


def wait_for(check, seconds=3):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.01)
    return False


def job(start, end="05:00"):
    return {"stream_id": 7, "name": "F1 Race", "date": "2026-11-22", "start_time": start, "end_time": end}


def test_jobs_run_one_after_another_without_a_client(app, monkeypatch):
    gate, running, order = threading.Event(), [], []

    def fake(dl_id):
        running.append(dl_id)
        assert len(running) == 1          # never two at once
        gate.wait(3)
        order.append(dl_id)
        running.remove(dl_id)
        app._active_downloads[dl_id].update(returncode=0, complete=True, got_min=60)

    monkeypatch.setattr(app, "_run_download", fake)
    client = app.app.test_client()
    first = client.post("/api/download", json=job("04:00")).get_json()
    second = client.post("/api/download", json=job("06:00", "07:30")).get_json()
    assert first["dl_id"] == "7_20261122_0400" and second["duration"] == 90

    assert wait_for(lambda: running == [first["dl_id"]])
    states = {j["id"]: j["state"] for j in client.get("/api/downloads").get_json()}
    assert states == {first["dl_id"]: "running", second["dl_id"]: "queued"}
    assert "wachtrij" in app._active_downloads[second["dl_id"]]["log"][0]

    gate.set()                             # nobody asks for the next one: the server starts it
    assert wait_for(lambda: all(j["state"] == "done" for j in client.get("/api/downloads").get_json()))
    assert order == [first["dl_id"], second["dl_id"]]
    assert all(j["ok"] for j in client.get("/api/downloads").get_json())


def test_a_job_that_waits_or_runs_is_not_queued_twice(app, monkeypatch):
    gate, calls = threading.Event(), []
    monkeypatch.setattr(app, "_run_download", lambda dl_id: (calls.append(dl_id), gate.wait(3)))
    client = app.app.test_client()
    client.post("/api/download", json=job("04:00"))
    client.post("/api/download", json=job("04:00"))
    assert len(client.get("/api/downloads").get_json()) == 1
    gate.set()
    assert wait_for(lambda: app._active_downloads["7_20261122_0400"]["done"])
    assert calls == ["7_20261122_0400"]


def test_cancelled_queued_job_is_skipped_and_a_broken_job_does_not_stop_the_queue(app, monkeypatch):
    gate, ran = threading.Event(), []

    def fake(dl_id):
        gate.wait(3)
        ran.append(dl_id)
        if dl_id.endswith("0400"):
            raise RuntimeError("ffmpeg ontbreekt")
        app._active_downloads[dl_id].update(returncode=0, complete=True)

    monkeypatch.setattr(app, "_run_download", fake)
    client = app.app.test_client()
    client.post("/api/download", json=job("04:00"))
    client.post("/api/download", json=job("06:00", "07:00"))
    client.post("/api/download", json=job("08:00", "09:00"))
    assert client.post("/api/cancel/7_20261122_0600").get_json() == {"ok": True}
    gate.set()
    assert wait_for(lambda: all(d["done"] for d in app._active_downloads.values()))
    assert ran == ["7_20261122_0400", "7_20261122_0800"]
    jobs = {j["id"]: j for j in client.get("/api/downloads").get_json()}
    assert jobs["7_20261122_0400"]["ok"] is False
    assert jobs["7_20261122_0600"]["cancelled"] is True
    assert jobs["7_20261122_0800"]["ok"] is True
