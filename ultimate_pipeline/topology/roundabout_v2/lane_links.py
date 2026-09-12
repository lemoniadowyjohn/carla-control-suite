from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class LaneLink:
    source_lane_id: int
    target_lane_id: int
    source: str
    confidence: float

def map_lanes(source_lane_ids: set[int], target_lane_ids: set[int], *, source: str = "topology_order") -> tuple[LaneLink, ...]:
    """Map lanes by lateral order; reject unequal sets instead of inventing links."""
    src = sorted((int(x) for x in source_lane_ids if int(x) != 0), key=lambda x: (abs(x), x))
    dst = sorted((int(x) for x in target_lane_ids if int(x) != 0), key=lambda x: (abs(x), x))
    if not src or not dst:
        raise ValueError("lane mapping requires non-empty source and target driving lanes")
    if len(src) != len(dst):
        raise ValueError("ambiguous lane-count transition requires an explicit split/merge mapping")
    result = tuple(LaneLink(a, b, source, 1.0) for a, b in zip(src, dst))
    # -1 is a real OpenDRIVE rightmost driving-lane ID when it exists in both
    # lane sections; only missing/implicit mappings are rejected above.
    return result

def validate_links(links: tuple[LaneLink, ...], source_lane_ids: set[int], target_lane_ids: set[int]) -> None:
    seen=set()
    for link in links:
        if link.source_lane_id not in source_lane_ids or link.target_lane_id not in target_lane_ids:
            raise ValueError("lane-link references a missing lane")
        key=(link.source_lane_id, link.target_lane_id)
        if key in seen: raise ValueError("duplicate lane-link")
        seen.add(key)
        if not 0.0 <= link.confidence <= 1.0: raise ValueError("lane-link confidence outside [0,1]")
