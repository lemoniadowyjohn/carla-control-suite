#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM-based quality gate on top of deterministic validation.

Takes:
- final_out.xodr
- validation_report_full.json

Produces:
- A human-readable Markdown verdict that can be archived with the map.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from ultimate_pipeline.llm.llm_client import LLMClient


class LLMQualityGate:
    def __init__(self, client: Optional[LLMClient] = None) -> None:
        self.client = client or LLMClient()

    @staticmethod
    def review_gate_failures(failures_dict):
        md = []
        for gate, info in failures_dict.items():
            md.append(f"## ❌ Gate Failed: {gate}\n")
            md.append("Details:\n")
            md.append("```json\n" + json.dumps(info, indent=2) + "\n```")
        return "\n".join(md)

    def review(
        self,
        xodr_path: str,
        validation_report_path: str,
        out_md_path: Optional[str] = None,
    ) -> str:
        if not os.path.exists(xodr_path):
            raise FileNotFoundError(xodr_path)
        if not os.path.exists(validation_report_path):
            raise FileNotFoundError(validation_report_path)

        with open(validation_report_path, "r", encoding="utf-8") as f:
            report = json.load(f)

        # Keep it small for the model
        report_str = json.dumps(report, indent=2)
        if len(report_str) > 6000:
            report_str = report_str[:6000] + "\n\n[...VALIDATION REPORT TRUNCATED...]"

        prompt = f"""
You are an HD-map QA engineer reviewing an automatically generated CARLA/OpenDRIVE map.

You are given a validation report from a deterministic pipeline. Based on this report:

1. Summarize the health of the map (topology, elevation, lanes, markings)
2. Classify the risk level: LOW / MEDIUM / HIGH
3. Decide whether the map is READY_FOR_SIMULATION or NEEDS_FIXES
4. List the top 5 actions for the map engineer.

Return a Markdown report using exactly this structure:

# Map Quality Summary
(2–4 bullet points)

# Risk Level
- Level: LOW / MEDIUM / HIGH
- Justification: (1–3 bullet points)

# Recommendation
- Decision: READY_FOR_SIMULATION or NEEDS_FIXES
- Rationale: (1–3 bullet points)

# Suggested Engineering Actions
- [ ] item 1
- [ ] item 2
- [ ] item 3
- [ ] item 4
- [ ] item 5

---

VALIDATION REPORT (TRUNCATED JSON):

{report_str}
"""

        answer = self.client.ask(prompt)

        if out_md_path:
            os.makedirs(os.path.dirname(out_md_path), exist_ok=True)
            with open(out_md_path, "w", encoding="utf-8") as f:
                f.write(answer)

        return answer
