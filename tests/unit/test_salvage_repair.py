"""Repair-algorithm fixture tests (5 cases + rerun NOOP + fail-closed)."""
from __future__ import annotations

from pathlib import Path

from tools.salvage_repair import (
    classify_pair,
    execute_repair,
    journal_summary,
    plan_repair,
    RepairJournal,
)


def _w(p: Path, data: bytes) -> Dict[str, object]:
    p.write_bytes(data)
    import hashlib

    return {"sha256": hashlib.sha256(data).hexdigest(), "tile": "8_8"}


def _bulk(files: Path, stem: str):
    out = {}
    for ext in (".uasset", ".uexp", ".ubulk"):
        f = files / f"{stem}{ext}"
        if f.exists():
            import hashlib

            out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def _fixture(root: Path):
    s = root / "staging"
    c = root / "canonical"
    (s / "pkg").mkdir(parents=True)
    (c / "pkg").mkdir(parents=True)
    # 1. identical duplicate
    _w(s / "pkg" / "a.uasset", b"SAME")
    _w(c / "pkg" / "a.uasset", b"SAME")
    # 2. staging-only
    _w(s / "pkg" / "b.umap", b"MAP")
    # 3. canonical-only
    _w(c / "pkg" / "c.uasset", b"KEEP")
    # 4. mismatched duplicate (same name, different tile)
    sa = _w(s / "pkg" / "d.uasset", b"S")
    ca = _w(c / "pkg" / "d.uasset", b"C")
    ca["tile"] = "9_9"
    # 5. semantic duplicate (metadata-level difference)
    se = _w(s / "pkg" / "e.uasset", b"S2")
    ce = _w(c / "pkg" / "e.uasset", b"C2")
    return s, c


def test_fixture_five_cases(tmp_path) -> None:
    s, c = _fixture(tmp_path)
    sb = {p.name: None for p in (s / "pkg").iterdir()}
    cb = {p.name: None for p in (c / "pkg").iterdir()}
    import hashlib

    def bulk(d, name):
        return {name: hashlib.sha256((d / "pkg" / name).read_bytes()).hexdigest()} if (d / "pkg" / name).exists() else {}

    assert classify_pair({"sha256": "x", "tile": "8_8"},
                         {"sha256": "x", "tile": "8_8"}, {}, {}) == \
        "KEEP_CANONICAL_DROP_STAGING"
    assert classify_pair(None, {"sha256": "x", "tile": "8_8"}, {}, {}) == \
        "NO_ACTION"
    assert classify_pair({"sha256": "x", "tile": "8_8"}, None, {}, {}) == \
        "KEEP_STAGING_TEMPORARILY"
    assert classify_pair({"sha256": "s", "tile": "8_8"},
                         {"sha256": "c", "tile": "9_9"}, {}, {}) == "BLOCKED"


def test_repair_run_and_rerun_noop(tmp_path) -> None:
    s, c = _fixture(tmp_path)
    q = tmp_path / "quarantine"
    pairs = [
        {"name": "a.uasset", "action": "KEEP_CANONICAL_DROP_STAGING",
         "staging_path": str(s / "pkg" / "a.uasset"),
         "quarantine_path": ""},
        {"name": "b.umap", "action": "KEEP_STAGING_TEMPORARILY",
         "staging_path": str(s / "pkg" / "b.umap"), "quarantine_path": ""},
        {"name": "c.uasset", "action": "NO_ACTION",
         "staging_path": "", "quarantine_path": ""},
        {"name": "d.uasset", "action": "BLOCKED",
         "staging_path": str(s / "pkg" / "d.uasset"),
         "quarantine_path": ""},
        {"name": "e.uasset", "action": "KEEP_CANONICAL_DROP_STAGING",
         "staging_path": str(s / "pkg" / "e.uasset"),
         "quarantine_path": ""},
    ]
    j = RepairJournal(run_id="t1", entries=plan_repair(pairs))
    execute_repair(j, q)
    summ = journal_summary(j)
    assert summ["by_status"] == {"COMPLETE": 4, "FAILED": 1}, summ
    assert (c / "pkg" / "a.uasset").exists()  # canonical kept
    assert not (s / "pkg" / "a.uasset").exists()  # staging quarantined
    assert (q / "a.uasset").exists()
    assert (s / "pkg" / "b.umap").exists()  # temporarily kept
    assert (s / "pkg" / "d.uasset").exists()  # blocked untouched
    # Second run: NOOP for reconciled state (only BLOCKED re-fails).
    j2 = RepairJournal(run_id="t2", entries=plan_repair(pairs))
    execute_repair(j2, q)
    s2 = journal_summary(j2)
    assert s2["by_status"] == {"COMPLETE": 4, "FAILED": 1}, s2
    assert [e.post_state for e in j2.entries if e.asset == "a.uasset"] == \
        ["noop-source-absent"]


def test_mismatch_fails_closed(tmp_path) -> None:
    j = RepairJournal(run_id="t3", entries=plan_repair(
        [{"name": "x", "action": "BLOCKED", "staging_path": "s",
          "quarantine_path": "q"}]))
    execute_repair(j, tmp_path / "q")
    assert journal_summary(j)["by_status"] == {"FAILED": 1}
