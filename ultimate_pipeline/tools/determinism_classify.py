#!/usr/bin/env python3
"""
Emit a simple determinism_report.json / .csv for reproducibility checks.

Usage (single entry):
  python determinism_classify.py --file path --sha256 HEX --semantic SIGNATURE --classification byte_identical --out out_dir

Usage (multiple):
  python determinism_classify.py --entry path sha256 semantic classification --entry path2 sha2562 semantic2 classification2 --out out_dir
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import List, Dict

ALLOWED_CLASSES = {"byte_identical", "semantic_identical_only", "semantic_different"}


def build_entries(args: argparse.Namespace) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    if args.entry:
        for path, sha256, semantic, cls in args.entry:
            if cls not in ALLOWED_CLASSES:
                raise ValueError(f"Invalid classification '{cls}' (allowed: {sorted(ALLOWED_CLASSES)})")
            entries.append(
                {
                    "file": path,
                    "sha256": sha256,
                    "semantic_signature": semantic,
                    "classification": cls,
                }
            )
    elif args.file and args.sha256 and args.semantic and args.classification:
        if args.classification not in ALLOWED_CLASSES:
            raise ValueError(f"Invalid classification '{args.classification}' (allowed: {sorted(ALLOWED_CLASSES)})")
        entries.append(
            {
                "file": args.file,
                "sha256": args.sha256,
                "semantic_signature": args.semantic,
                "classification": args.classification,
            }
        )
    return entries


def write_reports(out_dir: Path, rows: List[Dict[str, str]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "determinism_report.json"
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")

    csv_path = out_dir / "determinism_report.csv"
    headers = ["file", "sha256", "semantic_signature", "classification"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit determinism_report.{json,csv} with classification.")
    ap.add_argument("--file", help="Path to file entry (single-entry mode)")
    ap.add_argument("--sha256", help="SHA256 hex digest (single-entry mode)")
    ap.add_argument("--semantic", help="Semantic signature string (single-entry mode)")
    ap.add_argument("--classification", help="Classification label", choices=sorted(ALLOWED_CLASSES))
    ap.add_argument(
        "--entry",
        nargs=4,
        action="append",
        metavar=("FILE", "SHA256", "SEMANTIC", "CLASSIFICATION"),
        help="Add an entry (multi-entry mode). CLASSIFICATION must be one of byte_identical|semantic_identical_only|semantic_different.",
    )
    ap.add_argument("--out", default=".", help="Output directory")
    args = ap.parse_args()

    rows = build_entries(args)
    if not rows:
        raise SystemExit("No entries provided. Use --entry ... or --file/--sha256/--semantic/--classification.")

    write_reports(Path(args.out), rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
