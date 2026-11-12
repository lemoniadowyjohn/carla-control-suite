"""Offline release-authority controls; exercise the real terminal_release module.

These tests use fake gate/lease/pack dependencies, NOT a fake release guard.
They are source-level controls only; CI, Windows and CARLA runtime still needed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import threading
import types
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_FILE = Path(__file__).resolve().parents[2] / "ultimate_pipeline/core/terminal_release.py"
GATES = ("origin_sanity", "artifact_structure", "elevation_continuity", "carla_opendrive_compat")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, payload):
    Path(path).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def harness(monkeypatch, tmp_path):
    # Install only upstream boundary/lease dependencies. The module under
    # test is loaded from its actual source path and remains unmocked.
    main = types.ModuleType("ultimate_pipeline")
    main.__path__ = [str(MODULE_FILE.parents[2])]
    quality = types.ModuleType("ultimate_pipeline.quality")
    quality.__path__ = []
    gates = types.ModuleType("ultimate_pipeline.quality.final_artifact_gates")
    gates.RELEASE_MANDATORY_GATES = GATES
    gates.ACCEPTANCE_POLICY_VERSION = "v86-test"
    utils = types.ModuleType("ultimate_pipeline.utils")
    utils.__path__ = []
    packs = types.ModuleType("ultimate_pipeline.utils.finalize_run_pack")
    def verify_run_pack(root):
        root = Path(root)
        try:
            manifest = json.loads((root / "signature.json").read_text())
            files = manifest["files"]
            if manifest.get("status") != "PASS":
                return {"status": "FAIL"}
            if not all((root / k).is_file() and digest(root / k) == v
                       for k, v in files.items()):
                return {"status": "FAIL"}
        except (OSError, KeyError, ValueError):
            return {"status": "FAIL"}
        return {"status": "PASS"}
    packs.verify_run_pack = verify_run_pack
    governance = types.ModuleType("ultimate_pipeline.governance")
    governance.__path__ = []
    single_writer = types.ModuleType("ultimate_pipeline.governance.single_writer")
    single_writer.__path__ = []
    locks = types.ModuleType("ultimate_pipeline.governance.single_writer.worktree_lock")
    mutex = threading.RLock()
    current = {"lease_id": "lease-one", "generation": 1}
    @contextmanager
    def claim(path):
        with mutex:
            yield
    locks._generation_claim = claim
    locks._ledger_path = lambda path: Path(path) / ".generations"
    locks.lease_is_current = lambda lease: (lease.lease_id == current["lease_id"]
                                            and lease.generation == current["generation"])
    for name, module in {
        "ultimate_pipeline": main,
        "ultimate_pipeline.quality": quality,
        "ultimate_pipeline.quality.final_artifact_gates": gates,
        "ultimate_pipeline.utils": utils,
        "ultimate_pipeline.utils.finalize_run_pack": packs,
        "ultimate_pipeline.governance": governance,
        "ultimate_pipeline.governance.single_writer": single_writer,
        "ultimate_pipeline.governance.single_writer.worktree_lock": locks,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("v94_actual_release", MODULE_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = tmp_path
    source_manifest = root / "input_manifest.json"
    source_manifest.write_text('{"inputs": {"osm": "sha256-pinned"}}\n', encoding="utf-8")
    xodr = root / "final.xodr"
    xodr.write_bytes(b"<OpenDRIVE><road id='10' length='9.0'/></OpenDRIVE>")
    run_id = uuid.uuid4().hex
    put(root / "run_identity.json", {"run_id": run_id, "source_sha": "a" * 40,
        "profile": "structural_release", "settings_digest": "b" * 64})
    put(root / "map_acceptance.json", {
        "run_id": run_id, "valid_for_experiments": True,
        "release_eligible": True, "acceptance_policy": {"purpose": "release", "policy_version": "v86-test"},
        "mandatory_gates": list(GATES), "mandatory_gate_status": dict.fromkeys(GATES, "PASS"),
        "final_xodr_path": str(xodr), "final_xodr_sha256": digest(xodr),
        "evaluated_xodr_sha256": digest(xodr),
    })
    put(root / "final_artifact_receipt.json", {
        "run_id": run_id, "publication_status": "PUBLISHED",
        "final_xodr": {"path": "final.xodr", "sha256": digest(xodr), "bytes": xodr.stat().st_size},
        "acceptance_receipt": {"path": "map_acceptance.json",
                               "sha256": digest(root / "map_acceptance.json")},
        "topology_certification": {"SPEC_TOPOLOGY": "PASS"},
        "capability_state": {"held": ["STRUCTURE_FROZEN", "FINAL_ARTIFACT_PUBLISHED"]},
        "source_manifest": {"path": str(source_manifest), "sha256": digest(source_manifest)},
    })
    put(root / "pipeline_health_summary.json", {"overall_ok": True})
    put(root / "final_run_verdict.json", {"run_id": run_id, "status": "PASS",
        "release_profile": "structural_release", "blocking_failures": [], "blocked_external": []})
    put(root / "run_status.json", {"run_id": run_id, "status": "ok", "stage": "done"})
    paths = ("map_acceptance.json", "final_artifact_receipt.json",
             "final_run_verdict.json", "pipeline_health_summary.json", "final.xodr")
    put(root / "signature.json", {"status": "PASS", "files": {k: digest(root / k) for k in paths}})
    (root / "SUCCESS.txt").write_text("OK synthetic success\n", encoding="utf-8")
    (root / ".generations").write_text("1\n", encoding="ascii")
    lease = SimpleNamespace(generation=1, worktree_root=str(root), lease_id="lease-one", owner_token="test-private")
    return SimpleNamespace(root=root, xodr=xodr, mod=mod, lease=lease, current=current,
                           run_id=run_id, rebuild_pack=lambda: put(root / "signature.json",
                              {"status": "PASS", "files": {k: digest(root / k) for k in paths}}))


def change_json(h, file, key, value, *, update_pack=False, update_receipt=False):
    path = h.root / file
    obj = json.loads(path.read_text())
    obj[key] = value
    put(path, obj)
    if update_receipt:
        rec_path = h.root / "final_artifact_receipt.json"
        receipt = json.loads(rec_path.read_text())
        receipt["acceptance_receipt"]["sha256"] = digest(h.root / "map_acceptance.json")
        put(rec_path, receipt)
    if update_pack:
        h.rebuild_pack()


def assert_rejects(h, match=None):
    with pytest.raises(h.mod.ReleaseAuthorityError, match=match):
        h.mod.validate_release_candidate(h.root, h.xodr)


def test_valid_candidate_binds_real_files(harness):
    h = harness
    snapshot = h.mod.validate_release_candidate(h.root, h.xodr)
    assert snapshot["run_id"] == h.run_id
    assert snapshot["map_sha256"] == digest(h.xodr)


def test_diagnostic_cannot_publish_even_with_true_experiment(harness):
    h = harness
    acc = json.loads((h.root / "map_acceptance.json").read_text())
    acc["acceptance_policy"]["purpose"] = "diagnostic"
    change_json(h, "map_acceptance.json", "acceptance_policy", acc["acceptance_policy"],
                update_pack=True, update_receipt=True)
    assert_rejects(h, "diagnostic")


def test_wrong_policy_version_rejected(harness):
    h = harness
    change_json(h, "map_acceptance.json", "acceptance_policy",
                {"purpose": "release", "policy_version": "old"},
                update_pack=True, update_receipt=True)
    assert_rejects(h, "policy version")


def test_false_release_eligible_rejected(harness):
    h = harness
    change_json(h, "map_acceptance.json", "release_eligible", False,
                update_pack=True, update_receipt=True)
    assert_rejects(h, "not release eligible")


@pytest.mark.parametrize("field,value", [
    ("valid_for_experiments", "true"), ("release_eligible", 1),
    ("mandatory_gate_status", {"origin_sanity": "PASS"}),
    ("mandatory_gates", ["origin_sanity"]),
    ("evaluated_xodr_sha256", "0" * 64),
    ("final_xodr_sha256", "0" * 64),
    ("run_id", "other-run"),
])
def test_bad_acceptance_refused(harness, field, value):
    h = harness
    change_json(h, "map_acceptance.json", field, value,
                update_pack=True, update_receipt=True)
    assert_rejects(h)


def test_map_modified_after_receipt_fails(harness):
    h = harness
    h.xodr.write_bytes(b"changed different final map bytes")
    assert_rejects(h, "map bytes")


def test_input_manifest_mutation_fails(harness):
    h = harness
    (h.root / "input_manifest.json").write_text("changed", encoding="utf-8")
    assert_rejects(h, "input manifest bytes changed")


def test_missing_input_manifest_fails(harness):
    h = harness
    (h.root / "input_manifest.json").unlink()
    assert_rejects(h)


def test_topology_nonpass_fails(harness):
    h = harness
    change_json(h, "final_artifact_receipt.json", "topology_certification",
                {"SPEC_TOPOLOGY": "NOT_RUN"}, update_pack=True)
    assert_rejects(h, "topology")


def test_verdict_mismatched_run_refused(harness):
    h = harness
    change_json(h, "final_run_verdict.json", "run_id", "stale", update_pack=True)
    assert_rejects(h, "verdict run_id")


def test_status_truthiness_refused(harness):
    h = harness
    change_json(h, "run_status.json", "status", "true")
    assert_rejects(h, "run status")


def test_pack_tampering_rejected(harness):
    h = harness
    (h.root / "signature.json").write_text('{"status": "FAIL"}\n', encoding="utf-8")
    assert_rejects(h, "pack")


def test_success_absent_is_not_release(harness):
    h = harness
    (h.root / "SUCCESS.txt").unlink()
    assert_rejects(h, "SUCCESS")


def test_commit_is_required_even_with_prior_success(harness):
    h = harness
    with pytest.raises(h.mod.ReleaseAuthorityError, match="release_commit"):
        h.mod.resolve_terminal_release(h.root)


def test_publish_and_resolve(harness):
    h = harness
    commit = h.mod.publish_terminal_release(h.root, h.xodr, h.lease)
    assert commit["run_id"] == h.run_id
    assert commit["status"] == "COMMITTED"
    assert h.mod.resolve_terminal_release(h.root) == h.xodr


def test_change_after_commit_refused(harness):
    h = harness
    h.mod.publish_terminal_release(h.root, h.xodr, h.lease)
    change_json(h, "run_status.json", "status", "failed")
    with pytest.raises(h.mod.ReleaseAuthorityError):
        h.mod.resolve_terminal_release(h.root)


def test_later_fencing_generation_invalidates_old_commit(harness):
    h = harness
    h.mod.publish_terminal_release(h.root, h.xodr, h.lease)
    (h.root / ".generations").write_text("1\n2\n", encoding="ascii")
    with pytest.raises(h.mod.ReleaseAuthorityError, match="superseded"):
        h.mod.resolve_terminal_release(h.root)


def test_stale_lease_cannot_commit(harness):
    h = harness
    h.current["lease_id"] = "successor"
    with pytest.raises(h.mod.ReleaseAuthorityError, match="lease was lost"):
        h.mod.publish_terminal_release(h.root, h.xodr, h.lease)
    assert not (h.root / "release_commit.json").exists()


def test_failure_before_commit_does_not_leave_commit(harness, monkeypatch):
    h = harness
    old_replace = os.replace
    def fail_replace(source, target):
        if str(target).endswith("release_commit.json"):
            raise OSError("injected ENOSPC")
        return old_replace(source, target)
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="ENOSPC"):
        h.mod.publish_terminal_release(h.root, h.xodr, h.lease)
    assert not (h.root / "release_commit.json").exists()


def test_symlink_escape_refused(harness, tmp_path):
    h = harness
    outside = tmp_path.parent / "outside-v94.xodr"
    outside.write_bytes(h.xodr.read_bytes())
    link = h.root / "symlink.xodr"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this OS")
    with pytest.raises(h.mod.ReleaseAuthorityError):
        h.mod.validate_release_candidate(h.root, link)


def test_legacy_or_malformed_commit_refused(harness):
    h = harness
    put(h.root / "release_commit.json", {"status": "COMMITTED", "schema": "final_artifact/v2"})
    with pytest.raises(h.mod.ReleaseAuthorityError, match="weak terminal commit"):
        h.mod.resolve_terminal_release(h.root)


def test_reused_run_root_revokes_commit(harness):
    h = harness
    h.mod.publish_terminal_release(h.root, h.xodr, h.lease)
    h.mod.revoke_previous_commit(h.root)
    assert not (h.root / "release_commit.json").exists()
    with pytest.raises(h.mod.ReleaseAuthorityError):
        h.mod.resolve_terminal_release(h.root)
