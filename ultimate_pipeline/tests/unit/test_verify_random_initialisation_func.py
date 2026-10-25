#!/usr/bin/env python3
"""CHAT-09 / B2: tests for verify_random_initialisation function behavior.

These tests verify the function itself (not the factory source).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import torch
import torch.nn as nn

# Mock torchvision BEFORE importing rq5_provenance
import builtins
original_import = builtins.__import__

def mock_import(name, *args, **kwargs):
    if name == 'torchvision':
        mock_tv = MagicMock()
        mock_tv.__version__ = '0.15.0'
        mock_tv.models = MagicMock()
        mock_tv.models.segmentation = MagicMock()
        return mock_tv
    return original_import(name, *args, **kwargs)

from unittest.mock import MagicMock, patch

# Apply the mock at module level
builtins.__import__ = mock_import

# Now import the module under test
from ultimate_pipeline.perception.rq5_provenance import verify_random_initialisation, PretrainingContractError


def test_verify_random_initialisation_records_none_args():
    """verify_random_initialisation with weights_backbone=None records None."""
    # Create a simple model for testing
    model = nn.Linear(10, 5)

    result = verify_random_initialisation(model, weights=None, weights_backbone=None)
    assert result["weights_argument"] is None
    assert result["weights_backbone_argument"] is None
    assert "instantiated_state_sha256" in result
    print("PASS: verify_random_initialisation records None args")


def test_verify_random_initialisation_rejects_pretrained_weights():
    """verify_random_initialisation rejects non-None weights."""
    model = nn.Linear(10, 5)
    try:
        verify_random_initialisation(model, weights="pretrained", weights_backbone=None)
        raise AssertionError("Should have raised PretrainingContractError")
    except PretrainingContractError as e:
        assert "weights argument must be None" in str(e)
        print("PASS: verify_random_initialisation rejects non-None weights")


def test_verify_random_initialisation_rejects_pretrained_backbone():
    """verify_random_initialisation rejects non-None weights_backbone."""
    model = nn.Linear(10, 5)
    try:
        verify_random_initialisation(model, weights=None, weights_backbone="IMAGENET1K_V1")
        raise AssertionError("Should have raised PretrainingContractError")
    except PretrainingContractError as e:
        assert "weights_backbone argument must be None" in str(e)
        print("PASS: verify_random_initialisation rejects non-None weights_backbone")


def test_verify_random_initialisation_rejects_both():
    """verify_random_initialisation rejects both non-None."""
    model = nn.Linear(10, 5)
    try:
        verify_random_initialisation(model, weights="pretrained", weights_backbone="IMAGENET1K_V1")
        raise AssertionError("Should have raised PretrainingContractError")
    except PretrainingContractError:
        print("PASS: verify_random_initialisation rejects both non-None")


if __name__ == "__main__":
    test_verify_random_initialisation_records_none_args()
    test_verify_random_initialisation_rejects_pretrained_weights()
    test_verify_random_initialisation_rejects_pretrained_backbone()
    test_verify_random_initialisation_rejects_both()
    print("\n=== B2 verify_random_initialisation tests: ALL PASS ===")