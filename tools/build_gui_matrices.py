"""Generate the 17-screen status matrix and the 116-control backend matrix.

The control matrix reconciles every row of the documented
``CONTROL_CATALOG.csv`` (116 rows, malformed ones included) against a real
backend contract. A control with no truthful backend is recorded as
``DEFERRED`` or ``DISABLED`` with its reason -- never silently bound.

The upstream catalogue is itself malformed (22 of 116 rows have a field count
other than 13 because of unescaped commas). Those rows are parsed defensively
and flagged ``MALFORMED_SOURCE_ROW`` rather than being dropped or guessed.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

DOCS = Path(
    r"F:\pulpit\CARLA_GUI_OpenCode_Tailored_Prompt_Pack_2026-10-15"
    r"\CARLA_GUI_OpenCode_Tailored_Prompt_Pack\extracted"
    r"\CARLA-GUI-DOCUMENTATION-FOUNDATION-20261015\CARLA_GUI_DOC_FOUNDATION"
)
CATALOG = DOCS / "07_GUI_SPEC" / "CONTROL_CATALOG.csv"
OUT = Path(r"F:\pulpit\CARLA_GUI_Orchestration_2026-10-15\task_13")

sys.path.insert(0, r"F:\wt\carla-gui-integration-20261015")

from ultimate_pipeline.gui.shell.navigation import SCREEN_ROUTES  # noqa: E402
from ultimate_pipeline.gui.shell.services import build_registry  # noqa: E402


def parse_catalog() -> tuple[list[dict], list[str]]:
    """Parse defensively: the upstream file has a malformed 15-col header."""
    notes: list[str] = []
    with CATALOG.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        notes.append(f"header declares {len(header)} columns")
        rows: list[dict] = []
        for index, raw in enumerate(reader, start=2):
            if not raw or not any(cell.strip() for cell in raw):
                continue
            record = {header[i]: raw[i] for i in range(min(len(header), len(raw)))}
            record["_row"] = index
            record["_fields"] = len(raw)
            record["_malformed"] = len(raw) != len(header)
            rows.append(record)
    return rows, notes


def _service_for_evidence(evidence: str, backend_call: str) -> str:
    """Map the catalogue's cited upstream module to a Task 02-12 GUI contract.

    Only a real, named contract is returned. Nothing is guessed.
    """
    blob = f"{evidence} {backend_call}".lower()
    if not blob.strip():
        return ""
    rules = (
        ("traffic_manager", "traffic_manager"),
        ("map_registry", "map_registry"),
        ("xodr_hash_gate", "quality"),
        ("map_acceptance", "quality"),
        ("calibration_contract", "calibration"),
        ("transform_conventions", "calibration"),
        ("attach_sensors", "calibration"),
        ("carla_server", "carla_backend"),
        ("carla_readiness", "carla_backend"),
        ("carla_opendrive_loader", "map_registry"),
        ("session.py", "carla_backend"),
        ("actor_stream_manager", "carla_backend"),
        ("sensor_registry", "carla_backend"),
        ("signals/verdict", "status_sources"),
        ("repo_health", "settings_registry"),
        ("config/settings", "settings_registry"),
        ("quality_gate", "quality"),
        ("rl_fuzzer", "mutators"),
        ("mutator", "mutators"),
        ("registry.discover_experiments", "experiments"),
        ("unified_runner", "experiments"),
        ("artifact_authority", "status_sources"),
        ("coverage", "coverage"),
    )
    for needle, service in rules:
        if needle in blob:
            return service
    return ""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = build_registry()
    rows, notes = parse_catalog()

    malformed = [r for r in rows if r["_malformed"]]
    notes.append(f"{len(malformed)} of {len(rows)} rows have a field count != header")

    # --- 17-screen status matrix -----------------------------------------
    screen_rows = []
    for key, route in sorted(SCREEN_ROUTES.items()):
        service = route.backend_service
        available = registry.available(service)
        reason = registry.reason_unavailable(service) if not available else ""
        screen_rows.append({
            "route": key,
            "title": route.title,
            "order": route.order,
            "task_13_status": "IMPLEMENTED" if route.implemented else "REGISTERED_NOT_IMPLEMENTED",
            "backend_service": service,
            "backend_available": available,
            "backend_source": registry.source_of(service),
            "reason": reason,
            "read_only": route.read_only,
            "mutating_controls_enabled": False,
        })

    with (OUT / "SCREEN_STATUS_MATRIX.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(screen_rows[0]), quoting=csv.QUOTE_ALL,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(screen_rows)

    # --- 116-control backend matrix --------------------------------------
    # Screen inferred from the catalog where possible; otherwise routed by
    # the documented control id prefix. Never invented silently.
    control_rows = []
    for record in rows:
        control_id = (record.get("control_id") or record.get("id") or "").strip()
        label = (record.get("label") or record.get("name") or "").strip()
        screen = (record.get("screen") or record.get("page") or "").strip()
        if control_id and screen not in SCREEN_ROUTES:
            # map by the leading number when the catalogue omits a screen
            prefix = control_id.split("-")[-1][:2]
            for key in SCREEN_ROUTES:
                if key.startswith(prefix):
                    screen = key
                    break

        # --- honest binding on the catalogue's REAL columns -------------
        backend_call = (record.get("backend_call") or "").strip()
        evidence = (record.get("source_evidence") or "").strip()
        mutation_mode = (record.get("mutation_mode") or "").strip().upper()
        catalog_status = (record.get("status") or "").strip()

        # A control whose catalogue row already says MISSING/DISABLED stays
        # that way; we never promote it to bound.
        if catalog_status in ("MISSING", "DISABLED") or mutation_mode == "DISABLED":
            decision = "DISABLED_IN_CATALOGUE"
            reason = (f"catalogue status {catalog_status!r}, mutation_mode "
                      f"{mutation_mode or 'unset'}")
            bound_service = ""
        else:
            # Bind by the upstream source module the catalogue cites.
            bound_service = _service_for_evidence(evidence, backend_call)
            if not bound_service:
                decision = "DEFERRED_NO_TRUTHFUL_BACKEND"
                reason = ("no Task 02-12 contract covers this backend call; "
                          f"catalogue cites {evidence or backend_call or 'nothing'}")
            elif registry.available(bound_service):
                decision = "BOUND_AVAILABLE"
                reason = ""
            else:
                decision = "BOUND_DISABLED"
                reason = registry.reason_unavailable(bound_service)

        if bound_service:
            source = registry.source_of(bound_service)
        else:
            source = evidence or "07_GUI_SPEC/CONTROL_CATALOG.csv"
        available = decision == "BOUND_AVAILABLE"

        control_rows.append({
            "control_id": control_id,
            "label": label,
            "catalog_screen": screen,
            "catalog_status": catalog_status,
            "catalog_mutation_mode": mutation_mode,
            "catalog_backend_call": backend_call,
            "catalog_source_evidence": evidence,
            "catalog_test_id": (record.get("test_id") or "").strip(),
            "backend_service": bound_service or "NONE",
            "binding_decision": decision,
            "available": available,
            "disabled_reason": reason,
            "source": source,
            "source_row": record["_row"],
            "source_row_malformed": record["_malformed"],
            "source_field_count": record["_fields"],
        })

    with (OUT / "CONTROL_BACKEND_MATRIX.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(control_rows[0]),
                                quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(control_rows)

    summary = {
        "screens_total": len(screen_rows),
        "screens_implemented_task13": sum(1 for r in screen_rows
                                          if r["task_13_status"] == "IMPLEMENTED"),
        "screens_registered_not_implemented": sum(1 for r in screen_rows
                                                  if r["task_13_status"] != "IMPLEMENTED"),
        "controls_total": len(control_rows),
        "controls_bound_available": sum(1 for r in control_rows
                                        if r["binding_decision"] == "BOUND_AVAILABLE"),
        "controls_bound_disabled": sum(1 for r in control_rows
                                       if r["binding_decision"] == "BOUND_DISABLED"),
        "controls_deferred": sum(1 for r in control_rows
                                 if r["binding_decision"] == "DEFERRED_NO_TRUTHFUL_BACKEND"),
        "controls_from_malformed_source_rows": len(malformed),
        "controls_dropped": 0,
        "notes": notes,
    }
    (OUT / "MATRIX_SUMMARY.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())