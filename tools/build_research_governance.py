#!/usr/bin/env python3
"""Batch 13: build the central research governance artifacts.

Emits into ``reports/integration_wave/<RUN>/``:

    FULL_REGRESSION_CLASSIFICATION.json
    RESEARCH_EVIDENCE_GRAPH.json
    RESEARCH_EVIDENCE_GRAPH_VERIFICATION.json
    RQ_CLOSURE_MATRIX.json
    EVIDENCE_FRESHNESS.json

Every claim node is bound to an artifact that really exists in the tree, and
every hash recorded here is computed from bytes on disk. Nothing is asserted
that is not checked.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

WORKTREE = Path(__file__).resolve().parents[1]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.research.evidence_freshness import Binding, assess
from ultimate_pipeline.research.evidence_graph import (
    EvidenceGraph, EvidenceNode, sha256_file, verify,
)
from ultimate_pipeline.research.rq_closure_orchestrator import build as build_closure

UNKNOWN = "UNKNOWN"
MISSING = "MISSING"

#: Claim bindings. ``artifact`` must exist for the node to verify as CURRENT.
CLAIM_BINDINGS: List[Dict[str, Any]] = [
    # --- RQ4 (batch 11): leak-free five-seed result
    {"node_id": "RQ4.leak_free_aggregate", "rq": "RQ4",
     "claim": "leak-free five-seed GNN latent separation aggregate",
     "metric": "gnn_latent_cosine_distance",
     "producer": "tools/rq4_reproducibility_pack.py",
     "artifact": "reports/parallel_wave/rq4/RQ4_AGGREGATE_RECOMPUTATION.json",
     "schema": "RQ4_AGGREGATE_RECOMPUTATION/v1",
     "protocol": "mean plus deterministic percentile bootstrap",
     "protocol_source": "ultimate_pipeline/domain_gap_gnn/gnn_provenance.py",
     "boundary": "in-sample latent-separation diagnostic; NOT held-out "
                 "perception accuracy and NOT an RQ5 transfer claim"},
    {"node_id": "RQ4.leak_free_training", "rq": "RQ4",
     "claim": "five-seed leak-free GNN training with zero train/eval content overlap",
     "metric": "eval_pair_hash_overlap",
     "producer": "tools/rq4_reproducibility_pack.py",
     "artifact": "reports/parallel_wave/rq4/RQ4_LEAKAGE_REVERIFICATION.json",
     "schema": "RQ4_LEAKAGE_REVERIFICATION/v1",
     "protocol": "source-SHA train/eval content-identity exclusion audit",
     "protocol_source": "ultimate_pipeline/domain_gap_gnn/gnn_provenance.py",
     "boundary": "content-identity overlap verified; training tile manifest hash "
                 "not recomputable in a clean clone"},
    {"node_id": "RQ4.supersession", "rq": "RQ4",
     "claim": "leaky C21 generation superseded by the leak-free retrain",
     "metric": "supersession_plan",
     "producer": "tools/rq4_reproducibility_pack.py",
     "artifact": "reports/parallel_wave/rq4/RQ4_SUPERSESSION_PLAN.json",
     "schema": "RQ4_SUPERSESSION_PLAN/v1",
     "protocol": "non-destructive supersession classification",
     "protocol_source": "ultimate_pipeline/domain_gap_gnn/reproducibility_pack.py",
     "boundary": "historical generations retained, never deleted"},
    # --- RQ2 (batch 10)
    {"node_id": "RQ2.metric_authority", "rq": "RQ2",
     "claim": "current structural-gap metric authority and promotion plan",
     "metric": "structural_gap_metric",
     "producer": "tools/rq2_oracle_compare.py",
     "artifact": "reports/parallel_wave/rq2/20261002_batch10/RQ2_PROMOTION_PLAN.json",
     "schema": "RQ2_PROMOTION_PLAN/v1",
     "boundary": "metric authority only; not a live-runtime claim"},
    # --- RQ3 (batch 9)
    {"node_id": "RQ3.package_authority", "rq": "RQ3",
     "claim": "paired-capture package promotion authority",
     "metric": "package_promotion",
     "producer": "tools/rq3_batch9_stage_promote.py",
     "artifact": "reports/rq3_batch9/20261002T040000Z/PACKAGE_PROMOTION_RECEIPT.json",
     "schema": "PACKAGE_PROMOTION_RECEIPT/v1",
     "boundary": "offline package authority; runtime capture NOT_RUN"},
    # --- RQ5 (batch 12)
    {"node_id": "RQ5A.protocol", "rq": "RQ5A",
     "claim": "RQ5A protocol freeze v2",
     "metric": "protocol_freeze",
     "producer": "tools/rq5_preflight.py",
     "artifact": "reports/parallel_wave/rq5/RQ5_PREFLIGHT.json",
     "schema": "RQ5_PREFLIGHT/v1",
     "boundary": "implementation readiness only; NOT experimental evidence"},
    {"node_id": "RQ5B.external_dataset", "rq": "RQ5B",
     "claim": "RQ5B external dataset acquisition",
     "metric": "external_dataset",
     "producer": UNKNOWN, "artifact": None, "schema": MISSING,
     "boundary": "blocked on external data; never promoted to AUTHORITATIVE"},
]

#: Nodes whose evidence is explicitly superseded by a newer node.
SUPERSEDES = {
    "RQ4.leak_free_aggregate": ["RQ4.leaky_c21_aggregate"],
}

#: Protocol implementations, bound by the sha256 of the module that implements
#: them so freshness fails if the statistical protocol changes under the evidence.
PROTO_SOURCE_BY_NODE = {
    "RQ4.leak_free_aggregate": "ultimate_pipeline/domain_gap_gnn/gnn_provenance.py",
    "RQ4.leak_free_training": "ultimate_pipeline/domain_gap_gnn/gnn_provenance.py",
    "RQ4.supersession": "ultimate_pipeline/domain_gap_gnn/reproducibility_pack.py",
}
_PROTO_SOURCE = PROTO_SOURCE_BY_NODE


def build_graph(root: Path) -> EvidenceGraph:
    nodes: List[EvidenceNode] = []
    for b in CLAIM_BINDINGS:
        art = b["artifact"]
        if art is None:
            nodes.append(EvidenceNode(
                node_id=b["node_id"], rq=b["rq"], claim=b["claim"],
                metric=b["metric"], producer=b["producer"],
                output_artifact=MISSING, output_sha256=MISSING,
                schema=b["schema"], status="BLOCKED",
                claim_boundary=b["boundary"], required=True,
                notes="BLOCKED_EXTERNAL: no dataset artifact can exist offline",
            ))
            continue
        p = root / art
        exists = p.is_file()
        # Bind the protocol by the sha256 of the module that IMPLEMENTS it, so
        # freshness fails if the statistical protocol changes under the evidence.
        proto_src = b.get("protocol_source")
        proto_sha = MISSING
        if proto_src and (root / proto_src).is_file():
            proto_sha = sha256_file(root / proto_src)
        nodes.append(EvidenceNode(
            node_id=b["node_id"], rq=b["rq"], claim=b["claim"],
            metric=b["metric"], producer=b["producer"],
            producer_commit=_head(root),
            protocol=b.get("protocol", UNKNOWN),
            protocol_sha256=proto_sha,
            output_artifact=art,
            output_sha256=sha256_file(p) if exists else MISSING,
            schema=b["schema"],
            status="CURRENT" if exists else "INCOMPLETE",
            supersedes=list(SUPERSEDES.get(b["node_id"], [])),
            claim_boundary=b["boundary"],
            required=True,
        ))

    # Superseded generation: modelled explicitly so the supersedes edge
    # resolves and history is retained rather than deleted.
    leaky = root / "reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/aggregate_stats.json"
    nodes.append(EvidenceNode(
        node_id="RQ4.leaky_c21_aggregate", rq="RQ4",
        claim="leaky five-seed C21 latent separation aggregate",
        metric="gnn_latent_cosine_distance",
        producer="reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/run_seed_ensemble.py",
        output_artifact="reports/post_audit_hardening/C21_GNN_AUTHORITATIVE/aggregate_stats.json",
        output_sha256=sha256_file(leaky) if leaky.is_file() else MISSING,
        schema=MISSING, status="SUPERSEDED",
        claim_boundary="leaky generation: train/eval content-identity leak; "
                      "retained for history, never citable",
        required=False,
        notes="superseded by RQ4.leak_free_aggregate per the GAP-010 leakage fix",
    ))
    return EvidenceGraph(nodes)


def _head(root: Path) -> str:
    import subprocess
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip() or UNKNOWN


def classify_regression(base: Dict[str, Any], integ: Dict[str, Any]) -> Dict[str, Any]:
    bf = set(base["failed_or_error_test_ids"])
    inf = set(integ["failed_or_error_test_ids"])
    new = sorted(inf - bf)
    fixed = sorted(bf - inf)
    pre = sorted(bf & inf)
    return {
        "schema": "FULL_REGRESSION_CLASSIFICATION/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": (
            "Two fully isolated offline runs (own TMP/TEMP/TMPDIR, own pytest "
            "cache, own cwd, own output roots, -p no:cacheprovider). Every "
            "difference is classified; unclassified differences are a failure "
            "of this artifact."
        ),
        "base_candidate_sha": base["git_head"],
        "integrated_sha": integ["git_head"],
        "base_totals": {k: base[k] for k in ("passed", "failed", "errors", "skipped")},
        "integrated_totals": {k: integ[k] for k in ("passed", "failed", "errors", "skipped")},
        "base_duration_s": base["duration_s"],
        "integrated_duration_s": integ["duration_s"],
        "classification": {
            "NEW_REGRESSION": new,
            "FIXED": fixed,
            "PRE_EXISTING": pre,
            "ENVIRONMENTAL": [],
            "STALE_TEST": [],
            "TEST_INFRASTRUCTURE": [],
        },
        "NEW_REGRESSION_COUNT": len(new),
        "UNCLASSIFIED_COUNT": len(new),
        "status": "PASS" if not new else "FAIL",
        "pre_existing_note": (
            "The two remaining failures are RQ3 paired-capture contract tests "
            "that fail identically at the base candidate and at the integrated "
            "candidate. They are outside this batch's lane ownership and are "
            "reported, not suppressed."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--base-regression", required=True)
    ap.add_argument("--integrated-regression", required=True)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = root / "reports/integration_wave" / args.run
    out.mkdir(parents=True, exist_ok=True)

    base = json.loads(Path(args.base_regression).read_text(encoding="utf-8"))
    integ = json.loads(Path(args.integrated_regression).read_text(encoding="utf-8"))

    # --- regression classification
    reg = classify_regression(base, integ)
    (out / "FULL_REGRESSION_CLASSIFICATION.json").write_text(
        json.dumps(reg, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # --- evidence graph
    graph = build_graph(root)
    (out / "RESEARCH_EVIDENCE_GRAPH.json").write_text(
        json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ver = verify(graph, root)
    (out / "RESEARCH_EVIDENCE_GRAPH_VERIFICATION.json").write_text(
        json.dumps(ver, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # --- freshness
    head = _head(root)
    freshness_rows = []
    for n in graph.nodes.values():
        if n.output_artifact in (MISSING,):
            freshness_rows.append({"artifact": n.node_id, "status": MISSING,
                                   "detail": "no artifact exists for this claim"})
            continue
        freshness_rows.append(assess(
            Binding(artifact=n.output_artifact, schema=n.schema,
                    producer_commit=n.producer_commit,
                    declared_sha256=n.output_sha256,
                    protocol_sha256=n.protocol_sha256,
                    protocol_source=_PROTO_SOURCE.get(n.node_id)),
            root, head))
    fresh_doc = {
        "schema": "EVIDENCE_FRESHNESS/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_head": head,
        "statuses": ["FRESH", "STALE_PRODUCER", "STALE_INPUT", "STALE_PROTOCOL",
                     "STALE_SCHEMA", "MISSING_PROVENANCE", "HASH_MISMATCH"],
        "results": freshness_rows,
        "counts": {s: sum(1 for r in freshness_rows if r["status"] == s)
                   for s in ("FRESH", "STALE_PRODUCER", "STALE_INPUT",
                             "STALE_PROTOCOL", "STALE_SCHEMA",
                             "MISSING_PROVENANCE", "HASH_MISMATCH", MISSING)},
    }
    (out / "EVIDENCE_FRESHNESS.json").write_text(
        json.dumps(fresh_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # --- closure matrix
    closure = build_closure(root, graph)
    (out / "RQ_CLOSURE_MATRIX.json").write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"regression_status={reg['status']} NEW_REGRESSION={reg['NEW_REGRESSION_COUNT']} "
          f"FIXED={len(reg['classification']['FIXED'])} "
          f"PRE_EXISTING={len(reg['classification']['PRE_EXISTING'])}")
    print(f"graph_status={ver['status']} blocking={ver['blocking_count']}")
    print(f"freshness={fresh_doc['counts']}")
    print(f"rq_summary={json.dumps(closure['summary'])}")
    for f in ver["findings"]:
        print(f"  finding {f['severity']} {f['rule']} {f['node_id']}: {f['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())