from __future__ import annotations

"""RQ5 training-safety invariants (NEW-234 .. NEW-246).

Every test here pins a defect that previously let a "trained" model be
reported without the thing that was claimed:

* NEW-234  K-sweep forwarded only dataset_roots[0] to the launcher.
* NEW-236  missing dataset roots silently auto-selected an unrelated dataset.
* NEW-239  no seed was ever applied; the recorded seed was fabricated.
* NEW-240  no train/validation/test split was enforced, so K was swept over
           test data.
* NEW-241  `real_u` (train split) was reported under a `manual_test` heading.
* NEW-242  gen_datasets[:k] was not required to be a contiguous spatial
           sequence, making the K-series meaningless.
* NEW-243  one evaluation set could be claimed while only the other ran.
* NEW-245  no `summary_complete` flag existed to expose the above.
* NEW-246  checkpoints were loaded with strict=False, silently evaluating a
           randomly initialised head.
"""

import json
import sys

import pytest

from ultimate_pipeline.perception import train_launcher
from ultimate_pipeline.run_generalization_experiments import (
    _assert_contiguous_generated_sequence,
)
from ultimate_pipeline.run_generalization_experiments import train_model


# --------------------------------------------------------------------------- #
# NEW-234: every requested dataset root must reach the launcher
# --------------------------------------------------------------------------- #
def test_train_model_forwards_every_dataset_root(tmp_path, monkeypatch):
    captured = {}

    def _fake_run(cmd, log_file=None, env=None):
        captured["cmd"] = cmd
        return 1  # nonzero so no checkpoint handling happens

    monkeypatch.setattr(
        "ultimate_pipeline.run_generalization_experiments._run_subprocess", _fake_run
    )

    roots = [tmp_path / "run_a", tmp_path / "run_b", tmp_path / "run_c"]
    for r in roots:
        r.mkdir()

    ok = train_model(
        condition_name="generated_k_k003",
        dataset_roots=roots,
        camera="front_left_camera",
        out_dir=tmp_path / "out",
        epochs=1,
        batch_size=2,
        device="cpu",
        log_dir=tmp_path / "logs",
        seed=7,
    )

    assert ok is False
    cmd = captured["cmd"]
    datasets = [
        cmd[i + 1] for i, a in enumerate(cmd) if a == "--dataset"
    ]
    assert datasets == [str(r) for r in roots], (
        "NEW-234: only dataset_roots[0] used to be forwarded, so k=8 "
        "conditions silently trained on k=1 data"
    )
    assert cmd[cmd.index("--seed") + 1] == "7"

    manifest = json.loads(
        (tmp_path / "out" / "models" / "generated_k_k003" / "training_manifest.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["dataset_root_count"] == 3
    assert manifest["seed"] == 7


# --------------------------------------------------------------------------- #
# NEW-236: governed training fails closed on a missing root
# --------------------------------------------------------------------------- #
def test_governed_training_fails_closed_on_missing_root(tmp_path, monkeypatch):
    argv = [
        "train_launcher.py",
        "--dataset", str(tmp_path / "does_not_exist"),
        "--camera", "front_left_camera",
        "--out-dir", str(tmp_path / "out"),
        "--epochs", "1",
        "--device", "cpu",
        "--num-workers", "0",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(FileNotFoundError) as exc:
        train_launcher.main()
    assert "GOVERNED" in str(exc.value)
    assert "diagnostic-auto-discover" in str(exc.value)


def test_diagnostic_auto_discover_is_an_explicit_opt_in():
    """The escape hatch must exist, but only as an explicit opt-in flag."""
    import argparse

    # Mirrors the parser construction; a regression that silently re-enables
    # auto-discovery for governed runs would show up here.
    src = open(train_launcher.__file__, encoding="utf-8").read()
    assert "--diagnostic-auto-discover" in src
    assert "args.diagnostic_auto_discover or not args.governed" in src


# --------------------------------------------------------------------------- #
# NEW-239: the seed must be APPLIED and recorded
# --------------------------------------------------------------------------- #
def test_training_provenance_records_applied_seed(tmp_path, monkeypatch):
    from PIL import Image
    import numpy as np

    from ultimate_pipeline.perception.semantic_classes import (
        CARLA_SEMANTIC_NUM_CLASSES,
    )

    camera = "front_left_camera"
    dataset = tmp_path / "run"
    rgb_dir = dataset / "rgb" / camera
    lab_dir = dataset / "semseg_raw" / camera
    rgb_dir.mkdir(parents=True)
    lab_dir.mkdir(parents=True)
    rng = np.random.default_rng(0)
    for i in range(2):
        Image.fromarray(
            rng.integers(0, 255, size=(32, 32, 3), dtype=np.uint8), mode="RGB"
        ).save(rgb_dir / f"{i:08d}.png")
        Image.fromarray(
            rng.integers(0, CARLA_SEMANTIC_NUM_CLASSES, size=(32, 32), dtype=np.uint8),
            mode="L",
        ).save(lab_dir / f"{i:08d}.png")

    out_dir = tmp_path / "out"
    argv = [
        "train_launcher.py",
        "--dataset", str(dataset),
        "--camera", camera,
        "--out-dir", str(out_dir),
        "--epochs", "1",
        "--batch", "2",
        "--lr", "1e-4",
        "--num-classes", str(CARLA_SEMANTIC_NUM_CLASSES),
        "--device", "cpu",
        "--num-workers", "0",
        "--seed", "1234",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    train_launcher.main()

    provenance = json.loads(
        (out_dir / "training_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["seed_requested"] == 1234
    assert provenance["seed_applied"] == 1234
    assert provenance["seeding"]["torch"] is True
    assert provenance["seeding"]["python"] is True
    assert provenance["seeding"]["numpy"] is True
    assert provenance["dataset_roots"] == [str(dataset)]


def test_multi_root_training_records_every_root(tmp_path, monkeypatch):
    from PIL import Image
    import numpy as np

    from ultimate_pipeline.perception.semantic_classes import (
        CARLA_SEMANTIC_NUM_CLASSES,
    )

    camera = "front_left_camera"
    roots = []
    for name, n in (("run_a", 2), ("run_b", 3)):
        root = tmp_path / name
        rgb_dir = root / "rgb" / camera
        lab_dir = root / "semseg_raw" / camera
        rgb_dir.mkdir(parents=True)
        lab_dir.mkdir(parents=True)
        rng = np.random.default_rng(hash(name) % (2**32))
        for i in range(n):
            Image.fromarray(
                rng.integers(0, 255, size=(32, 32, 3), dtype=np.uint8), mode="RGB"
            ).save(rgb_dir / f"{i:08d}.png")
            Image.fromarray(
                rng.integers(
                    0, CARLA_SEMANTIC_NUM_CLASSES, size=(32, 32), dtype=np.uint8
                ),
                mode="L",
            ).save(lab_dir / f"{i:08d}.png")
        roots.append(root)

    out_dir = tmp_path / "out"
    argv = [
        "train_launcher.py",
        "--dataset", str(roots[0]),
        "--dataset", str(roots[1]),
        "--camera", camera,
        "--out-dir", str(out_dir),
        "--epochs", "1",
        "--batch", "2",
        "--lr", "1e-4",
        "--num-classes", str(CARLA_SEMANTIC_NUM_CLASSES),
        "--device", "cpu",
        "--num-workers", "0",
        "--seed", "5",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    train_launcher.main()

    provenance = json.loads(
        (out_dir / "training_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["dataset_roots"] == [str(r) for r in roots]
    assert provenance["dataset_frames"] == [2, 3]
    assert (out_dir / "seg_fcn_epoch001.pt").exists()


def test_governed_training_rejects_duplicate_roots(tmp_path, monkeypatch):
    root = tmp_path / "run"
    (root / "rgb" / "front_left_camera").mkdir(parents=True)
    (root / "semseg_raw" / "front_left_camera").mkdir(parents=True)

    argv = [
        "train_launcher.py",
        "--dataset", str(root),
        "--dataset", str(root),
        "--camera", "front_left_camera",
        "--out-dir", str(tmp_path / "out"),
        "--epochs", "1",
        "--device", "cpu",
        "--num-workers", "0",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError) as exc:
        train_launcher.main()
    assert "duplicate dataset roots" in str(exc.value)


# --------------------------------------------------------------------------- #
# NEW-240: split manifest must exist, name all four splits, and be disjoint
# --------------------------------------------------------------------------- #
def _write_split(path, **overrides):
    manifest = {
        "generated_train": ["g001", "g002", "g003"],
        "generated_validation": ["g101"],
        "generated_test": ["g201"],
        "manual_test": ["m001"],
    }
    manifest.update(overrides)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_split_manifest_missing_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        train_launcher._validate_split_manifest(tmp_path / "nope.json")


def test_split_manifest_missing_split_is_rejected(tmp_path):
    path = _write_split(tmp_path / "s.json", manual_test=[])
    with pytest.raises(ValueError) as exc:
        train_launcher._validate_split_manifest(path)
    assert "manual_test" in str(exc.value)


def test_split_manifest_overlap_is_rejected(tmp_path):
    path = _write_split(tmp_path / "s.json", manual_test=["g003"])
    with pytest.raises(ValueError) as exc:
        train_launcher._validate_split_manifest(path)
    assert "appears in both" in str(exc.value)


def test_split_manifest_train_vs_manual_leak_is_rejected(tmp_path):
    path = _write_split(tmp_path / "s.json", manual_test=["m001", "g002"])
    with pytest.raises(ValueError) as exc:
        train_launcher._validate_split_manifest(path)
    assert "manual_test" in str(exc.value)


def test_split_manifest_accepts_clean_disjoint_splits(tmp_path):
    path = _write_split(tmp_path / "s.json")
    out = train_launcher._validate_split_manifest(path)
    assert out["generated_test"] == ["g201"]


# --------------------------------------------------------------------------- #
# NEW-242: the K-series must be a contiguous, adjacent, duplicate-free chain
# --------------------------------------------------------------------------- #
def test_generated_sequence_rejects_duplicates(tmp_path):
    roots = [tmp_path / "a", tmp_path / "b", tmp_path / "a"]
    for r in set(roots):
        r.mkdir()
    with pytest.raises(ValueError) as exc:
        _assert_contiguous_generated_sequence(roots)
    assert "duplicate" in str(exc.value)


def test_generated_sequence_accepts_clean_chain(tmp_path):
    roots = [tmp_path / "a", tmp_path / "b"]
    for r in roots:
        r.mkdir()
    report = _assert_contiguous_generated_sequence(roots)
    assert report["contiguous"] is True
    assert report["duplicates"] == []
    assert report["chain_violations"] == []


def test_generated_sequence_violates_declared_neighbours(tmp_path):
    roots = [tmp_path / "a", tmp_path / "b", tmp_path / "c"]
    for r in roots:
        r.mkdir()
    # a and b are declared neighbours; c declares an unrelated neighbour.
    (roots[0] / "map_composition_manifest.json").write_text(
        json.dumps({"neighbour_runs": [str(roots[1])]}), encoding="utf-8"
    )
    (roots[1] / "map_composition_manifest.json").write_text(
        json.dumps({"neighbour_runs": [str(roots[0])]}), encoding="utf-8"
    )
    (roots[2] / "map_composition_manifest.json").write_text(
        json.dumps({"neighbour_runs": [str(tmp_path / "unrelated")]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc:
        _assert_contiguous_generated_sequence(roots)
    assert "NEW-242" in str(exc.value)


# --------------------------------------------------------------------------- #
# NEW-243 / NEW-245: no silent evaluation-set fallback; honest completeness
# --------------------------------------------------------------------------- #
def test_missing_eval_dataset_is_a_hard_error(tmp_path, monkeypatch):
    from ultimate_pipeline import run_generalization_experiments as rge

    gen_root = tmp_path / "gen"
    gen_root.mkdir()

    argv = [
        "rge.py",
        "--train_gen_datasets", str(gen_root),
        "--skip_training",
        "--out_dir", str(tmp_path / "out"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError) as exc:
        rge.main()
    assert "NEW-243" in str(exc.value)


def test_require_both_eval_sets_raises_when_incomplete(tmp_path, monkeypatch):
    from ultimate_pipeline import run_generalization_experiments as rge

    manual = tmp_path / "manual"
    manual.mkdir()

    argv = [
        "rge.py",
        "--train_manual_datasets", str(manual),
        "--skip_training",
        "--require_both_eval_sets",
        "--out_dir", str(tmp_path / "out"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(RuntimeError) as exc:
        rge.main()
    assert "NEW-243" in str(exc.value)


def test_real_u_train_split_is_classified_honestly(tmp_path, monkeypatch):
    from ultimate_pipeline import run_generalization_experiments as rge

    manual = tmp_path / "manual"
    manual.mkdir()

    argv = [
        "rge.py",
        "--train_manual_datasets", str(manual),
        "--skip_training",
        "--real_u_dir", str(tmp_path / "real_u"),
        "--real_u_is_train_split",
        "--out_dir", str(tmp_path / "out"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rge.main()

    status = json.loads(
        (tmp_path / "out" / "generalization" / "generalization_status.json")
        .read_text(encoding="utf-8")
    )
    # NEW-241: a train-split real directory must never be reported as a
    # held-out manual test.
    assert status["real_u_split_classification"] == "train_split"
    assert status["summary_complete"] is False
    assert status["incomplete_reasons"]
    assert status["eval_dataset_fallback_used"] is True


# --------------------------------------------------------------------------- #
# NEW-246: strict checkpoint loading
# --------------------------------------------------------------------------- #
def test_strict_load_rejects_mismatched_checkpoint(tmp_path, monkeypatch):
    from ultimate_pipeline.perception import eval_sim_labeled

    bad = tmp_path / "bad.pt"
    import torch

    torch.save({"definitely": torch.zeros(3)}, bad)

    with pytest.raises(RuntimeError) as exc:
        eval_sim_labeled.evaluate_model(
            model_path=bad,
            dataset_root=tmp_path / "no_dataset",
            camera="front_left_camera",
            device="cpu",
        )
    assert "STRICT model load failed" in str(exc.value)


def test_strict_load_partial_is_opt_in_and_recorded(tmp_path):
    from ultimate_pipeline.perception import eval_sim_labeled

    import torch

    bad = tmp_path / "bad.pt"
    torch.save({"definitely": torch.zeros(3)}, bad)

    result = eval_sim_labeled.evaluate_model(
        model_path=bad,
        dataset_root=tmp_path / "no_dataset",
        camera="front_left_camera",
        device="cpu",
        allow_partial=True,
    )
    assert result["strict_load_ok"] is False
    assert result["strict_load_error"]
    # Still refuses to invent a score: no paired frames were found.
    assert result["frames_count"] == 0
