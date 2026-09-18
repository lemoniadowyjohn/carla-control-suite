#!/usr/bin/env python3

import argparse


# --------------------------------------------------
# Avoid circular import by resolving inside function
# --------------------------------------------------
def run_gap(*args, **kwargs):
    from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap
    return run_full_domain_gap(*args, **kwargs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run full domain-gap analysis.")
    ap.add_argument("--manual", required=True, help="Path to manual .xodr")
    ap.add_argument("--auto", required=True, help="Path to auto .xodr")
    ap.add_argument("--manual_tiles", required=True)
    ap.add_argument("--auto_tiles", required=True)
    ap.add_argument("--out", default="domain_gap_results")
    ap.add_argument("--man_json", default=None)
    ap.add_argument("--auto_json", default=None)
    args = ap.parse_args()

    # --------------------------------------------------
    # Use wrapper function → NO circular import possible
    # --------------------------------------------------
    run_gap(
        manual_xodr=args.manual,
        auto_xodr=args.auto,
        manual_tiles=args.manual_tiles,
        auto_tiles=args.auto_tiles,
        perception_manual_json=args.man_json,
        perception_auto_json=args.auto_json,
        output_dir=args.out,
    )
