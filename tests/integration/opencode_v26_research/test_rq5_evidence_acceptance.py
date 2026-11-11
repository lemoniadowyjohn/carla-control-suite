#!/usr/bin/env python3
"""
RQ5 Evidence Acceptance Tests — V26-B Scientific Acceptance

Independent validation tests for RQ5 generalization evidence acceptance criteria.
Codex W-B owns production implementation (F:/carla-worktrees/rq5-sightb-20261009).
OpenCode provides read-only independent validation.

No live CARLA, no model training, no threshold changes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

# ---------------------------------------------------------------------------
# Synthetic RQ5 Test Fixtures
# ---------------------------------------------------------------------------

def _clean_rq5_result() -> Dict[str, Any]:
    """Clean RQ5 execution result - all criteria met."""
    return {
        "training_dataset": "dataset_A",
        "target_dataset": "dataset_B",
        "split_identity": "train_A_eval_B",
        "checkpoint_sha": "abc123def456",
        "class_map_version": "v20261001",
        "source_git_sha": "dfa6ffff07c38d0cc09507c52b3328900ef2d900",
        "metrics": {"accuracy": 0.85, "f1": 0.82, "mIoU": 0.78},
        "output_root": "/results/rq5/run_001",
        "target_map_id": "map_B",
        "sample_counts": {"train": 100, "eval": 50, "test": 25},
        "seed": 42,
        "status": "COMPLETED",
        "exit_code": 0
    }

def _wrong_training_dataset() -> Dict[str, Any]:
    """Defect 1: Training uses target dataset."""
    r = _clean_rq5_result()
    r["training_dataset"] = "dataset_B"  # Should be A
    r["target_dataset"] = "dataset_B"   # Same!
    return r

def _wrong_target_dataset() -> Dict[str, Any]:
    """Defect 2: Eval uses training data."""
    r = _clean_rq5_result()
    r["target_dataset"] = "dataset_A"  # Should be B
    return r

def _same_split_for_independent_eval() -> Dict[str, Any]:
    """Defect 3: Train and eval use identical split."""
    r = _clean_rq5_result()
    r["split_identity"] = "train_A_eval_A"  # Same!
    return r

def _wrong_checkpoint_identity() -> Dict[str, Any]:
    """Defect 4: Checkpoint SHA mismatch."""
    r = _clean_rq5_result()
    r["checkpoint_sha"] = "wrong_sha_789"
    return r

def _wrong_class_map_version() -> Dict[str, Any]:
    """Defect 5: Sensor class mapping version changed."""
    r = _clean_rq5_result()
    r["class_map_version"] = "v20250101"  # Old version
    return r

def _invalid_source_revision() -> Dict[str, Any]:
    """Defect 6: Git SHA not matching contract."""
    r = _clean_rq5_result()
    r["source_git_sha"] = "wrong_sha_0000000000000000000000000000000000000000"
    return r

def _missing_metric() -> Dict[str, Any]:
    """Defect 7: No evaluation output produced."""
    r = _clean_rq5_result()
    r.pop("metrics", None)
    return r

def _nan_infinity_metric() -> Dict[str, Any]:
    """Defect 8: Metric computation overflow."""
    r = _clean_rq5_result()
    r["metrics"]["accuracy"] = float('nan')
    return r

def _empty_result() -> Dict[str, Any]:
    """Defect 9: Zero-length output array."""
    r = _clean_rq5_result()
    r["metrics"] = {}
    r["sample_counts"] = {"train": 0, "eval": 0, "test": 0}
    return r

def _failed_execution_stale_receipt() -> Dict[str, Any]:
    """Defect 10: Failed execution with stale success receipt."""
    r = _clean_rq5_result()
    r["exit_code"] = 1  # FAILED
    r["status"] = "FAILED"
    # But receipt claims success (stale)
    return r

def _incorrect_output_root() -> Dict[str, Any]:
    """Defect 11: Output directory wrong path."""
    r = _clean_rq5_result()
    r["output_root"] = "/wrong/path/results"
    return r

def _missing_target_map_identity() -> Dict[str, Any]:
    """Defect 12: Target map not identified."""
    r = _clean_rq5_result()
    r.pop("target_map_id", None)
    return r

def _duplicate_contaminated_samples() -> Dict[str, Any]:
    """Defect 13: Same sample in multiple splits."""
    r = _clean_rq5_result()
    r["contaminated"] = True
    return r

def _missing_reproducibility_seed() -> Dict[str, Any]:
    """Defect 14: Seed not recorded or differs."""
    r = _clean_rq5_result()
    r.pop("seed", None)
    return r

def _partial_result_reported_complete() -> Dict[str, Any]:
    """Defect 15: Intermediate result claimed as final."""
    r = _clean_rq5_result()
    r["status"] = "INTERMEDIATE"
    return r

# ---------------------------------------------------------------------------
# Mock production validator (read-only)
# ---------------------------------------------------------------------------

class MockRQ5Validator:
    """Mock of RQ5 evidence acceptance validation."""

    # Expected contract values
    EXPECTED_SOURCE_SHA = "dfa6ffff07c38d0cc09507c52b3328900ef2d900"
    EXPECTED_CLASS_MAP_VERSION = "v20261001"
    EXPECTED_CHECKPOINT_SHA = "abc123def456"
    EXPECTED_TRAINING_DATASET = "dataset_A"
    EXPECTED_TARGET_DATASET = "dataset_B"
    EXPECTED_OUTPUT_ROOT_PREFIX = "/results/rq5/"

    @staticmethod
    def validate_training_dataset(result: Dict) -> bool:
        """Training must use correct dataset (not target)."""
        return (result.get("training_dataset") == MockRQ5Validator.EXPECTED_TRAINING_DATASET and
                result.get("training_dataset") != result.get("target_dataset"))

    @staticmethod
    def validate_target_dataset(result: Dict) -> bool:
        """Target (eval) must use correct dataset."""
        return result.get("target_dataset") == MockRQ5Validator.EXPECTED_TARGET_DATASET

    @staticmethod
    def validate_independent_eval_split(result: Dict) -> bool:
        """Train and eval must use different splits."""
        split_id = result.get("split_identity", "")
        return "train_A_eval_B" in split_id or "train_B_eval_A" in split_id

    @staticmethod
    def validate_checkpoint_identity(result: Dict) -> bool:
        """Checkpoint must match expected SHA."""
        return result.get("checkpoint_sha") == MockRQ5Validator.EXPECTED_CHECKPOINT_SHA

    @staticmethod
    def validate_class_map_version(result: Dict) -> bool:
        """Class map version must match expected."""
        return result.get("class_map_version") == MockRQ5Validator.EXPECTED_CLASS_MAP_VERSION

    @staticmethod
    def validate_source_revision(result: Dict) -> bool:
        """Source Git SHA must match contract."""
        return result.get("source_git_sha") == MockRQ5Validator.EXPECTED_SOURCE_SHA

    @staticmethod
    def validate_metrics_present(result: Dict) -> bool:
        """Metrics must be present and non-empty."""
        metrics = result.get("metrics")
        return isinstance(metrics, dict) and len(metrics) > 0

    @staticmethod
    def validate_metric_finiteness(result: Dict) -> Tuple[bool, List[str]]:
        """All metrics must be finite numbers."""
        metrics = result.get("metrics", {})
        invalid = []
        for key, value in metrics.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                invalid.append(key)
        return len(invalid) == 0, invalid

    @staticmethod
    def validate_non_empty_result(result: Dict) -> bool:
        """Result must have non-zero sample counts."""
        counts = result.get("sample_counts", {})
        return sum(counts.values()) > 0

    @staticmethod
    def validate_exit_code_gate(result: Dict) -> bool:
        """Failed execution cannot claim PASS."""
        exit_code = result.get("exit_code", 1)
        status = result.get("status", "FAILED")
        return exit_code == 0 and status == "COMPLETED"

    @staticmethod
    def validate_output_root(result: Dict) -> bool:
        """Output must be in correct directory."""
        root = result.get("output_root", "")
        return root.startswith(MockRQ5Validator.EXPECTED_OUTPUT_ROOT_PREFIX)

    @staticmethod
    def validate_target_map_identity(result: Dict) -> bool:
        """Target map must be identified."""
        return "target_map_id" in result and result["target_map_id"] is not None

    @staticmethod
    def validate_no_contamination(result: Dict) -> bool:
        """No duplicate/contaminated samples."""
        return not result.get("contaminated", False)

    @staticmethod
    def validate_reproducibility_seed(result: Dict) -> bool:
        """Seed must be recorded and match contract."""
        return "seed" in result and result["seed"] == 42

    @staticmethod
    def validate_complete_result(result: Dict) -> bool:
        """Result must be complete, not intermediate."""
        return result.get("status") == "COMPLETED"

    @staticmethod
    def evaluate_all_acceptance(result: Dict) -> Tuple[bool, List[str]]:
        """Evaluate all 15 acceptance criteria."""
        checks = [
            ("training_dataset", MockRQ5Validator.validate_training_dataset),
            ("target_dataset", MockRQ5Validator.validate_target_dataset),
            ("independent_eval_split", MockRQ5Validator.validate_independent_eval_split),
            ("checkpoint_identity", MockRQ5Validator.validate_checkpoint_identity),
            ("class_map_version", MockRQ5Validator.validate_class_map_version),
            ("source_revision", MockRQ5Validator.validate_source_revision),
            ("metrics_present", MockRQ5Validator.validate_metrics_present),
            ("metric_finiteness", lambda r: MockRQ5Validator.validate_metric_finiteness(r)[0]),
            ("non_empty_result", MockRQ5Validator.validate_non_empty_result),
            ("exit_code_gate", MockRQ5Validator.validate_exit_code_gate),
            ("output_root", MockRQ5Validator.validate_output_root),
            ("target_map_identity", MockRQ5Validator.validate_target_map_identity),
            ("no_contamination", MockRQ5Validator.validate_no_contamination),
            ("reproducibility_seed", MockRQ5Validator.validate_reproducibility_seed),
            ("complete_result", MockRQ5Validator.validate_complete_result),
        ]

        failed = []
        for name, check in checks:
            if not check(result):
                failed.append(name)

        return len(failed) == 0, failed


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestRQ5EvidenceAcceptance:
    """Test suite for RQ5 evidence acceptance criteria."""

    def test_clean_result_accepted(self):
        """Clean result passes all acceptance criteria."""
        result = _clean_rq5_result()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert accepted
        assert failed == []

    # Core defect detection tests
    def test_wrong_training_dataset_rejected(self):
        """Training on target dataset must be rejected."""
        result = _wrong_training_dataset()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "training_dataset" in failed

    def test_wrong_target_dataset_rejected(self):
        """Eval on training data must be rejected."""
        result = _wrong_target_dataset()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "target_dataset" in failed

    def test_same_split_rejected(self):
        """Same split for train/eval must be rejected."""
        result = _same_split_for_independent_eval()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "independent_eval_split" in failed

    def test_wrong_checkpoint_rejected(self):
        """Wrong checkpoint SHA must be rejected."""
        result = _wrong_checkpoint_identity()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "checkpoint_identity" in failed

    def test_wrong_class_map_version_rejected(self):
        """Wrong class map version must be rejected."""
        result = _wrong_class_map_version()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "class_map_version" in failed

    def test_invalid_source_revision_rejected(self):
        """Wrong Git SHA must be rejected."""
        result = _invalid_source_revision()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "source_revision" in failed

    def test_missing_metrics_rejected(self):
        """Missing metrics must be rejected."""
        result = _missing_metric()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "metrics_present" in failed

    def test_nan_infinity_rejected(self):
        """NaN/Inf metrics must be rejected."""
        result = _nan_infinity_metric()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "metric_finiteness" in failed

    def test_empty_result_rejected(self):
        """Zero samples must be rejected."""
        result = _empty_result()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "non_empty_result" in failed

    def test_failed_execution_cannot_claim_pass(self):
        """FAILED exit code cannot claim PASS."""
        result = _failed_execution_stale_receipt()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "exit_code_gate" in failed

    def test_incorrect_output_root_rejected(self):
        """Wrong output directory must be rejected."""
        result = _incorrect_output_root()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "output_root" in failed

    def test_missing_target_map_identity_rejected(self):
        """Unidentified target map must be rejected."""
        result = _missing_target_map_identity()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "target_map_identity" in failed

    def test_contaminated_samples_rejected(self):
        """Duplicate samples must be rejected."""
        result = _duplicate_contaminated_samples()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "no_contamination" in failed

    def test_missing_seed_rejected(self):
        """Missing seed must be rejected."""
        result = _missing_reproducibility_seed()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "reproducibility_seed" in failed

    def test_partial_result_rejected(self):
        """Intermediate result must not be accepted as final."""
        result = _partial_result_reported_complete()
        accepted, failed = MockRQ5Validator.evaluate_all_acceptance(result)
        assert not accepted
        assert "complete_result" in failed

    # Individual validator tests
    def test_validate_training_dataset_isolated(self):
        """Isolated test for training dataset validation."""
        assert MockRQ5Validator.validate_training_dataset(_clean_rq5_result())
        assert not MockRQ5Validator.validate_training_dataset(_wrong_training_dataset())

    def test_validate_checkpoint_identity_isolated(self):
        """Isolated test for checkpoint identity."""
        assert MockRQ5Validator.validate_checkpoint_identity(_clean_rq5_result())
        assert not MockRQ5Validator.validate_checkpoint_identity(_wrong_checkpoint_identity())

    def test_validate_exit_code_gate_isolated(self):
        """Isolated test for exit code gate."""
        assert MockRQ5Validator.validate_exit_code_gate(_clean_rq5_result())
        assert not MockRQ5Validator.validate_exit_code_gate(_failed_execution_stale_receipt())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])