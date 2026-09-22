"""OC-58 — map-registry integrity: schema, aliases, files, supersession,
roles, determinism. Focused fail-closed tests; deterministic, offline
(except pre-existing real-file tests in test_map_registry_pinning.py).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ultimate_pipeline.carla_tools.map_registry import (
    LEGACY_TEXT_ONLY,
    STRUCTURED_FRAME,
    MapRegistryDriftError,
    MapRegistryValidationError,
    assert_valid_registry,
    audit_registry,
    build_alias_authority,
    registry_fingerprint,
    resolve_historical_sha,
    validate_candidate_registry_entry,
    validate_registry,
    validate_registry_entry,
    validate_supersession_chains,
    verify_pinned_map,
)


def _sha(seed: bytes) -> str:
    return hashlib.sha256(seed).hexdigest()


def _entry(path: str, content: bytes, *, role: str = "auto",
           aliases=("m",), frame: str = "test frame", **extra):
    d = {
        "path": path,
        "sha256": _sha(content),
        "bytes": len(content),
        "role": role,
        "frame": frame,
        "aliases": list(aliases),
    }
    d.update(extra)
    return d


def _write(p: Path, content: bytes) -> Path:
    p.write_bytes(content)
    return p


# ---------------------------------------------------------------------------
# Schema (§3)
# ---------------------------------------------------------------------------

def test_schema_rejects_bad_sha_length():
    with pytest.raises(MapRegistryValidationError, match="sha256"):
        validate_registry_entry("k", _entry("a.xodr", b"x") | {"sha256": "abc123"})


def test_schema_rejects_nonhex_sha():
    with pytest.raises(MapRegistryValidationError, match="sha256"):
        validate_registry_entry("k", _entry("a.xodr", b"x") | {"sha256": "z" * 64})


def test_schema_rejects_prefixed_sha():
    with pytest.raises(MapRegistryValidationError, match="sha256"):
        validate_registry_entry(
            "k", _entry("a.xodr", b"x") | {"sha256": "sha256:" + "a" * 64})


def test_schema_normalizes_uppercase_sha():
    norm = validate_registry_entry(
        "k", _entry("a.xodr", b"x") | {"sha256": _sha(b"x").upper()})
    assert norm["sha256"] == _sha(b"x")


def test_schema_rejects_zero_and_negative_bytes():
    for bad in (0, -5, None, "100", True):
        with pytest.raises(MapRegistryValidationError, match="bytes"):
            validate_registry_entry("k", _entry("a.xodr", b"x") | {"bytes": bad})


def test_schema_rejects_unknown_role():
    for bad in ("Auto", "MANUAL", "automatic", "", None):
        with pytest.raises(MapRegistryValidationError, match="role"):
            validate_registry_entry("k", _entry("a.xodr", b"x") | {"role": bad})
    norm = validate_registry_entry("k", _entry("a.xodr", b"x") | {"role": "manual"})
    assert norm["role"] == "manual"


def test_schema_rejects_empty_and_padded_alias():
    for bad in ([""], ["  "], ["ok", "  padded  "]):
        with pytest.raises(MapRegistryValidationError, match="[Aa]lias"):
            validate_registry_entry("k", _entry("a.xodr", b"x", aliases=bad))


# ---------------------------------------------------------------------------
# Aliases (§6, §7)
# ---------------------------------------------------------------------------

def test_alias_collision_manual_variants_fail():
    reg = {
        "a": _entry("a.xodr", b"a", aliases=["manual"]),
        "b": _entry("b.xodr", b"b", aliases=["MANUAL"]),
    }
    with pytest.raises(MapRegistryValidationError, match="[Cc]ollision"):
        build_alias_authority(reg)
    reg["b"]["aliases"] = ["Manual"]
    with pytest.raises(MapRegistryValidationError, match="[Cc]ollision"):
        build_alias_authority(reg)


def test_canonical_key_collision_with_other_alias_fails():
    reg = {
        "alpha": _entry("a.xodr", b"a", aliases=["alpha"]),
        "beta": _entry("b.xodr", b"b", aliases=["ALPHA"]),
    }
    with pytest.raises(MapRegistryValidationError, match="[Cc]ollision"):
        build_alias_authority(reg)


def test_canonical_key_resolves_without_explicit_alias(tmp_path):
    content = b"<OpenDRIVE/>"
    _write(tmp_path / "m.xodr", content)
    reg = {"lonely_key": _entry(str(tmp_path / "m.xodr"), content, aliases=["other"])}
    receipt = verify_pinned_map("lonely_key", registry=reg)
    assert receipt["registry_key"] == "lonely_key"
    assert receipt["verification_status"] == "VERIFIED"


def test_module_alias_authority_has_no_collisions():
    # Import-time construction already gates this; belt and suspenders.
    from ultimate_pipeline.carla_tools.map_registry import _ALIAS_TO_KEY
    assert _ALIAS_TO_KEY["manual_grid0828"] == "manual_grid0828"
    assert _ALIAS_TO_KEY["grid0821"] == "manual_grid0828"


# ---------------------------------------------------------------------------
# Files: receipt, bytes, LFS, missing, traversal (§4, §5, §8)
# ---------------------------------------------------------------------------

def test_receipt_contains_verified_identity(tmp_path):
    content = b"<OpenDRIVE/>"
    p = _write(tmp_path / "m.xodr", content)
    reg = {"k": _entry(str(p), content, aliases=["k", "alias"])}
    r = verify_pinned_map("ALIAS", registry=reg)
    assert r["registry_key"] == "k"
    assert r["requested_name"] == "ALIAS"
    assert r["resolved_path"] == str(p.resolve())
    assert r["declared_path"] == str(p)
    assert r["sha256_expected"] == r["sha256_actual"] == _sha(content)
    assert r["bytes_expected"] == r["bytes_actual"] == len(content)
    assert r["verification_status"] == "VERIFIED"
    assert r["registry_sha256"] == registry_fingerprint(reg)
    # backward compat
    assert r["path"] == str(p) and r["sha256"] == _sha(content)


def test_correct_sha_but_wrong_pinned_bytes_fails(tmp_path):
    content = b"<OpenDRIVE/>"
    p = _write(tmp_path / "m.xodr", content)
    reg = {"k": _entry(str(p), content, aliases=["k"]) | {"bytes": len(content) + 1}}
    with pytest.raises(MapRegistryDriftError, match="[Bb]yte-size mismatch"):
        verify_pinned_map("k", registry=reg)


def test_missing_file_fails(tmp_path):
    reg = {"k": _entry(str(tmp_path / "nope.xodr"), b"x", aliases=["k"])}
    with pytest.raises(MapRegistryDriftError, match="not found"):
        verify_pinned_map("k", registry=reg)


def test_lfs_pointer_fails(tmp_path):
    p = _write(tmp_path / "m.xodr",
               b"version https://git-lfs.github.com/spec/v1\noid sha256:x\nsize 5\n")
    reg = {"k": _entry(str(p), b"real", aliases=["k"]) | {"bytes": p.stat().st_size}}
    with pytest.raises(MapRegistryDriftError, match="git-LFS pointer"):
        verify_pinned_map("k", registry=reg)


def test_relative_path_traversal_fails(tmp_path):
    outside = _write(tmp_path / "outside.xodr", b"<OpenDRIVE/>")
    base = tmp_path / "base"
    base.mkdir()
    reg = {"k": _entry("../outside.xodr", b"<OpenDRIVE/>", aliases=["k"])}
    with pytest.raises(MapRegistryDriftError, match="[Ee]scape"):
        verify_pinned_map("k", base_dir=base, registry=reg)
    assert outside.is_file()  # never touched


def test_absolute_external_path_requires_explicit_policy(tmp_path):
    content = b"<OpenDRIVE/>"
    p = _write(tmp_path / "m.xodr", content)
    reg = {"k": _entry(str(p), content, aliases=["k"])}
    ok = verify_pinned_map("k", base_dir=tmp_path / "elsewhere",
                           registry=reg, allow_external_absolute_paths=True)
    assert ok["verification_status"] == "VERIFIED"
    with pytest.raises(MapRegistryDriftError, match="[Ee]scape"):
        verify_pinned_map("k", base_dir=tmp_path / "elsewhere",
                          registry=reg, allow_external_absolute_paths=False)


# ---------------------------------------------------------------------------
# Supersession (§10, §12)
# ---------------------------------------------------------------------------

def _chain_registry(n: int = 5):
    """Valid n-hop chain head_0 -> ... -> head_{n-1}(tail). Deterministic."""
    reg = {}
    prev_sha = None
    prev_path = None
    for i in reversed(range(n)):
        content = f"gen{i}".encode()
        key = f"gen{i}"
        extra = {}
        if prev_sha is not None:
            extra = {"supersedes_sha256": prev_sha, "supersedes_path": prev_path}
        reg[key] = _entry(f"gen{i}.xodr", content, aliases=[key], **extra)
        prev_sha = _sha(content)
        prev_path = f"gen{i}.xodr"
    return reg


def test_valid_5hop_chain(tmp_path):
    reg = _chain_registry(5)
    for i in range(5):
        _write(tmp_path / f"gen{i}.xodr", f"gen{i}".encode())
    report = validate_supersession_chains(reg, base_dir=tmp_path)
    assert report["valid"], report["errors"]
    head = report["chains"]["gen0"]
    assert head["chain_depth"] == 4
    assert head["chain_keys"] == [f"gen{i}" for i in range(5)]
    assert head["chain_status"] == "OK"


def test_missing_predecessor_fails():
    reg = {"head": _entry("h.xodr", b"h", aliases=["head"],
                          supersedes_sha256=_sha(b"ghost"),
                          supersedes_path="ghost.xodr")}
    report = validate_supersession_chains(reg, verify_historical_files=False)
    assert not report["valid"]
    assert report["chains"]["head"]["chain_status"] == "MISSING_PREDECESSOR"


def test_wrong_predecessor_path_fails():
    reg = {
        "head": _entry("h.xodr", b"h", aliases=["head"],
                       supersedes_sha256=_sha(b"mid"), supersedes_path="other.xodr"),
        "mid": _entry("mid.xodr", b"mid", aliases=["mid"]),
        "other": _entry("other.xodr", b"other", aliases=["other"]),
    }
    report = validate_supersession_chains(reg, verify_historical_files=False)
    assert not report["valid"]
    assert report["chains"]["head"]["chain_status"] == "WRONG_PREDECESSOR_PATH"


def test_self_cycle_fails():
    sha = _sha(b"self")
    reg = {"a": {"path": "a.xodr", "sha256": sha, "bytes": 4, "role": "auto",
                 "frame": "f", "aliases": ["a"],
                 "supersedes_sha256": sha, "supersedes_path": "a.xodr"}}
    report = validate_supersession_chains(reg, verify_historical_files=False)
    assert not report["valid"]
    assert report["chains"]["a"]["chain_status"] == "CYCLE"


def test_three_entry_cycle_fails():
    reg = {
        "a": _entry("a.xodr", b"a", aliases=["a"],
                    supersedes_sha256=_sha(b"b"), supersedes_path="b.xodr"),
        "b": _entry("b.xodr", b"b", aliases=["b"],
                    supersedes_sha256=_sha(b"c"), supersedes_path="c.xodr"),
        "c": _entry("c.xodr", b"c", aliases=["c"],
                    supersedes_sha256=_sha(b"a"), supersedes_path="a.xodr"),
    }
    report = validate_supersession_chains(reg, verify_historical_files=False)
    assert not report["valid"]
    assert any(v["chain_status"] == "CYCLE" for v in report["chains"].values())


def test_historical_sha_resolves_with_distance_and_successor():
    reg = _chain_registry(5)
    mid_sha = _sha(b"gen2")
    res = resolve_historical_sha(mid_sha, registry=reg)
    assert res is not None
    assert res["historical_registry_key"] == "gen2"
    assert res["historical_sha"] == mid_sha
    assert res["current_successor_key"] == "gen0"
    assert res["current_successor_sha"] == _sha(b"gen0")
    assert res["supersession_distance"] == 2


def test_unregistered_sha_resolves_to_none():
    assert resolve_historical_sha(_sha(b"nope"), registry=_chain_registry(3)) is None


def test_role_change_through_chain_fails():
    reg = {
        "head": _entry("h.xodr", b"h", aliases=["head"], role="auto",
                       supersedes_sha256=_sha(b"mid"), supersedes_path="mid.xodr"),
        "mid": _entry("mid.xodr", b"mid", aliases=["mid"], role="manual"),
    }
    report = validate_supersession_chains(reg, verify_historical_files=False)
    assert not report["valid"]
    assert report["chains"]["head"]["chain_status"] == "ROLE_CHANGE"


# ---------------------------------------------------------------------------
# Roles / content identity (§13, §14)
# ---------------------------------------------------------------------------

def test_manual_manual_identical_content_allowed_when_declared(tmp_path):
    content = b"same-manual-bytes"
    _write(tmp_path / "a.xodr", content)
    _write(tmp_path / "b.xodr", content)
    reg = {
        "m1": _entry(str(tmp_path / "a.xodr"), content, role="manual",
                     aliases=["m1"], equivalent_names=["m1", "m2"]),
        "m2": _entry(str(tmp_path / "b.xodr"), content, role="manual",
                     aliases=["m2"], equivalent_names=["m1", "m2"]),
    }
    report = validate_registry(reg, base_dir=tmp_path,
                               verify_historical_files=False,
                               require_repo_contained_paths=False)
    assert report["valid"], report["errors"]
    assert report["content_groups"][0]["classification"] == "same_content_same_role"


def test_undeclared_content_sharing_rejected():
    content = b"same-bytes"
    reg = {
        "m1": _entry("a.xodr", content, role="manual", aliases=["m1"]),
        "m2": _entry("b.xodr", content, role="manual", aliases=["m2"]),
    }
    report = validate_registry(reg, verify_historical_files=False,
                               require_repo_contained_paths=False)
    assert not report["valid"]
    assert any("undeclared" in e for e in report["errors"])


def test_auto_manual_identical_content_rejected():
    content = b"same-bytes-both-roles"
    reg = {
        "a": _entry("a.xodr", content, role="auto", aliases=["a"]),
        "m": _entry("b.xodr", content, role="manual", aliases=["m"]),
    }
    report = validate_registry(reg, verify_historical_files=False,
                               require_repo_contained_paths=False)
    assert not report["valid"]
    assert any("cross-role" in e for e in report["errors"])


def test_cross_role_override_is_explicit_test_only():
    content = b"same-bytes"
    reg = {
        "a": _entry("a.xodr", content, role="auto", aliases=["a"],
                    allow_cross_role_content=True),
        "m": _entry("b.xodr", content, role="manual", aliases=["m"]),
    }
    report = validate_registry(reg, verify_historical_files=False,
                               require_repo_contained_paths=False)
    assert report["valid"], report["errors"]
    assert "OVERRIDDEN_cross_role_test_only" in str(report["content_groups"])


# ---------------------------------------------------------------------------
# Determinism (§9 fingerprint)
# ---------------------------------------------------------------------------

def test_registry_digest_ignores_insertion_order():
    reg_a = _chain_registry(3)
    reg_b = {k: reg_a[k] for k in reversed(list(reg_a))}
    assert registry_fingerprint(reg_a) == registry_fingerprint(reg_b)


def test_one_alias_change_changes_digest():
    reg_a = _chain_registry(3)
    reg_b = {k: dict(v, aliases=list(v["aliases"])) for k, v in reg_a.items()}
    reg_b["gen0"]["aliases"] = ["gen0", "extra_alias"]
    assert registry_fingerprint(reg_a) != registry_fingerprint(reg_b)


def test_one_map_sha_change_changes_digest():
    reg_a = _chain_registry(3)
    reg_b = {k: dict(v) for k, v in reg_a.items()}
    reg_b["gen1"] = dict(reg_b["gen1"], sha256=_sha(b"mutated"))
    assert registry_fingerprint(reg_a) != registry_fingerprint(reg_b)


# ---------------------------------------------------------------------------
# Promotion contract (§16), frames (§15), audit (§19), fail-closed (§20)
# ---------------------------------------------------------------------------

def test_promotion_contract_accepts_valid_candidate(tmp_path):
    content = b"candidate-bytes"
    p = _write(tmp_path / "cand.xodr", content)
    reg = {"old": _entry(str(tmp_path / "old.xodr"), b"old", aliases=["old"])}
    _write(tmp_path / "old.xodr", b"old")
    report = validate_candidate_registry_entry(
        key="new", path=str(p), sha256=_sha(content), bytes=len(content),
        role="auto", frame="rebased", aliases=["new"],
        registry=reg, base_dir=tmp_path,
        supersedes_sha256=_sha(b"old"), supersedes_path=str(tmp_path / "old.xodr"),
        allow_external_absolute_paths=True,
    )
    assert report["ok"], report["errors"]
    assert "new" not in reg  # never edits the registry


def test_promotion_contract_rejects_conflicting_alias(tmp_path):
    content = b"candidate-bytes"
    p = _write(tmp_path / "cand.xodr", content)
    reg = {"old": _entry(str(tmp_path / "old.xodr"), b"old", aliases=["old", "new"])}
    report = validate_candidate_registry_entry(
        key="new", path=str(p), sha256=_sha(content), bytes=len(content),
        role="auto", frame="f", aliases=["new"],
        registry=reg, base_dir=tmp_path,
        allow_external_absolute_paths=True,
    )
    assert not report["ok"]
    assert any("alias" in e for e in report["errors"])


def test_frame_status_structured_vs_legacy():
    structured = _entry("a.xodr", b"a", aliases=["a"],
                        frame_id="f", frame_kind="k", crs_authority="c",
                        rebase_dx=1.0, rebase_dy=2.0)
    assert validate_registry_entry("s", structured)["frame_status"] == STRUCTURED_FRAME
    assert validate_registry_entry("l", _entry("a.xodr", b"a"))["frame_status"] == (
        LEGACY_TEXT_ONLY)


def test_real_registry_frames_are_structured_for_active_pins():
    from ultimate_pipeline.carla_tools.map_registry import (
        PINNED_MAP_REGISTRY, validate_frame_metadata)
    report = validate_frame_metadata(PINNED_MAP_REGISTRY)
    assert report["auto_map_of_record"]["frame_status"] == STRUCTURED_FRAME
    assert report["manual_grid0828"]["frame_status"] == STRUCTURED_FRAME


def test_audit_tool_shape_and_no_mutation(tmp_path):
    content = b"audit-bytes"
    _write(tmp_path / "m.xodr", content)
    reg = {"k": _entry("m.xodr", content, aliases=["k"])}
    before = {k: dict(v) for k, v in reg.items()}
    report = audit_registry(reg, base_dir=tmp_path)
    assert report["registry_valid"] is True
    assert set(report) >= {"registry_valid", "registry_sha256", "entry_count",
                           "alias_count", "active_map_roles", "entries",
                           "alias_collisions", "content_collisions",
                           "supersession_chains", "errors", "warnings"}
    assert reg == before
    assert report["entries"]["k"]["sha_match"] is True


def test_assert_valid_registry_raises_fail_closed():
    reg = {"k": _entry("a.xodr", b"x", aliases=["k"]) | {"role": "bogus"}}
    with pytest.raises(MapRegistryValidationError):
        assert_valid_registry(reg, require_repo_contained_paths=False,
                              verify_historical_files=False)
