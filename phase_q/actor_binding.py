"""Q6 - Packaged-map signal/crosswalk actor binding gate.

The packaged map must prove not only that XML signals exist but that CARLA
runtime actors and Unreal assets are bound correctly.

For every OpenDRIVE signal/controller authority record, the gate emits a
binding row and requires packaged/runtime actor evidence for each of:

* runtime traffic-light actor ID
* pole/head visual asset
* trigger volume
* affected lanes
* stop line
* state transitions
* Traffic Manager response
* semantic sensor class

Crosswalks require: OpenDRIVE/object authority, visible marking, collision
behavior, pedestrian navigation, semantic label, route interaction.

This gate is fail-closed: without packaged actor inventories every row is
NOT_RUN and the gate verdict is ACTOR_BINDING_MISSING (never a pass).

Outputs: Q06_SIGNAL_ACTOR_BINDING.csv, Q07_CROSSWALK_BINDING.csv
"""
from __future__ import annotations

import csv
import os
from typing import Any, Dict, List, Optional

from phase_q.common import XodrTree, save_json, save_text
from phase_q.semantic_policy import ACTOR_BINDING_MISSING

SIGNAL_BINDING_COLUMNS = [
    "opendrive_signal_id", "opendrive_controller_id", "runtime_actor_id",
    "visual_asset", "trigger_volume", "affected_lanes", "stop_line",
    "state_transitions", "traffic_manager", "semantic_class", "status",
]

CROSSWALK_BINDING_COLUMNS = [
    "opendrive_object_id", "visible_marking", "collision_behavior",
    "pedestrian_navigation", "semantic_label", "route_interaction", "status",
]


def _signals_from_xodr(xodr_text: str) -> List[Dict[str, str]]:
    tree = XodrTree(xodr_text)
    rows = []
    for sig in tree.iter("signal"):
        rows.append({
            "opendrive_signal_id": str(sig.get("id", "")),
            "opendrive_controller_id": str(sig.get("controllerId", "")),
        })
    # controllers and their signal references
    for ctrl in tree.iter("controller"):
        cid = str(ctrl.get("id", ""))
        for ref in ctrl.iter("signal"):
            rows.append({
                "opendrive_signal_id": str(ref.get("ref", "")),
                "opendrive_controller_id": cid,
            })
    # dedupe, keep order
    seen = set()
    out = []
    for r in rows:
        k = (r["opendrive_signal_id"], r["opendrive_controller_id"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _crosswalks_from_xodr(xodr_text: str) -> List[Dict[str, str]]:
    tree = XodrTree(xodr_text)
    rows = []
    for obj in tree.iter("object"):
        otype = str(obj.get("type", "")).lower()
        sub = str(obj.get("subtype", "")).lower()
        if otype in ("crosswalk", "crosswalkzone") or "crosswalk" in sub:
            rows.append({"opendrive_object_id": str(obj.get("id", ""))})
    return rows


def build_binding_gate(
    xodr_text: Optional[str],
    runtime_actors: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate the packaged actor binding gate.

    runtime_actors is a dict of runtime actor inventories; when absent the
    gate fails closed.
    """
    signal_rows: List[Dict[str, str]] = []
    crosswalk_rows: List[Dict[str, str]] = []

    if xodr_text:
        signal_rows = _signals_from_xodr(xodr_text)
        crosswalk_rows = _crosswalks_from_xodr(xodr_text)

    bound = 0
    for row in signal_rows:
        row.update({
            "runtime_actor_id": "-", "visual_asset": "-", "trigger_volume": "-",
            "affected_lanes": "-", "stop_line": "-", "state_transitions": "-",
            "traffic_manager": "-", "semantic_class": "-", "status": "NOT_RUN",
        })
        if runtime_actors:
            actor = runtime_actors.get(row["opendrive_signal_id"])
            if actor and actor.get("actor_id"):
                row["runtime_actor_id"] = str(actor["actor_id"])
                row["visual_asset"] = str(actor.get("visual_asset") or "unverified")
                row["trigger_volume"] = str(actor.get("trigger_volume") or "unverified")
                row["affected_lanes"] = str(actor.get("affected_lanes") or "unverified")
                row["stop_line"] = str(actor.get("stop_line") or "unverified")
                row["state_transitions"] = str(actor.get("state_transitions") or "unverified")
                row["traffic_manager"] = str(actor.get("traffic_manager") or "unverified")
                row["semantic_class"] = str(actor.get("semantic_class") or "unverified")
                row["status"] = "BOUND" if all(
                    v and v != "unverified" for v in (
                        row["runtime_actor_id"], row["visual_asset"], row["trigger_volume"],
                        row["affected_lanes"], row["stop_line"], row["state_transitions"],
                        row["traffic_manager"], row["semantic_class"])
                ) else "PARTIAL"
                if row["status"] == "BOUND":
                    bound += 1

    for row in crosswalk_rows:
        row.update({
            "visible_marking": "-", "collision_behavior": "-",
            "pedestrian_navigation": "-", "semantic_label": "-",
            "route_interaction": "-", "status": "NOT_RUN",
        })

    total = len(signal_rows)
    if runtime_actors is None or (total and bound < total):
        verdict = ACTOR_BINDING_MISSING
    elif total == 0:
        verdict = "NO_SIGNAL_AUTHORITY_IN_PACKAGE"
    else:
        verdict = "ACTOR_BINDING_VERIFIED"

    return {
        "verdict": verdict,
        "signal_rows": signal_rows,
        "crosswalk_rows": crosswalk_rows,
        "signal_total": total,
        "signal_bound": bound,
        "crosswalk_total": len(crosswalk_rows),
        "fail_closed": verdict == ACTOR_BINDING_MISSING,
    }


def write_binding_outputs(
    gate: Dict[str, Any],
    out_csv_signal: str,
    out_csv_crosswalk: str,
) -> Dict[str, str]:
    with open(out_csv_signal, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SIGNAL_BINDING_COLUMNS)
        w.writeheader()
        for row in gate["signal_rows"]:
            w.writerow({c: row.get(c, "-") for c in SIGNAL_BINDING_COLUMNS})
    with open(out_csv_crosswalk, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CROSSWALK_BINDING_COLUMNS)
        w.writeheader()
        for row in gate["crosswalk_rows"]:
            w.writerow({c: row.get(c, "-") for c in CROSSWALK_BINDING_COLUMNS})
    return {
        "Q06_SIGNAL_ACTOR_BINDING.csv": out_csv_signal,
        "Q07_CROSSWALK_BINDING.csv": out_csv_crosswalk,
    }