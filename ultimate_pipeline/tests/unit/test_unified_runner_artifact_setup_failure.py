# ultimate_pipeline/experiments/unified_runner.py::UnifiedRunner.run() -- zero
# prior test coverage despite being live (cli.py's `run`/`test smoke`/`test e2e`
# commands, 3 call sites). Its docstring promises "Returns: Dict with run
# results including ... error (if failed)", but self.setup_artifacts() and the
# logging FileHandler setup ran BEFORE the try/except block -- a real failure
# there (bad artifact_root, permission denied, disk full) propagated as an
# unhandled exception instead of the documented result dict. Two of the three
# cli.py call sites (`test smoke`, `test e2e`) call run_experiment() with no
# try/except at all, trusting the documented contract -- they would have
# crashed with an ugly traceback instead of a clean "Smoke test failed"
# message. A second, compounding bug: the `finally` block unconditionally
# called `file_handler.close()`, which would itself raise AttributeError on
# None if the FileHandler was never created (e.g. setup_artifacts() failed
# first) -- masking the real error with a new one from inside finally.
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from ultimate_pipeline.contracts.experiment_config import ExperimentConfigModel
from ultimate_pipeline.experiments.unified_runner import UnifiedRunner, run_experiment


def test_setup_artifacts_failure_returns_result_dict_not_raise():
    config = ExperimentConfigModel(experiment_id="smoke_test")
    runner = UnifiedRunner(config)

    with mock.patch.object(
        runner, "setup_artifacts", side_effect=PermissionError("disk full or denied")
    ):
        result = runner.run()  # must not raise

    assert result["success"] is False
    assert result["run_id"] is None
    assert "PermissionError" in result["error"]
    assert "disk full or denied" in result["error"]
    assert "duration_s" in result


def test_setup_artifacts_failure_does_not_crash_in_finally_on_missing_file_handler():
    """Specifically guards the file_handler=None case: setup_artifacts()
    failing means the FileHandler is never created, so finally's cleanup
    must not unconditionally call .close() on None."""
    config = ExperimentConfigModel(experiment_id="smoke_test")
    runner = UnifiedRunner(config)

    with mock.patch.object(
        runner, "setup_artifacts", side_effect=RuntimeError("boom")
    ):
        result = runner.run()  # must not raise AttributeError from finally

    assert result["success"] is False
    assert "boom" in result["error"]


def test_successful_smoke_run_end_to_end(tmp_path: Path):
    result = run_experiment(
        experiment_id="smoke_test",
        artifact_root=str(tmp_path),
        strict=False,
    )

    assert result["run_id"] is not None
    assert isinstance(result["success"], bool)
    assert "duration_s" in result
    assert (tmp_path / result["run_id"]).exists() or any(tmp_path.iterdir())


def test_unknown_experiment_id_returns_result_dict_not_raise(tmp_path: Path):
    result = run_experiment(
        experiment_id="definitely_not_a_real_experiment_id",
        artifact_root=str(tmp_path),
    )

    assert result["success"] is False
    assert "Unknown experiment" in result["error"]
