#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Small CLI helper to run LLM checks from the command line.

Examples (from project root):

    python -m ultimate_pipeline.llm.llm_check xodr ^
        --xodr cities/ingolstadt/ultimate_pipeline/.../08_final_*.xodr ^
        --report cities/ingolstadt/ultimate_pipeline/.../logs/validation_report_full.json

    python -m ultimate_pipeline.llm.llm_check quality_gate ^
        --xodr path/to/final.xodr ^
        --report path/to/validation_report_full.json ^
        --out reports/quality_gate.md
"""

from __future__ import annotations

import argparse
import os

from ultimate_pipeline.llm.llm_xodr_checker import LLMXODRChecker
from ultimate_pipeline.llm.llm_quality_gate import LLMQualityGate
from ultimate_pipeline.llm.llm_domain_gap_reviewer import LLMDomainGapReviewer
from ultimate_pipeline.llm.llm_safety_assistant import LLMSafetyAssistant


def main() -> None:
    ap = argparse.ArgumentParser(description="Run LLM-based checks for the ultimate pipeline.")
    sub = ap.add_subparsers(dest="mode", required=True)

    # XODR checker
    p_xodr = sub.add_parser("xodr", help="LLM review of a single XODR file.")
    p_xodr.add_argument("--xodr", required=True)
    p_xodr.add_argument("--report", required=False)
    p_xodr.add_argument("--out", required=False)

    # Quality gate
    p_q = sub.add_parser("quality_gate", help="LLM-based quality gate.")
    p_q.add_argument("--xodr", required=True)
    p_q.add_argument("--report", required=True)
    p_q.add_argument("--out", required=False)

    # Domain gap
    p_dg = sub.add_parser("domain_gap", help="LLM review of domain gap full_report.json.")
    p_dg.add_argument("--full_report", required=True)
    p_dg.add_argument("--out", required=False)

    # Safety
    p_s = sub.add_parser("safety", help="LLM-based safety assistant.")
    p_s.add_argument("--report", required=True)
    p_s.add_argument("--scenario", required=False, default="")
    p_s.add_argument("--out", required=False)

    args = ap.parse_args()

    if args.mode == "xodr":
        checker = LLMXODRChecker()
        md = checker.review_xodr(args.xodr, args.report, args.out)
        print(md)

    elif args.mode == "quality_gate":
        gate = LLMQualityGate()
        md = gate.review(args.xodr, args.report, args.out)
        print(md)

    elif args.mode == "domain_gap":
        dg = LLMDomainGapReviewer()
        md = dg.review(args.full_report, args.out)
        print(md)

    elif args.mode == "safety":
        sa = LLMSafetyAssistant()
        md = sa.review_safety(args.report, args.scenario, args.out)
        print(md)


if __name__ == "__main__":
    main()
