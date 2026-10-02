"""
RQ5 preflight orchestrator tests (batch 12 section 15).

Preflight answers one question -- is RQ5 ready to train, and if not, exactly
what is missing -- without training anything and without inventing a dataset.

Two properties matter most here:

* with no explicit dataset it reports ``dataset_blocked`` and searches nothing;
* with an explicit synthetic dataset it runs the whole chain (quality gate,
  grouped splits, leakage audit) and reaches ``RQ5_PROTOCOL_V2_READY``.

All dataset fixtures are synthetic and carry ``claim_scope = TEST_FIXTURE_ONLY``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.rq5_preflight import (  # noqa: E402
    PREFLIGHT_FILENAME,
    PREFLIGHT_SCHEMA,
    SEED_LIST,
    STATUS_PARTIAL,
    STATUS_PROTOCOL_READY,
    STATUS_READY_BLOCKED,
    check_dataset_inputs,
    check_evaluation_roles,
    check_output_isolation,
    check_protocol,
    check_seed_list,
    check_trainer_strict_mode,
    run_preflight,
)

CAMERA = "front_left_camera"
SIZE = 32


def _write_capture(root: Path, capture_id: str, segment: int, frames: int, seed: int, route: str) -> list[dict]:
    rgb_dir = root / "rgb" / CAMERA
    lab_dir = root / "semseg_raw" / CAMERA
    rgb_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    records: list[dict] = []
    base = int(capture_id.split("_")[-1]) * 1000
    for i in range(frames):
        frame_id = base + i
        name = f"{frame_id:08d}.png"
        Image.fromarray(
            rng.integers(0, 255, size=(SIZE, SIZE, 3), dtype=np.uint8), mode="RGB"
        ).save(rgb_dir / name)
        lab = rng.integers(0, 12, size=(SIZE, SIZE), dtype=np.uint8)
        lab[rng.random((SIZE, SIZE)) < 0.02] = 255
        Image.fromarray(lab, mode="L").save(lab_dir / name)
        records.append(
            {
                "frame_id": frame_id,
                "filename": name,
                "route_id": route,
                "segment_id": segment,
                "capture_id": capture_id,
            }
        )
    return records


def _make_dataset(root: Path, captures: int, frames: int, route: str, seed0: int) -> Path:
    records: list[dict] = []
    for i in range(captures):
        records += _write_capture(root, f"cap_{i:03d}", i, frames, seed0 + i, route)
    (root / "frame_index.json").write_text(json.dumps({"frames": records}), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# offline sections
# ---------------------------------------------------------------------------


def test_protocol_section_validates_v2():
    section = check_protocol()
    assert section["ok"], [c for c in section["checks"] if c["status"] == "FAIL"]
    codes = {c["code"] for c in section["checks"]}
    assert "protocol_amendment_rationale" in codes
    assert "protocol_v1_hyperparameters_preserved" in codes
    assert "underpowered_contingency" in codes


def test_protocol_section_fails_when_the_file_is_missing(tmp_path):
    section = check_protocol(tmp_path / "absent.json")
    assert section["ok"] is False
    assert section["checks"][0]["code"] == "protocol_present"


def test_seed_list_section_matches_the_protocol():
    assert SEED_LIST == (7, 17, 42)
    section = check_seed_list()
    assert section["ok"] is True
    assert section["seeds"] == [7, 17, 42]
    assert check_seed_list((1, 1, 2))["ok"] is False
    assert check_seed_list((1, 2))["ok"] is False


def test_evaluation_roles_section_pins_accuracy_to_labeled_roles():
    section = check_evaluation_roles()
    assert section["ok"] is True
    contracts = section["contracts"]
    assert contracts["manual_test"]["accuracy_claim_allowed"] is True
    assert contracts["real_unlabeled"]["accuracy_claim_allowed"] is False


def test_output_isolation_section_plans_one_directory_per_seed(tmp_path):
    section = check_output_isolation(tmp_path)
    assert section["ok"] is True
    assert len(set(section["planned_dirs"])) == len(SEED_LIST)
    for seed in SEED_LIST:
        assert any(f"seed_{seed}" in d for d in section["planned_dirs"])


def test_trainer_strict_mode_section_exercises_the_prohibitions():
    section = check_trainer_strict_mode()
    assert section["ok"], [c for c in section["checks"] if c["status"] == "FAIL"]
    codes = {c["code"] for c in section["checks"]}
    assert "strict_forbids_implicit_split_creation" in codes
    assert "strict_forbids_implicit_camera" in codes
    assert "strict_forbids_implicit_seed" in codes
    assert "legacy_fallback_preserved" in codes


# ---------------------------------------------------------------------------
# dataset-blocked path
# ---------------------------------------------------------------------------


def test_no_dataset_is_never_guessed_or_searched(tmp_path):
    section = check_dataset_inputs(
        generated_root=None, camera=None, out_dir=tmp_path / "out"
    )
    assert section["dataset_blocked"] is True
    assert section["ok"] is False
    assert not list((tmp_path / "out").glob("*")), "no evidence may be produced without a dataset"
    message = section["checks"][0]["detail"]
    assert "Nothing was searched or guessed" in message


def test_preflight_without_a_dataset_reports_dataset_blocked(tmp_path):
    report = run_preflight(out_dir=tmp_path / "out", repo_root=REPO_ROOT, write_evidence=False)
    assert report["final_rq5_training_executed"] is False
    if report["offline_authority_ok"]:
        assert report["final_status"] == STATUS_READY_BLOCKED
        assert report["dataset_blocked"] is True
        assert "no validated RQ3 paired dataset" in report["rationale"]
    else:  # a dirty candidate tree is reported honestly, not papered over
        assert report["final_status"] == STATUS_PARTIAL


def test_preflight_never_claims_to_have_trained(tmp_path):
    report = run_preflight(out_dir=tmp_path / "out", repo_root=REPO_ROOT, write_evidence=False)
    assert report["final_rq5_training_executed"] is False
    assert report["claim_scope"] == "OFFLINE_READINESS_AUDIT"
    assert "performs no training" in report["claim_boundary"]


# ---------------------------------------------------------------------------
# full chain on an explicit synthetic dataset
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def preflight_ready(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("preflight_ready")
    generated = _make_dataset(tmp_path / "generated", 6, 4, "ing_sim", 10)
    manual = _make_dataset(tmp_path / "manual", 3, 3, "ing_manual", 70)
    out_dir = tmp_path / "evidence"
    report = run_preflight(
        generated_root=generated,
        camera=CAMERA,
        manual_root=manual,
        out_dir=out_dir,
        repo_root=REPO_ROOT,
        write_evidence=True,
    )
    return {"report": report, "out_dir": out_dir}


def test_full_chain_on_an_explicit_dataset_is_protocol_ready(preflight_ready):
    report = preflight_ready["report"]
    datasets = report["sections"]["datasets"]
    assert datasets["ok"], [c for c in datasets["checks"] if c["status"] == "FAIL"]
    assert datasets["dataset_blocked"] is False
    # The only remaining offline gate is candidate cleanliness, which is an
    # honest function of the tree this test happens to run in: a dirty tree is
    # reported as PARTIAL_WITH_EXACT_BLOCKERS rather than papered over.
    if report["offline_authority_ok"]:
        assert report["final_status"] == STATUS_PROTOCOL_READY
    else:
        assert report["final_status"] == STATUS_PARTIAL
        assert report["sections"]["candidate"]["ok"] is False


def test_full_chain_writes_split_manifests_and_the_leakage_audit(preflight_ready):
    out_dir = preflight_ready["out_dir"]
    for name in (
        "train_manifest.json",
        "validation_manifest.json",
        "generated_test_manifest.json",
        "manual_test_manifest.json",
        "RQ5_SPLIT_LEAKAGE_AUDIT.json",
        PREFLIGHT_FILENAME,
    ):
        assert (out_dir / name).is_file(), f"{name} was not written"

    audit = json.loads((out_dir / "RQ5_SPLIT_LEAKAGE_AUDIT.json").read_text(encoding="utf-8"))
    assert audit["leak_free"] is True
    assert audit["status"] == "PASS"
    assert audit["claim_scope"] == "TEST_FIXTURE_ONLY"


def test_preflight_payload_records_evidence_hashes_and_self_hash(preflight_ready):
    report = preflight_ready["report"]
    assert report["schema"] == PREFLIGHT_SCHEMA
    assert report["report_sha256"]
    assert report["evidence_sha256"], "evidence file hashes must be recorded"
    assert "train_manifest.json" in report["evidence_sha256"]
    assert "RQ5_SPLIT_LEAKAGE_AUDIT.json" in report["evidence_sha256"]
    summary = report["sections"]["datasets"]["evidence"]["split_summary"]
    assert summary["generated"]["group_kind"] == "route_segment"
    assert summary["generated"]["identity_complete"] is True
    assert summary["degraded_grouping"] is False


def test_quality_evidence_is_captured_for_every_role(preflight_ready):
    quality = preflight_ready["report"]["sections"]["datasets"]["evidence"]["dataset_quality"]
    assert set(quality) == {"generated", "manual"}
    for role, payload in quality.items():
        assert payload["status"] == "PASS", (role, payload["quality_failures"])
        assert payload["paired_frame_count"] > 0
        assert payload["claim_scope"] == "TEST_FIXTURE_ONLY"


def test_a_failing_dataset_is_reported_not_passed(tmp_path):
    generated = _make_dataset(tmp_path / "generated", 6, 4, "ing_sim", 10)
    Image.fromarray(np.zeros((SIZE, SIZE, 3), dtype=np.uint8), mode="RGB").save(
        generated / "rgb" / CAMERA / "00000000.png"
    )
    section = check_dataset_inputs(
        generated_root=generated, camera=CAMERA, out_dir=tmp_path / "out"
    )
    assert section["ok"] is False
    codes = {c["code"] for c in section["checks"] if c["status"] == "FAIL"}
    assert "dataset_quality_pass" in codes