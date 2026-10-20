"""Independent oracles.

An oracle observes the *system under test*, not the mutator's own claim. Each
returns an evidence-carrying verdict and an explicit confidence.

The rule that matters: **never PASS when the oracle cannot observe the
condition.** Those cases are ``INCONCLUSIVE`` or ``UNVERIFIED`` -- exactly the
distinction the Task 02 ``RunStatus`` vocabulary exists to express.

In particular: geometry continuity has **no made-up GAP-026 acceptance
threshold**. The oracle reports the measured discontinuity and defers; it does
not invent a number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from ultimate_pipeline.gui.run_status import RunStatus
from ultimate_pipeline.gui.sensors.queues import Frame

__all__ = [
    "Verdict", "OracleResult", "ORACLES", "oracle_registry",
    "xml_safe_parse", "lane_width_invariant", "road_s_invariant",
    "lane_link_integrity", "determinism_signature", "geometry_continuity",
    "actor_cap", "cleanup_leak_check", "sync_restored", "sensor_frame_attribution",
    "replay_verdict_match", "tm_write_only_ack",
]


class Verdict(str, Enum):
    """Oracle verdicts. Reuses the normalised Task 02 vocabulary."""

    PASS = RunStatus.PASS.value
    FAIL = RunStatus.FAIL.value
    INCONCLUSIVE = RunStatus.INCONCLUSIVE.value
    UNVERIFIED = RunStatus.NOT_EVALUATED.value
    BLOCKED_EXTERNAL = RunStatus.BLOCKED_EXTERNAL.value


@dataclass
class OracleResult:
    """Evidence, confidence, and expected-versus-actual. Never a bare bool."""

    oracle: str
    verdict: str
    evidence: dict
    confidence: str            # HIGH | MEDIUM | LOW | NONE
    expected: str = ""
    actual: str = ""
    observable: bool = True

    @property
    def passed(self) -> bool:
        return self.verdict == Verdict.PASS

    def as_dict(self) -> dict:
        return {"oracle": self.oracle, "verdict": self.verdict,
                "confidence": self.confidence, "expected": self.expected,
                "actual": self.actual, "observable": self.observable,
                "evidence": self.evidence}


# ------------------------------------------------------------------ helpers
def _result(oracle: str, verdict: str, evidence: dict, confidence: str,
            expected: str = "", actual: str = "", observable: bool = True) -> OracleResult:
    return OracleResult(oracle, verdict, evidence, confidence, expected, actual, observable)


# ------------------------------------------------------------------ oracles
def xml_safe_parse(payload: str, *, site: str = "fuzz") -> OracleResult:
    """Independent observation: did the parser refuse the hostile document?"""
    from ultimate_pipeline.gui.maps.secure_xml import XmlRefusal, _prescan

    try:
        _prescan(payload, __import__(
            "ultimate_pipeline.gui.maps.secure_xml", fromlist=["DEFAULT_LIMITS"]
        ).DEFAULT_LIMITS)
    except XmlRefusal as refusal:
        return _result("xml_safe_parse", Verdict.PASS,
                       {"refused": True, "reason": refusal.reason}, "HIGH",
                       expected="REFUSED", actual="REFUSED")
    return _result("xml_safe_parse", Verdict.FAIL,
                   {"refused": False}, "HIGH",
                   expected="REFUSED", actual="ACCEPTED")


def lane_width_invariant(widths: Iterable[float]) -> OracleResult:
    """Lane widths must be strictly positive and finite."""
    values = list(widths)
    if not values:
        return _result("lane_width_invariant", Verdict.UNVERIFIED, {"count": 0},
                       "NONE", expected="all widths > 0", actual="no lanes observed")
    bad = [w for w in values if not math.isfinite(w) or w <= 0.0]
    verdict = Verdict.FAIL if bad else Verdict.PASS
    return _result("lane_width_invariant", verdict,
                   {"count": len(values), "violations": bad}, "HIGH",
                   expected="all widths > 0", actual=f"{len(bad)} violation(s)")


def road_s_invariant(s_values: Iterable[float]) -> OracleResult:
    """Road ``s`` must be non-negative and non-decreasing along the road."""
    values = list(s_values)
    if not values:
        return _result("road_s_invariant", Verdict.UNVERIFIED, {"count": 0}, "NONE",
                       expected="s >= 0 and non-decreasing",
                       actual="no s values observed")
    violations = [v for v in values if v < 0.0]
    regressions = sum(1 for a, b in zip(values, values[1:]) if b < a)
    verdict = Verdict.FAIL if (violations or regressions) else Verdict.PASS
    return _result("road_s_invariant", verdict,
                   {"count": len(values), "negative": violations,
                    "regressions": regressions}, "HIGH",
                   expected="s >= 0 and non-decreasing",
                   actual=f"{len(violations)} negative, {regressions} regressions")


def lane_link_integrity(lane_ids: Iterable[int],
                        links: Iterable[tuple[int, int]]) -> OracleResult:
    """Every lane link endpoint must exist in the lane set."""
    known = set(lane_ids)
    pairs = list(links)
    if not known:
        return _result("lane_link_integrity", Verdict.UNVERIFIED, {"lanes": 0}, "NONE",
                       expected="all endpoints resolve", actual="no lanes observed")
    dangling = [{"from": a, "to": b} for a, b in pairs
                if a not in known or b not in known]
    verdict = Verdict.FAIL if dangling else Verdict.PASS
    return _result("lane_link_integrity", verdict,
                   {"lanes": len(known), "links": len(pairs), "dangling": dangling},
                   "HIGH", expected="all endpoints resolve",
                   actual=f"{len(dangling)} dangling")


def determinism_signature(runs: Iterable[str]) -> OracleResult:
    """Identical inputs must produce identical signatures across runs."""
    signatures = list(runs)
    if len(signatures) < 2:
        return _result("determinism_signature", Verdict.UNVERIFIED,
                       {"runs": len(signatures)}, "NONE",
                       expected=">= 2 runs to compare", actual="insufficient runs")
    verdict = Verdict.PASS if len(set(signatures)) == 1 else Verdict.FAIL
    return _result("determinism_signature", verdict,
                   {"runs": len(signatures), "distinct": len(set(signatures))},
                   "HIGH", expected="one distinct signature",
                   actual=f"{len(set(signatures))} distinct")


def geometry_continuity(points: Iterable[tuple[float, float, float]],
                        *, max_step_m: float | None = None) -> OracleResult:
    """Measure the discontinuity; do NOT invent a GAP-026 acceptance threshold.

    ``max_step_m`` is supplied by the caller. When it is absent the oracle
    reports the measured maximum step and returns ``INCONCLUSIVE`` -- it does
    not fall back to a made-up bound.
    """
    pts = list(points)
    if len(pts) < 2:
        return _result("geometry_continuity", Verdict.UNVERIFIED,
                       {"points": len(pts)}, "NONE",
                       expected="a continuity measure", actual="too few points")
    steps = [
        math.dist(a, b) for a, b in zip(pts, pts[1:])
    ]
    worst = max(steps)
    evidence = {"points": len(pts), "max_step_m": worst, "steps": steps}
    if max_step_m is None:
        return _result("geometry_continuity", Verdict.INCONCLUSIVE, evidence, "NONE",
                       expected="an owner-approved max step",
                       actual=f"measured max step {worst:.3f} m",
                       observable=False)
    verdict = Verdict.FAIL if worst > max_step_m else Verdict.PASS
    return _result("geometry_continuity", verdict, evidence, "HIGH",
                   expected=f"max step <= {max_step_m} m",
                   actual=f"{worst:.3f} m")


def actor_cap(declared: int, cap: int) -> OracleResult:
    verdict = Verdict.FAIL if declared > cap else Verdict.PASS
    return _result("actor_cap", verdict, {"declared": declared, "cap": cap}, "HIGH",
                   expected=f"<= {cap} actors", actual=str(declared))


def cleanup_leak_check(leaked: Iterable[int]) -> OracleResult:
    ids = sorted(leaked)
    verdict = Verdict.FAIL if ids else Verdict.PASS
    return _result("cleanup_leak_check", verdict, {"leaked": ids}, "HIGH",
                   expected="no leaked actor ids", actual=f"{len(ids)} leaked")


def sync_restored(restored: bool) -> OracleResult:
    verdict = Verdict.PASS if restored else Verdict.FAIL
    return _result("sync_restored", verdict, {"restored": restored}, "HIGH",
                   expected="synchronous settings restored", actual=str(restored))


def sensor_frame_attribution(frame: Frame | None) -> OracleResult:
    """A frame with no id cannot be attributed. Never fabricate one.

    Defensive by design: an oracle observes arbitrary system output, so a
    malformed object must produce a verdict rather than an exception.
    """
    if frame is None:
        return _result("sensor_frame_attribution", Verdict.UNVERIFIED, {}, "NONE",
                       expected="a frame with an id", actual="no frame supplied")
    frame_id = getattr(frame, "frame_id", None)
    if frame_id is None:
        return _result("sensor_frame_attribution", Verdict.FAIL,
                       {"frame_id": None}, "HIGH",
                       expected="a real frame id", actual="missing frame id")
    return _result("sensor_frame_attribution", Verdict.PASS,
                   {"frame_id": frame_id}, "HIGH",
                   expected="a real frame id", actual=str(frame_id))


def replay_verdict_match(recorded: str, replayed: str) -> OracleResult:
    verdict = Verdict.PASS if recorded == replayed else Verdict.FAIL
    return _result("replay_verdict_match", verdict,
                   {"recorded": recorded, "replayed": replayed}, "HIGH",
                   expected=recorded, actual=replayed)


def tm_write_only_ack(setter: str, readable: bool) -> OracleResult:
    """TM setters in 0.9.16 are write-only: acknowledgement is not confirmation."""
    verdict = Verdict.INCONCLUSIVE if not readable else Verdict.PASS
    return _result("tm_write_only_ack", verdict,
                   {"setter": setter, "readable": readable}, "MEDIUM",
                   expected="acknowledged (not confirmed)",
                   actual="unreadable in CARLA 0.9.16", observable=readable)


#: Every oracle with the conditions under which it becomes observable.
ORACLES: dict[str, Callable[..., OracleResult]] = {
    "xml_safe_parse": xml_safe_parse,
    "lane_width_invariant": lane_width_invariant,
    "road_s_invariant": road_s_invariant,
    "lane_link_integrity": lane_link_integrity,
    "determinism_signature": determinism_signature,
    "geometry_continuity": geometry_continuity,
    "actor_cap": actor_cap,
    "cleanup_leak_check": cleanup_leak_check,
    "sync_restored": sync_restored,
    "sensor_frame_attribution": sensor_frame_attribution,
    "replay_verdict_match": replay_verdict_match,
    "tm_write_only_ack": tm_write_only_ack,
}


class _OracleRegistry(dict):
    pass


def oracle_registry() -> dict[str, Callable[..., OracleResult]]:
    return dict(ORACLES)