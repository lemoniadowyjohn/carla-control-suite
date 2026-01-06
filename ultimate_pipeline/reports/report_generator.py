# ultimate_pipeline/reports/report_generator.py

from __future__ import annotations
import os
import subprocess
import datetime
import json
import markdown

class ReportGenerator:
    """
    Generates a Markdown + PDF summary of all experiments
    """

    @staticmethod
    def create_markdown(summary_json: str, out_md: str) -> None:
        with open(summary_json, "r", encoding="utf-8") as f:
            rows = json.load(f)

        lines = []
        lines.append("# Domain Gap & Perception Summary\n")
        lines.append(f"*Generated: {datetime.datetime.now()}*\n\n")

        for r in rows:
            lines.append(f"## Experiment: {r['experiment']}\n")
            lines.append("### Domain Gap Metrics\n")
            for k, v in r.items():
                if k.startswith("dg_"):
                    lines.append(f"- {k[3:]}: {v}")

            lines.append("\n### Perception Metrics\n")
            for k, v in r.items():
                if k.startswith("pg_"):
                    lines.append(f"- {k[3:]}: {v}")
            lines.append("\n---\n")

        md = "\n".join(lines)
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(md)

    @staticmethod
    def export_pdf(md_path: str, pdf_path: str) -> None:
        subprocess.run(["pandoc", md_path, "-o", pdf_path], check=True)
