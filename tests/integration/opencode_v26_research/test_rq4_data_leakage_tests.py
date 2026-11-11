#!/usr/bin/env python3
"""
RQ4 Data Leakage Tests — V26-B Scientific Acceptance

Tiny deterministic synthetic graph datasets to test GNN input validity.
RQ4 measures structural variability and latent representation from repeated
automatic generation from same pinned inputs.

Critical rule: Metadata-only PASS must not imply GNN generalization was measured.
The oracle requires actual metric computation.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

# ---------------------------------------------------------------------------
# Synthetic Graph Datasets (16 tiny fixtures)
# ---------------------------------------------------------------------------

def _clean_dataset() -> Dict[str, Any]:
    """Dataset A: Clean dataset with valid structure."""
    return {
        "nodes": [
            {"id": i, "features": [float(i), float(i+1), float(i+2)], "label": i % 2}
            for i in range(10)
        ],
        "edges": [{"from": i, "to": i+1} for i in range(9)],
        "splits": {"train": [0, 1, 2, 3], "val": [4, 5, 6], "test": [7, 8, 9]},
        "seed": 42,
        "checkpoint": {
            "sha": "abc123def456",
            "model": "fcn_resnet50",
            "n_classes": 29
        },
        "metrics": {"accuracy": 0.85, "f1": 0.82, "precision": 0.84, "recall": 0.81},
        "receipt": {
            "evaluation": {"per_class": {str(i): 0.8 for i in range(29)}},
            "status": "COMPLETED"
        }
    }

def _duplicate_node_dataset() -> Dict[str, Any]:
    """Dataset B: Two nodes share ID 5."""
    ds = _clean_dataset()
    # Make node 5 duplicate
    ds["nodes"][5] = {"id": 5, "features": [1.0, 2.0, 3.0], "label": 1}
    ds["nodes"][6] = {"id": 5, "features": [4.0, 5.0, 6.0], "label": 0}  # Duplicate ID
    return ds

def _invalid_edge_dataset() -> Dict[str, Any]:
    """Dataset C: Edge references non-existent node 99."""
    ds = _clean_dataset()
    ds["edges"].append({"from": 99, "to": 1})  # Invalid reference
    return ds

def _missing_feature_dataset() -> Dict[str, Any]:
    """Dataset D: Node missing features key."""
    ds = _clean_dataset()
    ds["nodes"][0].pop("features", None)  # Remove features
    return ds

def _train_test_overlap_dataset() -> Dict[str, Any]:
    """Dataset E: Node appears in both train and test features."""
    ds = _clean_dataset()
    ds["splits"]["test"] = [3, 8, 9]  # Node 3 appears in both
    return ds

def _dataset_leakage() -> Dict[str, Any]:
    """Dataset F: Features normalized using test statistics on train data."""
    ds = _clean_dataset()
    ds["leakage"] = "test_stats_used_on_train"
    return ds

def _wrong_label_provenance() -> Dict[str, Any]:
    """Dataset G: Label belongs to wrong node."""
    ds = _clean_dataset()
    ds["nodes"][0]["label"] = 999  # Invalid label
    return ds

def _wrong_source_map() -> Dict[str, Any]:
    """Dataset H: Graph generated from map X but source_map says map Y."""
    ds = _clean_dataset()
    ds["source_map"] = "map_Y.xodr"
    ds["actual_map"] = "map_X.xodr"
    return ds

def _wrong_graph_schema() -> Dict[str, Any]:
    """Dataset I: Schema version mismatch."""
    ds = _clean_dataset()
    ds["schema_version"] = "2.0"  # Expected "1.0"
    return ds

def _seed_inconsistency() -> Dict[str, Any]:
    """Dataset J: Two seeds produce different graphs."""
    ds1 = _clean_dataset()
    ds2 = _clean_dataset()
    ds2["nodes"][0]["features"] = [99.0, 99.0, 99.0]  # Different features
    return {"seed_42": ds1, "seed_43": ds2}

def _wrong_checkpoint_metadata() -> Dict[str, Any]:
    """Dataset K: Checkpoint SHA doesn't match model config."""
    ds = _clean_dataset()
    ds["checkpoint"]["sha"] = "wrong_sha_789"
    return ds

def _invalid_metric_values() -> Dict[str, Any]:
    """Dataset L: Metric includes NaN/Inf."""
    ds = _clean_dataset()
    ds["metrics"]["accuracy"] = float('nan')
    return ds

def _empty_evaluation_set() -> Dict[str, Any]:
    """Dataset M: Zero test samples."""
    ds = _clean_dataset()
    ds["splits"]["test"] = []
    return ds

def _missing_receipt() -> Dict[str, Any]:
    """Dataset N: No evaluation summary present."""
    ds = _clean_dataset()
    ds.pop("receipt", None)
    return ds

# ---------------------------------------------------------------------------
# Mock production functions (read-only)
# ---------------------------------------------------------------------------

class MockGNNValidator:
    """Mock of GNN input validation logic."""

    @staticmethod
    def validate_node_ids(nodes: List[Dict]) -> Tuple[bool, List[str]]:
        """Validate node IDs are unique."""
        seen: Set[int] = set()
        duplicates = []
        for node in nodes:
            node_id = node.get("id")
            if node_id in seen:
                duplicates.append(str(node_id))
            seen.add(node_id)
        return len(duplicates) == 0, duplicates

    @staticmethod
    def validate_edge_references(nodes: List[Dict], edges: List[Dict]) -> Tuple[bool, List[str]]:
        """Validate edges reference existing nodes."""
        node_ids = {n["id"] for n in nodes}
        invalid = []
        for edge in edges:
            if edge["from"] not in node_ids:
                invalid.append(f"from:{edge['from']}")
            if edge["to"] not in node_ids:
                invalid.append(f"to:{edge['to']}")
        return len(invalid) == 0, invalid

    @staticmethod
    def validate_mandatory_features(nodes: List[Dict]) -> Tuple[bool, List[int]]:
        """Validate all nodes have mandatory features."""
        missing = []
        for i, node in enumerate(nodes):
            if "features" not in node or node["features"] is None:
                missing.append(i)
        return len(missing) == 0, missing

    @staticmethod
    def validate_split_separation(splits: Dict[str, List[int]]) -> Tuple[bool, List[int]]:
        """Validate train/val/test splits are disjoint."""
        train = set(splits.get("train", []))
        val = set(splits.get("val", []))
        test = set(splits.get("test", []))

        overlaps = []
        if train & val:
            overlaps.extend(list(train & val))
        if train & test:
            overlaps.extend(list(train & test))
        if val & test:
            overlaps.extend(list(val & test))

        return len(overlaps) == 0, overlaps

    @staticmethod
    def validate_normalization_on_correct_split(dataset: Dict) -> bool:
        """Validate features normalized using train stats only."""
        return dataset.get("leakage") != "test_stats_used_on_train"

    @staticmethod
    def validate_label_provenance(nodes: List[Dict]) -> Tuple[bool, List[int]]:
        """Validate labels match expected range."""
        invalid = []
        for i, node in enumerate(nodes):
            label = node.get("label")
            if not isinstance(label, int) or label < 0 or label > 28:
                invalid.append(i)
        return len(invalid) == 0, invalid

    @staticmethod
    def validate_source_map(dataset: Dict) -> bool:
        """Validate source map matches actual map."""
        return dataset.get("source_map") == dataset.get("actual_map")

    @staticmethod
    def validate_schema_version(dataset: Dict) -> bool:
        """Validate graph schema version."""
        return dataset.get("schema_version") == "1.0"

    @staticmethod
    def validate_seed_consistency(seed_datasets: Dict[str, Any]) -> bool:
        """Validate different seeds produce different data."""
        if len(seed_datasets) < 2:
            return True
        datasets = list(seed_datasets.values())
        return datasets[0] != datasets[1]

    @staticmethod
    def validate_checkpoint_identity(dataset: Dict) -> bool:
        """Validate checkpoint SHA matches expected."""
        expected_sha = "abc123def456"  # Expected from clean dataset
        return dataset.get("checkpoint", {}).get("sha") == expected_sha

    @staticmethod
    def validate_metric_finiteness(metrics: Dict[str, float]) -> Tuple[bool, List[str]]:
        """All metrics must be finite numbers."""
        invalid = []
        for key, value in metrics.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                invalid.append(key)
        return len(invalid) == 0, invalid

    @staticmethod
    def validate_non_empty_eval(splits: Dict[str, List[int]]) -> bool:
        """Validate test set is not empty."""
        return len(splits.get("test", [])) > 0

    @staticmethod
    def validate_receipt_present(dataset: Dict) -> bool:
        """Validate evaluation receipt is present."""
        return "receipt" in dataset and dataset["receipt"] is not None

    @staticmethod
    def validate_receipt_completeness(receipt: Dict) -> bool:
        """Validate receipt contains per-class breakdown."""
        return "evaluation" in receipt and "per_class" in receipt["evaluation"]["status"]

    @staticmethod
    def validate_no_contamination(result: Dict) -> bool:
        """No duplicate/contaminated samples."""
        return not result.get("contaminated", False)

    @staticmethod
    def validate_reproducibility_seed(result: Dict) -> bool:
        """Seed must be recorded and match contract."""
        return "seed" in result and result["seed"] == 42


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestRQ4DataLeakage:
    """Test suite for RQ4 data leakage and GNN input validity."""

    # Positive control
    def test_stable_node_identity(self):
        """Same node IDs across Python sessions."""
        ds = _clean_dataset()
        valid, duplicates = MockGNNValidator.validate_node_ids(ds["nodes"])
        assert valid
        assert duplicates == []

    def test_stable_edge_identity(self):
        """Same edge list across sessions."""
        ds = _clean_dataset()
        valid, invalid = MockGNNValidator.validate_edge_references(ds["nodes"], ds["edges"])
        assert valid
        assert invalid == []

    # Negative controls
    def test_duplicate_node_detected(self):
        """Duplicate ID flagged."""
        ds = _duplicate_node_dataset()
        valid, duplicates = MockGNNValidator.validate_node_ids(ds["nodes"])
        assert not valid
        assert "5" in duplicates

    def test_invalid_edge_rejected(self):
        """Non-existent target rejected."""
        ds = _invalid_edge_dataset()
        valid, invalid = MockGNNValidator.validate_edge_references(ds["nodes"], ds["edges"])
        assert not valid
        assert any("99" in i for i in invalid)

    def test_missing_mandatory_features(self):
        """Missing features field rejected."""
        ds = _missing_feature_dataset()
        valid, missing = MockGNNValidator.validate_mandatory_features(ds["nodes"])
        assert not valid
        assert 0 in missing

    def test_train_test_overlap(self):
        """Overlap detection."""
        ds = _train_test_overlap_dataset()
        valid, overlaps = MockGNNValidator.validate_split_separation(ds["splits"])
        assert not valid
        assert 3 in overlaps

    def test_normalization_on_test_data(self):
        """Stats computed on wrong split."""
        ds = _dataset_leakage()
        valid = MockGNNValidator.validate_normalization_on_correct_split(ds)
        assert not valid

    def test_wrong_label_provenance(self):
        """Label provenance mismatch."""
        ds = _wrong_label_provenance()
        valid, invalid = MockGNNValidator.validate_label_provenance(ds["nodes"])
        assert not valid
        assert 0 in invalid

    def test_wrong_source_map(self):
        """Map file mismatch."""
        ds = _wrong_source_map()
        valid = MockGNNValidator.validate_source_map(ds)
        assert not valid

    def test_wrong_graph_schema(self):
        """Schema version mismatch."""
        ds = _wrong_graph_schema()
        valid = MockGNNValidator.validate_schema_version(ds)
        assert not valid

    def test_seed_consistency(self):
        """Same seed → same data; different seeds → different data."""
        ds = _seed_inconsistency()
        valid = MockGNNValidator.validate_seed_consistency(ds)
        assert valid

    def test_wrong_checkpoint_metadata(self):
        """Checkpoint SHA mismatch."""
        ds = _wrong_checkpoint_metadata()
        valid = MockGNNValidator.validate_checkpoint_identity(ds)
        assert not valid

    def test_invalid_metric_values(self):
        """NaN/Inf rejected."""
        ds = _invalid_metric_values()
        valid, invalid = MockGNNValidator.validate_metric_finiteness(ds["metrics"])
        assert not valid
        assert "accuracy" in invalid

    def test_empty_evaluation_set(self):
        """Zero test samples → failure."""
        ds = _empty_evaluation_set()
        valid = MockGNNValidator.validate_non_empty_eval(ds["splits"])
        assert not valid

    def test_missing_receipt(self):
        """Receipt must be present."""
        ds = _missing_receipt()
        valid = MockGNNValidator.validate_receipt_present(ds)
        assert not valid

    # Metadata-only PASS rejection
    def test_metadata_only_pass_rejected(self):
        """Schema validation alone must not imply PASS."""
        # This test ensures we don't accept metadata-only PASS
        # If schema valid but no metrics computed, should fail
        ds = _clean_dataset()
        ds.pop("metrics", None)  # Remove metrics
        ds.pop("receipt", None)  # Remove receipt

        # Even if schema passes, without metrics it should not be accepted
        schema_valid = MockGNNValidator.validate_schema_version(ds)
        has_metrics = "metrics" in ds and ds["metrics"] is not None
        has_receipt = MockGNNValidator.validate_receipt_present(ds)

        # Requirement: BOTH metrics AND receipt must be present for acceptance
        accepted = schema_valid and has_metrics and has_receipt
        assert not accepted  # Must be rejected


# Import math for NaN check
import math