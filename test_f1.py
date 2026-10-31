import base64
import subprocess

import f1


def b64(text):
    return base64.b64encode(text.encode()).decode()


CATS = {"1": "UK| SPORTS", "2": "UK| FORMULA 1 + MOTOGP", "3": "DE| SPORTS", "4": "UK| SPORTS"}


def stream(sid, name, cat, archive=1):
    return {"stream_id": sid, "name": name, "category_id": cat,
            "tv_archive": archive, "tv_archive_duration": 3}


def test_candidates_keeps_only_uk_sky_f1_with_archive():
    streams = [
        stream(1, "UK| SKY SPORTS F1 HD", "1"),
        stream(2, "UK| SKY SPORTS F1 HD", "2"),
        stream(3, "DE| SKY SPORTS F1 HD", "3"),           # wrong country
        stream(4, "UK| SKY SPORTS F1 UHD/4K", "1", 0),    # no catch-up
        stream(5, "UK| SKY SPORTS FOOTBALL HD", "4"),     # not F1
    ]
    assert [c["id"] for c in f1.candidates(streams, CATS)] == [1, 2]


def test_pick_best_prefers_resolution_then_bitrate():
    probed = [
        {"id": 1, "height": 720, "bitrate": 6_000_000},
        {"id": 2, "height": 1080, "bitrate": 10_000_000},
        {"id": 3, "height": 1080, "bitrate": 8_000_000},
        {"id": 4},  # probe failed
    ]
    assert f1.pick_best(probed)["id"] == 2


def test_pick_best_falls_back_to_unprobed_and_handles_empty():
    assert f1.pick_best([{"id": 7}])["id"] == 7
    assert f1.pick_best([]) is None


def listing(title, start, end, start_ts, stop_ts, archive=1):
    return {"title": b64(title), "description": b64(""), "start": start, "end": end,
            "start_timestamp": str(start_ts), "stop_timestamp": str(stop_ts),
            "has_archive": archive}


def test_archived_programs_filters_and_sorts():
    now = 1_000_000
    listings = [
        listing("Live Mexico City F1 GP", "2026-10-30 19:00:00", "2026-10-30 21:00:00", now - 7000, now - 100),
        listing("The F1 Show", "2026-10-30 21:00:00", "2026-10-30 22:00:00", now - 100, now + 3000),  # on air
        listing("Old show", "2026-10-29 10:00:00", "2026-10-29 11:00:00", now - 90000, now - 86400, archive=0),
        listing("Paddock Uncut", "2026-10-29 11:00:00", "2026-10-29 11:30:00", now - 86000, now - 84000),
    ]
    progs = f1.archived_programs(listings, now_ts=now)
    assert [p["title"] for p in progs] == ["Live Mexico City F1 GP", "Paddock Uncut"]
    assert progs[0]["live"] is True
    assert progs[1]["live"] is False


def test_probe_parses_ffprobe_output(monkeypatch):
    out = "height=1080\nheight=1080\nbit_rate=10215505\n"
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    assert f1.probe("http://x") == {"height": 1080, "bitrate": 10215505}


def test_probe_returns_empty_on_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ffprobe", 1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert f1.probe("http://x") == {}


def test_session_label_reads_the_description():
    gp = "Mexico City F1 GP"
    assert f1.session_label(gp, "The opening Formula 1 practice session of Mexico City Grand Prix weekend.") == "VT1"
    assert f1.session_label("Live " + gp, "The second Formula 1 practice session of the weekend.") == "VT2"
    assert f1.session_label(gp, "The third and final practice session.") == "VT3"
    assert f1.session_label(gp, "Qualifying for the Mexico City Grand Prix.") == "Kwalificatie"
    assert f1.session_label(gp, "Sprint qualifying from Austin.") == "Sprint-kwalificatie"
    assert f1.session_label("Mexico City F1 Grand Prix", "It's lights out for the race in Mexico City.") == "Race"
    assert f1.session_label("US F1 GP Highlights", "It's lights out for the race in Austin.") == "Samenvatting"
    assert f1.session_label("Ted's Quali Notebook", "Ted looks back on qualifying.") is None
    assert f1.session_label("The F1 Show", "A sneak peek of the paddock.") is None
