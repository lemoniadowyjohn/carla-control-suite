"""Regression tests for RQ5 execution-correctness findings NEW-234..NEW-246.

Each test corresponds to a specific finding and fails on the pre-fix code.

NEW-234  the K-sweep trained on only the first dataset while claiming K
NEW-235  a failed training run fell through to a pre-existing checkpoint
NEW-236  a stale model_last.pt survived a successful retrain
NEW-237  the evaluation split defaulted to a training directory
NEW-238  a failed evaluation counted as valid evidence on key presence alone
NEW-239  unlabeled real-world evidence produced an over-broad authoritative claim
NEW-240  zero-frame labeled evaluation exited 0 with 0.0 metrics
NEW-241  an empty real-world directory exited 0 and looked like evidence
NEW-242  the runner exited 0 despite skipped/failed conditions
NEW-243  checkpoints were not bound to dataset/config/code/seed
NEW-244  training had no governed deterministic seed contract
NEW-245  strict=False loading ignored missing/unexpected parameters
NEW-246  missing results were exported to CSV as 0.0
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from ultimate_pipeline.config.thesis_contract import (
    GENERALIZATION_RQ5B_ACCURACY,
    GENERALIZATION_STATUS_AUTHORITATIVE,
    _labeled_sim_evidence_is_valid,
    _real_unlabeled_evidence_is_valid,
    infer_generalization_claim_status,
    infer_generalization_component_statuses,
)
from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID
from ultimate_pipeline.perception.rq5_provenance import (
    StateDictLoadError,
    assert_disjoint_splits,
    build_model_manifest,
    combine_dataset_identities,
    dataset_content_identity,
    load_state_dict_governed,
    load_model_manifest,
    seed_everything,
    verify_checkpoint_manifest,
    write_model_manifest,
)
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES
from ultimate_pipeline import run_generalization_experiments as rge

CAMERA = "front_left_camera"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_dataset(root: Path, camera: str = CAMERA, n: int = 2, h: int = 16, w: int = 16, seed: int = 0):
    """Write a structurally-correct synthetic segmentation dataset."""
    rgb_dir = root / "rgb" / camera
    lab_dir = root / "semseg_raw" / camera
    rgb_dir.mkdir(parents=True, exist_ok=True)
    lab_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    for i in range(n):
        rgb = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
        Image.fromarray(rgb, mode="RGB").save(rgb_dir / f"{i:08d}.png")
        lab = rng.integers(0, CARLA_SEMANTIC_NUM_CLASSES, size=(h, w), dtype=np.uint8)
        lab[rng.random((h, w)) < 0.05] = CARLA_SEMANTIC_ANY_CLASS_ID
        Image.fromarray(lab, mode="L").save(lab_dir / f"{i:08d}.png")
    return root


def _train_launcher_argv(out_dir: Path, roots, extra=()):
    return [
        "train_launcher.py",
        "--datasets", *[str(r) for r in roots],
        "--camera", CAMERA,
        "--out-dir", str(out_dir),
        "--epochs", "1",
        "--batch", "1",
        "--lr", "1e-4",
        "--num-classes", str(CARLA_SEMANTIC_NUM_CLASSES),
        "--limit", "0",
        "--device", "cpu",
        "--num-workers", "0",
        *extra,
    ]


# ---------------------------------------------------------------------------
# NEW-234: the K-sweep must actually train on K datasets
# ---------------------------------------------------------------------------


def test_multi_root_training_consumes_every_root(tmp_path, monkeypatch):
    """NEW-234: `--datasets A B C` must put all three roots into the dataset.

    Pre-fix, the runner passed only ``dataset_roots[0]`` and ``train_launcher``
    had no multi-root option at all, so K=1/3/5 could all train on the same
    first dataset.
    """
    from ultimate_pipeline.perception import train_launcher
    from ultimate_pipeline.perception.min_train_segmentation import MultiRootSegDataset

    roots = [_write_dataset(tmp_path / f"gen_{i}", n=2, seed=i) for i in range(3)]
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", _train_launcher_argv(out_dir, roots))

    train_launcher.main()

    ds = MultiRootSegDataset(roots, cam=CAMERA)
    assert len(ds) == 6, "all three roots' frames must be present"
    counts = ds.root_frame_counts
    assert all(v == 2 for v in counts.values()), counts

    # And the manifest must bind all three roots, not one.
    manifest = load_model_manifest(out_dir / "model_manifest.json")
    train_roots = manifest["dataset"]["train_roots"]
    assert [Path(p).name for p in train_roots] == ["gen_0", "gen_1", "gen_2"]
    assert manifest["dataset"]["train_root_count"] == 3
    assert manifest["dataset"]["train_identity_sha256"]


def test_multi_root_dataset_rejects_duplicate_roots(tmp_path):
    from ultimate_pipeline.perception.min_train_segmentation import MultiRootSegDataset

    root = _write_dataset(tmp_path / "gen_0", n=1)
    with pytest.raises(ValueError, match="duplicate dataset roots"):
        MultiRootSegDataset([root, root], cam=CAMERA)


def test_multi_root_dataset_reports_unpaired_frames(tmp_path):
    from ultimate_pipeline.perception.min_train_segmentation import MultiRootSegDataset

    root = _write_dataset(tmp_path / "gen_0", n=1)
    (root / "rgb" / CAMERA / "orphan.png").write_bytes(b"not-really-a-png")
    ds = MultiRootSegDataset([root], cam=CAMERA)
    assert len(ds) == 1
    assert any("orphan.png" in name for name in ds.unpaired_rgb)


def test_runner_passes_every_k_root_to_the_trainer(tmp_path, monkeypatch):
    """NEW-234 at the runner level: K=3 must hand 3 roots to train_launcher."""
    gen = [_write_dataset(tmp_path / f"gen_{i}", n=1, seed=i) for i in range(3)]
    ev = _write_dataset(tmp_path / "eval", n=1, seed=99)

    captured: list[list[str]] = []

    def _fake_subprocess(cmd, log_file=None, env=None):
        if "train_launcher" not in " ".join(cmd):
            return 0
        captured.append(list(cmd))
        model_dir = Path(cmd[cmd.index("--out-dir") + 1])
        model_dir.mkdir(parents=True, exist_ok=True)
        # Stand in for the real trainer: emit a checkpoint + manifest bound to
        # exactly the roots the runner asked for.
        from ultimate_pipeline.perception import train_launcher
        from ultimate_pipeline.perception.rq5_provenance import MULTI_ROOT_TRAIN

        roots = [Path(p) for p in cmd[cmd.index("--datasets") + 1 : cmd.index("--camera")]]
        model = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
        ckpt = model_dir / "seg_fcn_epoch001.pt"
        torch.save(model.state_dict(), ckpt)
        ids = [dataset_content_identity(r, CAMERA) for r in roots]
        ident = combine_dataset_identities(ids, strategy=MULTI_ROOT_TRAIN) if len(ids) > 1 else ids[0]
        write_model_manifest(
            model_dir,
            build_model_manifest(
                checkpoint=ckpt,
                train_dataset_identity=ident,
                train_roots=roots,
                camera=CAMERA,
                num_classes=CARLA_SEMANTIC_NUM_CLASSES,
            ),
        )
        return 0

    monkeypatch.setattr(rge, "_run_subprocess", _fake_subprocess)

    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", *[str(p) for p in gen],
            "--eval_dataset", str(ev),
            "--k_values", "1", "3",
            "--device", "cpu",
            "--epochs", "1",
        ]
    )

    train_cmds = [c for c in captured if "train_launcher" in " ".join(c)]
    assert train_cmds, "training must actually be invoked"
    by_k = {}
    for cmd in train_cmds:
        roots = [str(p) for p in cmd[cmd.index("--datasets") + 1 : cmd.index("--camera")]]
        by_k[len(roots)] = roots

    assert 1 in by_k, f"no K=1 training invocation found: {list(by_k)}"
    assert 3 in by_k, f"NEW-234: K=3 trained on {len(by_k.get(3, []))} root(s), not 3"
    assert [Path(p).name for p in by_k[3]] == ["gen_0", "gen_1", "gen_2"]
    # The old code emitted "--dataset <first>"; that must be gone.
    for cmd in train_cmds:
        assert "--dataset" not in cmd
    assert code != 0, "evaluation could not succeed with stubbed subprocesses"


# ---------------------------------------------------------------------------
# NEW-235: training failure must not fall through to an old checkpoint
# ---------------------------------------------------------------------------


def test_failed_training_does_not_evaluate_a_stale_checkpoint(tmp_path, monkeypatch):
    """NEW-235: ret==0 check missing pre-fix -> old checkpoint got evaluated."""
    gen = [_write_dataset(tmp_path / "gen_0", n=1)]
    ev = _write_dataset(tmp_path / "eval", n=1, seed=7)

    # Plant a *stale* checkpoint+manifest from a "previous run" in the condition dir.
    stale_model_dir = tmp_path / "out" / "models" / "generated_k_k001" / "OLD_RUN"
    stale_model_dir.mkdir(parents=True, exist_ok=True)
    from ultimate_pipeline.perception import train_launcher

    model = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    stale_ckpt = stale_model_dir / "seg_fcn_epoch001.pt"
    torch.save(model.state_dict(), stale_ckpt)
    ident = dataset_content_identity(gen[0], CAMERA)
    write_model_manifest(
        stale_model_dir,
        build_model_manifest(
            checkpoint=stale_ckpt, train_dataset_identity=ident, train_roots=gen, camera=CAMERA
        ),
    )

    evaluated: list[str] = []

    def _fail_training(cmd, log_file=None, env=None):
        return 3  # training fails

    def _record_eval(cmd, log_file=None, env=None):
        if "eval_sim_labeled" in " ".join(cmd):
            evaluated.append(cmd[cmd.index("--model") + 1])
            out_json = Path(cmd[cmd.index("--out-json") + 1])
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps({"status": "ok", "mIoU": 0.9, "frames_count": 1}))
        return 0

    def _dispatch(cmd, log_file=None, env=None):
        if "train_launcher" in " ".join(cmd):
            return _fail_training(cmd, log_file, env)
        return _record_eval(cmd, log_file, env)

    monkeypatch.setattr(rge, "_run_subprocess", _dispatch)

    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(gen[0]),
            "--eval_dataset", str(ev),
            "--k_values", "1",
            "--device", "cpu",
        ]
    )

    assert evaluated == [], (
        "NEW-235: a failed training run must not lead to any model being evaluated; "
        f"evaluated={evaluated}"
    )
    assert code == rge.EXIT_EXPERIMENT_INCOMPLETE

    report = json.loads(
        (tmp_path / "out" / "generalization" / "generalization_results.json").read_text()
    )
    row = report["results"][0]
    assert row["status"] == rge.STATUS_TRAIN_FAILED
    assert row["ok"] is False


# ---------------------------------------------------------------------------
# NEW-236: run-specific checkpoint identity, no stale model_last.pt
# ---------------------------------------------------------------------------


def test_purge_removes_stale_checkpoints_and_manifest(tmp_path):
    model_dir = tmp_path / "models" / "cond"
    (model_dir / "checkpoints").mkdir(parents=True)
    (model_dir / "checkpoints" / "model_last.pt").write_bytes(b"old")
    (model_dir / "seg_fcn_epoch001.pt").write_bytes(b"old")
    (model_dir / "seg_fcn_epoch009.pt").write_bytes(b"old")
    (model_dir / "model_manifest.json").write_text("{}")

    removed = rge._purge_stale_checkpoints(model_dir)

    assert len(removed) == 4
    assert rge._find_checkpoint(model_dir) is None
    assert rge._ensure_model_last(model_dir) is None


def test_ensure_model_last_overwrites_rather_than_early_returning(tmp_path):
    """NEW-236: pre-fix, `_ensure_model_last` returned the *existing* file."""
    model_dir = tmp_path / "models" / "cond"
    (model_dir / "checkpoints").mkdir(parents=True)
    stale = model_dir / "checkpoints" / "model_last.pt"
    stale.write_bytes(b"stale-from-previous-run")
    (model_dir / "seg_fcn_epoch002.pt").write_bytes(b"fresh-epoch-2")

    produced = rge._ensure_model_last(model_dir)

    assert produced == stale
    assert produced.read_bytes() == b"fresh-epoch-2", (
        "NEW-236: model_last.pt must be refreshed from this run's latest epoch"
    )


def test_successful_retrain_cannot_evaluate_the_previous_model(tmp_path, monkeypatch):
    """NEW-236 end-to-end: a stale model_last.pt must not win over new epochs."""
    gen = [_write_dataset(tmp_path / "gen_0", n=1)]
    ev = _write_dataset(tmp_path / "eval", n=1, seed=3)

    # Pre-existing stale model_last.pt in the run dir the runner will use.
    run_dir = tmp_path / "out" / "models" / "generated_k_k001" / "run_1"
    (run_dir / "checkpoints").mkdir(parents=True)
    (run_dir / "checkpoints" / "model_last.pt").write_bytes(b"stale")
    (run_dir / "seg_fcn_epoch005.pt").write_bytes(b"stale-epoch")

    def _train(cmd, log_file=None, env=None):
        model_dir = Path(cmd[cmd.index("--out-dir") + 1])
        from ultimate_pipeline.perception import train_launcher
        from ultimate_pipeline.perception.rq5_provenance import MULTI_ROOT_TRAIN

        roots = [Path(p) for p in cmd[cmd.index("--datasets") + 1 : cmd.index("--camera")]]
        model = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
        ckpt = model_dir / "seg_fcn_epoch001.pt"
        torch.save(model.state_dict(), ckpt)
        ids = [dataset_content_identity(r, CAMERA) for r in roots]
        ident = combine_dataset_identities(ids, strategy=MULTI_ROOT_TRAIN) if len(ids) > 1 else ids[0]
        write_model_manifest(
            model_dir,
            build_model_manifest(
                checkpoint=ckpt, train_dataset_identity=ident, train_roots=roots, camera=CAMERA
            ),
        )
        return 0

    def _eval(cmd, log_file=None, env=None):
        out_json = Path(cmd[cmd.index("--out-json") + 1])
        out_json.parent.mkdir(parents=True, exist_ok=True)
        model_arg = cmd[cmd.index("--model") + 1]
        out_json.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "mIoU": 0.5,
                    "frames_count": 1,
                    "model": model_arg,
                    "model_sha256": None,
                }
            )
        )
        return 0

    def _dispatch(cmd, log_file=None, env=None):
        return _train(cmd) if "train_launcher" in " ".join(cmd) else _eval(cmd)

    monkeypatch.setattr(rge, "_run_subprocess", _dispatch)

    rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(gen[0]),
            "--eval_dataset", str(ev),
            "--k_values", "1",
            "--run_id", "run_1",
            "--device", "cpu",
        ]
    )

    final_last = run_dir / "checkpoints" / "model_last.pt"
    assert final_last.read_bytes() != b"stale", "NEW-236: stale model_last.pt survived"
    assert final_last.read_bytes() != b"stale-epoch"


# ---------------------------------------------------------------------------
# NEW-237: explicit, disjoint, content-identified evaluation split
# ---------------------------------------------------------------------------


def test_eval_dataset_is_required_and_never_inferred(tmp_path):
    gen = _write_dataset(tmp_path / "gen_0", n=1)
    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(gen),
            "--k_values", "1",
            "--device", "cpu",
        ]
    )
    assert code == rge.EXIT_USAGE
    status = json.loads(
        (tmp_path / "out" / "generalization" / "experiment_status.json").read_text()
    )
    assert status["status"] == "preflight_failed"
    assert any("--eval_dataset is required" in e for e in status["preflight_errors"])
    # No training may have happened.
    assert not (tmp_path / "out" / "models").exists()


def test_manual_train_split_cannot_also_be_the_eval_split(tmp_path):
    """NEW-237: pre-fix, train A then evaluate A via manual_datasets[0]."""
    manual = _write_dataset(tmp_path / "manual", n=1)
    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_manual_datasets", str(manual),
            "--eval_dataset", str(manual),
            "--k_values", "1",
            "--device", "cpu",
        ]
    )
    assert code == rge.EXIT_USAGE
    status = json.loads(
        (tmp_path / "out" / "generalization" / "experiment_status.json").read_text()
    )
    assert any(
        "shares content identity" in e for e in status["preflight_errors"]
    ), status["preflight_errors"]


def test_copying_a_dataset_does_not_launder_train_eval_overlap(tmp_path):
    """Overlap is decided by content digest, not by path."""
    src = _write_dataset(tmp_path / "train_0", n=1)
    copy = tmp_path / "eval_copy"
    copy.mkdir()
    for sub in ("rgb", "semseg_raw"):
        src_copy = src / sub / CAMERA
        dst_copy = copy / sub / CAMERA
        dst_copy.mkdir(parents=True)
        for p in src_copy.iterdir():
            (dst_copy / p.name).write_bytes(p.read_bytes())

    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(src),
            "--eval_dataset", str(copy),
            "--k_values", "1",
            "--device", "cpu",
        ]
    )
    assert code == rge.EXIT_USAGE


def test_dataset_identity_changes_with_content_and_combination_is_ordered():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        a = _write_dataset(base / "a", n=1, seed=1)
        b = _write_dataset(base / "b", n=1, seed=2)
        a2 = _write_dataset(base / "a2", n=1, seed=1)  # identical content to a

        id_a = dataset_content_identity(a, CAMERA)
        id_b = dataset_content_identity(b, CAMERA)
        id_a2 = dataset_content_identity(a2, CAMERA)
        assert id_a["identity_sha256"] == id_a2["identity_sha256"]
        assert id_a["identity_sha256"] != id_b["identity_sha256"]

        ab = combine_dataset_identities([id_a, id_b])
        ba = combine_dataset_identities([id_b, id_a])
        assert ab["identity_sha256"] != ba["identity_sha256"], "combination must be ordered"
        assert ab["root_count"] == 2

        # K=1 can never collide with K=3.
        k1 = combine_dataset_identities([id_a])
        assert k1["identity_sha256"] != ab["identity_sha256"]


def test_assert_disjoint_splits_flags_identity_overlap():
    ident = {"identity_sha256": "deadbeef", "root": "/x"}
    other = {"identity_sha256": "cafe", "root": "/y"}
    assert assert_disjoint_splits([ident], [other]) == []
    overlaps = assert_disjoint_splits([ident], [dict(ident)])
    assert overlaps and "shares content identity" in overlaps[0]


# ---------------------------------------------------------------------------
# NEW-238: failed evaluation must not count as valid evidence
# ---------------------------------------------------------------------------


def test_failed_evaluation_with_zero_metrics_is_not_valid_evidence():
    payload = {
        "ok": False,
        "mIoU": 0.0,
        "pixel_accuracy": 0.0,
        "frames_count": 0,
        "error": "No paired RGB/semseg files found",
    }
    assert not _labeled_sim_evidence_is_valid(payload)
    assert not _real_unlabeled_evidence_is_valid({"ok": False, "n": 0, "entropy_mean": None})


def test_key_presence_alone_is_not_enough_for_sim_evidence():
    # Pre-fix, mere presence of these keys set sim_ok = True.
    assert not _labeled_sim_evidence_is_valid({"frames_count": 0})
    assert not _labeled_sim_evidence_is_valid({"mIoU": 0.0, "pixel_accuracy": 0.0, "frames_count": 3})
    assert not _labeled_sim_evidence_is_valid({"mIoU": 0.5, "frames_count": 3})  # no model/dataset
    assert _labeled_sim_evidence_is_valid(
        {"status": "ok", "mIoU": 0.5, "frames_count": 3, "model": "/m.pt", "dataset": "/d"}
    )


def test_key_presence_alone_is_not_enough_for_real_evidence():
    assert not _real_unlabeled_evidence_is_valid({"entropy_mean": 0.1, "confidence_mean": 0.2, "n": 0})
    assert not _real_unlabeled_evidence_is_valid({"n": 1, "entropy_mean": 0.1, "confidence_mean": 0.2})
    assert _real_unlabeled_evidence_is_valid({"n": 5, "entropy_mean": 0.1, "confidence_mean": 0.2})


def test_claim_status_defers_when_only_failed_outputs_exist():
    status = infer_generalization_claim_status(
        results=[
            {
                "sim": {"ok": False, "mIoU": 0.0, "frames_count": 0, "error": "no frames"},
                "real": {"ok": False, "n": 0, "entropy_mean": None},
            }
        ],
        train_gen_datasets=["/gen"],
        train_manual_datasets=[],
        eval_manual_dataset="/eval",
        real_u_dir="/real",
    )
    assert status.value != GENERALIZATION_STATUS_AUTHORITATIVE
    assert "none satisfy the governed evidence requirements" in status.reason


# ---------------------------------------------------------------------------
# NEW-239: unlabeled real data must not license an accuracy/generalization claim
# ---------------------------------------------------------------------------


def test_unlabeled_real_evidence_never_supports_accuracy_claims():
    status = infer_generalization_claim_status(
        results=[{"sim": {}, "real": {"status": "ok", "n": 42, "entropy_mean": 0.9, "confidence_mean": 0.3}}],
        train_gen_datasets=["/gen"],
        train_manual_datasets=[],
        eval_manual_dataset="",
        real_u_dir="/real",
    )
    assert status.value == GENERALIZATION_STATUS_AUTHORITATIVE
    assert GENERALIZATION_RQ5B_ACCURACY in status.reason
    assert "does NOT support a generalization-accuracy" in status.reason


def test_component_statuses_separate_shift_from_accuracy():
    components = infer_generalization_component_statuses(
        results=[{"sim": {}, "real": {"status": "ok", "n": 42, "entropy_mean": 0.9, "confidence_mean": 0.3}}],
        eval_manual_dataset="",
        real_u_dir="/real",
    )
    shift = components["real_unlabeled_eval"]
    accuracy = components["real_world_generalization_accuracy"]
    assert shift.value == GENERALIZATION_STATUS_AUTHORITATIVE
    assert "domain shift" in shift.reason
    assert accuracy.value == "deferred"
    assert GENERALIZATION_RQ5B_ACCURACY in accuracy.reason


def test_combined_claim_names_both_families_and_defers_accuracy():
    status = infer_generalization_claim_status(
        results=[
            {
                "sim": {"status": "ok", "mIoU": 0.4, "frames_count": 10, "model": "/m.pt", "dataset": "/d"},
                "real": {"status": "ok", "n": 42, "entropy_mean": 0.9, "confidence_mean": 0.3},
            }
        ],
        train_gen_datasets=["/gen"],
        train_manual_datasets=[],
        eval_manual_dataset="/eval",
        real_u_dir="/real",
    )
    assert status.value == GENERALIZATION_STATUS_AUTHORITATIVE
    assert "rq5a_simulated_transfer" in status.reason
    assert "rq5b_real_unlabeled_shift" in status.reason
    assert GENERALIZATION_RQ5B_ACCURACY in status.reason


# ---------------------------------------------------------------------------
# NEW-240 / NEW-241: evaluators must fail explicitly instead of faking success
# ---------------------------------------------------------------------------


def test_zero_frame_labeled_eval_exits_nonzero_with_null_metrics(tmp_path, monkeypatch):
    from ultimate_pipeline.perception import eval_sim_labeled as esl

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    from ultimate_pipeline.perception import train_launcher

    ckpt = model_dir / "seg_fcn_epoch001.pt"
    torch.save(train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt)

    empty_ds = tmp_path / "empty"
    (empty_ds / "rgb" / CAMERA).mkdir(parents=True)
    (empty_ds / "semseg_raw" / CAMERA).mkdir(parents=True)

    out_json = tmp_path / "eval.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_sim_labeled.py",
            "--model", str(ckpt),
            "--dataset", str(empty_ds),
            "--camera", CAMERA,
            "--out-json", str(out_json),
            "--device", "cpu",
        ],
    )
    code = esl.main()
    report = json.loads(out_json.read_text())

    assert code != 0, "NEW-240: zero-frame evaluation must not exit 0"
    assert report["status"] == "failed"
    assert report["mIoU"] is None, "0.0 mIoU would falsely read as a measured zero"
    assert report["pixel_accuracy"] is None
    assert report["frames_count"] == 0
    assert "no_paired_frames" in report["errors"]


def test_empty_real_world_directory_exits_nonzero(tmp_path, monkeypatch):
    from ultimate_pipeline.perception import eval_real_unlabeled as eru

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    from ultimate_pipeline.perception import train_launcher

    ckpt = model_dir / "seg_fcn_epoch001.pt"
    torch.save(train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt)

    real_dir = tmp_path / "real"
    real_dir.mkdir()  # exists, empty

    out_json = tmp_path / "real.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_real_unlabeled.py",
            "--model", str(ckpt),
            "--real-dir", str(real_dir),
            "--out-json", str(out_json),
            "--device", "cpu",
            "--limit", "0",
        ],
    )
    code = eru.main()
    report = json.loads(out_json.read_text())

    assert code != 0, "NEW-241: an empty real-world directory must not exit 0"
    assert report["status"] == "failed"
    assert report["real"]["n"] == 0
    assert any("insufficient_real_images" in e for e in report["errors"])


def test_real_unlabeled_report_declares_it_cannot_produce_accuracy(tmp_path, monkeypatch):
    from ultimate_pipeline.perception import eval_real_unlabeled as eru

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    from ultimate_pipeline.perception import train_launcher

    ckpt = model_dir / "seg_fcn_epoch001.pt"
    torch.save(train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt)

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    for name in ("a.png", "b.png"):
        Image.fromarray(
            np.random.default_rng(abs(hash(name)) % 2**32).integers(
                0, 255, size=(16, 16, 3), dtype=np.uint8
            ),
            mode="RGB",
        ).save(real_dir / name)

    out_json = tmp_path / "real.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_real_unlabeled.py",
            "--model", str(ckpt),
            "--real-dir", str(real_dir),
            "--out-json", str(out_json),
            "--device", "cpu",
            "--limit", "0",
        ],
    )
    assert eru.main() == 0
    report = json.loads(out_json.read_text())
    assert report["claim_scope"] == "domain_shift_indicators_only"
    assert report["accuracy_metrics_available"] is False
    assert report["deferred_claim"] == "real_world_generalization_accuracy"
    assert "mIoU" not in report and "pixel_accuracy" not in report


# ---------------------------------------------------------------------------
# NEW-243 / NEW-244 / NEW-245: provenance, seeds, strict loading
# ---------------------------------------------------------------------------


def test_seed_everything_is_reproducible_and_recorded():
    import random

    first = seed_everything(4242)
    a = (random.random(), float(np.random.rand()), float(torch.rand(1)))
    second = seed_everything(4242)
    b = (random.random(), float(np.random.rand()), float(torch.rand(1)))
    assert a == b, "NEW-244: the same seed must reproduce the same RNG stream"
    assert first["seed"] == second["seed"] == 4242
    assert first["torch"]["seeded"] is True
    assert first["random"] == "seeded"
    with pytest.raises(ValueError):
        seed_everything(-1)


def test_training_is_deterministic_for_a_frozen_seed(tmp_path, monkeypatch):
    from ultimate_pipeline.perception import train_launcher

    root = _write_dataset(tmp_path / "gen_0", n=3, h=16, w=16, seed=5)

    def _run(name, seed):
        out_dir = tmp_path / name
        monkeypatch.setattr(
            sys, "argv", _train_launcher_argv(out_dir, [root], extra=["--seed", str(seed)])
        )
        train_launcher.main()
        return torch.load(out_dir / "seg_fcn_epoch001.pt", map_location="cpu")

    a = _run("run_a", 777)
    b = _run("run_b", 777)
    c = _run("run_c", 778)

    for key in a:
        assert torch.equal(a[key], b[key]), f"NEW-244: seed 777 diverged at {key}"
    assert not all(torch.equal(a[k], c[k]) for k in a), (
        "a different seed should not be expected to give an identical model"
    )


def test_model_manifest_binds_checkpoint_dataset_git_and_seed(tmp_path, monkeypatch):
    from ultimate_pipeline.perception import train_launcher

    root = _write_dataset(tmp_path / "gen_0", n=1)
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        sys, "argv", _train_launcher_argv(out_dir, [root], extra=["--seed", "31337"])
    )
    train_launcher.main()

    manifest = load_model_manifest(out_dir / "model_manifest.json")
    assert manifest["seed"]["seed"] == 31337
    assert manifest["dataset"]["train_identity_sha256"]
    assert manifest["dataset"]["train_roots"] == [str(root.resolve())] or manifest["dataset"]["train_roots"]
    assert manifest["optimization"]["learning_rate"] == pytest.approx(1e-4)
    assert manifest["optimization"]["optimizer"] == "Adam"
    assert manifest["model"]["num_classes"] == CARLA_SEMANTIC_NUM_CLASSES
    assert manifest["model"]["architecture_version"]
    assert manifest["camera"] == CAMERA
    assert manifest["preprocessing"]
    assert manifest["augmentation_policy"] == "none"
    # The checkpoint SHA must match the file actually on disk.
    from ultimate_pipeline.utils.file_hashing import sha256_file

    assert manifest["checkpoint"]["sha256"] == sha256_file(
        out_dir / "seg_fcn_epoch001.pt"
    )


def test_verify_checkpoint_manifest_rejects_a_swapped_checkpoint(tmp_path):
    from ultimate_pipeline.perception import train_launcher

    model = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    ckpt = out_dir / "seg_fcn_epoch001.pt"
    torch.save(model.state_dict(), ckpt)
    manifest = build_model_manifest(
        checkpoint=ckpt,
        train_dataset_identity={"identity_sha256": "abc", "root_count": 1},
        train_roots=["/gen"],
        camera=CAMERA,
        seed=1,
    )
    write_model_manifest(out_dir, manifest)

    assert verify_checkpoint_manifest(ckpt, out_dir / "model_manifest.json")["ok"]

    # Swap in a different checkpoint: the binding must break.
    torch.save(model.state_dict(), out_dir / "seg_fcn_epoch002.pt")
    verification = verify_checkpoint_manifest(
        out_dir / "seg_fcn_epoch002.pt", out_dir / "model_manifest.json"
    )
    assert not verification["ok"]
    assert any("sha256 mismatch" in f for f in verification["failures"])


def test_verify_checkpoint_manifest_requires_provenance_when_governed(tmp_path):
    from ultimate_pipeline.perception import train_launcher

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    ckpt = out_dir / "seg_fcn_epoch001.pt"
    torch.save(train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt)
    # A manifest with no dataset identity, git commit or seed.
    write_model_manifest(
        out_dir,
        {
            "schema": "rq5_model_manifest_v1",
            "checkpoint": {"sha256": None},
        },
    )
    verification = verify_checkpoint_manifest(
        ckpt, out_dir / "model_manifest.json", require_provenance=True
    )
    assert not verification["ok"]
    reasons = " ".join(verification["failures"])
    assert "training dataset identity" in reasons
    assert "git commit" in reasons
    assert "seed" in reasons


def test_strict_load_rejects_incompatible_checkpoint(tmp_path):
    """NEW-245: pre-fix, strict=False hid missing/unexpected parameters."""
    from ultimate_pipeline.perception import train_launcher

    model = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    state = model.state_dict()
    # Drop one parameter entirely: a partially-initialised model would silently
    # report metrics while never having learned that layer.
    victim = sorted(state)[0]
    partial = {k: v for k, v in state.items() if k != victim}

    ckpt = tmp_path / "partial.pt"
    torch.save(partial, ckpt)

    fresh = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    with pytest.raises(StateDictLoadError) as exc:
        load_state_dict_governed(fresh, ckpt)
    assert victim in str(exc.value) or "missing" in str(exc.value)

    # Explicitly opting in is allowed, and the mismatch is still reported.
    fresh2 = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    record: dict = {}
    outcome = load_state_dict_governed(fresh2, ckpt, allow_partial=True, record=record)
    assert victim in outcome["missing_keys"]
    assert outcome["strict"] is False
    assert record["state_dict_load"]["missing_keys"] == outcome["missing_keys"]


def test_strict_load_rejects_unexpected_parameters(tmp_path):
    from ultimate_pipeline.perception import train_launcher

    model = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    state = dict(model.state_dict())
    state["totally.unexpected.parameter"] = torch.zeros(1)

    ckpt = tmp_path / "extra.pt"
    torch.save(state, ckpt)

    fresh = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    with pytest.raises(StateDictLoadError, match="unexpected"):
        load_state_dict_governed(fresh, ckpt)


def test_evaluator_refuses_unbound_checkpoint_when_manifest_required(tmp_path, monkeypatch):
    from ultimate_pipeline.perception import eval_sim_labeled as esl

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    from ultimate_pipeline.perception import train_launcher

    ckpt = model_dir / "seg_fcn_epoch001.pt"
    torch.save(train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES).state_dict(), ckpt)
    _write_dataset(tmp_path / "ds", n=1)

    out_json = tmp_path / "eval.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_sim_labeled.py",
            "--model", str(ckpt),
            "--dataset", str(tmp_path / "ds"),
            "--camera", CAMERA,
            "--out-json", str(out_json),
            "--device", "cpu",
            "--require-manifest",
        ],
    )
    assert esl.main() != 0
    report = json.loads(out_json.read_text())
    assert report["status"] == "failed"
    assert any("no_companion_manifest" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# NEW-242 / NEW-246: experiment exit semantics and null-not-zero CSV
# ---------------------------------------------------------------------------


def test_missing_k_value_makes_the_experiment_exit_nonzero(tmp_path, monkeypatch):
    gen = _write_dataset(tmp_path / "gen_0", n=1)
    ev = _write_dataset(tmp_path / "eval", n=1, seed=11)

    monkeypatch.setattr(rge, "_run_subprocess", lambda cmd, log_file=None, env=None: 0)

    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(gen),
            "--eval_dataset", str(ev),
            "--k_values", "1", "3", "5",  # only 1 dataset available
            "--device", "cpu",
        ]
    )
    assert code == rge.EXIT_EXPERIMENT_INCOMPLETE

    status = json.loads(
        (tmp_path / "out" / "generalization" / "experiment_status.json").read_text()
    )
    assert status["experiment_status"] == "incomplete"
    assert status["exit_code"] == rge.EXIT_EXPERIMENT_INCOMPLETE
    skipped = {c["condition"] for c in status["conditions_not_completed"]}
    assert "generated_k_k003" in skipped
    assert "generated_k_k005" in skipped


def test_csv_exports_missing_metrics_as_na_not_zero(tmp_path, monkeypatch):
    gen = _write_dataset(tmp_path / "gen_0", n=1)
    ev = _write_dataset(tmp_path / "eval", n=1, seed=13)

    def _fail_all(cmd, log_file=None, env=None):
        return 1

    monkeypatch.setattr(rge, "_run_subprocess", _fail_all)

    rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(gen),
            "--eval_dataset", str(ev),
            "--k_values", "1",
            "--device", "cpu",
        ]
    )

    csv_path = tmp_path / "out" / "generalization" / "generalization_results.csv"
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert rows, "even a failed condition must appear in the results table"
    row = rows[0]
    assert row["mIoU"] == rge.NA, "NEW-246: missing mIoU must not be exported as 0.0"
    assert row["pixel_accuracy"] == rge.NA
    assert row["frames_count"] == rge.NA
    assert row["real_entropy_mean"] == rge.NA
    assert row["real_confidence_mean"] == rge.NA
    assert row["status"] == rge.STATUS_TRAIN_FAILED


def test_metric_cell_keeps_measured_zero_distinct_from_missing():
    assert rge._metric_cell(None) == rge.NA
    assert rge._metric_cell(0.0) == 0.0
    assert rge._metric_cell(0) == 0
    assert rge._metric_cell("oops") == rge.NA
    assert rge._metric_cell(True) == rge.NA


def test_skip_training_requires_explicit_reuse_opt_in(tmp_path):
    gen = _write_dataset(tmp_path / "gen_0", n=1)
    ev = _write_dataset(tmp_path / "eval", n=1, seed=17)
    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(gen),
            "--eval_dataset", str(ev),
            "--k_values", "1",
            "--skip_training",
            "--device", "cpu",
        ]
    )
    assert code == rge.EXIT_USAGE
    status = json.loads(
        (tmp_path / "out" / "generalization" / "experiment_status.json").read_text()
    )
    assert any("--allow_checkpoint_reuse" in e for e in status["preflight_errors"])


def test_allow_incomplete_flag_can_suppress_the_nonzero_exit(tmp_path, monkeypatch):
    gen = _write_dataset(tmp_path / "gen_0", n=1)
    ev = _write_dataset(tmp_path / "eval", n=1, seed=19)
    monkeypatch.setattr(rge, "_run_subprocess", lambda cmd, log_file=None, env=None: 1)
    code = rge.main(
        [
            "--out_dir", str(tmp_path / "out"),
            "--train_gen_datasets", str(gen),
            "--eval_dataset", str(ev),
            "--k_values", "1",
            "--allow_incomplete",
            "--device", "cpu",
        ]
    )
    assert code == 0
    status = json.loads(
        (tmp_path / "out" / "generalization" / "experiment_status.json").read_text()
    )
    assert status["experiment_status"] == "incomplete", (
        "the recorded status must stay truthful even when the exit code is suppressed"
    )
