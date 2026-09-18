#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM-based reviewer for domain gap results.

Input:
- full_report.json (from run_full_domain_gap.py)

Output:
- Markdown report interpreting the domain-gap metrics and heatmaps.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from ultimate_pipeline.llm.llm_client import LLMClient


class LLMDomainGapReviewer:
    def __init__(self, client: Optional[LLMClient] = None) -> None:
        self.client = client or LLMClient()

    def review(
        self,
        full_report_json: str,
        out_md_path: Optional[str] = None,
    ) -> str:
        if not os.path.exists(full_report_json):
            raise FileNotFoundError(full_report_json)

        with open(full_report_json, "r", encoding="utf-8") as f:
            report = json.load(f)

        report_str = json.dumps(report, indent=2)
        if len(report_str) > 7000:
            report_str = report_str[:7000] + "\n\n[...FULL REPORT TRUNCATED...]"

        prompt = f"""
You are analyzing a domain gap study between:

- a manually authored HD map (manual_full.xodr)
- an automatically generated HD map (auto_full.xodr)

You receive a JSON 'full_report' with:
- whole_geometry_gap
- whole_curvature_gap (includes KL-divergence)
- whole_intersection_gap
- whole_semantic_gap
- per_tile_geometry_gap (RMSE XY)
- per_tile_curvature_gap (KL-div)
- tile_matches
- perception_gap (may be null)

Tasks:

1. Provide a concise textual summary of the domain gap between manual and auto map.
2. Identify which aspects are most problematic (geometry, curvature, intersections, semantics, perception).
3. Explain what the per-tile gaps imply (e.g. localized trouble spots vs global drift).
4. Suggest at least 5 concrete improvements to the automatic pipeline.
5. Comment briefly on whether the automatic map is "good enough" for perception training, given the metrics.

Output Markdown with sections:

# Domain Gap Summary
# Main Problem Areas
# Spatial Pattern of Errors
# Recommendations for Pipeline Improvements
# Suitability for Perception Training

---

FULL_REPORT.JSON (TRUNCATED):

{report_str}
"""

        answer = self.client.ask(prompt)

        if out_md_path:
            os.makedirs(os.path.dirname(out_md_path), exist_ok=True)
            with open(out_md_path, "w", encoding="utf-8") as f:
                f.write(answer)

        return answer
