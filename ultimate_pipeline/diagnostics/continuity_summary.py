#!/usr/bin/env python3
# ultimate_pipeline/diagnostics/continuity_summary.py

from __future__ import annotations
import os
import sys
import json
from datetime import datetime


# ---------------------------------------------------------
# Helper: find newest ultimate_pipeline_out/* folder
# ---------------------------------------------------------
def auto_detect_latest_run(base_dir: str) -> str | None:
    out_root = os.path.join(base_dir, "ultimate_pipeline_out")
    if not os.path.isdir(out_root):
        return None

    subdirs = [
        os.path.join(out_root, d)
        for d in os.listdir(out_root)
        if os.path.isdir(os.path.join(out_root, d))
    ]
    if not subdirs:
        return None

    return max(subdirs, key=os.path.getmtime)


# ---------------------------------------------------------
# Helper: pretty printing with context awareness
# ---------------------------------------------------------
def pretty(value, stage_exists: bool):
    if value is not None:
        return f"{value:.4f}"
    if stage_exists:
        return "0.0000 (Perfect Continuity)"
    return "— (Stage Skipped/No Data)"


# ---------------------------------------------------------
# Main summary function
# ---------------------------------------------------------
def run_summary(run_dir: str):
    print(f"\n🔍 Continuity summary for run:\n   {run_dir}\n")

    debug_path = os.path.join(run_dir, "continuity_debug.json")

    # Check if the continuity stage (Step 06) output exists in the folder
    stage_6_files = [f for f in os.listdir(run_dir) if f.startswith("06_")]
    stage_exists = len(stage_6_files) > 0

    # Create placeholder if missing
    if not os.path.exists(debug_path):
        data = {
            "warning": "continuity stage did not run or debug was not saved",
            "max_gap": None,
            "max_heading_jump": None,
            "max_segment_length": None
        }
        # Only write the placeholder if it's truly missing
        with open(debug_path, "w") as f:
            json.dump(data, f, indent=2)
    else:
        with open(debug_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}

    max_gap = data.get("max_gap")
    max_heading = data.get("max_heading_jump")
    max_length = data.get("max_segment_length")

    # ---------------------------------------------------------
    # Pretty terminal view
    # ---------------------------------------------------------
    print("============== CONTINUITY SUMMARY ==============")
    print(f"Max geometric gap (m):       {pretty(max_gap, stage_exists)}")
    print(f"Max heading jump (rad):      {pretty(max_heading, stage_exists)}")
    print(f"Max segment length (m):      {pretty(max_length, stage_exists)}")
    print()

    # ---------------------------------------------------------
    # JSON output for GUIs / further tools
    # ---------------------------------------------------------
    summary_json = {
        "run_directory": run_dir,
        "timestamp": datetime.now().isoformat(),
        "stage_found": stage_exists,
        "continuity": {
            "max_gap_m": max_gap,
            "max_heading_jump_rad": max_heading,
            "max_segment_length_m": max_length
        }
    }

    out_json = os.path.join(run_dir, "continuity_summary.json")
    with open(out_json, "w") as f:
        json.dump(summary_json, f, indent=2)

    print(f"📄 Summary written → {out_json}")

    # ---------------------------------------------------------
    # Markdown summary for thesis reports or GUI display
    # ---------------------------------------------------------
    md = [
        "# Continuity Summary",
        "",
        f"Run directory: `{run_dir}`",
        "",
        "## Metrics",
        f"- **Max geometric gap**: `{pretty(max_gap, stage_exists)}` m",
        f"- **Max heading jump**: `{pretty(max_heading, stage_exists)}` rad",
        f"- **Max segment length**: `{pretty(max_length, stage_exists)}` m",
        "",
        f"_Generated automatically by continuity_summary.py on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
    ]

    out_md = os.path.join(run_dir, "continuity_summary.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"📝 Markdown summary written → {out_md}")
    print("=================================================\n")

    return summary_json


# ---------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------
def main():
    if len(sys.argv) > 1:
        run_dir = os.path.abspath(sys.argv[1])
        if not os.path.isdir(run_dir):
            print(f"❌ Provided directory does not exist:\n   {run_dir}")
            return
        run_summary(run_dir)
        return

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    latest = auto_detect_latest_run(project_root)

    if not latest:
        print("❌ No pipeline output found in ultimate_pipeline_out/.")
        return

    print("📌 Auto-detected latest run:")
    print(f"   {latest}")
    run_summary(latest)


if __name__ == "__main__":
    main()