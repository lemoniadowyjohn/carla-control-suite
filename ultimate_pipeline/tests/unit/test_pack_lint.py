# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/tools/pack_lint.py (V5 packaging closure).

The lint exists because the V4 pack shipped authoritative files whose own
headers still declared an earlier generation, and because a controller/README
can claim a number of bounded prompts that the archive does not contain. These
tests build small synthetic packs and assert each defect code fires, and that a
truthful pack passes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ultimate_pipeline.tools.pack_lint import DEFECT_CODES, lint_pack, main


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pack(root: Path, *, master_title: str, version: str = "5") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "00_V5_INCREMENTAL_MASTER.md").write_text(
        f"# {master_title}\n\nbody\n", encoding="utf-8"
    )
    return root


def _write_sha_manifest(root: Path, files: list[Path]) -> None:
    files = [f for f in files if f.is_file()]
    lines = [f"{_sha(f)}  {f.relative_to(root).as_posix()}" for f in files]
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _codes(report) -> set:
    return {d["code"] for d in report["defects"]}


# ---------------------------------------------------------------------------
# truthful packs
# ---------------------------------------------------------------------------


def test_truthful_pack_passes(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="5")
    assert report["status"] == "PASS", report["defects"]
    assert report["defects"] == []


def test_stale_master_title_is_detected(tmp_path):
    """The exact V4 defect: a v4 pack whose master still says 'audited v3'."""
    root = _make_pack(tmp_path / "CARLA_V4_PACK", master_title="Master execution controller - audited v3")
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="4")
    assert report["status"] == "FAIL"
    assert "stale_top_level_version" in _codes(report)
    stale = [d for d in report["defects"] if d["code"] == "stale_top_level_version"]
    assert stale[0]["found"] == "3"
    assert stale[0]["expected"] == "4"


def test_historical_reference_to_earlier_pack_is_not_a_defect(tmp_path):
    """'this pack extends audited v2' is legitimate prose, not a stale label."""
    root = _make_pack(tmp_path / "CARLA_V4_PACK", master_title="Master execution controller - audited v4")
    master = root / "00_V5_INCREMENTAL_MASTER.md"
    master.write_text(
        "# Master execution controller - audited v4\n\n"
        "This pack extends audited v2 after a fresh audit. The v3 gates still apply.\n",
        encoding="utf-8",
    )
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="4")
    assert "stale_top_level_version" not in _codes(report), report["defects"]


def test_top_level_file_without_generation_is_flagged(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    (root / "README.md").write_text("# Just a readme with no generation\n", encoding="utf-8")
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="5")
    assert "stale_top_level_version" in _codes(report)


# ---------------------------------------------------------------------------
# task-count truthfulness (the "seven prompts" class of defect)
# ---------------------------------------------------------------------------


def _pack_with_prompts(root: Path, count: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "00_V5_INCREMENTAL_MASTER.md").write_text(
        "# Master execution controller - audited v5\n", encoding="utf-8"
    )
    phase = root / "prompts" / "phase_D_release_authority"
    phase.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (phase / f"D{i:02d}_NEW20{i}_task.md").write_text("# task\n", encoding="utf-8")
    return root


def test_documented_prompt_count_is_verified(tmp_path):
    root = _pack_with_prompts(tmp_path / "CARLA_V5_PACK", 7)
    _write_sha_manifest(root, [p for p in root.iterdir() if p.is_file()])
    ok = lint_pack(root, expect_version="5", expect_task_count=7)
    assert "documented_count_mismatch" not in _codes(ok)

    bad = lint_pack(root, expect_version="5", expect_task_count=9)
    assert "documented_count_mismatch" in _codes(bad)
    assert bad["status"] == "FAIL"


def test_task_count_detected_without_expectation(tmp_path):
    root = _pack_with_prompts(tmp_path / "CARLA_V5_PACK", 4)
    report = lint_pack(root, expect_version="5")
    assert report["task_count"] == 4


# ---------------------------------------------------------------------------
# manifest-based checks
# ---------------------------------------------------------------------------


def test_task_count_mismatch_detected(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    (root / "prompt_manifest.json").write_text(
        json.dumps({"schema": "AUDITED_V5", "task_count": 5, "tasks": [{"file": "a.md"}]}),
        encoding="utf-8",
    )
    (root / "a.md").write_text("# a\n", encoding="utf-8")
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="5")
    assert "task_count_mismatch" in _codes(report)


def test_missing_referenced_prompt_detected(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    (root / "prompt_manifest.json").write_text(
        json.dumps({"schema": "AUDITED_V5", "task_count": 1,
                    "tasks": [{"file": "prompts/phase_X/D01_NEW202_gone.md"}]}),
        encoding="utf-8",
    )
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="5")
    assert "missing_referenced_prompt" in _codes(report)


def test_missing_referenced_module_detected(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    (root / "MODULE_LIST.txt").write_text(
        "src/ultimate_pipeline/utils/present.py\nsrc/ultimate_pipeline/utils/absent.py\n",
        encoding="utf-8",
    )
    (root / "src" / "ultimate_pipeline" / "utils").mkdir(parents=True)
    (root / "src" / "ultimate_pipeline" / "utils" / "present.py").write_text("", encoding="utf-8")
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="5")
    assert "missing_referenced_module" in _codes(report)


# ---------------------------------------------------------------------------
# SHA-256 manifest coverage
# ---------------------------------------------------------------------------


def test_missing_sha_manifest_is_a_defect(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    report = lint_pack(root, expect_version="5")
    assert "sha256_manifest_coverage" in _codes(report)


def test_sha_digest_mismatch_detected(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    _write_sha_manifest(root, list(root.iterdir()))
    (root / "00_V5_INCREMENTAL_MASTER.md").write_text("# tampered\n", encoding="utf-8")
    report = lint_pack(root, expect_version="5")
    assert "sha256_manifest_coverage" in _codes(report)


def test_uncovered_file_detected(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    _write_sha_manifest(root, list(root.iterdir()))
    (root / "smuggled.md").write_text("# not listed\n", encoding="utf-8")
    report = lint_pack(root, expect_version="5")
    assert any("not covered" in d["detail"] for d in report["defects"])


def test_sha_manifest_listing_absent_file_detected(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    (root / "SHA256SUMS.txt").write_text(
        f"{'0' * 64}  ghost.md\n", encoding="utf-8"
    )
    report = lint_pack(root, expect_version="5")
    assert any("does not exist" in d["detail"] for d in report["defects"])


# ---------------------------------------------------------------------------
# companion references
# ---------------------------------------------------------------------------


def test_stale_companion_reference_detected(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    (root / "NOTES.md").write_text(
        "See CARLA_gap_closure_prompts_AUDITED_V2_2026-01-01.zip for history.\n",
        encoding="utf-8",
    )
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="5")
    assert "stale_companion_reference" in _codes(report)


def test_matching_companion_reference_is_allowed(tmp_path):
    root = _make_pack(tmp_path / "CARLA_V5_PACK", master_title="Master execution controller - audited v5")
    (root / "NOTES.md").write_text(
        "See CARLA_gap_closure_prompts_AUDITED_V5_2026-01-01.zip for this generation.\n",
        encoding="utf-8",
    )
    _write_sha_manifest(root, list(root.iterdir()))
    report = lint_pack(root, expect_version="5")
    assert "stale_companion_reference" not in _codes(report)


# ---------------------------------------------------------------------------
# API / CLI contract
# ---------------------------------------------------------------------------


def test_missing_pack_directory_fails(tmp_path):
    report = lint_pack(tmp_path / "nope")
    assert report["status"] == "FAIL"
    assert report["defects"][0]["code"] == "pack_missing"


def test_all_defect_codes_are_declared():
    assert "documented_count_mismatch" in DEFECT_CODES
    assert "stale_top_level_version" in DEFECT_CODES
    assert len(DEFECT_CODES) == 7


def test_cli_exit_codes(tmp_path, capsys):
    good = _make_pack(tmp_path / "good", master_title="Master execution controller - audited v5")
    _write_sha_manifest(good, list(good.iterdir()))
    assert main([str(good), "--expect-version", "5"]) == 0

    bad = _make_pack(tmp_path / "bad", master_title="Master execution controller - audited v2")
    _write_sha_manifest(bad, list(bad.iterdir()))
    assert main([str(bad), "--expect-version", "5"]) == 1


def test_cli_json_output_is_parseable(tmp_path, capsys):
    good = _make_pack(tmp_path / "good", master_title="Master execution controller - audited v5")
    _write_sha_manifest(good, list(good.iterdir()))
    main([str(good), "--expect-version", "5", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["schema"] == "PACK_LINT/v1"
