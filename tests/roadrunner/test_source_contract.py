"""ultimate_pipeline/roadrunner/source_contract.py -- the factory helper that builds a
governed-input SourceDataContract for RoadRunner workflows. Found untested while auditing
tests/roadrunner/ coverage against ultimate_pipeline/roadrunner/'s actual module list.
"""
from __future__ import annotations

import pytest

from ultimate_pipeline.roadrunner.exceptions import RoadRunnerContractError
from ultimate_pipeline.roadrunner.models import AuthorityClass, PathKind, SourceDataContract
from ultimate_pipeline.roadrunner.source_contract import governed_xodr_source


def test_governed_xodr_source_builds_a_source_data_contract():
    contract = governed_xodr_source(
        source_id="ingolstadt_auto",
        path="campaigns/ingolstadt/candidate/map.xodr",
        sha256="a" * 64,
    )
    assert isinstance(contract, SourceDataContract)
    assert contract.source_id == "ingolstadt_auto"
    assert contract.sha256 == "a" * 64
    assert contract.path.kind is PathKind.FILE
    assert contract.path.path == "campaigns/ingolstadt/candidate/map.xodr"


def test_governed_xodr_source_always_uses_governed_input_authority():
    contract = governed_xodr_source(source_id="x", path="a.xodr", sha256="b" * 64)
    assert contract.authority_class is AuthorityClass.GOVERNED_INPUT


def test_governed_xodr_source_rejects_invalid_sha256():
    with pytest.raises(RoadRunnerContractError):
        governed_xodr_source(source_id="x", path="a.xodr", sha256="not_a_real_hash")


def test_governed_xodr_source_rejects_placeholder_source_id():
    with pytest.raises(RoadRunnerContractError):
        governed_xodr_source(source_id="TODO", path="a.xodr", sha256="c" * 64)
