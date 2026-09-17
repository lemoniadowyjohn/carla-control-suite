# -*- coding: utf-8 -*-
"""Tests for MainPipeline._validate_stage_capability_contract() wiring.

This is the "runs before pipeline execution" half of the stage capability
contract (the data model + validator itself is tested in
ultimate_pipeline/tests/unit/test_stage_capability_contract.py). Covers:

1. The method is callable directly (no full MainPipeline instantiation
   needed -- it does not touch ``self``) and does not raise against the
   real, current CURRENT_PIPELINE_STAGE_SEQUENCE.
2. It DOES raise, fail-closed, if the declared sequence it validates is
   corrupted (simulating a future regression -- e.g. someone reorders a
   stage or adds a mismatched requires/provides).
3. UP_SKIP_STAGE_CAPABILITY_CONTRACT=1 bypasses the check.
4. run() calls this validation after _mark_stage("start") and before
   _run_internal() (source-level check, since exercising a full run()
   requires live CARLA/settings infrastructure this test suite doesn't
   have).
"""
from __future__ import annotations

import inspect
import os

import pytest

import ultimate_pipeline.contracts.stage_capabilities as contract_mod
import ultimate_pipeline.main_pipeline as main_pipeline_mod
from ultimate_pipeline.contracts.stage_capabilities import (
    StageCapabilitySpec,
    StageDependencyViolation,
)


class _DummyPipeline:
    """Stand-in receiver for the unbound method -- the method under test
    does not read or write any `self` attribute."""


def test_validate_stage_capability_contract_passes_on_real_sequence():
    dummy = _DummyPipeline()
    # Must not raise.
    main_pipeline_mod.MainPipeline._validate_stage_capability_contract(dummy)


def test_validate_stage_capability_contract_fails_closed_on_regression(monkeypatch):
    """Simulate a future regression: a stage is reordered so its
    requirement is no longer satisfied by an earlier stage. The wired
    check must raise, not warn-and-continue."""
    broken_sequence = [
        StageCapabilitySpec("consume", requires=frozenset({"x"})),
        StageCapabilitySpec("produce", provides=frozenset({"x"})),
    ]
    monkeypatch.setattr(
        contract_mod, "CURRENT_PIPELINE_STAGE_SEQUENCE", broken_sequence
    )
    dummy = _DummyPipeline()
    with pytest.raises(StageDependencyViolation):
        main_pipeline_mod.MainPipeline._validate_stage_capability_contract(dummy)


def test_env_skip_bypasses_the_check(monkeypatch):
    broken_sequence = [
        StageCapabilitySpec("consume", requires=frozenset({"x"})),
        StageCapabilitySpec("produce", provides=frozenset({"x"})),
    ]
    monkeypatch.setattr(
        contract_mod, "CURRENT_PIPELINE_STAGE_SEQUENCE", broken_sequence
    )
    monkeypatch.setenv("UP_SKIP_STAGE_CAPABILITY_CONTRACT", "1")
    dummy = _DummyPipeline()
    # Must NOT raise -- the escape hatch is honored.
    main_pipeline_mod.MainPipeline._validate_stage_capability_contract(dummy)


def test_run_calls_validation_after_start_before_run_internal():
    """Source-level check that run() wires the validation call in the
    right place, without needing to execute a full pipeline run (which
    needs live settings/CARLA infra unavailable in this test suite)."""
    source = inspect.getsource(main_pipeline_mod.MainPipeline.run)
    start_idx = source.index('self._mark_stage("start")')
    validate_idx = source.index("self._validate_stage_capability_contract()")
    run_internal_idx = source.index("self._run_internal()")
    assert start_idx < validate_idx < run_internal_idx
