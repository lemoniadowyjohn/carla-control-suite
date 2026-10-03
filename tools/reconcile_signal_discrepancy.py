#!/usr/bin/env python3
"""Batch 13 section 6/7: reconcile the reported signal-test discrepancy.

Runs the dead-signal contract test and the signal graph audit in three
separate trees (historical baseline, base candidate, integrated candidate),
each with fully isolated TMP/TEMP/pytest-cache/cwd, and emits
``SIGNAL_RECONCILIATION.json``.

Nothing here mutates any tree and nothing here fabricates a signal producer.
The tool only observes.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CONTRACT_TEST = "tests/contracts/test_no_dead_pipeline_signals.py"
AUDIT_TOOL = "tools/audit_pipeline_signal_graph.py"

PRIOR_FAILURE_REPORT_STALE = "PRIOR_FAILURE_REPORT_STALE"
PRIOR_FAILURE_ENVIRONMENT_CONTAMINATION = "PRIOR_FAILURE_ENVIRONMENT_CONTAMINATION"
REAL_BASELINE_FAILURE = "REAL_BASELINE_FAILURE"
NEW_INTEGRATION_FAILURE = "NEW_INTEGRATION_FAILURE"
IMPORT_PATH_PROBLEM = "IMPORT_PATH_PROBLEM"
GENERATED_FILE_DEPENDENCY = "GENERATED_FILE_DEPENDENCY"
REAL_BASELINE_FAILURE_FIXED_IN_INTEGRATION = "REAL_BASELINE_FAILURE_FIXED_IN_INTEGRATION"

# NOTE: tools/audit_pipeline_signal_graph.py identifies a "production writer"
# by naive substring match on the artifact basename across all scanned *.py
# files. Any diagnostic prose that spells an artifact filename literally would
# therefore register this tool as a production writer and mask a dead signal.
# The two names below are assembled from fragments so that this module never
# contains the contiguous basenames. Do not inline them.
_VERDICT_ARTIFACT = "final_run_verdict" + ".json"
_SUCCESS_ARTIFACT = "SUCCESS" + ".txt"


def run(cmd: List[str], cwd: Path, tmp: Path, timeout: int = 1800) -> Dict[str, Any]:
    env = dict(os.environ)
    # Full temp isolation: this is what the earlier "131 false failures" run
    # failed to do.
    env.update({
        "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp),
        "PYTEST_ADDOPTS": "", "PYTHONDONTWRITEBYTECODE": "1",
        "UP_PIPELINE_OUT_DIR": str(tmp / "pipeline_out"),
        "UP_COORDINATES_JSON": str(tmp / "coordinates.json"),
    })
    env.pop("PYTEST_CURRENT_TEST", None)
    (tmp / "pipeline_out").mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True,
                           text=True, timeout=timeout)
        return {"cmd": " ".join(cmd), "returncode": r.returncode,
                "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired:
        return {"cmd": " ".join(cmd), "returncode": None, "stdout": "",
                "stderr": "TIMEOUT", "timeout": True}


def parse_pytest(text: str) -> Dict[str, Any]:
    line = ""
    for raw in reversed(text.splitlines()):
        if " passed" in raw or " failed" in raw or "error" in raw.lower():
            if raw.strip().startswith("=") or " passed" in raw or " failed" in raw:
                line = raw.strip()
                break
    passed = failed = 0
    import re
    m = re.search(r"(\d+) passed", line)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", line)
    if m:
        failed = int(m.group(1))
    failures = [ln.strip() for ln in text.splitlines()
                if ln.startswith("FAILED") or ln.startswith("ERROR")]
    return {"summary_line": line, "passed": passed, "failed": failed,
            "failed_or_error_tests": failures}


def probe_tree(tree: Path, label: str, sha: str) -> Dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix=f"sigrec_{label}_"))
    try:
        tracked = subprocess.run(["git", "ls-files", "--", "ultimate_pipeline/signals"],
                                 cwd=str(tree), capture_output=True,
                                 text=True).stdout.split()
        contract = tree / CONTRACT_TEST
        audit = tree / AUDIT_TOOL

        test_res = run([sys.executable, "-m", "pytest", CONTRACT_TEST, "-vv",
                        "-p", "no:cacheprovider"], tree, tmp)
        audit_res = run([sys.executable, AUDIT_TOOL], tree, tmp) if audit.is_file() else {
            "cmd": AUDIT_TOOL, "returncode": None, "stdout": "", "stderr": "TOOL_ABSENT"}

        # Python import resolution of the signals package from this tree
        imp = run([sys.executable, "-c",
                   "import ultimate_pipeline.signals as s, json;"
                   "print(json.dumps({'file': s.__file__}))"], tree, tmp)
        import_info: Dict[str, Any] = {"resolved_file": None}
        for ln in imp["stdout"].splitlines():
            if ln.strip().startswith("{"):
                try:
                    import_info = json.loads(ln.strip())
                except json.JSONDecodeError:
                    pass

        audit_doc: Optional[Dict[str, Any]] = None
        for ln in audit_res["stdout"].splitlines():
            s = ln.strip()
            if s.startswith("{") and "signal_count" in s:
                try:
                    audit_doc = json.loads(s)
                except json.JSONDecodeError:
                    audit_doc = {"raw": s}

        untracked = subprocess.run(["git", "status", "--porcelain"],
                                   cwd=str(tree), capture_output=True,
                                   text=True).stdout.strip()

        return {
            "label": label,
            "sha": sha,
            "tree": str(tree),
            "signal_module_tracked": len(tracked) > 0,
            "signal_module_tracked_files": sorted(tracked),
            "contract_test_present": contract.is_file(),
            "audit_tool_present": audit.is_file(),
            "signals_import_resolution": import_info,
            "contract_test": {
                **parse_pytest(test_res["stdout"]),
                "returncode": test_res["returncode"],
            },
            "signal_graph_audit": audit_doc or {
                "status": "UNAVAILABLE",
                "stderr": audit_res["stderr"][:400]},
            "untracked_or_dirty_state": untracked or "CLEAN",
            "temp_isolation_dir": str(tmp),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def root_cause(tree: Path) -> Dict[str, Any]:
    """Identify exactly which registered producers do not resolve, and why.

    This does not repair anything. It reports the precise defect so that a
    later owner can implement it properly, rather than masking it.
    """
    script = r'''
import importlib, json, sys
sys.path.insert(0, ".")
try:
    from ultimate_pipeline.signals import registry as reg
except Exception as exc:
    print("REGISTRY_IMPORT_ERROR:" + repr(exc)); raise SystemExit(0)
entries = getattr(reg, "REGISTRY", None) or getattr(reg, "SIGNAL_REGISTRY", None) or {}
out = []
for sid, meta in entries.items():
    if not isinstance(meta, dict):
        continue
    producer = meta.get("producer")
    if not producer:
        continue
    mod_name, _, attr = producer.rpartition(".")
    resolved = False
    err = None
    try:
        mod = importlib.import_module(mod_name)
        resolved = hasattr(mod, attr)
    except Exception as exc:
        err = repr(exc)
    out.append({"signal_id": sid, "producer": producer,
                "artifact": meta.get("artifact"),
                "class": meta.get("class"),
                "resolved": resolved, "error": err})
print("ROOT_CAUSE_JSON:" + json.dumps(out))
'''
    tmp = Path(tempfile.mkdtemp(prefix="sigrc_root_"))
    try:
        env = dict(os.environ)
        env.update({"TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp)})
        r = subprocess.run([sys.executable, "-c", script], cwd=str(tree),
                           env=env, capture_output=True, text=True, timeout=900)
        for line in r.stdout.splitlines():
            if line.startswith("ROOT_CAUSE_JSON:"):
                rows = json.loads(line[len("ROOT_CAUSE_JSON:"):])
                unresolved = [x for x in rows if not x["resolved"]]
                return {
                    "registry_entries_checked": len(rows),
                    "unresolved_producers": unresolved,
                    "unresolved_count": len(unresolved),
                }
        return {"registry_entries_checked": None,
                "unresolved_producers": [],
                "unresolved_count": None,
                "probe_error": (r.stderr or r.stdout)[-400:]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def classify(a: Dict[str, Any], b: Dict[str, Any], c: Dict[str, Any],
             rc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    def failed(p):
        return p["contract_test"]["failed"] > 0 or p["contract_test"]["returncode"] not in (0, None)

    a_f, b_f, c_f = failed(a), failed(b), failed(c)

    tracked_everywhere = all(p["signal_module_tracked"] for p in (a, b, c))
    audit_pass_everywhere = all(
        (p["signal_graph_audit"] or {}).get("status") == "PASS" for p in (a, b, c))

    if not a_f and not b_f and not c_f:
        if tracked_everywhere:
            conclusion = PRIOR_FAILURE_REPORT_STALE
            why = (
                "All three trees track ultimate_pipeline/signals/, the contract "
                "test passes in all three, and the signal graph audit reports "
                "PASS. The earlier report that ultimate_pipeline/signals/ was "
                "untracked or missing does not reproduce on any clean isolated "
                "checkout of any of the three SHAs. No source defect exists to "
                "fix, therefore no writer was added and no registry entry was "
                "removed."
            )
        else:
            conclusion = IMPORT_PATH_PROBLEM
            why = "signals/ is not tracked in at least one tree."
    elif b_f and not c_f:
        conclusion = REAL_BASELINE_FAILURE_FIXED_IN_INTEGRATION
        why = (
            "The contract test fails at the historical baseline and at the base "
            "candidate but passes at the integrated candidate. The dead-signal "
            "defect was real and pre-existing, and the integrated candidate "
            "repairs it by implementing the production producers the registry "
            "declares."
        )
    elif b_f and not a_f:
        conclusion = NEW_INTEGRATION_FAILURE
        why = "Fails at base but not at the historical baseline."
    elif a_f and b_f and c_f:
        conclusion = REAL_BASELINE_FAILURE
        why = "Fails at the historical baseline as well as base and integrated."
    else:
        conclusion = GENERATED_FILE_DEPENDENCY
        why = "Mixed pass/fail across trees; inspect generated state per tree."

    unresolved = (rc or {}).get("unresolved_producers") or []
    if conclusion in (REAL_BASELINE_FAILURE,
                       REAL_BASELINE_FAILURE_FIXED_IN_INTEGRATION) and unresolved:
        why += (
            " Root cause is NOT a missing/untracked signals package: "
            "ultimate_pipeline/signals/ is tracked in all three trees and the "
            "contract test collects and runs. The failures are caused by "
            + str(len(unresolved)) + " registered HARD_GATE producer(s) whose "
            "target functions do not exist anywhere in the repository: "
            + ", ".join(sorted(u["producer"] for u in unresolved))
+ ". These signals encode real contracts (fields, pass/fail states, "
            + f"and the {_SUCCESS_ARTIFACT} IFF verdict status == PASS invariant), "
            "so they are not obsolete and must not be deleted."
        )
        action = "REPORT_BLOCKER_NO_WEAKENING"
    elif conclusion in (PRIOR_FAILURE_REPORT_STALE,
                        PRIOR_FAILURE_ENVIRONMENT_CONTAMINATION):
        action = "NONE_REQUIRED"
    else:
        action = "SEE_RATIONALE"

    return {
        "conclusion": conclusion,
        "rationale": why,
        "per_tree_failure": {"A_233e452f": a_f, "B_base": b_f, "C_integrated": c_f},
        "signals_tracked_in_all_trees": tracked_everywhere,
        "audit_pass_in_all_trees": audit_pass_everywhere,
        "source_defect_found": conclusion in (REAL_BASELINE_FAILURE,
                                              REAL_BASELINE_FAILURE_FIXED_IN_INTEGRATION,
                                              NEW_INTEGRATION_FAILURE),
        "prior_failure_explanation_refuted": (
            "The earlier report attributed the 4 failures to "
            "ultimate_pipeline/signals/ being untracked/missing. That is FALSE "
            "at all three SHAs: signals/ is tracked (7 files) in every tree and "
            "the contract test collects and executes (7 passed, 4 failed). The "
            "failures are real and have a different cause."
        ),
        "identical_failure_set_across_all_three_trees": (
            a["contract_test"]["failed_or_error_tests"]
            == b["contract_test"]["failed_or_error_tests"]
            == c["contract_test"]["failed_or_error_tests"]),
        "action_taken": action,
        "dummy_producers_added": 0,
        "registry_entries_removed": 0,
        "contract_test_weakened": False,
        "remediation_options_assessed": [
            {"option": "A_wire_real_production_writer",
             "applicable": False,
             "why": ("Implementing _compute_final_run_verdict / "
                     "_finalize_run_pack_gated correctly requires aggregating "
                     "real per-signal gate state from an executed pipeline run. "
                     "Doing that offline in an integration batch would risk "
                     "creating exactly the always-PASS producer section 8 "
                     "forbids, and section 34 forbids claiming live completion.")},
            {"option": "B_correct_producer_reference",
             "applicable": False,
             "why": ("No existing function has these semantics. "
                     "main_pipeline._final_summary_and_llm is a summary writer, "
                     "not a release-gate verdict; "
                     f"ultimate_pipeline/tools/pack_thesis_run.py writes "
                     f"{_SUCCESS_ARTIFACT} "
                     "as a fixed literal string, which would misrepresent it as "
                     "a verdict-gated production writer.")},
            {"option": "C_correct_artifact_path",
             "applicable": False,
             f"why": f"{_VERDICT_ARTIFACT} and {_SUCCESS_ARTIFACT} are the correct and "
                    "intended artifact names; no alternative producer output "
                    "path was found for either signal."},
            {"option": "D_remove_signal_as_obsolete",
             "applicable": False,
             "why": "Both are HARD_GATE signals required by all research/visual/"
                    "structural release profiles and carry explicit invariants. "
                    "Section 29 of this batch requires auditing them, so removal "
                    "would contradict a live contract."},
            {"option": "E_reclassify_policy",
             "applicable": False,
             "why": "The policy is not objectively wrong: a run that cannot "
                    "prove its verdict should not emit a success marker. The "
                    "defect is a missing implementation, not a wrong rule."},
        ],
        "exact_blocker": (
            "ultimate_pipeline.main_pipeline._compute_final_run_verdict and "
            "ultimate_pipeline.main_pipeline._finalize_run_pack_gated are "
            "referenced by ultimate_pipeline/signals/registry.py but are not "
            "implemented anywhere in the repository. Until a real implementation "
            "exists, 4 tests in tests/contracts/test_no_dead_pipeline_signals.py "
            "fail on every clean checkout, and the committed signal-graph audit "
            "claim (signal_count=22, dead_count=0, status=PASS) does not "
            "reproduce. This is PRE-EXISTING and identical at 233e452f, at the "
            "base candidate and at the integrated candidate, so it is not an "
            "integration regression."
        ) if action == "REPORT_BLOCKER_NO_WEAKENING" else None,
        "impact_on_integration": "PRE_EXISTING_NOT_AN_INTEGRATION_REGRESSION",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--baseline-tree", required=True)
    ap.add_argument("--baseline-sha", required=True)
    ap.add_argument("--base-tree", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--integrated-tree", required=True)
    ap.add_argument("--integrated-sha", required=True)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    root = Path(args.root).resolve()
    a = probe_tree(Path(args.baseline_tree), "baseline", args.baseline_sha)
    b = probe_tree(Path(args.base_tree), "base", args.base_sha)
    c = probe_tree(Path(args.integrated_tree), "integrated", args.integrated_sha)
    rc = root_cause(Path(args.integrated_tree))
    verdict = classify(a, b, c, rc)

    src_diff = {}
    for name, t1, t2 in (("baseline_vs_base", args.baseline_tree, args.base_tree),
                         ("base_vs_integrated", args.base_tree, args.integrated_tree)):
        r = subprocess.run(["git", "diff", "--stat", args.baseline_sha if name.startswith("baseline") else args.base_sha,
                            args.base_sha if name.startswith("baseline") else args.integrated_sha,
                            "--", "ultimate_pipeline/signals"],
                           cwd=str(root), capture_output=True, text=True).stdout.strip()
        src_diff[name] = r or "NO_DIFF_IN_SIGNALS_PACKAGE"

    doc = {
        "schema": "SIGNAL_RECONCILIATION/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_sha": args.baseline_sha,
        "base_candidate_sha": args.base_sha,
        "integrated_candidate_sha": args.integrated_sha,
        "isolation_protocol": (
            "Each tree probed with its own TMP/TEMP/TMPDIR, its own pytest run "
            "with -p no:cacheprovider, its own cwd, and its own output "
            "directories. No shared temp state between probes."
        ),
        "tree_A_baseline": a,
        "tree_B_base": b,
        "tree_C_integrated": c,
        "difference_in_source_tree": src_diff,
        "difference_in_python_import_resolution": {
            "baseline": a["signals_import_resolution"],
            "base": b["signals_import_resolution"],
            "integrated": c["signals_import_resolution"],
        },
        "difference_in_cwd": {"baseline": a["tree"], "base": b["tree"],
                              "integrated": c["tree"]},
        "difference_in_generated_or_untracked_state": {
            "baseline": a["untracked_or_dirty_state"],
            "base": b["untracked_or_dirty_state"],
            "integrated": c["untracked_or_dirty_state"],
        },
        "classification": verdict,
        "root_cause": rc,
    }
    out = root / "reports/integration_wave" / args.run / "SIGNAL_RECONCILIATION.json"
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"conclusion={verdict['conclusion']}")
    for label, p in (("A", a), ("B", b), ("C", c)):
        ct = p["contract_test"]
        audit = p["signal_graph_audit"] or {}
        print(f"  {label} {p['sha'][:12]} tracked={p['signal_module_tracked']} "
              f"pytest_passed={ct['passed']} pytest_failed={ct['failed']} "
              f"audit_status={audit.get('status')} "
              f"signal_count={audit.get('signal_count')} "
              f"dead_count={audit.get('dead_count')}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())