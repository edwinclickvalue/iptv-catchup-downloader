"""The NAS container steers host, port and cache folder through the environment."""
import importlib
import os
import sys

import pytest


@pytest.fixture
def load_app(monkeypatch):
    for key, value in {"XTREAM_SERVER": "http://x", "XTREAM_USER": "u", "XTREAM_PASS": "p"}.items():
        monkeypatch.setenv(key, value)

    def _load():
        sys.modules.pop("app", None)
        return importlib.import_module("app")

    yield _load
    sys.modules.pop("app", None)


def test_cache_dir_defaults_next_to_the_code(load_app, monkeypatch):
    monkeypatch.delenv("CACHE_DIR", raising=False)
    app = load_app()
    here = os.path.dirname(os.path.abspath(app.__file__))
    assert app.HISTORY_FILE == os.path.join(here, ".cache", "guide.json")


def test_cache_dir_from_environment(load_app, monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    app = load_app()
    assert app.HISTORY_FILE == os.path.join(str(tmp_path), "guide.json")


def test_refresh_expires_the_guide_cache_but_keeps_the_stale_copy(load_app, monkeypatch):
    app = load_app()
    listings = [{"start_timestamp": 1}]
    app._xmltv_cache["sky.f1"] = (app.time.time(), listings)
    monkeypatch.setattr(app, "best_f1_channel", lambda: None)

    client = app.app.test_client()
    client.get("/api/f1")
    assert app._xmltv_cache["sky.f1"][0] > 0          # plain load keeps the cache

    assert client.get("/api/f1?refresh=1").get_json() == {"channel": None, "programs": []}
    assert app._xmltv_cache["sky.f1"] == (0.0, listings)
