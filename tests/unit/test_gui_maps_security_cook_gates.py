"""Task 07 acceptance tests: hardened XML, map identity, cooking, gates.

Covers T-SEC-01..08, T-COOK-01..06, T-COOK-BUDGET-01..04, T-MAP-PROBE-01 and
T-GATE-01..04.

Offline. No cook is ever executed; the adapter refuses before it could reach
``make import`` or ``UnrealEditor-Cmd``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ultimate_pipeline.gui.maps.cook import (
    CookBudget,
    CookCapability,
    MapCookingAdapter,
    ProbeOutcome,
    bind_runtime_identity,
    probe_maps,
)
from ultimate_pipeline.gui.maps.secure_xml import (
    PARSING_SITES,
    XmlLimits,
    XmlRefusal,
    defusedxml_available,
    parse_untrusted_xml,
    resolve_inside,
    try_parse,
)
from ultimate_pipeline.gui.maps.cook import MapPin, MapRegistry, VerifyOutcome
from ultimate_pipeline.gui.maps.gates import (
    GAP026_RECORD,
    GateStatus,
    TILE_FRAME_CONSISTENCY,
    accept_suite,
    gate_taxonomy_status,
    run_gates,
)


BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<OpenDRIVE><road name="&lol2;"/></OpenDRIVE>
"""

XXE = """<?xml version="1.0"?>
<!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
<OpenDRIVE><road name="&xxe;"/></OpenDRIVE>
"""

DEFAULT_TEST_LIMITS = XmlLimits()
PLAIN = """<?xml version="1.0"?>
<OpenDRIVE><road id="1" name="ok"/></OpenDRIVE>
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ================================================================= T-SEC
def test_T_SEC_01_all_eleven_parsing_sites_are_centrally_listed():
    assert len(PARSING_SITES) == 11
    kinds = {k for k, _ in PARSING_SITES}
    assert kinds == {"xodr", "osm", "roadrunner", "sensors"}
    for kind, path in PARSING_SITES:
        assert path.startswith(("ultimate_pipeline/", "tools/", "phase_q/")), path


def test_T_SEC_02_doctype_is_refused(tmp_path):
    p = _write(tmp_path, "billion.xml", BILLION_LAUGHS)
    with pytest.raises(XmlRefusal) as exc:
        parse_untrusted_xml(p, site="xodr")
    assert "DOCTYPE" in exc.value.reason


def test_T_SEC_03_xxe_entity_is_refused(tmp_path):
    p = _write(tmp_path, "xxe.xml", XXE)
    with pytest.raises(XmlRefusal) as exc:
        parse_untrusted_xml(p, site="xodr")
    # A DOCTYPE-bearing payload is refused at the DOCTYPE gate, which is the
    # stricter and earlier check -- an external-entity payload always has one.
    assert "DOCTYPE" in exc.value.reason


def test_T_SEC_03b_bare_entity_declaration_is_refused_by_prescan():
    from ultimate_pipeline.gui.maps.secure_xml import _prescan

    with pytest.raises(XmlRefusal) as exc:
        _prescan('<r><!ENTITY evil "x"></r>', DEFAULT_TEST_LIMITS)
    assert "entity" in exc.value.reason.lower()

    with pytest.raises(XmlRefusal):
        _prescan('<r>%payload;</r>', DEFAULT_TEST_LIMITS)


def test_T_SEC_04_parameter_entity_reference_is_refused(tmp_path):
    p = _write(tmp_path, "param.xml",
               '<?xml version="1.0"?><r><n>%payload;</n></r>')
    with pytest.raises(XmlRefusal):
        parse_untrusted_xml(p, site="xodr")


def test_T_SEC_05_oversized_payload_is_refused_on_bytes(tmp_path):
    limits = XmlLimits(max_bytes=64)
    p = _write(tmp_path, "big.xml", PLAIN * 50)
    with pytest.raises(XmlRefusal) as exc:
        parse_untrusted_xml(p, site="xodr", limits=limits)
    assert "exceeds" in exc.value.reason


def test_T_SEC_06_excessive_nesting_depth_is_refused(tmp_path):
    deep = "<a>" * 200 + "</a>" * 200
    p = _write(tmp_path, "deep.xml", deep)
    with pytest.raises(XmlRefusal) as exc:
        parse_untrusted_xml(p, site="xodr", limits=XmlLimits(max_depth=32))
    assert "nesting depth" in exc.value.reason


def test_T_SEC_07_path_traversal_is_refused(tmp_path):
    base = tmp_path / "maps"
    base.mkdir()
    with pytest.raises(XmlRefusal) as exc:
        resolve_inside(base, "../../etc/passwd")
    assert "escapes" in exc.value.reason
    with pytest.raises(XmlRefusal):
        resolve_inside(base, "C:/Windows/System32")
    assert resolve_inside(base, "Town01.xodr").name == "Town01.xodr"


def test_T_SEC_08_wellformed_payload_parses_and_refusal_is_typed(tmp_path):
    good = _write(tmp_path, "ok.xml", PLAIN)
    root = parse_untrusted_xml(good, site="xodr")
    assert root.tag == "OpenDRIVE"

    tree, refused = try_parse(_write(tmp_path, "bad.xml", XXE), site="osm")
    assert tree is None and refused is not None
    assert refused.as_dict()["refused"] is True
    assert "DOCTYPE" in refused.reason

    broken = _write(tmp_path, "broken.xml", "<OpenDRIVE><road></OpenDRIVE>")
    tree2, refused2 = try_parse(broken, site="xodr")
    assert tree2 is None and refused2 is not None
    assert "well-formed" in refused2.remediation


# ================================================================= map registry
def _registry(tmp_path: Path, *, blob: bytes, sha: str) -> MapRegistry:
    reg = MapRegistry(tmp_path)
    (tmp_path / "Town01.xodr").write_bytes(blob)
    reg.add(MapPin("Town01", "Town01.xodr", sha))
    return reg


def test_map_verify_is_fail_closed_on_every_refusal_mode(tmp_path):
    good = PLAIN.encode()
    reg = _registry(tmp_path, blob=good, sha=hashlib.sha256(good).hexdigest())
    assert reg.verify("Town01").ok is True
    assert reg.verify("Nope").outcome == VerifyOutcome.UNKNOWN_NAME.value

    # sha drift
    (tmp_path / "Town01.xodr").write_bytes(PLAIN.encode() + b"<!-- changed -->")
    drifted = reg.verify("Town01")
    assert drifted.outcome == VerifyOutcome.SHA_DRIFT.value
    assert "do not promote" in drifted.remediation

    # unresolved LFS pointer
    (tmp_path / "Town01.xodr").write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:x")
    assert reg.verify("Town01").outcome == VerifyOutcome.LFS_POINTER.value
    assert reg.verify("Town01").remediation == "run git lfs pull"

    # not a file
    (tmp_path / "Town01.xodr").unlink()
    assert reg.verify("Town01").outcome == VerifyOutcome.NOT_A_FILE.value

    # empty file
    (tmp_path / "Town01.xodr").write_bytes(b"")
    assert reg.verify("Town01").outcome == VerifyOutcome.EMPTY_FILE.value


def test_registry_path_escape_is_refused(tmp_path):
    reg = MapRegistry(tmp_path)
    reg.add(MapPin("Escape", "../../outside.xodr", "0" * 64))
    assert reg.verify("Escape").outcome == VerifyOutcome.PATH_ESCAPE.value


def test_runtime_identity_is_bound_to_fingerprint_not_name(tmp_path):
    good = PLAIN.encode()
    reg = _registry(tmp_path, blob=good, sha=hashlib.sha256(good).hexdigest())
    pin_sha = hashlib.sha256(good).hexdigest()

    trusted = bind_runtime_identity("Town01", pin_sha, reg)
    assert trusted.trusted is True

    impostor = bind_runtime_identity("Town01", "f" * 64, reg)
    assert impostor.trusted is False
    assert "NOT the pinned map" in impostor.reason

    unknown = bind_runtime_identity("Ghost", "a" * 64, reg)
    assert unknown.trusted is False


# ================================================================= T-MAP-PROBE
def test_T_MAP_PROBE_01_unavailable_is_distinct_from_zero_maps():
    class Tri:
        def __init__(self, state, value=None, reason=""):
            self.state, self.value, self.reason = state, value, reason

    unavailable = probe_maps(Tri("PROBE_UNSUPPORTED", reason="stub backend"))
    assert unavailable.outcome == ProbeOutcome.UNAVAILABLE.value
    assert "capability gap" in unavailable.remediation

    zero = probe_maps(Tri("EMPTY", reason="no maps"))
    assert zero.outcome == ProbeOutcome.ZERO_MAPS.value
    assert unavailable.outcome != zero.outcome

    ok = probe_maps(Tri("AVAILABLE", ["Town01", "Town02"]))
    assert ok.outcome == ProbeOutcome.OK.value and len(ok.maps) == 2


# ================================================================= T-COOK
def test_T_COOK_01_cooking_is_blocked_without_an_operator_install():
    adapter = MapCookingAdapter()
    report = adapter.diagnose(editor_installed=False)
    assert report.capability == CookCapability.BLOCKED_OPERATOR_INSTALL.value
    assert report.can_cook is False
    assert "install UE4.26" in report.remediation


def test_T_COOK_02_cook_refuses_and_never_launches_a_tool():
    adapter = MapCookingAdapter(editor_path="C:/UE_4.26/UnrealEditor-Cmd.exe")
    result = adapter.cook(free_disk_gib=500.0, total_vram_mib=6144)
    assert result.ok is False
    # the refusal happens on approval grounds even with an editor present
    assert "explicit approval" in result.reason or "blocked" in result.reason


def test_T_COOK_03_capability_diagnosis_is_explicit():
    adapter = MapCookingAdapter(editor_path="C:/UE_4.26/UnrealEditor-Cmd.exe")
    report = adapter.diagnose()
    assert report.editor_installed is True
    assert report.editor_path.endswith("UnrealEditor-Cmd.exe")


def test_T_COOK_04_too_small_a_vram_budget_is_refused():
    adapter = MapCookingAdapter(editor_path="C:/UE/x.exe",
                                budget=CookBudget(max_vram_mib=8192))
    report = adapter.diagnose()
    assert report.can_cook is False
    assert any("headroom" in r or "below the full device" in r for r in report.reasons)


def test_T_COOK_05_budget_checks_enforce_disk_and_vram():
    adapter = MapCookingAdapter(budget=CookBudget(free_disk_gib_required=80.0,
                                                 max_vram_mib=5632))
    assert adapter.check_budgets(10.0, 6144).ok is False
    assert adapter.check_budgets(500.0, 1024).ok is False
    assert adapter.check_budgets(500.0, 6144).ok is True


def test_T_COOK_06_cancellation_is_honoured_before_any_work():
    from ultimate_pipeline.gui.cancellation import CancellationToken, OperationCancelled

    token = CancellationToken()
    token.cancel("operator stop")
    adapter = MapCookingAdapter()
    with pytest.raises(OperationCancelled):
        adapter.cook(free_disk_gib=500.0, total_vram_mib=6144, token=token)


def test_T_COOK_BUDGET_vram_ceiling_leaves_headroom():
    # the ceiling must never equal the full device capacity
    assert CookBudget().max_vram_mib < 6144
    adapter = MapCookingAdapter(budget=CookBudget(max_vram_mib=6144))
    assert adapter.check_budgets(500.0, 6144).ok is False


# ================================================================= T-GATE
def test_T_GATE_01_supplied_versus_silently_skipped_are_distinguished():
    suite = run_gates({"topology": True}, requested=["topology", "hash", "elevation"])
    statuses = {o.name: o.status for o in suite.outcomes}
    assert statuses["topology"] == GateStatus.PASS.value
    assert statuses["hash"] == GateStatus.NOT_SUPPLIED.value
    assert statuses["elevation"] == GateStatus.NOT_SUPPLIED.value
    assert [o.name for o in suite.not_supplied] == ["hash", "elevation"]
    assert suite.all_green is False


def test_T_GATE_02_invalid_metric_is_never_corrected_to_a_pass():
    suite = run_gates({"tile_frame_consistency": "INVALID", "topology": True})
    status = {o.name: o.status for o in suite.outcomes}["tile_frame_consistency"]
    assert status == GateStatus.INVALID_METRIC.value
    assert TILE_FRAME_CONSISTENCY["status"] == GateStatus.INVALID_METRIC.value
    assert suite.all_green is False


def test_T_GATE_03_gap026_stays_unresolved_and_blocks_acceptance():
    suite = run_gates({"topology": True, "hash": True, "elevation": True})
    decision = accept_suite(suite)
    assert decision.ok is False
    assert "GAP-026" in decision.reason
    assert GAP026_RECORD["failed_lane_links"] == 2992
    assert GAP026_RECORD["total_lane_links"] == 23529
    assert GAP026_RECORD["waivable"] is False


def test_T_GATE_04_non_waivable_taxonomy_is_proposed_until_q12_is_decided():
    pending = gate_taxonomy_status(operator_decided_q12=False)
    assert pending.ok is False
    assert "PROPOSED" in pending.reason

    decided = gate_taxonomy_status(operator_decided_q12=True)
    assert decided.ok is True
    assert "GAP-026" in decided.unwrap()["non_waivable"]


def test_gate_results_never_invent_a_verdict():
    suite = run_gates({"weird": "BANANA", "empty": None, "skipped": "SKIPPED",
                       "blocked": "BLOCKED", "bad": False})
    statuses = {o.name: o.status for o in suite.outcomes}
    assert statuses["weird"] == GateStatus.NOT_EVALUATED.value
    assert statuses["empty"] == GateStatus.NOT_EVALUATED.value
    assert statuses["skipped"] == GateStatus.SKIPPED.value
    assert statuses["blocked"] == GateStatus.BLOCKED.value
    assert statuses["bad"] == GateStatus.FAIL.value
    assert all(o.status != GateStatus.PASS.value for o in suite.outcomes)
