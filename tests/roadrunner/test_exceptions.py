"""ultimate_pipeline/roadrunner/exceptions.py -- the two exception types used across the
RoadRunner contract/gate system. Found untested while auditing tests/roadrunner/ coverage
against ultimate_pipeline/roadrunner/'s actual module list (this whole test directory was
itself only discovered today after fixing a pytest.ini testpaths scope gap).
"""
from __future__ import annotations

from ultimate_pipeline.roadrunner.exceptions import (
    RoadRunnerContractError,
    RoadRunnerGateError,
)


def test_roadrunner_contract_error_is_a_value_error():
    assert issubclass(RoadRunnerContractError, ValueError)


def test_roadrunner_gate_error_is_a_contract_error():
    assert issubclass(RoadRunnerGateError, RoadRunnerContractError)


def test_gate_error_can_be_caught_as_contract_error():
    try:
        raise RoadRunnerGateError("release rejected")
    except RoadRunnerContractError as exc:
        assert str(exc) == "release rejected"
    else:
        raise AssertionError("expected RoadRunnerContractError to catch RoadRunnerGateError")
