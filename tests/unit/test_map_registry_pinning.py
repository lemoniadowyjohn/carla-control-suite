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


def _fake_registry(tmp_path: Path, sha256: str, nbytes: int = 100) -> dict:
    # OC-58 hardened contract: schema-valid entry (exact bytes where the
    # file exists, vocabulary role, frame text).
    return {
        "fake_entry": {
            "path": str(tmp_path / "fake.xodr"),
            "sha256": sha256,
            "bytes": nbytes,
            "role": "manual",
            "frame": "test frame",
            "aliases": ["fake_entry", "FakeAlias"],
        }
    }


def test_verify_pinned_map_positive_control_matching_content(tmp_path: Path) -> None:
    content = b"clean fixture content"
    p = tmp_path / "fake.xodr"
    p.write_bytes(content)
    import hashlib

    sha = hashlib.sha256(content).hexdigest()
    result = verify_pinned_map(
        "fake_entry", registry=_fake_registry(tmp_path, sha, len(content))
    )
    assert result["sha256"] == sha
    assert result["role"] == "manual"


def test_verify_pinned_map_negative_control_content_drift_raises(tmp_path: Path) -> None:
    content = b"drifted content, not what the registry expects"
    p = tmp_path / "fake.xodr"
    p.write_bytes(content)
    wrong_sha = "0" * 64
    with pytest.raises(MapRegistryDriftError, match="drift"):
        verify_pinned_map(
            "fake_entry",
            registry=_fake_registry(tmp_path, wrong_sha, len(content)),
        )


def test_verify_pinned_map_raises_on_missing_file(tmp_path: Path) -> None:
    registry = _fake_registry(tmp_path, "a" * 64)  # fake.xodr never written
    with pytest.raises(MapRegistryDriftError, match="not found|missing"):
        verify_pinned_map("fake_entry", registry=registry)


def test_verify_pinned_map_raises_on_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(LookupError):
        verify_pinned_map("not_a_registered_name", registry=_fake_registry(tmp_path, "a" * 64))


def test_verify_pinned_map_alias_resolves_to_same_entry(tmp_path: Path) -> None:
    content = b"aliased content"
    p = tmp_path / "fake.xodr"
    p.write_bytes(content)
    import hashlib

    sha = hashlib.sha256(content).hexdigest()
    registry = _fake_registry(tmp_path, sha, len(content))
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
    # 2026-09-17 promotion: regenerated after two real pipeline bugs were fixed
    # since the prior pin (2ca342d8, 2026-09-05) -- 946228f9 (hardener no longer
    # strips road-level <link> from junction connectors) and a13efd91
    # (GeometryValidator repairs a degenerate <planView> in place instead of
    # leaving it empty). Verified directly before promotion: well-formed XML,
    # 32267 roads / 3561 junctions, all 5 roads that previously crashed the
    # pipeline on the planView bug now have a valid non-empty <planView>, 0
    # roads anywhere with an empty/missing <planView>. Pipeline acceptance:
    # valid_for_experiments=True, hard_fail_reasons=[]; 2 soft-only warnings
    # (lane_count_changes unexplained=3007, component_reachability 3 isolated
    # lane components largest_fraction=0.99793). component_reachability is
    # within precedent already accepted for this map lineage (27 isolated
    # lane components on 2026-09-04); lane_count_changes has NO prior
    # baseline -- this gate postdates the previous pin, so 3007 is its
    # first-ever measurement here (see map_registry.py's PINNED_MAP_REGISTRY
    # comment for the full 2026-09-17 root-cause note). Supersedes
    # 2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798, which
    # remains on disk for provenance but is no longer "the" auto map of record.
    result = verify_pinned_map("auto_map_of_record")
    assert result["sha256"] == "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
    assert result["role"] == "auto"


def test_pinned_map_registry_covers_both_roles() -> None:
    roles = {entry["role"] for entry in PINNED_MAP_REGISTRY.values()}
    assert roles == {"auto", "manual"}
