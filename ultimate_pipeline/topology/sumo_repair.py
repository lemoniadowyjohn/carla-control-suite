# ultimate_pipeline/topology/sumo_repair.py

import os
import re
import subprocess
from typing import Any, Dict

from ultimate_pipeline.core.file_utils import copy_file, ensure_dir
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.quality.check_junction_integrity import JunctionIntegrityGate
from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator


class RepairResult(str):
    """String-like SUMO repair result that also carries audit metadata."""

    def __new__(cls, path: str, meta: Dict[str, Any] | None = None):
        obj = str.__new__(cls, str(path))
        obj.meta = dict(meta or {})
        return obj

    def __iter__(self):
        yield str(self)
        yield self.meta


class SUMORepair:
    """
    Optional: use SUMO netconvert to reconstruct topology and export a cleaned OpenDRIVE.
    """

    @staticmethod
    def repair(input_xodr: str, output_xodr: str) -> RepairResult:
        exe = getattr(SETTINGS, "SUMO_NETCONVERT", "")
        ensure_dir(os.path.dirname(output_xodr))
        log_path = os.path.join(os.path.dirname(output_xodr), "sumo_netconvert.log")
        geometry_remove = bool(getattr(SETTINGS, "SUMO_REPAIR_GEOMETRY_REMOVE", True))
        ignore_errors = bool(getattr(SETTINGS, "SUMO_REPAIR_IGNORE_ERRORS", True))

        if (not getattr(SETTINGS, "ENABLE_SUMO_REPAIR", False)) or (not exe) or (not os.path.exists(exe)):
            print("? SUMORepair: SUMO not available or disabled; copying input.")
            copy_file(input_xodr, output_xodr)
            return RepairResult(output_xodr, {"enabled": False})

        temp_net = output_xodr + ".net.xml"
        gate_before = SUMORepair._gate_counts(input_xodr)

        cmd = [
            exe,
            "--opendrive", input_xodr,
            "-o", temp_net,
            "--opendrive-output", output_xodr,
        ]
        # F1 CRS contract: keep geometry in the Osm2Odr-native global tmerc(0,0)
        # frame. By default netconvert normalizes node positions to a local origin
        # (offset ~832671, ~5458671 for Ingolstadt), silently moving geometry off
        # the frame the downstream DEM sampler requires -> it then fails closed
        # (no_frame_matches_osm_source) and no elevation can be imported. Disable
        # normalization so the round-trip preserves the input frame.
        if bool(getattr(SETTINGS, "SUMO_REPAIR_PRESERVE_FRAME", True)):
            cmd += ["--offset.disable-normalization", "true"]
        if geometry_remove:
            cmd += ["--geometry.remove", "true"]
        if ignore_errors:
            cmd += ["--ignore-errors"]

        result_meta: Dict[str, Any] = {
            "enabled": True,
            "returncode": -1,
            "geometry_remove": bool(geometry_remove),
            "ignore_errors": bool(ignore_errors),
            "log_path": str(log_path),
            "warnings": {
                "no_lane_edges": 0,
                "sharp_turns": 0,
                "incompatible_connections": 0,
                "shape_failures": 0,
                "stop_line_misalignments": 0,
            },
            "gate_before": dict(gate_before),
            "gate_after": {},
        }

        print("? Running SUMO netconvert for topology repair...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            result_meta["returncode"] = int(result.returncode)
            with open(log_path, "w", encoding="utf-8") as log:
                log.write("$ " + " ".join(cmd) + "\n\n")
                log.write(result.stdout or "")
                if result.stderr:
                    log.write("\n--- STDERR ---\n")
                    log.write(result.stderr)
            result_meta["warnings"] = SUMORepair._parse_warning_counts(
                "\n".join(
                    [
                        str(result.stdout or ""),
                        str(result.stderr or ""),
                    ]
                )
            )
            if result.returncode != 0:
                print("? SUMORepair: netconvert failed; stderr tail:")
                print("\n".join((result.stderr or "").splitlines()[-20:]))
                copy_file(input_xodr, output_xodr)
            else:
                print(f"? SUMORepair: repaired XODR -> {output_xodr}")
                SUMORepair._verify_gate_regression(input_xodr, output_xodr)
        except Exception as e:
            result_meta["returncode"] = int(result_meta.get("returncode", -1) or -1)
            result_meta["exception"] = str(e)
            print(f"? SUMORepair: exception {e}; using original file.")
            copy_file(input_xodr, output_xodr)
        finally:
            result_meta["gate_after"] = SUMORepair._gate_counts(output_xodr)
            try:
                if os.path.exists(temp_net):
                    os.remove(temp_net)
            except Exception:
                pass

        return RepairResult(output_xodr, result_meta)

    @staticmethod
    def _parse_warning_counts(text: str) -> Dict[str, int]:
        payload = str(text or "")
        return {
            "no_lane_edges": len(re.findall(r"No lanes given for edge", payload, flags=re.IGNORECASE)),
            "sharp_turns": len(re.findall(r"Warning.*sharp turn", payload, flags=re.IGNORECASE)),
            "incompatible_connections": len(
                re.findall(r"Geometrically,\s*no connection", payload, flags=re.IGNORECASE)
            ),
            "shape_failures": len(re.findall(r"Failed to compute shape", payload, flags=re.IGNORECASE)),
            "stop_line_misalignments": len(re.findall(r"stop line", payload, flags=re.IGNORECASE)),
        }

    @staticmethod
    def _gate_counts(xodr_path: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        try:
            rep = JunctionIntegrityGate.validate(xodr_path)
            counts["junction_integrity"] = int(rep.get("issue_count", 0))
        except Exception:
            counts["junction_integrity"] = -1
        try:
            rep = check_lane_link_targets_exist(xodr_path)
            counts["lane_link_targets"] = int(rep.get("num_issues", 0))
        except Exception:
            counts["lane_link_targets"] = -1
        try:
            rep = StrictXodrValidator().validate_path(xodr_path)
            counts["xodr_strict_errors"] = int(rep.get("n_errors", 0))
        except Exception:
            counts["xodr_strict_errors"] = -1
        return counts

    @staticmethod
    def _verify_gate_regression(input_xodr: str, output_xodr: str) -> None:
        max_delta = int(getattr(SETTINGS, "SUMO_REPAIR_MAX_ERROR_DELTA", 0))
        before = SUMORepair._gate_counts(input_xodr)
        after = SUMORepair._gate_counts(output_xodr)
        before_total = sum(v for v in before.values() if v >= 0)
        after_total = sum(v for v in after.values() if v >= 0)
        if after_total > before_total + max_delta:
            raise RuntimeError(
                f"SUMO repair worsened gate errors: before={before_total} after={after_total} "
                f"(delta>{max_delta})."
            )
