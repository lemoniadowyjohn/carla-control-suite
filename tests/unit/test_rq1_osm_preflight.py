"""RQ1 OSM fail-closed preflight tests.

Five cases, all offline. The critical property is that a bad or absent OSM
input is rejected BEFORE any network fallback could be reached, so an RQ1
determinism run can never silently switch to Overpass acquisition.

  1. correct path + correct hash   -> PASS
  2. missing path                  -> FAIL, before network
  3. wrong file hash               -> FAIL
  4. UP_OSM_FILE unset             -> FAIL
  5. alternate unpinned .osm       -> FAIL
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

from rq1_osm_preflight import (  # noqa: E402
    PreflightRejected, check_rq1_osm_preflight, governed_source,
    require_rq1_osm_preflight)

REL, EXPECTED_SHA = governed_source()
GOVERNED_ABS = os.path.join(REPO, *REL.split("/"))


def test_1_correct_path_and_hash_passes():
    res = check_rq1_osm_preflight({"UP_OSM_FILE": GOVERNED_ABS})
    assert res.ok, res.reason
    assert res.failures == []
    assert res.sha256 == EXPECTED_SHA
    # the strict entry point must agree and not raise
    assert require_rq1_osm_preflight({"UP_OSM_FILE": GOVERNED_ABS}).ok


def test_2_missing_path_fails_before_network():
    missing = os.path.join(REPO, "campaigns", "ingolstadt_cooked_perception_v1",
                           "source", "definitely_absent.osm")
    assert not os.path.exists(missing)
    res = check_rq1_osm_preflight({"UP_OSM_FILE": missing})
    assert not res.ok
    # a nonexistent path can only be reported as missing; identity comparison
    # is not attempted because there is nothing to compare
    assert "OSM_FILE_MISSING" in res.failures
    with pytest.raises(PreflightRejected):
        require_rq1_osm_preflight({"UP_OSM_FILE": missing})


def test_3_wrong_hash_fails():
    """A real file with correct shape but wrong bytes must be rejected."""
    tmp = tempfile.mkdtemp(prefix="rq1_osm_")
    try:
        bad = os.path.join(tmp, "ingolstadt_authoritative.osm")
        with open(GOVERNED_ABS, "rb") as src, open(bad, "wb") as dst:
            data = src.read()
            # flip one byte deep inside the payload
            dst.write(data[:1000] + bytes([data[1000] ^ 0xFF]) + data[1001:])
        res = check_rq1_osm_preflight({"UP_OSM_FILE": bad})
        assert not res.ok
        assert "OSM_FILE_HASH_MISMATCH" in res.failures, res.failures
        assert "OSM_FILE_NOT_GOVERNED_SOURCE" in res.failures, res.failures
        with pytest.raises(PreflightRejected):
            require_rq1_osm_preflight({"UP_OSM_FILE": bad})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_4_unset_up_osm_file_fails():
    res = check_rq1_osm_preflight({})
    assert not res.ok
    assert "UP_OSM_FILE_UNSET" in res.failures
    with pytest.raises(PreflightRejected):
        require_rq1_osm_preflight({})
    # an empty string must behave the same as unset, not slip through
    assert "UP_OSM_FILE_UNSET" in \
        check_rq1_osm_preflight({"UP_OSM_FILE": ""}).failures


def test_5_alternate_unpinned_osm_fails():
    """A plausible but unpinned .osm must never be accepted."""
    tmp = tempfile.mkdtemp(prefix="rq1_osm_alt_")
    try:
        alt = os.path.join(tmp, "ingolstadt.osm")
        shutil.copyfile(GOVERNED_ABS, alt)
        res = check_rq1_osm_preflight({"UP_OSM_FILE": alt})
        assert not res.ok, "an unpinned path with correct bytes must still fail"
        assert "OSM_FILE_NOT_GOVERNED_SOURCE" in res.failures, res.failures
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_preflight_never_touches_network(monkeypatch):
    """No socket may be created by the preflight, in any outcome."""
    import socket
    created = []
    real = socket.socket

    def guard(*a, **k):
        created.append(a)
        raise AssertionError("preflight attempted network access")

    monkeypatch.setattr(socket, "socket", guard)
    for env in ({}, {"UP_OSM_FILE": GOVERNED_ABS},
                {"UP_OSM_FILE": "nope.osm"}):
        check_rq1_osm_preflight(env)
    assert created == []
    assert real is not None


def test_manifest_pin_is_the_authority():
    """The expected digest must come from INPUTS_MANIFEST, not a constant."""
    import json
    man = os.path.join(REPO, "campaigns", "ingolstadt_cooked_perception_v1",
                       "source", "INPUTS_MANIFEST.json")
    with open(man, encoding="utf-8") as fh:
        entry = json.load(fh)["inputs"]["roads_osm"]
    assert entry["status"] == "pinned"
    assert entry["sha256"].lower() == EXPECTED_SHA
    assert entry["path"] == REL
