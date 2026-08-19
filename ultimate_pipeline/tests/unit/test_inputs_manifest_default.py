# C11 hardening: INPUTS_MANIFEST is now DEFAULT ON for the campaign of
# record — when no UP_INPUTS_MANIFEST env is set, Settings() must resolve
# to the campaign's INPUTS_MANIFEST.json if it exists on disk (fail-closed
# guard active out of the box), and must remain a no-op (empty) in checkouts
# without that file (e.g. other cities). Explicit env always wins, and
# UP_INPUTS_MANIFEST="" is the documented bypass.
from __future__ import annotations

import os
from pathlib import Path

from ultimate_pipeline.config.settings import Settings

CAMPAIGN_MANIFEST = str(
    Path(__file__).resolve().parents[3]
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "source"
    / "INPUTS_MANIFEST.json"
)


def test_inputs_manifest_defaults_to_campaign_of_record(monkeypatch) -> None:
    monkeypatch.delenv("UP_INPUTS_MANIFEST", raising=False)
    s = Settings()
    assert s.INPUTS_MANIFEST != ""
    assert Path(s.INPUTS_MANIFEST).resolve() == Path(CAMPAIGN_MANIFEST).resolve()
    assert Path(s.INPUTS_MANIFEST).is_file()


def test_inputs_manifest_bypass_via_empty_env(monkeypatch) -> None:
    monkeypatch.setenv("UP_INPUTS_MANIFEST", "")
    s = Settings()
    assert s.INPUTS_MANIFEST == ""


def test_inputs_manifest_explicit_env_wins(monkeypatch, tmp_path) -> None:
    custom = tmp_path / "custom_manifest.json"
    custom.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("UP_INPUTS_MANIFEST", str(custom))
    s = Settings()
    assert Path(s.INPUTS_MANIFEST).resolve() == custom.resolve()


def test_inputs_manifest_stays_noop_when_campaign_manifest_absent(
    monkeypatch, tmp_path
) -> None:
    """Checkouts without the campaign manifest must keep the guard a no-op
    (empty INPUTS_MANIFEST), never default to a nonexistent path (which would
    turn the guard into a FileNotFoundError on every run)."""
    monkeypatch.delenv("UP_INPUTS_MANIFEST", raising=False)

    real_is_file = Path.is_file
    campaign_abs = Path(CAMPAIGN_MANIFEST).resolve()

    def _guarded_is_file(self, *args, **kwargs):
        if Path(self).resolve() == campaign_abs:
            return False
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", _guarded_is_file)
    s = Settings()
    assert s.INPUTS_MANIFEST == ""
