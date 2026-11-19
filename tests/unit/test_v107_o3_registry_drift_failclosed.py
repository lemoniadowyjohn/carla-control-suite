"""V107: source-grounded orphan reconciliation must never certify unpinned map bytes."""
from __future__ import annotations

import hashlib
import json

import pytest

from reports.v103.o3 import run_orphan_reconciliation as audit
from ultimate_pipeline.carla_tools import map_registry


@pytest.mark.parametrize(
    ("declared_sha", "expected_reason"),
    [
        ("0" * 64, "candidate_digest_differs_from_registry_pin"),
        (None, "candidate_registry_digest_missing"),
    ],
)
def test_candidate_registry_digest_drift_is_terminal(
    tmp_path, monkeypatch, declared_sha, expected_reason
):
    """The old implementation overwrote BLOCKED_INPUT with PASS later in main()."""
    osm = tmp_path / "source.osm"
    osm.write_text("<osm version='0.6'/>", encoding="utf-8")
    candidate = tmp_path / "candidate.xodr"
    candidate.write_text("<OpenDRIVE/>", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"inputs": {"roads_osm": {
            "sha256": hashlib.sha256(osm.read_bytes()).hexdigest()
        }}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(audit, "REPO", tmp_path)
    monkeypatch.setattr(audit, "OSM", "source.osm")
    monkeypatch.setattr(audit, "MANIFEST", "manifest.json")
    monkeypatch.setattr(
        map_registry,
        "verify_pinned_map",
        lambda *args, **kwargs: {
            "path": str(candidate), "sha256": declared_sha,
        },
    )

    assert audit.main() != 0
    out_dir = tmp_path / "reports" / "v103" / "o3"
    result = json.loads(
        (out_dir / "ORPHAN_ROAD_SOURCE_RECONCILIATION.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["status"] == "BLOCKED_INPUT"
    assert result["reason"] == expected_reason
    assert result["candidate_matches_registry_pin"] is False
    assert "reconciliation" not in result
    assert not (out_dir / "ORPHAN_ROAD_SOURCE_RECONCILIATION.csv").exists()
