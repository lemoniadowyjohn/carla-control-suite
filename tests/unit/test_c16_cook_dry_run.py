"""C16 step 1 — c16_cook_dry_run.py: dry-run scaffold entrypoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.c16_cook_dry_run import _find_real_manifest, run_dry_run


def test_find_real_manifest_ignores_trivial_smoke_fixtures(tmp_path: Path) -> None:
    trivial = tmp_path / "a" / "fbx_roundtrip_manifest.json"
    trivial.parent.mkdir(parents=True)
    trivial.write_text(json.dumps({"objects": [{"name": "SurfaceArea2", "materials": ["MAT_0_0"]}]}), encoding="utf-8")
    assert _find_real_manifest(tmp_path) is None


def test_find_real_manifest_finds_a_substantial_one(tmp_path: Path) -> None:
    real = tmp_path / "b" / "fbx_roundtrip_manifest.json"
    real.parent.mkdir(parents=True)
    real.write_text(json.dumps({"objects": [{"name": f"Road_{i}", "materials": []} for i in range(15)]}), encoding="utf-8")
    assert _find_real_manifest(tmp_path) == real


def test_run_dry_run_falls_back_to_fixture_and_passes(tmp_path: Path) -> None:
    result = run_dry_run(tmp_path)
    assert result["validation"]["ok"] is True
    assert "representative_fixture" in result["source"]
    assert result["verdict"] == "COOK_SCAFFOLD_READY dry_run=OK"


def test_run_dry_run_uses_real_manifest_when_present(tmp_path: Path) -> None:
    real = tmp_path / "fbx_roundtrip_manifest.json"
    real.write_text(json.dumps({"objects": [{"name": f"Road_{i}", "materials": []} for i in range(15)]}), encoding="utf-8")
    result = run_dry_run(tmp_path)
    assert "real_manifest" in result["source"]
    assert result["validation"]["ok"] is True
