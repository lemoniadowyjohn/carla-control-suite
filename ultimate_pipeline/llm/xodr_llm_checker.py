#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM-assisted XODR sanity checker.

Public API:

    from ultimate_pipeline.llm.xodr_llm_checker import LLMXODRChecker
    issues = LLMXODRChecker.check("/path/to/map.xodr")

Returns a dict with:
- basic structural issues (missing geometry, strange lanes, etc.)
- optional LLM summary / flags (if local LLM is reachable)

This uses the same SETTINGS.* LLM config as LLMQualityGate, so both
systems are consistent in model, temperature, and context length.
"""

from __future__ import annotations
import os
import json
import logging
import textwrap
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

from ultimate_pipeline.config.settings import SETTINGS

logger = logging.getLogger(__name__)


class LLMXODRChecker:
    """Static helper for LLM-assisted XODR validation."""

    @classmethod
    def check(cls, xodr_path: str) -> Dict[str, Any]:
        """
        Run structural checks + (optional) LLM pass on the given XODR.

        Returns a structured dict; safe to store directly into ValidationReport.
        """
        issues: Dict[str, Any] = {
            "xodr_path": xodr_path,
            "errors": [],
            "warnings": [],
            "lane_issues": [],
            "geometry_issues": [],
            "junction_issues": [],
            "llm_summary": "",
            "llm_flags": [],
        }

        if not os.path.isfile(xodr_path):
            msg = f"XODR file not found: {xodr_path}"
            issues["errors"].append(msg)
            logger.error(msg)
            return issues

        # --- Parse XML ---
        try:
            tree = ET.parse(xodr_path)
            root = tree.getroot()
        except Exception as e:
            msg = f"XML parse error: {e}"
            issues["errors"].append(msg)
            logger.exception(msg)
            return issues

        # Local heuristic checks (no LLM needed)
        cls._basic_structure_checks(root, issues)
        cls._lane_and_width_checks(root, issues)
        cls._geometry_checks(root, issues)

        # --- Optional LLM pass ---
        # Uses same config as LLMQualityGate via SETTINGS.
        if getattr(SETTINGS, "ENABLE_LLM_XODR_CHECK", False):
            try:
                snippet = cls._extract_xml_snippet(xodr_path, max_chars=getattr(SETTINGS, "LLM_CONTEXT_LENGTH", 8192) // 4)
                llm_result = cls._run_llm(snippet, issues)
                issues["llm_summary"] = llm_result.get("summary", "")
                issues["llm_flags"] = llm_result.get("flags", [])
            except Exception as e:
                msg = f"LLM XODR check failed: {e}"
                issues["warnings"].append(msg)
                logger.exception(msg)

        return issues

    # ------------------------------------------------------------------
    # Local structural checks
    # ------------------------------------------------------------------

    @staticmethod
    def _basic_structure_checks(root: ET.Element, issues: Dict[str, Any]) -> None:
        roads = root.findall("road")
        juncs = root.findall("junction")
        if not roads:
            issues["errors"].append("no_road_elements")
        if not juncs:
            issues["warnings"].append("no_junctions_defined")

        # Check that each road has a planView
        for r in roads:
            rid = r.get("id", "?")
            pv = r.find("planView")
            if pv is None:
                issues["geometry_issues"].append(
                    {"road_id": rid, "problem": "missing_planView"}
                )

    @staticmethod
    def _lane_and_width_checks(root: ET.Element, issues: Dict[str, Any]) -> None:
        for road in root.findall("road"):
            rid = road.get("id", "?")
            lanes = road.find("lanes")
            if lanes is None:
                issues["lane_issues"].append(
                    {"road_id": rid, "problem": "missing_lanes_block"}
                )
                continue

            lane_sections = lanes.findall("laneSection")
            if not lane_sections:
                issues["lane_issues"].append(
                    {"road_id": rid, "problem": "no_laneSections"}
                )
                continue

            for ls in lane_sections:
                for side_tag in ["left", "right"]:
                    side = ls.find(side_tag)
                    if side is None:
                        continue
                    for lane in side.findall("lane"):
                        lid = lane.get("id", "?")
                        widths = lane.findall("width")
                        if not widths:
                            issues["lane_issues"].append(
                                {
                                    "road_id": rid,
                                    "lane_id": lid,
                                    "problem": "missing_width",
                                }
                            )

    @staticmethod
    def _geometry_checks(root: ET.Element, issues: Dict[str, Any]) -> None:
        for road in root.findall("road"):
            rid = road.get("id", "?")
            pv = road.find("planView")
            if pv is None:
                continue
            geoms = pv.findall("geometry")
            if not geoms:
                issues["geometry_issues"].append(
                    {"road_id": rid, "problem": "no_geometry_elements"}
                )
                continue

            # Example simple check: very short geometries
            for g in geoms:
                length_str = g.get("length", None)
                try:
                    length = float(length_str) if length_str is not None else 0.0
                except ValueError:
                    length = 0.0
                if length < 0.05:
                    issues["geometry_issues"].append(
                        {
                            "road_id": rid,
                            "problem": "geometry_too_short",
                            "length": length,
                        }
                    )

    # ------------------------------------------------------------------
    # LLM integration
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_xml_snippet(path: str, max_chars: int = 6000) -> str:
        """Read the beginning of the XODR file so we stay within context limits."""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read(max_chars)
        return txt

    @classmethod
    def _run_llm(cls, xml_snippet: str, issues: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ask local LLM (Ollama or similar) for a short JSON report.

        This is intentionally robust: if `requests` or the server is missing,
        we just return an empty dict and log a warning.
        """
        try:
            import requests
        except ImportError:
            logger.warning("requests not installed; skipping LLM XODR check.")
            return {}

        model = getattr(SETTINGS, "LLM_MODEL", "deepseek-coder:6.7b")
        temp = float(getattr(SETTINGS, "LLM_TEMP", 0.2))
        max_tokens = int(getattr(SETTINGS, "LLM_MAX_TOKENS", 1024))

        system_prompt = (
            "You are an expert on OpenDRIVE (XODR) road networks. "
            "You receive:\n"
            "1) A short pre-computed issue list from a structural checker.\n"
            "2) A snippet of the XODR XML.\n"
            "You must respond with **pure JSON** only, no extra text.\n"
            "JSON schema:\n"
            "{\n"
            '  \"summary\": \"short human-readable summary\",\n'
            '  \"flags\": [\"string_tag1\", \"string_tag2\", ...]\n'
            "}\n"
        )

        user_prompt = textwrap.dedent(
            f"""
            Precomputed_issues = {json.dumps(issues, indent=2)}

            XODR_snippet (truncated):
            ------------------------
            {xml_snippet}
            ------------------------

            Based on the snippet and issues, produce JSON as described.
            """
        )

        payload = {
            "model": model,
            "prompt": system_prompt + "\n\n" + user_prompt,
            "stream": False,
            "options": {
                "temperature": temp,
            },
        }

        # Default Ollama endpoint
        url = "http://localhost:11434/api/generate"

        try:
            resp = requests.post(url, json=payload, timeout=getattr(SETTINGS, "OLLAMA_STARTUP_TIMEOUT", 12))
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("response", "") or data.get("data", "")
        except Exception as e:
            logger.warning("LLM HTTP error: %s", e)
            return {}

        # Attempt to find JSON in the response
        raw_text = raw_text.strip()
        json_str = raw_text
        # Sometimes models add junk; try to isolate {...}
        if "{" in raw_text and "}" in raw_text:
            json_str = raw_text[raw_text.find("{") : raw_text.rfind("}") + 1]

        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            logger.warning("Failed to parse LLM JSON: %r", raw_text[:200])

        return {}
