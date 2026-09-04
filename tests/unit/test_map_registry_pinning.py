"""C13 — content-addressed map-registry drift guard (auto + manual pin).

RQ1/RQ2 need the auto<->manual pair referenced by sha256, not by mutable
name. Memory records a real Grid0821/Grid0828 name<->content drift risk
(project_map_safety_untracked_20260730) this guard exists to prevent: a
registry name must never silently resolve to unexpected file content.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.carla_tools.map_registry import (
    MapRegistryDriftError,
    PINNED_MAP_REGISTRY,
    verify_pinned_map,
)


def _fake_registry(tmp_path: Path, sha256: str) -> dict:
    return {
        "fake_entry": {
            "path": str(tmp_path / "fake.xodr"),
            "sha256": sha256,
            "bytes": None,
            "role": "manual",
            "aliases": ["fake_entry", "FakeAlias"],
        }
    }


def test_verify_pinned_map_positive_control_matching_content(tmp_path: Path) -> None:
    p = tmp_path / "fake.xodr"
    p.write_bytes(b"clean fixture content")
    import hashlib

    sha = hashlib.sha256(b"clean fixture content").hexdigest()
    result = verify_pinned_map("fake_entry", registry=_fake_registry(tmp_path, sha))
    assert result["sha256"] == sha
    assert result["role"] == "manual"


def test_verify_pinned_map_negative_control_content_drift_raises(tmp_path: Path) -> None:
    p = tmp_path / "fake.xodr"
    p.write_bytes(b"drifted content, not what the registry expects")
    wrong_sha = "0" * 64
    with pytest.raises(MapRegistryDriftError, match="drift"):
        verify_pinned_map("fake_entry", registry=_fake_registry(tmp_path, wrong_sha))


def test_verify_pinned_map_raises_on_missing_file(tmp_path: Path) -> None:
    registry = _fake_registry(tmp_path, "a" * 64)  # fake.xodr never written
    with pytest.raises(MapRegistryDriftError, match="not found|missing"):
        verify_pinned_map("fake_entry", registry=registry)


def test_verify_pinned_map_raises_on_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(LookupError):
        verify_pinned_map("not_a_registered_name", registry=_fake_registry(tmp_path, "a" * 64))


def test_verify_pinned_map_alias_resolves_to_same_entry(tmp_path: Path) -> None:
    p = tmp_path / "fake.xodr"
    p.write_bytes(b"aliased content")
    import hashlib

    sha = hashlib.sha256(b"aliased content").hexdigest()
    registry = _fake_registry(tmp_path, sha)
    direct = verify_pinned_map("fake_entry", registry=registry)
    via_alias = verify_pinned_map("FakeAlias", registry=registry)
    assert direct["sha256"] == via_alias["sha256"] == sha


def test_verify_pinned_map_detects_unsmudged_lfs_pointer(tmp_path: Path) -> None:
    p = tmp_path / "fake.xodr"
    # A real git-lfs pointer stub: small text, distinctive header.
    p.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:deadbeef\n"
        "size 144142210\n",
        encoding="utf-8",
    )
    registry = _fake_registry(tmp_path, "b" * 64)
    with pytest.raises(MapRegistryDriftError, match="lfs|LFS"):
        verify_pinned_map("fake_entry", registry=registry)


# --- Integration-style: verify against the REAL pinned files in this repo ---


def test_real_manual_grid0828_matches_pinned_sha256() -> None:
    result = verify_pinned_map("Grid0828")
    assert result["sha256"] == "5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c"
    assert result["role"] == "manual"


def test_real_grid0821_alias_resolves_to_same_content_as_grid0828() -> None:
    """Grid0821.xodr and Grid0828.xodr under CARLA Content are byte-identical
    (see source/manual/MANUAL_MANIFEST.json name_content_drift note). The
    registry must resolve both names to the SAME pinned content, not two
    different files."""
    grid0828 = verify_pinned_map("Grid0828")
    grid0821 = verify_pinned_map("Grid0821")
    assert grid0821["sha256"] == grid0828["sha256"]


def test_real_auto_map_of_record_matches_pinned_sha256() -> None:
    # Round-5 promotion (2026-09-04): repair_lane_width_discontinuities()
    # (round 2's fix for road 46620) had only ever been applied as a one-off
    # manual repair, never wired into stage_08_hygiene.py's live C10 hygiene
    # stage -- every canonical regen since round 2 was silently exposed to
    # the same rejection. Wired in as step 8H-4; a real end-to-end regen
    # confirms the fix (map_hygiene_report.json: issues_before=1 ->
    # issues_after=0 for road 46620) and valid_for_experiments=True.
    # Supersedes the deep-audit pin
    # e281367e5429533a25c809272de697e2a4166c042bf069f89daffbde7f638ba2, which
    # remains on disk for provenance but is no longer "the" auto map of record.
    result = verify_pinned_map("auto_map_of_record")
    assert result["sha256"] == "60a363258c29b22b4abd1151ea9aa6ab19510cf89107b72f3a2892c933ca0d75"
    assert result["role"] == "auto"


def test_pinned_map_registry_covers_both_roles() -> None:
    roles = {entry["role"] for entry in PINNED_MAP_REGISTRY.values()}
    assert roles == {"auto", "manual"}
