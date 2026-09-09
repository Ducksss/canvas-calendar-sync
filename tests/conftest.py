"""Every test uses an isolated profile; never read a developer's real state."""
import json
from dataclasses import asdict

import pytest

from canvas_calendar_sync import config


@pytest.fixture(autouse=True)
def isolated_profile(monkeypatch, tmp_path):
    settings = config.Settings(canvas_url="https://canvas.example.edu/", timezone="Asia/Singapore")
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "settings", settings)
    (tmp_path / "config.json").write_text(json.dumps(asdict(settings)))
