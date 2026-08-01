#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM-based safety assistant.

Goal:
- Give qualitative safety feedback on map usage, traffic density, pedestrians, etc.
- This is purely advisory and does NOT replace safety engineering.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from ultimate_pipeline.llm.llm_client import LLMClient


class LLMSafetyAssistant:
    def __init__(self, client: Optional[LLMClient] = None) -> None:
        self.client = client or LLMClient()

    def review_safety(
        self,
        validation_report_path: str,
        scenario_description: str = "",
        out_md_path: Optional[str] = None,
    ) -> str:
        """
        scenario_description: free text from you, e.g.
            "Urban map, ~20 NPC vehicles, 10 pedestrians, ego on autopilot."
        """
        if not os.path.exists(validation_report_path):
            raise FileNotFoundError(validation_report_path)

        with open(validation_report_path, "r", encoding="utf-8") as f:
            report = json.load(f)

        rep_str = json.dumps(report, indent=2)
        if len(rep_str) > 5000:
            rep_str = rep_str[:5000] + "\n\n[...VALIDATION REPORT TRUNCATED...]"

        prompt = f"""
You are acting as a virtual safety engineer for an autonomous driving simulator.

You are given:
- A validation report for an HD map (OpenDRIVE for CARLA).
- A short free-text description of planned scenarios: NPC density, pedestrians, ego behaviour.

Your tasks:
1. Identify potential safety pitfalls for simulation:
    - Unrealistic geometry or lane behavior
    - Dangerous intersections
    - Missing or weird traffic lights
    - Pedestrian / vehicle interactions that could be misleading
2. Suggest safe configuration ranges for:
    - number of vehicles / pedestrians
    - ego vehicle speed
    - traffic light timing realism
3. Recommend extra safety checks a human should do before training / demos.

Output Markdown:

# Scenario Description
# Potential Simulation Safety Issues
# Recommended Safe Configuration Ranges
# Extra Safety Checks

---

SCENARIO DESCRIPTION:
{scenario_description}

---

VALIDATION REPORT (TRUNCATED JSON):
{rep_str}
"""

        answer = self.client.ask(prompt)

        if out_md_path:
            os.makedirs(os.path.dirname(out_md_path), exist_ok=True)
            with open(out_md_path, "w", encoding="utf-8") as f:
                f.write(answer)

        return answer
