#!/usr/bin/env python3
"""Verify the central research claim graph (batch 13 section 12).

Fails closed when any of the governed rules is violated:

  * one claim has multiple current authorities
  * a current artifact points at an unreachable or stale producer commit
  * a recorded input SHA differs from the input on disk
  * a recorded protocol SHA differs from the protocol implementation on disk
  * a required artifact is absent
  * an artifact hash does not match the recorded hash
  * a producer commit does not exist in this repository
  * SUPERSEDED evidence is used as current
  * DEFERRED / BLOCKED evidence is represented as a pass
  * a historical result silently replaces a current result

Exit code 0 only when there are no BLOCKING findings.

Usage:
    python tools/verify_research_claim_graph.py [--graph <graph.json>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.research.evidence_graph import EvidenceGraph, verify


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph", default=None,
                    help="path to a serialized evidence graph; rebuilt from "
                         "the batch bindings when omitted")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.graph:
        doc = json.loads(Path(args.graph).read_text(encoding="utf-8"))
        graph = EvidenceGraph()
        for node in doc["nodes"].values():
            graph.add(__import__(
                "ultimate_pipeline.research.evidence_graph",
                fromlist=["EvidenceNode"]).EvidenceNode(**node))
    else:
        sys.path.insert(0, str(WORKTREE / "tools"))
        from build_research_governance import build_graph
        graph = build_graph(WORKTREE)

    result = verify(graph, WORKTREE)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)

    if result["blocking_count"]:
        print(f"RESEARCH_CLAIM_GRAPH_FAIL blocking={result['blocking_count']}",
              file=sys.stderr)
        return 1
    print("RESEARCH_CLAIM_GRAPH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())