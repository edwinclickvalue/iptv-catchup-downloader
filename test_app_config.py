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
