# ultimate_pipeline/core/repair_diff.py

from __future__ import annotations

import json
from typing import Any, Dict, List


class RepairDiff:
    """
    Global, append-only repair provenance log.

    Usage:
        from ultimate_pipeline.core.repair_diff import diff_log

        diff_log.add("geometry_validator", "42", {"fix": "clamped_curvStart", "value": 0.9})
        diff_log.save("repair_diff.json")
    """

    def __init__(self) -> None:
        # stage_name -> list of events
        self._events: Dict[str, List[Dict[str, Any]]] = {}

    def add(self, stage: str, road_id: str, payload: Dict[str, Any]) -> None:
        """
        Record a single repair event.

        :param stage: logical module name, e.g. "geometry_validator"
        :param road_id: XODR road.id
        :param payload: structured info about the change
        """
        if stage not in self._events:
            self._events[stage] = []
        entry = {"road_id": road_id}
        entry.update(payload)
        self._events[stage].append(entry)

    def to_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        return self._events

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._events, f, indent=2)


# Global singleton instance used across the pipeline
diff_log = RepairDiff()
