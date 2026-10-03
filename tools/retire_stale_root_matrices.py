#!/usr/bin/env python3
"""Batch 14 section 10: retire the stale root matrices non-destructively.

The root RQ_CLOSURE_MATRIX.json and PRODUCTION_READINESS_MATRIX.json were
computed for candidate 7fbd33ff, which is no longer the integration candidate.
Their bodies are NOT recomputed here, so simply swapping candidate_commit would
misattribute a verdict computed for a different tree.

Instead this marks them superseded, records the current candidate, and points at
the regenerated authority. No original field is edited and nothing is deleted,
per section 28.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = "reports/integration_wave/20261003_batch14"

REASON = (
    "This matrix body was computed for an earlier candidate and has not been "
    "recomputed for the current one. It is retained verbatim as historical "
    "provenance and is NOT the current authority. The current authority is the "
    "superseded_by artifact, regenerated from the current candidate. No "
    "original field of this document was edited."
)


def main() -> int:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    targets = {
        "RQ_CLOSURE_MATRIX.json": f"{RUN}/RQ_CLOSURE_MATRIX.json",
        "PRODUCTION_READINESS_MATRIX.json":
            f"{RUN}/PRODUCTION_READINESS_MATRIX.json",
    }
    for name, replacement in targets.items():
        p = ROOT / name
        if not p.is_file():
            print(f"{name}: absent, nothing to supersede")
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        original = doc.get("candidate_commit")
        doc["superseded_by"] = replacement
        doc["current_candidate_commit"] = head
        doc["supersession_reason"] = REASON
        p.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
        repl = ROOT / replacement
        print(f"{name}: historical candidate_commit={str(original)[:12]} "
              f"retained; current_candidate_commit={head[:12]}; "
              f"replacement_present={repl.is_file()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())