# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/quality/quality_gates.py.

Live: main_pipeline.py._run_quality_gates_wrapper (line ~2827) imports
run_quality_gates + DRIVABILITY_GATES and hard-fails
(`raise RuntimeError(f"Drivability gates failed: {drivability_failures}")`)
whenever any failed gate name is in DRIVABILITY_GATES -- this is the ONE
enforcement path that fires even when UP_STRICT_QUALITY_GATES is unset.
Zero prior test coverage.

The bug: _try() recorded a crashed gate's failure under `label + "_error"`
(e.g. "xml_integrity_error"), but DRIVABILITY_GATES only contains the bare
name ("xml_integrity"). A gate that crashes with an exception -- as
opposed to running cleanly and returning ok=False -- was silently excluded
from the hard drivability check, even though the same gate's OWN internal
self.fail() calls (when it runs cleanly and finds issues) use the bare
name. Confirmed by isolating: force gate_xml_integrity to raise while
every other gate passes cleanly -- drivability_failures came back empty.
"""
from __future__ import annotations

from unittest import mock
from pathlib import Path

import ultimate_pipeline.quality.quality_gates as qg_mod
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager


def _minimal_xodr(tmp_path: Path) -> Path:
    # Padded past MIN_XODR_SIZE_BYTES so the stub-rejection gate doesn't
    # short-circuit before we reach the gates under test.
    xodr = tmp_path / "probe.xodr"
    xodr.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<OpenDRIVE></OpenDRIVE>\n'
        + ("<!--" + "x" * 10500 + "-->"),
        encoding="utf-8",
    )
    return xodr


def _passthrough(self, *a, **k):
    self.passed("stub")


def test_stub_xodr_below_minimum_size_is_rejected(tmp_path):
    tiny = tmp_path / "tiny.xodr"
    tiny.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    failures = qg_mod.run_quality_gates(str(tiny))
    assert failures["xodr_minimum_size"]["ok"] is False


def test_missing_file_reports_stat_error():
    failures = qg_mod.run_quality_gates(str(Path("does_not_exist_at_all.xodr")))
    assert failures["xodr_minimum_size"]["ok"] is False


def test_crashed_xml_integrity_gate_is_recorded_under_the_bare_drivability_name(
    tmp_path,
):
    xodr = _minimal_xodr(tmp_path)

    def _boom(self, xodr_path):
        raise RuntimeError("simulated crash")

    with mock.patch.object(QualityGateManager, "gate_xml_integrity", _boom), \
        mock.patch.object(QualityGateManager, "gate_junction_integrity", lambda self, *a, **k: {"ok": True}), \
        mock.patch.object(QualityGateManager, "gate_carla_opendrive_compat", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_xodr_strict_carla", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_elevation_smoothness", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_physics_feasibility", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_randomness_entropy", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_semantic_overlap", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_collision_mesh", _passthrough):
        failures = qg_mod.run_quality_gates(str(xodr))

    assert "xml_integrity" in failures, (
        "a crashed drivability gate must be recorded under its bare name so "
        "DRIVABILITY_GATES membership actually catches it"
    )
    drivability_failures = set(failures.keys()) & qg_mod.DRIVABILITY_GATES
    assert "xml_integrity" in drivability_failures, (
        "main_pipeline.py's hard drivability check must see this failure"
    )


def test_crashed_external_libopendrive_validator_is_recorded_under_bare_name(
    tmp_path, monkeypatch
):
    xodr = _minimal_xodr(tmp_path)

    with mock.patch.object(QualityGateManager, "gate_xml_integrity", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_junction_integrity", lambda self, *a, **k: {"ok": True}), \
        mock.patch.object(QualityGateManager, "gate_carla_opendrive_compat", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_xodr_strict_carla", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_elevation_smoothness", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_physics_feasibility", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_randomness_entropy", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_semantic_overlap", _passthrough), \
        mock.patch.object(QualityGateManager, "gate_collision_mesh", _passthrough):

        import ultimate_pipeline.config.settings as settings_mod

        monkeypatch.setattr(
            settings_mod.SETTINGS, "ENABLE_LIBOPENDRIVE_VALIDATION", True, raising=False
        )

        def _boom_import(*a, **k):
            raise RuntimeError("external validator crashed")

        with mock.patch(
            "ultimate_pipeline.quality.check_external_libopendrive.run_external_libopendrive_validation",
            _boom_import,
        ):
            failures = qg_mod.run_quality_gates(str(xodr))

    assert "external_libopendrive" in failures
    drivability_failures = set(failures.keys()) & qg_mod.DRIVABILITY_GATES
    assert "external_libopendrive" in drivability_failures
