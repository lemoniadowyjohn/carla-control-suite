from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Sequence

from ultimate_pipeline.domain_gap.elevation_invariants import (
    check_strict_monotonic_s,
    check_smooth_height,
    check_non_decreasing_s,
    check_total_length,
)


@dataclass(frozen=True)
class ElevationSegment:
    s_start: float
    s_end: float
    height_start: float
    height_end: float
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    d: float = 0.0

    def height_at(self, s: float) -> float:
        ds = s - self.s_start
        return self.a + self.b * ds + self.c * ds ** 2 + self.d * ds ** 3


@dataclass
class ElevationProfile:
    road_id: str
    length: float
    segments: list[ElevationSegment] = field(default_factory=list)

    @property
    def total_elevation_length(self) -> float:
        return sum(s.s_end - s.s_start for s in self.segments)

    def height_at(self, s: float) -> float | None:
        if not self.segments:
            return None
        if s < self.segments[0].s_start or s > self.segments[-1].s_end:
            return None
        for seg in self.segments:
            if seg.s_start <= s <= seg.s_end:
                return seg.height_at(s)
        return None

    @classmethod
    def from_xml(cls, road_elem: ET.Element) -> ElevationProfile:
        road_id = road_elem.get("id", "")
        length = float(road_elem.get("length", "0"))
        profile = cls(road_id=road_id, length=length)
        raw: list[ElevationSegment] = []
        for elev_elem in road_elem.findall("elevationProfile/elevation"):
            seg = ElevationSegment(
                s_start=float(elev_elem.get("s", "0")),
                s_end=float(elev_elem.get("s", "0")),
                height_start=float(elev_elem.get("a", "0")),
                height_end=float(elev_elem.get("a", "0")),
                a=float(elev_elem.get("a", "0")),
                b=float(elev_elem.get("b", "0")),
                c=float(elev_elem.get("c", "0")),
                d=float(elev_elem.get("d", "0")),
            )
            raw.append(seg)
        resolved: list[ElevationSegment] = []
        for i, seg in enumerate(raw):
            s_end = raw[i + 1].s_start if i + 1 < len(raw) else length
            resolved.append(ElevationSegment(
                s_start=seg.s_start, s_end=s_end,
                height_start=seg.a, height_end=seg.height_at(s_end),
                a=seg.a, b=seg.b, c=seg.c, d=seg.d,
            ))
        profile.segments = resolved
        return profile


@dataclass
class ElevationReport:
    road_id: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    profile: ElevationProfile | None = None

    def to_dict(self) -> dict:
        return {
            "road_id": self.road_id,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "segment_count": len(self.profile.segments) if self.profile else 0,
        }


class ElevationContract:
    def __init__(
        self,
        height_tol: float = 1e-4,
        s_tol: float = 1e-6,
        length_tol: float = 1e-3,
        auto_correct: bool = False,
    ):
        self.height_tol = height_tol
        self.s_tol = s_tol
        self.length_tol = length_tol
        self.auto_correct = auto_correct

    def validate(self, road_elem: ET.Element) -> ElevationReport:
        profile = ElevationProfile.from_xml(road_elem)
        report = ElevationReport(road_id=profile.road_id, passed=False, profile=profile)
        errors: list[str] = []
        errors.extend(check_strict_monotonic_s(profile.segments, self.s_tol))
        errors.extend(check_smooth_height(profile.segments, self.height_tol))
        errors.extend(check_non_decreasing_s(profile.segments, self.s_tol))
        errors.extend(check_total_length(profile.segments, profile.length, self.length_tol))
        report.errors = errors
        report.passed = len(errors) == 0
        return report
