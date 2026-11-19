#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ultimate_pipeline.quality.quality_gates

Stable orchestration entrypoint for post-pipeline quality gates.

This patch adds an **optional external validation gate** using libOpenDRIVE:
- Controlled by SETTINGS.ENABLE_LIBOPENDRIVE_VALIDATION
- Strictness controlled by SETTINGS.LIBOPENDRIVE_VALIDATION_STRICT
- Safe fallback (skip) when binary not present

MainPipeline expects:
    from ultimate_pipeline.quality.quality_gates import run_quality_gates
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

MIN_XODR_SIZE_BYTES = 10_000  # Minimum bytes for a real road-network XODR; stubs are ~796 bytes


DRIVABILITY_GATES = {
    "xml_integrity",
    "junction_integrity",
    "lane_link_targets",
    "carla_opendrive_compat",
    "xodr_strict_carla",
    # external validator (optional)
    "external_libopendrive",
}

#: Hard-stop gates that fire BEFORE the normal sweep (missing/unreadable file,
#: unparseable XML, unusable gate manager).  NEW-341: they are failures by
#: construction and must be treated as blocking by every consumer -- previously
#: they were returned to a caller that only intersected with DRIVABILITY_GATES,
#: so ``xml_parse``/``quality_gate_manager_import`` were silently non-blocking.
TRANSPORT_GATES = frozenset(
    {
        "xodr_minimum_size",
        "xml_parse",
        "quality_gate_manager_import",
        "xodr_identity_changed",
    }
)

#: Every gate name a consumer must treat as blocking when it appears in the
#: returned failure mapping.
BLOCKING_GATE_NAMES = frozenset(DRIVABILITY_GATES) | TRANSPORT_GATES


class QualityGateInputError(RuntimeError):
    """The input was unsafe or changed while gate reports were produced."""


def _resolve_vreport(vreport: Optional[object]) -> object:
    if vreport is not None:
        return vreport
    try:
        from ultimate_pipeline.core.validation_report import ValidationReport

        return ValidationReport()
    except Exception:

        class _MiniVReport:
            def __init__(self) -> None:
                self.data: Dict[str, Any] = {}

            def add(self, section: str, key: str, value: Any) -> None:
                self.data.setdefault(section, {})[key] = value

            def add_dict(self, section: str, d: Dict[str, Any]) -> None:
                self.data[section] = d

        return _MiniVReport()


def run_quality_gates(
    xodr_path: str,
    out_dir: Optional[str] = None,
    vreport: Optional[object] = None,
    qgate: Optional[object] = None,
) -> Dict[str, Any]:
    """Run the post-pipeline gate sweep and return the failure mapping.

    ``qgate``/``vreport`` (NEW-342): when the caller supplies its own gate
    manager and validation report, every gate result -- including the hard-stop
    ones below -- is recorded THERE, so it reaches ``gate_failures.json`` and
    ``validation_report_full.json`` instead of dying with a throwaway manager.
    Without them this function keeps its historical self-contained behaviour.
    """
    print("\n=== Running Quality Gates ===\n")

    # Resolve the reporting sinks FIRST so even a hard stop is recorded in the
    # ledger a consumer will actually read.
    vreport = _resolve_vreport(vreport)
    if qgate is None:
        try:
            from ultimate_pipeline.quality.quality_gate_manager import (
                QualityGateManager,
            )

            qgate = QualityGateManager(vreport, logs_dir=out_dir)
        except Exception as e:
            if vreport is not None:
                try:
                    # import failure {"ok": False} -> "error"
                    vreport.add(
                        "error",
                        "quality_gates",
                        {"key": "quality_gate_manager_import", "ok": False, "error": str(e)},
                    )
                except Exception:
                    pass
            return {"quality_gate_manager_import": {"ok": False, "error": str(e)}}

    def _transport(name: str, detail: Dict[str, Any]) -> Dict[str, Any]:
        """Record a hard-stop gate and return it as the failure mapping."""
        payload: Dict[str, Any] = {"ok": False}
        payload.update(detail)
        try:
            qgate.fail(name, payload)
        except Exception:
            pass
        return {name: payload}

    # --- Hard-stop: reject stub XODR files ---
    try:
        xodr_size = os.path.getsize(xodr_path)
    except OSError as e:
        return _transport(
            "xodr_minimum_size",
            {"error": f"Cannot stat XODR file: {e}", "path": xodr_path},
        )
    if xodr_size < MIN_XODR_SIZE_BYTES:
        return _transport(
            "xodr_minimum_size",
            {
                "error": (
                    f"stub XODR rejected: {xodr_size} bytes < {MIN_XODR_SIZE_BYTES} "
                    "minimum"
                ),
                "path": xodr_path,
                "size_bytes": xodr_size,
            },
        )

    # --- Admit one bounded byte snapshot before any downstream parser runs ---
    try:
        from ultimate_pipeline.quality.xml_admission import parse_xodr_bytes, read_xodr_bytes

        source_xodr_path = xodr_path
        admitted_bytes = read_xodr_bytes(source_xodr_path)
        admitted_sha256 = hashlib.sha256(admitted_bytes).hexdigest()
        root = parse_xodr_bytes(admitted_bytes)
        # Existing gate APIs accept paths and reopen them. Point every such
        # consumer at a private snapshot of the already-admitted bytes.
        snapshot_directory = tempfile.TemporaryDirectory(
            prefix="up-quality-xodr-", dir=str(Path(source_xodr_path).resolve().parent)
        )
        snapshot_path = Path(snapshot_directory.name) / "admitted.xodr"
        with snapshot_path.open("xb") as stream:
            stream.write(admitted_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            snapshot_path.chmod(0o400)
        except OSError:
            pass
        xodr_path = str(snapshot_path)
    except Exception as e:
        return _transport("xml_parse", {"error": str(e), "path": xodr_path})

    def _try(label: str, fn) -> None:
        try:
            fn()
        except ModuleNotFoundError as e:
            qgate.passed(label + "_skipped")
            # "skip"/"skipped" status -> "skipped" level
            vreport.add(
                "skipped",
                "quality_gates",
                {"key": label + "_skipped", "status": "skip", "reason": str(e)},
            )
        except Exception as e:
            # Record under the SAME bare name a clean ok=False failure would
            # use (see e.g. gate_xml_integrity's own self.fail("xml_integrity",
            # ...)) -- DRIVABILITY_GATES matches on bare names, so a suffixed
            # key here would make a crashed gate invisible to the hard
            # drivability check even though a cleanly-failed one is caught.
            qgate.fail(label, {"error": str(e)})

    _try("xml_integrity", lambda: qgate.gate_xml_integrity(xodr_path))
    _try("junction_integrity", lambda: qgate.gate_junction_integrity(root, stage="final"))
    _try("carla_opendrive_compat", lambda: qgate.gate_carla_opendrive_compat(root))
    _try("xodr_strict_carla", lambda: qgate.gate_xodr_strict_carla(xodr_path))
    _try("elevation_smoothness", lambda: qgate.gate_elevation_smoothness(root))
    _try("physics_feasibility", lambda: qgate.gate_physics_feasibility(root))
    _try("randomness_entropy", lambda: qgate.gate_randomness_entropy(root))
    _try("semantic_overlap", lambda: qgate.gate_semantic_overlap(root))
    _try("collision_mesh", lambda: qgate.gate_collision_mesh(root))

    # --- Lane link targets check ---
    lane_link_result: Dict[str, Any] = {"status": "skipped"}
    try:
        from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
        lane_link_result = check_lane_link_targets_exist(xodr_path)
        if not lane_link_result.get("ok", True):
            qgate.fail("lane_link_targets", lane_link_result)
        else:
            qgate.passed("lane_link_targets")
    except Exception as e:
        lane_link_result = {"status": "error", "error": str(e)}

    # --- Optional external libOpenDRIVE validation ---
    external_rep: Dict[str, Any] = {"status": "skipped"}
    try:
        from ultimate_pipeline.config.settings import SETTINGS
        if getattr(SETTINGS, "ENABLE_LIBOPENDRIVE_VALIDATION", False):
            from ultimate_pipeline.quality.check_external_libopendrive import run_external_libopendrive_validation
            external_rep = run_external_libopendrive_validation(
                xodr_path,
                out_dir=out_dir,
                validator_exe=getattr(SETTINGS, "LIBOPENDRIVE_VALIDATOR_EXE", None),
                strict=bool(getattr(SETTINGS, "LIBOPENDRIVE_VALIDATION_STRICT", False)),
                timeout_s=float(getattr(SETTINGS, "LIBOPENDRIVE_VALIDATOR_TIMEOUT_S", 20.0)),
            )
            # Record in vreport
            try:
                # Plain data payload (raw validator report, not itself a
                # pass/fail verdict -- the verdict is recorded separately via
                # qgate.fail()/qgate.passed() below) -> "warning".
                vreport.add(
                    "warning",
                    "quality_gates",
                    {"key": "external_libopendrive", **external_rep}
                    if isinstance(external_rep, dict) and "key" not in external_rep
                    else {"key": "external_libopendrive", "value": external_rep},
                )
            except Exception:
                pass
            if not external_rep.get("ok", True) and bool(getattr(SETTINGS, "LIBOPENDRIVE_VALIDATION_STRICT", False)):
                qgate.fail("external_libopendrive", external_rep)
            else:
                qgate.passed("external_libopendrive")
        else:
            # explicitly skipped
            try:
                vreport.add(
                    "skipped",
                    "quality_gates",
                    {"key": "external_libopendrive", "status": "skipped", "reason": "disabled"},
                )
            except Exception:
                pass
            qgate.passed("external_libopendrive_skipped")
    except Exception as e:
        external_rep = {"status": "error", "error": str(e)}
        # Bare name, matching DRIVABILITY_GATES -- see the _try() comment above.
        qgate.fail("external_libopendrive", external_rep)

    # Do not let reports about the admitted snapshot authorize a candidate path
    # that changed while the sweep was in progress.
    try:
        current_bytes = read_xodr_bytes(source_xodr_path)
        current_sha256 = hashlib.sha256(current_bytes).hexdigest()
        if current_sha256 != admitted_sha256:
            raise RuntimeError(
                f"candidate SHA-256 changed from {admitted_sha256} to {current_sha256}"
            )
    except Exception as e:
        _transport(
            "xodr_identity_changed",
            {"error": str(e), "path": source_xodr_path, "admitted_sha256": admitted_sha256},
        )

    failures = qgate.get_failures()

    # --- Write artifacts ---
    artifacts: Dict[str, Any] = {
        "carla_compat_report": {},
        "strict_xodr_validation": {},
        "lane_link_check": lane_link_result,
        "external_libopendrive": external_rep,
    }

    try:
        from ultimate_pipeline.quality.check_carla_opendrive_compat import StrictCarlaOpendriveGate
        artifacts["carla_compat_report"] = {
            "issues": StrictCarlaOpendriveGate.validate(root),
            "xodr_path": source_xodr_path,
            "admitted_xodr_sha256": admitted_sha256,
        }
    except Exception as e:
        artifacts["carla_compat_report"] = {"error": str(e)}

    try:
        from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator
        validator = StrictXodrValidator(allow_spiral=True)
        artifacts["strict_xodr_validation"] = validator.validate_path(xodr_path)
    except Exception as e:
        artifacts["strict_xodr_validation"] = {"error": str(e)}

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        def _dump(name: str, data: Any) -> None:
            try:
                with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
            except Exception:
                pass
        _dump("carla_compat_report.json", artifacts["carla_compat_report"])
        _dump("strict_xodr_validation.json", artifacts["strict_xodr_validation"])
        _dump("lane_link_check.json", artifacts["lane_link_check"])
        _dump("external_libopendrive_report.json", artifacts["external_libopendrive"])

    print("\n=== Quality Gate Summary ===")
    if not failures:
        print("All gates passed (or were skipped safely).")
    else:
        print("Failures detected:")
        for k, v in failures.items():
            print(f"  - {k}: {v}")

    if "xodr_identity_changed" in failures:
        snapshot_directory.cleanup()
        raise QualityGateInputError(
            "candidate XODR identity changed during quality-gate evaluation"
        )
    snapshot_directory.cleanup()
    return failures
