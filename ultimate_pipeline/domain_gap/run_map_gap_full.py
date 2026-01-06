"""
DEPRECATED:
Replaced by: ultimate_pipeline.run_full_domain_gap.run_full_domain_gap

This file is kept ONLY for backwards compatibility.
Do not import from core pipeline.
"""

from __future__ import annotations

import argparse
from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap


def parse_args():
    ap = argparse.ArgumentParser(description="DEPRECATED domain-gap runner")
    ap.add_argument("--manual-xodr", required=True)
    ap.add_argument("--auto-xodr", required=True)
    ap.add_argument("--manual-tiles", required=True)
    ap.add_argument("--auto-tiles", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--perception-manual-json")
    ap.add_argument("--perception-auto-json")
    return ap.parse_args()


def main():
    args = parse_args()

    run_full_domain_gap(
        manual_xodr=args.manual_xodr,
        auto_xodr=args.auto_xodr,
        manual_tiles=args.manual_tiles,
        auto_tiles=args.auto_tiles,
        perception_manual_json=args.perception_manual_json,
        perception_auto_json=args.perception_auto_json,
        output_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
