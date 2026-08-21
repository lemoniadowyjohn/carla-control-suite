#!/usr/bin/env python3
"""C19 (step 4) — pack a reproducible thesis-run bundle.

A manifest-of-manifests, not a copy of the (144MB+66MB) pinned maps
themselves -- those are referenced by path + sha256 through the existing
content-addressed registry (C13), consistent with how this repo already
treats large regenerable/pinned binaries everywhere else. Ties together:
maps by sha, the actual git/settings state ("protocol snapshot" -- no
protocol.py exists in this repo despite being referenced in earlier specs,
so this captures what genuinely governs a run instead of a fictional file),
every per-RQ evidence report, and the C19 steps 1-3 outputs, with claim
boundaries collected from the RQ table's own notes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.carla_tools.map_registry import PINNED_MAP_REGISTRY  # noqa: E402
from ultimate_pipeline.governance.inputs_manifest import sha256_file  # noqa: E402

C19_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / "C19_THESIS_ASSEMBLY"

RQ_EVIDENCE_REPORTS = [
    "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_REPORT.md",
    "reports/post_audit_hardening/C15_RQ4_DR/C15_RQ4_REPORT.md",
    "reports/post_audit_hardening/C18_GNN_LATENT_GAP/C18_GNN_LATENT_GAP_REPORT.md",
    "reports/post_audit_hardening/C17_rq2_perception_capture.md",
    "reports/post_audit_hardening/C13_manual_map_and_registry.md",
    "reports/post_audit_hardening/C20_CARLA_RUNTIME_UNBLOCK.md",
    "reports/post_audit_hardening/C20_TIER1_PROBE_20260821/FINDINGS.md",
]


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()
    except Exception as exc:
        return f"<git error: {exc}>"


def _protocol_snapshot() -> Dict[str, Any]:
    return {
        "note": "No protocol.py exists in this repo (referenced in earlier C13/C15 specs but never "
                "built) -- this snapshot captures what actually governs a run instead.",
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "canonical_regen_entrypoint": "scripts/regen_map_of_record.py",
        "inputs_manifest": "campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json",
    }


def _evidence_reports() -> List[Dict[str, Any]]:
    out = []
    for rel in RQ_EVIDENCE_REPORTS:
        p = REPO_ROOT / rel
        out.append({
            "path": rel,
            "present": p.is_file(),
            "sha256": sha256_file(p) if p.is_file() else None,
        })
    return out


def _claim_boundaries(rq_tables_path: Path) -> List[Dict[str, str]]:
    if not rq_tables_path.is_file():
        return []
    payload = json.loads(rq_tables_path.read_text(encoding="utf-8"))
    return [
        {"rq": row["rq"], "metric": row["metric"], "status": row["status"], "note": row.get("note", "")}
        for row in payload.get("rows", [])
    ]


def pack(repo_root: Path) -> Dict[str, Any]:
    maps = {key: {"path": e["path"], "sha256": e["sha256"], "role": e["role"], "bytes": e.get("bytes")}
            for key, e in PINNED_MAP_REGISTRY.items()}

    c19_outputs = {}
    for name in ("rq_tables.json", "contract_audit.json", "provenance_validation.json"):
        p = C19_DIR / name
        c19_outputs[name] = {"present": p.is_file(), "sha256": sha256_file(p) if p.is_file() else None}

    bundle = {
        "bundle_kind": "thesis_run_bundle",
        "maps_by_sha": maps,
        "protocol_snapshot": _protocol_snapshot(),
        "evidence_reports": _evidence_reports(),
        "c19_step_outputs": c19_outputs,
        "claim_boundaries": _claim_boundaries(C19_DIR / "rq_tables.json"),
    }
    return bundle


def _to_markdown(bundle: Dict[str, Any]) -> str:
    lines = ["# Thesis run bundle (C19 step 4)", ""]
    lines.append("## Pinned maps")
    for key, m in bundle["maps_by_sha"].items():
        lines.append(f"- **{key}** ({m['role']}): `{m['sha256']}` — {m['path']}")
    lines.append("")
    lines.append("## Protocol snapshot")
    for k, v in bundle["protocol_snapshot"].items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Evidence reports")
    for r in bundle["evidence_reports"]:
        mark = "✓" if r["present"] else "MISSING"
        lines.append(f"- [{mark}] {r['path']}")
    lines.append("")
    lines.append("## Claim boundaries (per RQ metric)")
    for c in bundle["claim_boundaries"]:
        lines.append(f"- **{c['rq']}/{c['metric']}** [{c['status']}]: {c['note']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    bundle = pack(REPO_ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "thesis_run_bundle.json").write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    (args.out / "THESIS_RUN_BUNDLE.md").write_text(_to_markdown(bundle), encoding="utf-8")
    missing = [r["path"] for r in bundle["evidence_reports"] if not r["present"]]
    print(f"[pack_thesis_run] -> {args.out}")
    if missing:
        print(f"[pack_thesis_run] WARNING: missing evidence reports: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
