"""Generate a current-map static release matrix without mutating the map."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

ROOT = Path(__file__).resolve().parents[1]
CURRENT = verify_pinned_map("auto_map_of_record")
CURRENT_SHA = CURRENT["sha256"]
CURRENT_PATH = CURRENT["resolved_path"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _record(name: str, command: str, evidence: str | None, *, evidence_sha_fields: tuple[str, ...] = ("map_sha256", "input_xodr_sha256", "xodr_sha256", "map_of_record_sha256", "auto_xodr_sha256")) -> dict[str, Any]:
    path = ROOT / evidence if evidence else None
    exists = bool(path and path.is_file())
    evidence_sha = sha256(path) if exists else None
    bound = False
    source_sha = None
    if exists:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for field in evidence_sha_fields:
                value = data.get(field)
                if isinstance(value, str):
                    source_sha = value
                    bound = value.lower() == CURRENT_SHA
                    break
                if isinstance(value, dict):
                    nested = value.get("sha256")
                    if isinstance(nested, str):
                        source_sha = nested
                        bound = nested.lower() == CURRENT_SHA
                        break
            if not bound:
                prov = data.get("source_provenance")
                if isinstance(prov, dict):
                    value = prov.get("map_of_record_sha256")
                    if isinstance(value, str):
                        source_sha = value
                        bound = value.lower() == CURRENT_SHA
        except (OSError, json.JSONDecodeError):
            pass
    if not exists:
        status = "NOT_RUN"
    elif bound:
        status = "PASS"
    else:
        status = "STALE_OR_UNBOUND"
    return {
        "gate": name,
        "status": status,
        "command": command,
        "evidence_path": evidence,
        "evidence_sha256": evidence_sha,
        "source_map_sha256": source_sha,
        "source_map_bound_to_current_pin": bound,
        "gate_version_commit": git_sha(),
    }


def build_matrix() -> dict[str, Any]:
    rows = [
        _record("xml_validity", "python -m ultimate_pipeline.quality.check_xml_integrity", "reports/production_readiness/20260921_XODR_VALIDATOR_CONVERGENCE/04_VALIDATOR_DISAGREEMENTS.json"),
        _record("planview_completeness", "python -m ultimate_pipeline.quality.check_geometric_continuity", "reports/production_readiness/20260921_XODR_VALIDATOR_CONVERGENCE/04_VALIDATOR_DISAGREEMENTS.json"),
        _record("geometry_validation", "python -m ultimate_pipeline.quality.check_carla_opendrive_compat", "reports/production_readiness/20260921_XODR_VALIDATOR_CONVERGENCE/04_VALIDATOR_DISAGREEMENTS.json"),
        _record("lane_topology", "python -m ultimate_pipeline.quality.check_lane_link_targets_exist", None),
        _record("road_links", "python -m ultimate_pipeline.tools.audit_osm_road_link_topology", None),
        _record("junction_links", "python -m ultimate_pipeline.quality.check_junction_connection_coverage", None),
        _record("lane_count_classification", "python -m ultimate_pipeline.quality.check_lane_count_changes", "reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/lane_count_classification.json"),
        _record("component_reachability", "python -m ultimate_pipeline.quality.map_acceptance", "reports/production_readiness/20260919T000000Z_PRODUCTION_CLOSURE/00_BASELINE.json"),
        _record("crs_checks", "ultimate_pipeline.quality.xodr_strict_validator.thesis_strict_checks", "reports/production_readiness/20260921_XODR_VALIDATOR_CONVERGENCE/04_VALIDATOR_DISAGREEMENTS.json"),
        _record("map_acceptance", "python scripts/measure_candidate_acceptance.py <xodr>", None),
        _record("artifact_fingerprint", "python -m ultimate_pipeline.utils.map_fingerprint", None),
        _record("tile_readiness", "python -m ultimate_pipeline.tools.preflight_import_package --package-dir <package>", "reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/COOK_RESULTS.json"),
        _record("gap026", "python -c 'LaneLinkBuilder.sanitize_junction_lane_links(...)'", "reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json"),
        _record("waivers", "python -m ultimate_pipeline.quality.map_acceptance", None),
    ]
    statuses = {r["status"] for r in rows}
    overall = "STALE_OR_UNBOUND" if "STALE_OR_UNBOUND" in statuses else ("NOT_RUN" if "NOT_RUN" in statuses else "PASS")
    return {
        "schema": "current_map_static_release_matrix/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "map_registry": {
            "key": CURRENT["registry_key"],
            "path": CURRENT["declared_path"],
            "sha256": CURRENT_SHA,
            "bytes": CURRENT["bytes"],
            "registry_sha256": CURRENT["registry_sha256"],
            "verification_status": CURRENT["verification_status"],
        },
        "repository_commit": git_sha(),
        "overall_static_evidence_status": overall,
        "policy": "A historical report is current evidence only when its embedded source-map SHA equals the registry-resolved current map SHA; otherwise status is STALE_OR_UNBOUND.",
        "gates": rows,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="CURRENT_MAP_STATIC_RELEASE_MATRIX.json")
    args = parser.parse_args()
    payload = build_matrix()
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["overall_static_evidence_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
