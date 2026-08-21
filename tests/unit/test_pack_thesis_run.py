"""C19 step 4 — pack_thesis_run.py: bundle assembly."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pack_thesis_run import _claim_boundaries, _evidence_reports, pack


def test_claim_boundaries_pulled_from_rq_tables(tmp_path: Path) -> None:
    p = tmp_path / "rq_tables.json"
    p.write_text(json.dumps({"rows": [
        {"rq": "RQ1", "metric": "lane_width_gap", "status": "BOUNDED", "note": "agree"},
    ]}), encoding="utf-8")
    out = _claim_boundaries(p)
    assert out == [{"rq": "RQ1", "metric": "lane_width_gap", "status": "BOUNDED", "note": "agree"}]


def test_claim_boundaries_empty_when_missing(tmp_path: Path) -> None:
    assert _claim_boundaries(tmp_path / "does_not_exist.json") == []


def test_evidence_reports_flags_missing_not_silently_dropped() -> None:
    reports = _evidence_reports()
    assert len(reports) > 0
    for r in reports:
        assert "present" in r and "path" in r
        if r["present"]:
            assert r["sha256"] is not None


def test_pack_against_real_repo_covers_both_map_roles() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    bundle = pack(repo_root)
    roles = {m["role"] for m in bundle["maps_by_sha"].values()}
    assert roles == {"auto", "manual"}
    assert bundle["protocol_snapshot"]["git_commit"]
    assert len(bundle["claim_boundaries"]) > 0
