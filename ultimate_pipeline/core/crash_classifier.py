# ultimate_pipeline/core/crash_classifier.py
from __future__ import annotations

import os
import re
from typing import Optional


class CrashClassifier:
    """Classify CARLA/SUMO crashes by scanning log text.

    Notes:
      - CARLA can crash natively; this classifier is best-effort and depends on
        having access to the server log (or redirected stdout/stderr).
      - We intentionally keep categories coarse; they are used to route triage
        and produce thesis-friendly failure taxonomies.
    """

    GEOMETRY_OVERFLOW = "GEOMETRY_OVERFLOW"
    FLOAT_ERROR = "FLOAT_ERROR"
    S_INVARIANT = "S_INVARIANT"  # e.g. "s >= 0.0"
    LANE_WIDTH_ERROR = "LANE_WIDTH_ERROR"
    MISSING_LINK = "MISSING_LINK"
    JUNCTION_REF_ERROR = "JUNCTION_REF_ERROR"
    TOPOLOGY_BROKEN = "TOPOLOGY_BROKEN"
    FILE_IO_ERROR = "FILE_IO_ERROR"
    ENGINE_FATAL = "ENGINE_FATAL"
    PHYSX_ERROR = "PHYSX_ERROR"
    PLANVIEW_ERROR = "PLANVIEW_ERROR"
    LANE_OFFSET_ERROR = "LANE_OFFSET_ERROR"
    UNKNOWN = "UNKNOWN"

    # Patterns are evaluated in priority order (first match wins).
    _CARLA_RULES = [
        (S_INVARIANT, [
            r"\bs\s*>=\s*0\.0\b",
            r"Exception thrown:\s*s\s*>=\s*0\.0",
            r"assert.*s\s*>=\s*0\.0",
        ]),
        (LANE_OFFSET_ERROR, [
            r"laneoffset", r"invalid lane offset", r"offset.*nan", r"offset.*inf"
        ]),
        (PLANVIEW_ERROR, [
            r"planview", r"geometry.*invalid", r"arc.*problem", r"curve.*fail", r"spiral.*fail"
        ]),
        (FLOAT_ERROR, [
            r"\bnan\b", r"\binf\b", r"floating point", r"float.*overflow"
        ]),
        (PHYSX_ERROR, [
            r"physx", r"heightfield", r"trianglemesh", r"contact.*pair"
        ]),
        (GEOMETRY_OVERFLOW, [
            r"triangulation", r"degenerate", r"invalid mesh", r"overlapping", r"poly.*fail"
        ]),
        (FILE_IO_ERROR, [
            r"copy_opendrive_to_file", r"failed to open", r"permission denied", r"no such file"
        ]),
        (ENGINE_FATAL, [
            r"exception_access_violation", r"lowlevelfatalerror", r"fatal error", r"unhandled exception", r"ensurefailed"
        ]),
    ]

    _SUMO_RULES = [
        (GEOMETRY_OVERFLOW, [
            r"error.*geometry", r"invalid shape", r"self-intersection", r"overlapping geometry"
        ]),
        (MISSING_LINK, [
            r"missing.*connection", r"edge.*has no successor", r"incoming.*missing"
        ]),
        (JUNCTION_REF_ERROR, [
            r"junction.*error", r"connectingroad", r"incomingroad", r"connection.*reference"
        ]),
        (LANE_WIDTH_ERROR, [
            r"lane.*width", r"negative.*width", r"width.*too small"
        ]),
        (FILE_IO_ERROR, [
            r"cannot open", r"no such file", r"permission denied"
        ]),
    ]

    @staticmethod
    def extract_recent_log(path: str, tail: int = 200) -> str:
        if not path:
            return ""
        try:
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            return "".join(lines[-tail:])
        except Exception:
            return ""

    @classmethod
    def _match_rules(cls, text: str, rules) -> Optional[str]:
        if not text:
            return None
        low = text.lower()
        for category, pats in rules:
            for p in pats:
                try:
                    if re.search(p, low, flags=re.IGNORECASE):
                        return category
                except re.error:
                    if p.lower() in low:
                        return category
        return None

    @classmethod
    def classify(cls, *, carla_log: str = "", sumo_log: str = "") -> str:
        c = cls._match_rules(carla_log, cls._CARLA_RULES)
        if c:
            return c
        s = cls._match_rules(sumo_log, cls._SUMO_RULES)
        if s:
            return s
        return cls.UNKNOWN
