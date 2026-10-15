"""Fail-closed OSM preflight for the RQ1 deterministic campaign.

Generic pipeline behaviour is deliberately NOT changed. This preflight exists
only so the RQ1 path cannot silently fall through to a live Overpass fetch.

In UE 4.26-era CARLA pipelines `main_pipeline` calls
`ensure_osm_exists(GPS_BOUNDS, OSM_FILE)`; with `ENABLE_OSM_DOWNLOAD` true and
a missing OSM_FILE that becomes a network attempt. Prior receipts record HTTP
406/403/429 from every mirror, so a silent network fallback is both slow and
non-reproducible.

The preflight rejects an RQ1 run unless all of the following hold:
  * UP_OSM_FILE is explicitly set
  * the path exists and is a regular file
  * the resolved path is the governed campaign source
  * its SHA256 equals the value pinned in INPUTS_MANIFEST.json
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO, "campaigns", "ingolstadt_cooked_perception_v1",
                        "source", "INPUTS_MANIFEST.json")
GOVERNED_REL = ("campaigns/ingolstadt_cooked_perception_v1/source/"
                "ingolstadt_authoritative.osm")


class PreflightRejected(Exception):
    """Raised when RQ1 must not proceed. Never downgrade to a warning."""


@dataclass
class PreflightResult:
    ok: bool
    reason: str = ""
    osm_file: Optional[str] = None
    sha256: Optional[str] = None
    expected_sha256: Optional[str] = None
    failures: list = field(default_factory=list)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def governed_source() -> tuple:
    """The single governed OSM path and its pinned digest."""
    with open(MANIFEST, encoding="utf-8") as fh:
        man = json.load(fh)
    entry = man["inputs"]["roads_osm"]
    return entry["path"], entry["sha256"].lower()


def check_rq1_osm_preflight(env: Optional[dict] = None) -> PreflightResult:
    """Validate the RQ1 OSM input without touching the network."""
    env = os.environ if env is None else env
    failures = []

    raw = env.get("UP_OSM_FILE")
    if not raw:
        failures.append("UP_OSM_FILE_UNSET")

    rel, expected_sha = governed_source()
    governed_abs = os.path.join(REPO, *rel.split("/"))

    path = raw or ""
    if path:
        if not os.path.exists(path):
            failures.append("OSM_FILE_MISSING")
        elif not os.path.isfile(path):
            failures.append("OSM_FILE_NOT_REGULAR_FILE")
        else:
            if os.path.normcase(os.path.abspath(path)) != \
                    os.path.normcase(os.path.abspath(governed_abs)):
                failures.append("OSM_FILE_NOT_GOVERNED_SOURCE")
            got = _sha256(path)
            if got != expected_sha:
                failures.append("OSM_FILE_HASH_MISMATCH")

    return PreflightResult(
        ok=not failures,
        reason="OK" if not failures else ";".join(failures),
        osm_file=path or None,
        sha256=(None if "OSM_FILE_MISSING" in failures
                or not path else _sha256_safe(path)),
        expected_sha256=expected_sha,
        failures=failures,
    )


def _sha256_safe(path: str):
    try:
        return _sha256(path)
    except OSError:
        return None


def require_rq1_osm_preflight(env: Optional[dict] = None) -> PreflightResult:
    """Hard gate. Raises rather than returning a soft failure."""
    res = check_rq1_osm_preflight(env)
    if not res.ok:
        raise PreflightRejected(
            "RQ1 OSM preflight failed (%s); refusing to reach the network"
            % res.reason)
    return res
