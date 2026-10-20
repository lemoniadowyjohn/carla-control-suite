"""Task 08 acceptance tests: perception capability and model-truth gating.

Covers T-PERC-01..06 plus the missing-model smoke, the no-fabricated-metrics
regression, the GPU capability fallback, frame mismatch and documentation status.

Offline. No model is loaded, no GPU is used, no inference is faked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.gui.perception.service import (
    FABRICATED_METRICS_FORBIDDEN,
    WEIGHT_SUFFIXES,
    CapabilityState,
    ExperimentVariable,
    ModelSpec,
    Observation,
    ObservationKind,
    PerceptionService,
)


def _service(tmp_path: Path) -> PerceptionService:
    return PerceptionService(search_roots=[tmp_path])


# ================================================================= T-PERC
def test_T_PERC_01_repository_contains_no_model_weights():
    # The governing fact: no *.pt / *.onnx / *.pth / *.engine at HEAD.
    repo = Path(r"F:\wt\carla-gui-integration-20261015")
    if not repo.exists():
        pytest.skip("integration worktree not present")
    found = [p for p in repo.rglob("*")
             if p.suffix.lower() in WEIGHT_SUFFIXES and p.is_file()
             and ".venv" not in p.parts]
    assert found == [], f"unexpected weights found: {found}"


def test_T_PERC_02_missing_model_is_reported_as_MODEL_MISSING(tmp_path):
    service = _service(tmp_path)
    spec = ModelSpec("lane_gnn_refiner", str(tmp_path / "refiner.onnx"),
                     source="ml/lane_gnn_refiner.py is a stub")
    probe = service.probe_model(spec)
    assert probe.state == CapabilityState.MODEL_MISSING.value
    assert probe.usable is False
    assert "stub" in probe.provenance


def test_T_PERC_03_no_fabricated_metrics_are_returned(tmp_path):
    service = _service(tmp_path)
    for metric in sorted(FABRICATED_METRICS_FORBIDDEN):
        result = service.summarise_metric(metric)
        assert result.ok is False
        assert result.value is None
        assert "never promoted" in result.remediation


def test_T_PERC_04_measurements_are_summarised_only_from_real_observations(tmp_path):
    service = _service(tmp_path)
    for index in range(3):
        service.record(Observation(
            sequence=index, frame_id=index, kind=ObservationKind.LIVE.value,
            metric="precision", value=0.8, map_fingerprint="abc123"))
    result = service.summarise_metric("precision")
    assert result.ok is True
    assert result.unwrap()["n"] == 3
    assert abs(result.unwrap()["mean"] - 0.8) < 1e-9

    # unmeasured value stays unmeasured
    service.record(Observation(sequence=9, frame_id=9, kind=ObservationKind.LIVE.value,
                               metric="precision", value=None))
    assert service.summarise_metric("precision").unwrap()["n"] == 3


def test_T_PERC_05_synthetic_and_live_observations_are_separable(tmp_path):
    service = _service(tmp_path)
    service.record(Observation(0, 0, ObservationKind.SYNTHETIC.value, "precision", 0.99))
    service.record(Observation(1, 1, ObservationKind.LIVE.value, "precision", 0.50))
    live = service.summarise_metric("precision", kind=ObservationKind.LIVE.value)
    synthetic = service.summarise_metric("precision", kind=ObservationKind.SYNTHETIC.value)
    assert live.unwrap()["mean"] == 0.50
    assert synthetic.unwrap()["mean"] == 0.99


def test_T_PERC_06_calibration_reprojection_is_disabled_without_pixels(tmp_path):
    service = _service(tmp_path)
    disabled = service.calibration_reprojection(None)
    assert disabled.state == CapabilityState.NOT_MEASURED.value
    assert disabled.usable is False
    assert "cannot be computed" in disabled.detail

    enabled = service.calibration_reprojection([[1.0, 2.0]])
    assert enabled.state == CapabilityState.AVAILABLE.value


def test_gpu_capability_falls_back_and_reports_the_real_reason(tmp_path):
    service = _service(tmp_path)
    probe = service.probe_gpu()
    # The host has a CPU-only torch build; the probe must say so rather than
    # pretending a GPU exists.
    assert probe.state in (CapabilityState.UNSUPPORTED.value,
                           CapabilityState.AVAILABLE.value)
    if probe.state == CapabilityState.UNSUPPORTED.value:
        assert "CUDA" in probe.detail or "not installed" in probe.detail
        assert probe.usable is False
    assert probe.provenance.startswith("checked at runtime")


def test_missing_model_smoke_and_page_mode(tmp_path):
    service = _service(tmp_path)
    assert service.weights_present() == []
    assert service.page_mode() == "DIAGNOSTICS_REPLAY_ONLY"

    (tmp_path / "model.onnx").write_bytes(b"stub")
    assert service.page_mode() == "LIVE"


def test_frame_mismatch_is_detected():
    service = PerceptionService()
    service.record(Observation(0, 10, ObservationKind.LIVE.value, "precision", 0.1))
    service.record(Observation(1, 11, ObservationKind.LIVE.value, "precision", 0.2))
    with pytest.raises(ValueError) as exc:
        service.record(Observation(2, 5, ObservationKind.LIVE.value, "precision", 0.3))
    assert "backwards" in str(exc.value)


def test_frame_gaps_are_reported_as_missing():
    service = PerceptionService()
    for frame_id in (1, 2, 5):
        service.record(Observation(frame_id, frame_id, ObservationKind.LIVE.value,
                                   "precision", 0.1))
    assert service.sync.missing == 2
    assert service.sync.received == 3


def test_unknown_observation_kind_is_refused(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.record(Observation(0, 0, "MADE_UP", "precision", 0.1))


def test_weather_and_traffic_are_variables_not_causal_claims(tmp_path):
    service = _service(tmp_path)
    service.variables.append(ExperimentVariable("weather", "rainy", controlled=False))
    refused = service.causal_claim("weather")
    assert refused.ok is False
    assert "UNCONTROLLED" in refused.reason
    assert "no causal gain" in refused.reason

    service.variables.append(ExperimentVariable("traffic_density", "high", controlled=True))
    assert service.causal_claim("traffic_density").ok is True
    assert service.causal_claim("never_recorded").ok is False

    variable = ExperimentVariable("weather", "rainy", controlled=False)
    assert variable.as_dict()["causal_claim"].startswith("NOT CLAIMED")


def test_documentation_status_is_recorded_truthfully(tmp_path):
    service = _service(tmp_path)
    payload = service.as_dict()
    assert payload["page_mode"] == "DIAGNOSTICS_REPLAY_ONLY"
    assert payload["weights_found"] == []
    assert payload["frame_sync"]["received"] == 0