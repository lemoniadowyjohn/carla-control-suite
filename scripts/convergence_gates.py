"""Vendored-header drift gate, georeference preflight, and GNSS consumer audit.

The drift gate exists because a real defect was proven this cycle: the UE plugin
compiles against its own copy of the CARLA headers under
Plugins/Carla/CarlaDependencies/include/carla, so a change made only in
LibCarla/source/carla is invisible to the UE build. That produced a C2039
('HasAbsoluteOrigin' is not a member of carla::road::Map) that source review of
LibCarla alone could not have caught. Manual re-synchronisation is not an
acceptable control, so this compares the duplicated headers on every build
preflight.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import SCHEMA_VERSION, atomic_write_json, sha256_file, utc_now  # noqa: E402

CARLA = r"G:\CARLA\carla_source_probe"
LIB = os.path.join(CARLA, "LibCarla", "source", "carla")
VENDORED = os.path.join(CARLA, "Unreal", "CarlaUE4", "Plugins", "Carla",
                        "CarlaDependencies", "include", "carla")

# Headers the UE plugin actually consumes from the vendored tree. These are the
# ones whose divergence breaks the plugin build.
REQUIRED_MIRROR = [
    "road/Map.h",
    "road/MapData.h",
    "road/MapBuilder.h",
    "road/Lane.h",
    "road/Road.h",
    "geom/GeoLocation.h",
    "geom/Location.h",
    "geom/Transform.h",
    "rpc/WorldInfo.h",
]


# ---------------------------------------------------------------------------
# phase 4: vendored header drift gate
# ---------------------------------------------------------------------------
def _discover_mirrored_headers():
    """Every header present in BOTH trees, so coverage is manifest-driven."""
    both = []
    lib_root_len = len(LIB) + 1
    for dirpath, _dirs, files in os.walk(LIB):
        for name in files:
            if not name.endswith((".h", ".hpp")):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, LIB).replace("\\", "/")
            if os.path.isfile(os.path.join(VENDORED, rel.replace("/", os.sep))):
                both.append(rel)
    return sorted(both)


def vendored_header_drift(required=None, extra_allowed=()):
    required = required or REQUIRED_MIRROR
    discovered = _discover_mirrored_headers()
    rows = []
    failures = []

    for rel in sorted(set(required) | set(discovered) | set(extra_allowed)):
        lib_path = os.path.join(LIB, rel.replace("/", os.sep))
        ven_path = os.path.join(VENDORED, rel.replace("/", os.sep))
        lib_exists = os.path.isfile(lib_path)
        ven_exists = os.path.isfile(ven_path)

        if not lib_exists and not ven_exists:
            continue

        lib_sha = sha256_file(lib_path)
        ven_sha = sha256_file(ven_path)

        if not ven_exists:
            status = "MISSING_IN_VENDORED"
        elif not lib_exists:
            status = "VENDORED_ONLY"
        elif lib_sha == ven_sha:
            status = "IDENTICAL"
        else:
            status = "DRIFTED"

        # When both exist, a header that legitimately differs (e.g. a UE-specific
        # shim) must be allowlisted explicitly, not silently tolerated.
        allowlisted = rel in extra_allowed
        if status == "DRIFTED" and allowlisted:
            status = "DRIFTED_ALLOWLISTED"

        rows.append({
            "header": rel,
            "status": status,
            "libcarla_sha256": lib_sha,
            "vendored_sha256": ven_sha,
            "required_by_gate": rel in required,
        })
        if rel in required and status not in ("IDENTICAL", "DRIFTED_ALLOWLISTED"):
            failures.append({"header": rel, "status": status})

    unexpected = [r for r in rows
                  if r["status"] == "DRIFTED" and not r["required_by_gate"]]

    return {
        "schema": "VENDORED_HEADER_DRIFT_GATE/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "libcarla_root": LIB,
        "vendored_root": VENDORED,
        "required_headers": list(required),
        "discovered_mirrored_header_count": len(discovered),
        "compared_count": len(rows),
        "headers": rows,
        "required_failures": failures,
        "unexpected_drift_outside_required_set": unexpected,
        "PASS": not failures and not unexpected,
        "BUILD_PREFLIGHT_EFFECT": "ALLOW" if (not failures and not unexpected)
        else "DENY_BUILD_PREFLIGHT",
        "rationale": (
            "The UE plugin does not consume LibCarla/source/carla directly; it "
            "compiles against a vendored mirror. A LibCarla-only change is "
            "invisible to the UE build, which is how C2039 on "
            "carla::road::Map::HasAbsoluteOrigin reached the linker."),
    }


# ---------------------------------------------------------------------------
# phase 5: georeference preflight
# ---------------------------------------------------------------------------
PREFLIGHT_STATUS_ABSOLUTE_UNAVAILABLE = "ABSOLUTE_GEOREFERENCE_UNAVAILABLE"
PREFLIGHT_STATUS_OK = "ABSOLUTE_GEOREFERENCE_AVAILABLE"
PREFLIGHT_STATUS_UNKNOWN = "GEOREFERENCE_STATE_UNKNOWN"


def georeference_preflight(requires_gnss, has_absolute_origin=None,
                           map_name=None, probe=None):
    """Refuse a GNSS-dependent workload before any sensor is created.

    Rationale: a GNSS sensor on a map with no absolute origin emits nothing at
    all. A capture loop that waits for the first GNSS frame then waits forever,
    which is indistinguishable from sensor or network failure. The decision must
    be made up front, while the answer is still knowable.
    """
    if has_absolute_origin is None:
        state = PREFLIGHT_STATUS_UNKNOWN
        reason = ("georeference state could not be determined; refusing to "
                  "assume an origin exists")
        allowed = not requires_gnss
    elif has_absolute_origin:
        state = PREFLIGHT_STATUS_OK
        reason = "map declares a source-backed absolute geodetic origin"
        allowed = True
    else:
        state = PREFLIGHT_STATUS_ABSOLUTE_UNAVAILABLE
        reason = ("map geoReference declares no +lat_0/+lon_0, so GNSS cannot "
                  "produce a truthful fix. Local geometry, streaming and "
                  "non-geodetic sensors remain valid.")
        allowed = not requires_gnss

    return {
        "schema": "GEOREFERENCE_PREFLIGHT/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "map": map_name,
        "requires_gnss": requires_gnss,
        "has_absolute_origin": has_absolute_origin,
        "status": state,
        "reason": reason,
        "EXPERIMENT_ALLOWED": allowed,
        "gate_effect": "ALLOW" if allowed else "ABORT_BEFORE_SENSOR_STARTUP",
        "gnss_sensor_created": False,
        "policy": ("GNSS unavailability is decided here, not by observing "
                   "sensor silence later."),
    }


# ---------------------------------------------------------------------------
# phase 6: GNSS consumer audit
# ---------------------------------------------------------------------------
# Outcome taxonomy required by the batch.
CONSUMER_OUTCOMES = ("SAFE", "FAILS_EXPLICITLY", "TIMES_OUT", "CAN_DEADLOCK",
                     "SILENT_DATA_LOSS", "UNKNOWN")


def classify_consumer(name, waits_for_first_frame, timeout, aborts_on_timeout,
                      treats_missing_as_optional):
    """Classify what a consumer does when no GNSS event ever arrives.

    waits_for_first_frame            -> blocks until a frame arrives
    timeout + aborts_on_timeout       -> bounded failure
    timeout without abort             -> hangs past the timeout
    treats_missing_as_optional        -> proceeds, so nothing is reported missing
    """
    if treats_missing_as_optional:
        return {"outcome": "SILENT_DATA_LOSS",
                "detail": "consumer treats the absent sensor as optional and "
                          "proceeds, so the missing GNSS stream is never reported"}
    if not waits_for_first_frame:
        return {"outcome": "SAFE",
                "detail": "consumer never blocks on GNSS data"}
    if timeout is None:
        return {"outcome": "CAN_DEADLOCK",
                "detail": "blocks on the first GNSS frame with no timeout"}
    if aborts_on_timeout:
        return {"outcome": "FAILS_EXPLICITLY",
                "detail": "bounded by a %.1fs timeout that aborts the run" % timeout}
    return {"outcome": "TIMES_OUT",
            "detail": "has a %.1fs timeout but does not abort, so the run hangs "
                      "past the bound" % timeout}


def gnss_consumer_audit(consumers):
    rows = []
    tally = {k: 0 for k in CONSUMER_OUTCOMES}
    for c in consumers:
        verdict = classify_consumer(
            c["consumer"], c.get("waits_for_first_frame", False),
            c.get("timeout_sec"), c.get("aborts_on_timeout", False),
            c.get("treats_missing_as_optional", False))
        tally[verdict["outcome"]] += 1
        rows.append({**c, **verdict})
    unsafe = [r for r in rows
              if r["outcome"] in ("CAN_DEADLOCK", "TIMES_OUT", "SILENT_DATA_LOSS")]
    return {
        "schema": "GNSS_CONSUMER_AUDIT/v1",
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "consumer_count": len(rows),
        "outcomes": tally,
        "consumers": rows,
        "unsafe_consumers": [r["consumer"] for r in unsafe],
        "PASS": not unsafe,
        "GNSS_NO_ORIGIN_BEHAVIOR": "EXPLICIT" if not unsafe else "SILENT_NO_DATA",
        "rationale": (
            "Emitting no GNSS measurement is truthful, but silence is "
            "indistinguishable from sensor or network failure downstream. "
            "Every consumer must either fail fast or declare GNSS optional up "
            "front; none may wait indefinitely."),
    }


def main():
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "reports")
    os.makedirs(out, exist_ok=True)

    drift = vendored_header_drift()
    atomic_write_json(os.path.join(out, "VENDORED_HEADER_DRIFT_GATE.json"), drift)
    print("VENDORED_HEADER_DRIFT_GATE: PASS=%s compared=%d required=%d failures=%d"
          % (drift["PASS"], drift["compared_count"],
             len(drift["required_headers"]), len(drift["required_failures"])))
    for f in drift["required_failures"]:
        print("   FAIL %s -> %s" % (f["header"], f["status"]))
    for u in drift["unexpected_drift_outside_required_set"]:
        print("   UNEXPECTED DRIFT %s" % u["header"])


if __name__ == "__main__":
    main()
