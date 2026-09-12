"""Shared detection helper for micro-stub (very-short-but-nonzero) roads.

Verified against the pinned map-of-record: 657 roads have a declared
<road length> between 0 and 1.0m, many clustered at suspiciously round
values (0.1, 0.2, 0.3) -- confirmed to be real, drivable junction-internal
connector roads with genuine predecessor/successor links to substantial
roads, not degenerate/broken geometry (that class -- length <= 0.0 -- is
already handled separately by zero_length_connector_repair.py). These are
a legitimate, expected artifact of the OSM->SUMO->Osm2Odr conversion chain,
not a safely-mergeable defect: eliminating them would mean rewriting real
junction topology across hundreds of connector roads.

They do, however, produce unreliable signals in checks that compare a
road's own heading/curvature across its own length or endpoint pose,
because a sub-meter (sometimes sub-decimeter) span can have an
underdetermined or convention-mismatched heading. Consumers doing that
kind of comparison should use is_micro_stub_segment() to identify and
handle these roads with reduced confidence rather than as hard failures.

Separately (and NOT itself a micro-stub-length issue): 137 of the 657
sub-1m roads have a declared <road length> that does not match their true
planView geometry sum by more than 5mm (in several cases the true geometry
is only a few millimeters despite a declared length of 0.1m) -- this is a
distinct, unresolved data-quality gap, not addressed by this helper. See
G3_LENGTH_EPSILON_EVIDENCE.json for the unrelated, already-fixed 1mm
repair_road_lengths margin case, which is a different mechanism.
"""
from __future__ import annotations

MICRO_STUB_THRESHOLD_M = 0.5


def is_micro_stub_segment(length_m: float, threshold_m: float = MICRO_STUB_THRESHOLD_M) -> bool:
    """True when a road/geometry-segment length is short enough that its own
    heading/curvature cannot be trusted as a meaningful physical signal.

    ``length_m`` must be a real, positive length (already-degenerate
    zero/negative lengths are a different defect class -- see
    zero_length_connector_repair.py -- and are not "stubs" in this sense).
    """
    return 0.0 < length_m <= threshold_m
