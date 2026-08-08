"""Q-traffic-control digests (read-only analysis).

Canonical, deterministic digests for the OpenDRIVE traffic-control layer,
used to:

* freeze the semantic parent (Stage 1)
* enforce the parent gate (the crosswalk/pedestrian orchestrator refuses to
  run unless the parent signal/controller/signalReference digests match the
  frozen authority)
* prove semantic integrity after mutation (no signal deleted-and-recreated
  under the same count)
* govern/promote the perception candidate

Design contract (Claude C0 E0.1):

SIGNAL_ELEMENT_DIGEST
    One tuple per <signal> in deterministic document order:
        (id, road_id, s, t, zOffset, hOffset, type, subtype, dynamic,
         country, name, value, unit, orientation, validities)
    where `validities` is a sorted tuple of (lane, from, to, direction,
    side) for each <validity> child, empty tuple if none.
    Numbers are canonicalized via repr float (no trailing zeros; -0 -> 0).
    Tuples are SHA-256'd with a fixed separator.

SIGNAL_REFERENCE_DIGEST
    One tuple per <signalReference> in order: (id, s, t, type, subtype,
    validities). Some OpenDRIVE files use signalReference; the candidate
    uses <signal> elements instead, so this set is expected empty but is
    still digested for completeness.

CONTROLLER_DIGEST
    One tuple per <controller> in order: (id, name, type, delay,
    plugin).  Empty if none.

COMBINED_TRAFFIC_CONTROL_DIGEST
    Concatenation of SIGNAL_ELEMENT_DIGEST + SIGNAL_REFERENCE_DIGEST +
    CONTROLLER_DIGEST with fixed separators.

Determinism notes:
- Iterates the parsed tree in document order; ids are treated as strings
  (norm_id) so leading zeros are normalized.
- Floats canonicalized via ``_num`` (drops -0.0 / trailing zeros).
- The digest is independent of XML formatting / geoReference text.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from phase_q.common import XodrTree, norm_id


def _header_schema_version(parsed: XodrTree) -> str:
    header = parsed.find("header")
    if header is None:
        return "none"
    rev_major = norm_id(header.get("revMajor"))
    rev_minor = norm_id(header.get("revMinor"))
    return f"{rev_major}.{rev_minor}"

SEP = "\x1f"


def _num(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == 0.0:
        f = 0.0
    return repr(f)


def _attr(el: Any, name: str) -> str:
    return norm_id(el.get(name)) if el is not None else ""


def _validities(el: Any) -> Tuple[Tuple[str, str, str, str, str], ...]:
    out = []
    for val in el.findall("validity"):
        out.append((
            norm_id(val.get("lane")),
            _num(val.get("from")),
            _num(val.get("to")),
            norm_id(val.get("direction")),
            norm_id(val.get("side")),
        ))
    return tuple(sorted(out))


def signal_element_list(parsed: XodrTree) -> List[Dict[str, Any]]:
    """Deterministic, ordered list of signal element records."""
    root = parsed.root
    recs: List[Dict[str, Any]] = []
    for road in root.findall("road"):
        road_id = norm_id(road.get("id"))
        # signals directly under road (O Erdmann / OSM convention)
        for sig in road.findall("signal"):
            recs.append({
                "id": norm_id(sig.get("id")),
                "road_id": road_id,
                "s": _num(sig.get("s")),
                "t": _num(sig.get("t")),
                "zOffset": _num(sig.get("zOffset")),
                "hOffset": _num(sig.get("hOffset")),
                "type": norm_id(sig.get("type")),
                "subtype": norm_id(sig.get("subtype")),
                "dynamic": norm_id(sig.get("dynamic")),
                "country": norm_id(sig.get("country")),
                "name": norm_id(sig.get("name")),
                "value": norm_id(sig.get("value")),
                "unit": norm_id(sig.get("unit")),
                "orientation": norm_id(sig.get("orientation")),
                "validities": _validities(sig),
            })
        # signals nested under <signals> (CARLA convention)
        for sig in road.findall("signals/signal"):
            recs.append({
                "id": norm_id(sig.get("id")),
                "road_id": road_id,
                "s": _num(sig.get("s")),
                "t": _num(sig.get("t")),
                "zOffset": _num(sig.get("zOffset")),
                "hOffset": _num(sig.get("hOffset")),
                "type": norm_id(sig.get("type")),
                "subtype": norm_id(sig.get("subtype")),
                "dynamic": norm_id(sig.get("dynamic")),
                "country": norm_id(sig.get("country")),
                "name": norm_id(sig.get("name")),
                "value": norm_id(sig.get("value")),
                "unit": norm_id(sig.get("unit")),
                "orientation": norm_id(sig.get("orientation")),
                "validities": _validities(sig),
            })
    # document-order within the full tree (road order above) is deterministic.
    return recs


def signal_reference_list(parsed: XodrTree) -> List[Dict[str, Any]]:
    root = parsed.root
    recs: List[Dict[str, Any]] = []
    for road in root.findall("road"):
        for ref in road.findall("signalReference"):
            recs.append({
                "id": norm_id(ref.get("id")),
                "s": _num(ref.get("s")),
                "t": _num(ref.get("t")),
                "type": norm_id(ref.get("type")),
                "subtype": norm_id(ref.get("subtype")),
                "validities": _validities(ref),
            })
    return recs


def controller_list(parsed: XodrTree) -> List[Dict[str, Any]]:
    root = parsed.root
    recs: List[Dict[str, Any]] = []
    for ctrl in root.findall("controller"):
        recs.append({
            "id": norm_id(ctrl.get("id")),
            "name": norm_id(ctrl.get("name")),
            "type": norm_id(ctrl.get("type")),
            "delay": _num(ctrl.get("delay")),
            "plugin": norm_id(ctrl.get("plugin")),
        })
    return recs


def _digest_records(records: List[Dict[str, Any]]) -> str:
    h = hashlib.sha256()
    h.update(str(len(records)).encode("utf-8"))
    for r in records:
        flat = SEP.join(str(v) for v in r.values())
        h.update(SEP.encode("utf-8"))
        h.update(flat.encode("utf-8"))
    return h.hexdigest()


def signal_element_digest(parsed: XodrTree) -> str:
    return _digest_records(signal_element_list(parsed))


def signal_reference_digest(parsed: XodrTree) -> str:
    return _digest_records(signal_reference_list(parsed))


def controller_digest(parsed: XodrTree) -> str:
    return _digest_records(controller_list(parsed))


def combined_traffic_control_digest(parsed: XodrTree) -> Dict[str, str]:
    s_el = signal_element_list(parsed)
    s_ref = signal_reference_list(parsed)
    ctrl = controller_list(parsed)
    h = hashlib.sha256()
    h.update(b"SIGNALELEMENT")
    h.update(SEP.encode("utf-8"))
    for r in s_el:
        h.update(SEP.join(str(v) for v in r.values()).encode("utf-8"))
    h.update(b"SIGNALREFERENCE")
    h.update(SEP.encode("utf-8"))
    for r in s_ref:
        h.update(SEP.join(str(v) for v in r.values()).encode("utf-8"))
    h.update(b"CONTROLLER")
    h.update(SEP.encode("utf-8"))
    for r in ctrl:
        h.update(SEP.join(str(v) for v in r.values()).encode("utf-8"))
    combined = h.hexdigest()
    return {
        "schema": "phase_q/signal_digest/v1",
        "schema_version": _header_schema_version(parsed),
        "signal_count": len(s_el),
        "signal_reference_count": len(s_ref),
        "controller_count": len(ctrl),
        "signal_element_digest": signal_element_digest(parsed),
        "signal_reference_digest": signal_reference_digest(parsed),
        "controller_digest": controller_digest(parsed),
        "combined_traffic_control_digest": combined,
    }


# ---------------------------------------------------------------------------
# v2 canonical traffic-control digests (C0 remediation, R2)
#
# C0 finding: v1 collapses empty OR missing collections to a count-only
# sha256("0") digest, so empty == missing == count-only sha256("0") and a
# parse failure is indistinguishable from an empty document. v2 fixes that
# with a versioned canonical serialization:
#
#   digest = SHA256("phase_q/signal_digest/v2" SEP "<TAG>:<STATE>"
#                   SEP "<count>" ( SEP <flat record> )*)
#
# <STATE> in {PRESENT, EMPTY_COLLECTION, MISSING_COLLECTION, PARSE_FAILURE}.
# Records are sorted by their flat serialization so document order does not
# affect the digest (canonical ordering). Missing vs empty is detected via
# container presence (e.g. a <signals> wrapper). v1 functions above are kept
# unchanged for historical freeze comparison; new frozen authority is v2.
# ---------------------------------------------------------------------------
_V2_PREFIX = "phase_q/signal_digest/v2"
_V2_STATE_PRESENT = "PRESENT"
_V2_STATE_EMPTY = "EMPTY_COLLECTION"
_V2_STATE_MISSING = "MISSING_COLLECTION"
_V2_STATE_PARSE_FAILURE = "PARSE_FAILURE"
_V2_PARSE_FAILURE_DIGEST_TAG = "PARSE_FAILURE"


def _v2_record_key(record: Dict[str, Any]) -> str:
    return SEP.join(str(v) for v in record.values())


def _v2_sorted(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(records, key=_v2_record_key)


def _v2_digest_records(tag: str, state: str, records: List[Dict[str, Any]]) -> str:
    h = hashlib.sha256()
    h.update(_V2_PREFIX.encode("utf-8"))
    h.update(SEP.encode("utf-8"))
    h.update(("{}:{}".format(tag, state)).encode("utf-8"))
    h.update(SEP.encode("utf-8"))
    h.update(str(len(records)).encode("utf-8"))
    for r in _v2_sorted(records):
        h.update(SEP.encode("utf-8"))
        h.update(_v2_record_key(r).encode("utf-8"))
    return h.hexdigest()


def _v2_state(records: List[Dict[str, Any]], container_found: bool) -> str:
    if records:
        return _V2_STATE_PRESENT
    if container_found:
        return _V2_STATE_EMPTY
    return _V2_STATE_MISSING


# v2 container rules: a collection is "present" iff a container element for it
# exists in the tree (e.g. <signal> or <signals> for elements, <signals> for
# references, <controllers> or <controller> for controllers).
def _v2_find_container(root: Any, paths: Tuple[str, ...]) -> bool:
    for path in paths:
        if root.findall(path):
            return True
    return False


def traffic_control_digests_v2(parsed: XodrTree) -> Dict[str, Any]:
    """Versioned canonical traffic-control digests (C0 remediation R2).

    Distiguishes PRESENT / EMPTY_COLLECTION / MISSING_COLLECTION and rejects
    count-only collapses: the digest input prefixes the collection state.
    """
    root = parsed.root
    sig_el = signal_element_list(parsed)
    sig_ref = signal_reference_list_v2(parsed)
    ctrl = controller_list_v2(parsed)

    el_container = _v2_find_container(root, ("road/signals", "road/signal"))
    ref_container = _v2_find_container(root, ("road/signals", "road/signalReference"))
    ctrl_container = _v2_find_container(root, ("controllers", "controller"))

    el_state = _v2_state(sig_el, el_container)
    ref_state = _v2_state(sig_ref, ref_container)
    ctrl_state = _v2_state(ctrl, ctrl_container)

    d_el = _v2_digest_records("SIGNAL_ELEMENT", el_state, sig_el)
    d_ref = _v2_digest_records("SIGNAL_REFERENCE", ref_state, sig_ref)
    d_ctrl = _v2_digest_records("CONTROLLER", ctrl_state, ctrl)

    h = hashlib.sha256()
    h.update(_V2_PREFIX.encode("utf-8"))
    h.update(SEP.encode("utf-8"))
    for tag, state, d in (("SIGNAL_ELEMENT", el_state, d_el),
                          ("SIGNAL_REFERENCE", ref_state, d_ref),
                          ("CONTROLLER", ctrl_state, d_ctrl)):
        h.update(("{}:{}".format(tag, state)).encode("utf-8"))
        h.update(SEP.encode("utf-8"))
        h.update(d.encode("utf-8"))
        h.update(SEP.encode("utf-8"))

    return {
        "schema": "phase_q/signal_digest/v2",
        "schema_version": _header_schema_version(parsed),
        "signal_count": len(sig_el),
        "signal_reference_count": len(sig_ref),
        "controller_count": len(ctrl),
        "signal_element_state": el_state,
        "signal_reference_state": ref_state,
        "controller_state": ctrl_state,
        "parse_failure": False,
        "signal_element_digest": d_el,
        "signal_reference_digest": d_ref,
        "controller_digest": d_ctrl,
        "combined_traffic_control_digest": h.hexdigest(),
    }


def traffic_control_digests_v2_from_text(xodr_text: str) -> Dict[str, Any]:
    """v2 digests for raw XODR text; a malformed document yields a distinct
    PARSE_FAILURE digest instead of silently equal to an empty collection."""
    try:
        parsed = XodrTree(xodr_text)
        return traffic_control_digests_v2(parsed)
    except Exception as exc:  # noqa: BLE001 - parse failure is data, not bug
        return {
            "schema": "phase_q/signal_digest/v2",
            "schema_version": None,
            "signal_count": None,
            "signal_reference_count": None,
            "controller_count": None,
            "signal_element_state": _V2_STATE_PARSE_FAILURE,
            "signal_reference_state": _V2_STATE_PARSE_FAILURE,
            "controller_state": _V2_STATE_PARSE_FAILURE,
            "parse_failure": True,
            "parse_error": "{}: {}".format(type(exc).__name__, exc),
            "signal_element_digest": _V2_PARSE_FAILURE_DIGEST_TAG + ":SIGNAL_ELEMENT",
            "signal_reference_digest": _V2_PARSE_FAILURE_DIGEST_TAG + ":SIGNAL_REFERENCE",
            "controller_digest": _V2_PARSE_FAILURE_DIGEST_TAG + ":CONTROLLER",
            "combined_traffic_control_digest": _V2_PARSE_FAILURE_DIGEST_TAG + ":COMBINED",
        }
def signal_reference_list_v2(parsed: XodrTree) -> List[Dict[str, Any]]:
    """v2 reference inventory: also reads <signals><signalReference> (CARLA
    container convention), not only road-level <signalReference>."""
    root = parsed.root
    recs: List[Dict[str, Any]] = []
    for road in root.findall("road"):
        for ref in road.findall("signalReference") + road.findall("signals/signalReference"):
            recs.append({
                "id": norm_id(ref.get("id")),
                "s": _num(ref.get("s")),
                "t": _num(ref.get("t")),
                "type": norm_id(ref.get("type")),
                "subtype": norm_id(ref.get("subtype")),
                "validities": _validities(ref),
            })
    return recs


def controller_list_v2(parsed: XodrTree) -> List[Dict[str, Any]]:
    """v2 controller inventory: <controller> children of root or of an
    optional <controllers> wrapper (OpenDRIVE 1.7 container form)."""
    root = parsed.root
    recs: List[Dict[str, Any]] = []
    for ctrl in root.findall("controller") + root.findall("controllers/controller"):
        recs.append({
            "id": norm_id(ctrl.get("id")),
            "name": norm_id(ctrl.get("name")),
            "type": norm_id(ctrl.get("type")),
            "delay": _num(ctrl.get("delay")),
            "plugin": norm_id(ctrl.get("plugin")),
        })
    return recs
