# Two related bugs found in the GNN K-sweep/training entrypoints
# (ultimate_pipeline/domain_gap_gnn/{train_map_encoder,run_ksweep}.py), both
# zero prior test coverage:
#
# 1. train_map_encoder.py's checkpoint-save condition was
#    `(epoch + 1) % 10 == 0 or epoch == args.epochs`. `epoch` iterates over
#    `range(args.epochs)` (0-based), so its max value is `args.epochs - 1` --
#    `epoch == args.epochs` can NEVER be true. The intended "always save the
#    final epoch" fallback never fired; for any --epochs not a multiple of
#    10, the actual final (most-trained) model state was silently never
#    written to disk. Masked in the real C21_GNN_AUTHORITATIVE run only
#    because it used the default --epochs=50 (a multiple of 10).
#
# 2. run_ksweep.py's _checkpoint_final_epoch_path() hardcoded
#    "map_encoder_epoch50.pt" regardless of the actual --epochs value used,
#    so re-running with a non-default --epochs would never detect an
#    existing checkpoint and would always retrain from scratch.
#
# 3. Adjacent, same-file, same-root-cause: _resolve_checkpoint() sorted
#    checkpoint paths lexicographically ("epoch100.pt" < "epoch90.pt" as
#    strings), which could pick a less-trained checkpoint as "the latest"
#    once epoch counts cross a digit-width boundary. Not currently
#    reachable (default epochs=50 keeps all saved epochs 2-digit), but
#    fixed while in the area since fix #1 makes non-round final-epoch
#    checkpoints more likely to exist going forward.
from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.domain_gap_gnn.train_map_encoder import _should_save_checkpoint
from ultimate_pipeline.domain_gap_gnn.run_ksweep import (
    _checkpoint_epoch_number,
    _checkpoint_final_epoch_path,
    _resolve_checkpoint,
)


# ---------------------------------------------------------------------------
# train_map_encoder._should_save_checkpoint
# ---------------------------------------------------------------------------


def test_saves_every_10th_epoch():
    # epoch_idx is 0-based; epoch_num 10 -> epoch_idx 9
    assert _should_save_checkpoint(9, total_epochs=50) is True
    assert _should_save_checkpoint(19, total_epochs=50) is True


def test_does_not_save_non_multiple_of_10_mid_training():
    assert _should_save_checkpoint(4, total_epochs=50) is False


def test_always_saves_final_epoch_even_when_not_a_multiple_of_10():
    # total_epochs=45 -> final epoch_idx=44, epoch_num=45 (not a multiple of 10)
    assert _should_save_checkpoint(44, total_epochs=45) is True


def test_final_epoch_that_is_also_a_multiple_of_10_saves_once_correctly():
    # total_epochs=50 -> final epoch_idx=49, epoch_num=50 (multiple of 10 too)
    assert _should_save_checkpoint(49, total_epochs=50) is True


def test_regression_epoch_equals_total_epochs_never_true_pre_fix():
    """Documents the exact pre-fix bug: the old condition compared the
    0-based loop variable directly against total_epochs, which can never
    be true since range(total_epochs) tops out at total_epochs - 1."""
    epoch_idx = 44
    total_epochs = 45
    assert epoch_idx != total_epochs  # the old (broken) condition's LHS/RHS
    # the fixed helper still correctly identifies this as the final epoch:
    assert _should_save_checkpoint(epoch_idx, total_epochs) is True


# ---------------------------------------------------------------------------
# run_ksweep._checkpoint_final_epoch_path
# ---------------------------------------------------------------------------


def test_checkpoint_final_epoch_path_uses_actual_epochs_value(tmp_path):
    assert _checkpoint_final_epoch_path(tmp_path, 30) == tmp_path / "map_encoder_epoch30.pt"
    assert _checkpoint_final_epoch_path(tmp_path, 50) == tmp_path / "map_encoder_epoch50.pt"


# ---------------------------------------------------------------------------
# run_ksweep._checkpoint_epoch_number / _resolve_checkpoint
# ---------------------------------------------------------------------------


def test_checkpoint_epoch_number_parses_trailing_digits(tmp_path):
    assert _checkpoint_epoch_number(Path("map_encoder_epoch30.pt")) == 30
    assert _checkpoint_epoch_number(Path("map_encoder_epoch100.pt")) == 100


def test_resolve_checkpoint_picks_numerically_latest_not_lexicographically(tmp_path):
    for n in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        (tmp_path / f"map_encoder_epoch{n}.pt").touch()

    result = _resolve_checkpoint(tmp_path)

    assert result.name == "map_encoder_epoch100.pt"


def test_resolve_checkpoint_no_candidates_raises(tmp_path):
    with pytest.raises(RuntimeError):
        _resolve_checkpoint(tmp_path)


def test_resolve_checkpoint_two_digit_only_still_correct(tmp_path):
    for n in (10, 20, 30, 40, 50):
        (tmp_path / f"map_encoder_epoch{n}.pt").touch()

    result = _resolve_checkpoint(tmp_path)

    assert result.name == "map_encoder_epoch50.pt"
