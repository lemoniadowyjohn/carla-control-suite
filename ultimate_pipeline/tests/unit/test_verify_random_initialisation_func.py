#!/usr/bin/env python3
"""B2: behaviour tests for verify_random_initialisation.

L1-L2 review fix (MINOR-10): this file previously replaced
``builtins.__import__`` with a MagicMock-torchvision hook that was never
restored, corrupting other test files in the same pytest session.  The
project venv has real torchvision, so no mocking is needed: import
directly and rest assured the hook can never leak.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import torch
import torch.nn as nn

from ultimate_pipeline.perception.rq5_provenance import (
    verify_random_initialisation, PretrainingContractError,
)


def _small_model() -> nn.Module:
    return nn.Linear(10, 5)


def test_records_none_args():
    result = verify_random_initialisation(_small_model(), weights=None, weights_backbone=None)
    assert result["weights_argument"] is None
    assert result["weights_backbone_argument"] is None
    assert "instantiated_state_sha256" in result
    assert result["fingerprinted_tensors"] > 0
    print("PASS: records None args")


def test_rejects_pretrained_weights():
    try:
        verify_random_initialisation(_small_model(), weights="pretrained", weights_backbone=None)
        raise AssertionError("Should have raised PretrainingContractError")
    except PretrainingContractError as e:
        assert "weights argument must be None" in str(e)
    print("PASS: rejects non-None weights")


def test_rejects_pretrained_backbone():
    try:
        verify_random_initialisation(_small_model(), weights=None, weights_backbone="IMAGENET1K_V1")
        raise AssertionError("Should have raised PretrainingContractError")
    except PretrainingContractError as e:
        assert "weights_backbone argument must be None" in str(e)
    print("PASS: rejects non-None weights_backbone")


def test_rejects_both():
    try:
        verify_random_initialisation(_small_model(), weights="pretrained", weights_backbone="IMAGENET1K_V1")
        raise AssertionError("Should have raised PretrainingContractError")
    except PretrainingContractError:
        pass
    print("PASS: rejects both non-None")


def test_fingerprint_is_reproducible_under_same_state():
    model = _small_model()
    with torch.no_grad():
        for p in model.parameters():
            p.fill_(0.5)
    a = verify_random_initialisation(model, weights=None, weights_backbone=None)
    b = verify_random_initialisation(model, weights=None, weights_backbone=None)
    assert a["instantiated_state_sha256"] == b["instantiated_state_sha256"]
    print("PASS: fingerprint deterministic for identical state")
