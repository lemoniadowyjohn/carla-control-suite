"""V94 safety regression for the unimplemented lane-geometry refiner.

These tests lock the DISABLED/BLOCKED contract, not ML accuracy. Real GNN
learning and CARLA runtime tests remain NOT_RUN/BLOCKED_DATA.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.ml.lane_gnn_refiner import (
    GNN_GEOMETRY_REFINEMENT_IMPLEMENTED,
    LaneGNNRefiner,
    LaneRefinementBlocked,
    LaneRefinementReceipt,
)


XODR = (
    '<OpenDRIVE><road id="5" junction="-1"><lanes><laneSection s="0">'
    '<left><lane id="1" type="driving"/></left>'
    '<center><lane id="0" type="none"/></center>'
    '<right><lane id="-1" type="driving"/></right>'
    '</laneSection></lanes></road><junction id="10"/></OpenDRIVE>'
)


def _tree():
    return ET.fromstring(XODR)


def test_unconfigured_is_non_authoritative_and_does_not_touch_tree(capsys):
    root = _tree()
    before = ET.tostring(root)
    result = LaneGNNRefiner.run_inplace(root, "")
    assert isinstance(result, LaneRefinementReceipt)
    assert result.status == "DISABLED"
    assert not result and not result.ok and not result.applied
    assert result.release_eligible is False
    assert result.quality_gates_run is False
    assert result.geometry_before_sha256 is None
    assert result.geometry_after_sha256 is None
    assert result.model_sha256 is None
    assert result.policy_version == "lane-gnn-disabled-v1"
    assert ET.tostring(root) == before
    assert capsys.readouterr() == ("", "")
    assert GNN_GEOMETRY_REFINEMENT_IMPLEMENTED is False


def test_disabled_receipt_json_fails_all_success_predicates():
    rec = LaneGNNRefiner.run_inplace(_tree(), None)
    payload = json.loads(json.dumps(rec.to_dict()))
    assert payload["status"] == "DISABLED"
    assert payload["ok"] is False
    assert payload["release_eligible"] is False
    assert payload["quality_gates_run"] is False


def test_disabled_receipt_is_immutable():
    rec = LaneGNNRefiner.run_inplace(_tree(), "")
    with pytest.raises(FrozenInstanceError):
        rec.applied = True


@pytest.mark.parametrize("checkpoint", ["missing.pt", "   ", "not_a_checkpoint", Path("model.pt"), 7])
def test_explicit_model_request_fails_without_tree_mutation(checkpoint):
    root = _tree()
    before = ET.tostring(root)
    with pytest.raises(LaneRefinementBlocked) as e:
        LaneGNNRefiner.run_inplace(root, checkpoint)
    assert e.value.code == "BLOCKED_MODEL_UNVALIDATED"
    assert ET.tostring(root) == before


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf"), -0.01, 1.01, True, "0.7", None])
def test_malformed_threshold_fails_closed(threshold):
    with pytest.raises(LaneRefinementBlocked) as e:
        LaneGNNRefiner.run_inplace(_tree(), "", confidence_thresh=threshold)
    assert e.value.code == "INVALID_THRESHOLD"


@pytest.mark.parametrize("device", ["gpu", "cuda:-1", "cuda:01", "", None, 3])
def test_invalid_device_fails_closed(device):
    with pytest.raises(LaneRefinementBlocked) as e:
        LaneGNNRefiner.run_inplace(_tree(), "", device=device)
    assert e.value.code == "INVALID_DEVICE"


def test_valid_cuda_selector_does_not_initialize_gpu_when_disabled():
    result = LaneGNNRefiner.run_inplace(_tree(), None, device="cuda:0")
    assert result.status == "DISABLED" and not result


def test_model_is_not_deserialized_or_read_even_if_present(tmp_path, monkeypatch):
    ckpt = tmp_path / "untrusted.pt"
    ckpt.write_bytes(b"never-deserialize-this")
    def forbidden(*args, **kwargs):
        raise AssertionError("refiner must not read model contents")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    with pytest.raises(LaneRefinementBlocked, match="BLOCKED_MODEL_UNVALIDATED"):
        LaneGNNRefiner.run_inplace(_tree(), str(ckpt))
    assert ckpt.read_text(encoding="utf-8") == "never-deserialize-this"


def test_parallel_disabled_calls_are_nonmutating():
    root = _tree()
    before = ET.tostring(root)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: LaneGNNRefiner.run_inplace(root, None), range(40)))
    assert len(results) == 40
    assert all(r.status == "DISABLED" and not r for r in results)
    assert ET.tostring(root) == before


def test_explicit_model_request_rejects_without_existing_checkpoint(tmp_path):
    root = _tree()
    missing = tmp_path / "never-created.pt"
    assert not missing.exists()
    with pytest.raises(LaneRefinementBlocked, match="BLOCKED_MODEL_UNVALIDATED"):
        LaneGNNRefiner.run_inplace(root, str(missing))
    assert not missing.exists()
