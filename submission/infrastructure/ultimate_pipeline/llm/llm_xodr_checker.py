#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM-based XODR checker.

Goal:
- Take an XODR file and an optional validation_report_full.json
- Ask a local LLM (via Ollama) to:
    * summarize the map
    * highlight possible risks / weirdness
    * suggest manual checks

This is ADVISORY ONLY and does not replace hard validation.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from ultimate_pipeline.llm.llm_client import LLMClient


def _load_text_truncated(path: str, max_chars: int = 6000) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    if len(txt) > max_chars:
        return txt[:max_chars] + "\n\n[...XODR TRUNCATED FOR LLM INPUT...]"
    return txt


def _load_json_safe(path: str, max_chars: int = 3000) -> str:
    if not os.path.exists(path):
        return "No validation report available."
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # compact view
        dumped = json.dumps(data, indent=2)
        if len(dumped) > max_chars:
            dumped = dumped[:max_chars] + "\n\n[...VALIDATION JSON TRUNCATED...]"
        return dumped
    except Exception as e:
        return f"Failed to load validation JSON: {e}"


class LLMXODRChecker:
    def __init__(self, client: Optional[LLMClient] = None) -> None:
        self.client = client or LLMClient()

    def review_xodr(
        self,
        xodr_path: str,
        validation_report_path: Optional[str] = None,
        out_md_path: Optional[str] = None,
    ) -> str:
        """
        Run an LLM-based review of the XODR map.

        Returns:
            Markdown-like string with comments and recommendations.
        """
        if not os.path.exists(xodr_path):
            raise FileNotFoundError(xodr_path)

        xodr_snippet = _load_text_truncated(xodr_path)
        validation_snippet = (
            _load_json_safe(validation_report_path)
            if validation_report_path
            else "No validation report provided."
        )

        prompt = f"""
You are an expert in HD maps for autonomous driving and OpenDRIVE (XODR).

You will get:
1) A truncated XODR file (structure only, not full geometry)
2) A truncated JSON validation report from a deterministic validator

Task:
- Summarize what you can infer about the map structure
- Point out potential risks or suspicious patterns
- Suggest manual checks a human engineer should perform
- DO NOT hallucinate exact numbers: instead speak qualitatively
- Output structured Markdown with the following sections:

# Summary
# Potential Issues
# Recommended Manual Checks
# Overall Assessment

--- XODR (TRUNCATED) ---
{xodr_snippet}

--- VALIDATION REPORT (TRUNCATED) ---
{validation_snippet}
"""

        answer = self.client.ask(prompt)

        if out_md_path:
            os.makedirs(os.path.dirname(out_md_path), exist_ok=True)
            with open(out_md_path, "w", encoding="utf-8") as f:
                f.write(answer)

        return answer
