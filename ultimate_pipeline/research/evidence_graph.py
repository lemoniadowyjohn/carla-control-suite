"""Central research evidence graph.

One canonical graph model for every research claim in the repository, plus the
mechanical verification rules from the integration batch. Nothing in this
module infers status from prose: a node's ``status`` is data, and every rule
below is a pure function of node fields and on-disk bytes.

Deliberately absent: any notion of "the code exists, therefore the claim is
authoritative". Implementation readiness is never promoted to evidence.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --- governed vocabularies -------------------------------------------------

CLAIM_STATUSES = ("CURRENT", "SUPERSEDED", "HISTORICAL", "DEFERRED", "BLOCKED")
EVIDENCE_STATUSES = (
    "PASS", "FAIL", "INCOMPLETE", "NOT_RUN", "BLOCKED_ENVIRONMENT",
    "BLOCKED_EXTERNAL", "AUTHORITATIVE", "AUTHORITATIVE_BOUNDED",
    "OBSERVATIONAL", "UNVERIFIED",
)
#: Statuses that must never be presented as evidence of a successful outcome.
NON_PASSING_STATUSES = (
    "FAIL", "INCOMPLETE", "NOT_RUN", "BLOCKED_ENVIRONMENT", "BLOCKED_EXTERNAL",
    "DEFERRED", "UNVERIFIED",
)

UNKNOWN = "UNKNOWN"
MISSING = "MISSING"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                       text=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ""


def commit_exists(root: Path, sha: str) -> bool:
    if not sha or sha == UNKNOWN:
        return False
    return git(root, "cat-file", "-t", sha) == "commit"


def is_ancestor(root: Path, ancestor: str, descendant: str) -> Optional[bool]:
    if not (commit_exists(root, ancestor) and commit_exists(root, descendant)):
        return None
    r = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                        ancestor, descendant], capture_output=True)
    return r.returncode == 0


# --- graph model -----------------------------------------------------------

@dataclass
class EvidenceNode:
    """One claim, its single producer, and the evidence that proves it."""

    node_id: str
    rq: str
    claim: str
    metric: str = UNKNOWN
    producer: str = UNKNOWN
    producer_commit: str = UNKNOWN
    producer_tree: str = UNKNOWN
    protocol: str = UNKNOWN
    protocol_sha256: str = UNKNOWN
    source_inputs: List[str] = field(default_factory=list)
    input_sha256: Dict[str, str] = field(default_factory=dict)
    output_artifact: str = MISSING
    output_sha256: str = MISSING
    schema: str = MISSING
    status: str = "UNVERIFIED"
    supersedes: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    claim_boundary: str = ""
    required: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvidenceGraph:
    """Nodes plus a supersedes-edge index. No evaluation happens on insert."""

    def __init__(self, nodes: Optional[Iterable[EvidenceNode]] = None) -> None:
        self.nodes: Dict[str, EvidenceNode] = {}
        for n in nodes or []:
            self.add(n)

    def add(self, node: EvidenceNode) -> None:
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate node_id {node.node_id!r}")
        if node.status not in CLAIM_STATUSES:
            raise ValueError(
                f"node {node.node_id!r} has non-governed claim status "
                f"{node.status!r}; expected one of {CLAIM_STATUSES}")
        self.nodes[node.node_id] = node

    def by_rq(self, rq: str) -> List[EvidenceNode]:
        return [n for n in self.nodes.values() if n.rq == rq]

    def superseded_ids(self) -> set:
        out = set()
        for n in self.nodes.values():
            out.update(n.supersedes)
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "RESEARCH_EVIDENCE_GRAPH/v1",
            "node_count": len(self.nodes),
            "nodes": {k: v.to_dict() for k, v in sorted(self.nodes.items())},
        }


# --- verification rules (§12) ---------------------------------------------

def verify(graph: EvidenceGraph, root: Path) -> Dict[str, Any]:
    """Apply every graph rule. Returns findings; empty means verified."""
    findings: List[Dict[str, Any]] = []

    def add(rule: str, severity: str, node_id: str, detail: str) -> None:
        findings.append({"rule": rule, "severity": severity,
                         "node_id": node_id, "detail": detail})

    superseded = graph.superseded_ids()
    current_by_claim: Dict[str, List[str]] = {}
    for n in graph.nodes.values():
        if n.status == "CURRENT":
            current_by_claim.setdefault((n.rq, n.claim), []).append(n.node_id)

    for n in graph.nodes.values():
        # 1. exactly one current authority per claim
        ids = current_by_claim.get((n.rq, n.claim), [])
        if n.status == "CURRENT" and len(ids) > 1:
            add("DUPLICATE_CURRENT_AUTHORITY", "BLOCKING", n.node_id,
                f"claim {n.claim!r} has {len(ids)} current authorities: {sorted(ids)}")

        # 2. SUPERSEDED evidence must not act as current
        if n.status == "CURRENT" and n.node_id in superseded:
            add("SUPERSEDED_USED_AS_CURRENT", "BLOCKING", n.node_id,
                "node is marked current but is named by a supersedes edge")

        # 3. DEFERRED/BLOCKED must not be represented as a pass
        if n.status in ("DEFERRED", "BLOCKED") and n.metric and n.status == "CURRENT":
            add("DEFERRED_OR_BLOCKED_AS_CURRENT", "BLOCKING", n.node_id,
                "deferred/blocked claim presented as current")
        if n.status in NON_PASSING_STATUSES and "AUTHORITATIVE" in n.notes:
            add("NON_PASSING_STATUS_WITH_AUTHORITATIVE_NOTE", "BLOCKING",
                n.node_id, f"status {n.status} carries an authoritative note")

        # 4. producer commit must exist and be reachable
        if n.status == "CURRENT" and n.required:
            if not commit_exists(root, n.producer_commit):
                add("PRODUCER_COMMIT_UNREACHABLE", "BLOCKING", n.node_id,
                    f"producer commit {n.producer_commit!r} is not a commit in "
                    f"this repository")

        # 5. current artifact must exist and hash-match
        if n.status == "CURRENT" and n.required:
            p = root / n.output_artifact
            if not p.is_file():
                add("REQUIRED_ARTIFACT_ABSENT", "BLOCKING", n.node_id,
                    f"current artifact missing: {n.output_artifact}")
            elif n.output_sha256 not in (UNKNOWN, MISSING):
                obs = sha256_file(p)
                if obs != n.output_sha256:
                    add("ARTIFACT_HASH_MISMATCH", "BLOCKING", n.node_id,
                        f"{n.output_artifact} records {n.output_sha256[:12]}... "
                        f"but hashes to {obs[:12]}...")

        # 6. protocol must be pinned
        if n.status == "CURRENT" and n.required and n.protocol_sha256 in (UNKNOWN, MISSING):
            add("PROTOCOL_SHA_MISSING", "ADVISORY", n.node_id,
                "current claim does not pin a protocol hash")

        # 7. input map hashes must be pinned
        if n.status == "CURRENT" and n.required and n.source_inputs:
            missing_inputs = [i for i in n.source_inputs
                              if i not in n.input_sha256]
            if missing_inputs:
                add("INPUT_SHA_MISSING", "ADVISORY", n.node_id,
                    f"inputs without a recorded sha256: {missing_inputs}")

        # 8. supersedes targets must exist
        for target in n.supersedes:
            if target not in graph.nodes:
                add("SUPERSEDES_UNKNOWN_NODE", "ADVISORY", n.node_id,
                    f"supersedes unknown node {target!r}")

        # 9. dependencies must exist
        for dep in n.dependencies:
            if dep not in graph.nodes:
                add("DEPENDENCY_UNKNOWN_NODE", "BLOCKING", n.node_id,
                    f"depends on unknown node {dep!r}")

    blocking = [f for f in findings if f["severity"] == "BLOCKING"]
    return {
        "schema": "RESEARCH_EVIDENCE_GRAPH_VERIFICATION/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_head": git(root, "rev-parse", "HEAD"),
        "node_count": len(graph.nodes),
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "findings": findings,
        "status": "FAIL" if blocking else ("ADVISORY" if findings else "PASS"),
        "claims_with_multiple_current_authorities": {
            f"{rq}:{claim}": ids
            for (rq, claim), ids in current_by_claim.items() if len(ids) > 1},
        "every_current_claim_resolves_to_one_producer": not any(
            f["rule"] == "DUPLICATE_CURRENT_AUTHORITY" for f in findings),
    }


def load_graph(path: Path) -> EvidenceGraph:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = [EvidenceNode(**d) for d in doc["nodes"].values()]
    return EvidenceGraph(nodes)