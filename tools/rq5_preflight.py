#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/rq5_preflight.py

RQ5(a) dry-run orchestrator. Executes every offline readiness check *without*
performing final training.

It answers a single question: is RQ5 ready to train, and if not, exactly what is
missing? It never trains a model, never fabricates a dataset, and never
substitutes a dataset for the one requested.

Final status values
-------------------
``RQ5_OFFLINE_READY_DATASET_BLOCKED``
    All offline authority is in place and self-consistent, but no validated RQ3
    paired dataset exists yet. **This is success for an offline batch.**
``RQ5_PROTOCOL_V2_READY``
    Protocol v2 and every offline authority validated against a real dataset.
``RQ5_SPLIT_AUTHORITY_FAIL``
    Splits could not be produced, or leakage was proven.
``RQ5_TRAINING_CONTRACT_FAIL``
    Dataset identity, quality gate or the research-strict trainer contract fails.
``PARTIAL_WITH_EXACT_BLOCKERS``
    Anything else; the blockers are listed verbatim.

No CARLA import, no torch import, no network. Dataset contents are only read
when the caller supplies explicit paths; with no paths the tool reports
``dataset_blocked`` rather than guessing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.perception.dataset_quality_gate import (  # noqa: E402
    QUALITY_PASS,
    evaluate_dataset_quality,
)
from ultimate_pipeline.perception.dataset_split_authority import (  # noqa: E402
    ALL_ROLES,
    SPLIT_FILENAMES,
    SplitAuthorityError,
    audit_leakage,
    build_split_authority,
    load_split_manifest,
    write_leakage_audit,
    write_split_manifests,
)
from ultimate_pipeline.perception.rq5_provenance import (  # noqa: E402
    PROTOCOL_V2_RELPATH,
    canonical_dumps,
    evaluation_role_contract,
    protocol_identity,
    sha256_file,
    sha256_text,
)

__all__ = [
    "PREFLIGHT_SCHEMA",
    "PREFLIGHT_FILENAME",
    "SEED_LIST",
    "STATUS_READY_BLOCKED",
    "STATUS_PROTOCOL_READY",
    "STATUS_SPLIT_FAIL",
    "STATUS_TRAINING_FAIL",
    "STATUS_PARTIAL",
    "check_protocol",
    "check_candidate_clean",
    "check_seed_list",
    "check_evaluation_roles",
    "check_output_isolation",
    "check_trainer_strict_mode",
    "check_dataset_inputs",
    "run_preflight",
    "main",
]

PREFLIGHT_SCHEMA = "rq5_preflight_v1"
PREFLIGHT_FILENAME = "RQ5_PREFLIGHT.json"

#: Protocol v2 seed list.
SEED_LIST = (7, 17, 42)

STATUS_READY_BLOCKED = "RQ5_OFFLINE_READY_DATASET_BLOCKED"
STATUS_PROTOCOL_READY = "RQ5_PROTOCOL_V2_READY"
STATUS_SPLIT_FAIL = "RQ5_SPLIT_AUTHORITY_FAIL"
STATUS_TRAINING_FAIL = "RQ5_TRAINING_CONTRACT_FAIL"
STATUS_PARTIAL = "PARTIAL_WITH_EXACT_BLOCKERS"


def _check(code: str, ok: bool, detail: str, **data: Any) -> Dict[str, Any]:
    return {"code": code, "status": "PASS" if ok else "FAIL", "detail": detail, "data": data or {}}


# ---------------------------------------------------------------------------
# offline checks (never need a dataset)
# ---------------------------------------------------------------------------


def check_protocol(protocol_path: Optional[Path] = None) -> Dict[str, Any]:
    """Validate the frozen protocol v2 contract and its amendment rationale."""
    checks: List[Dict[str, Any]] = []
    try:
        identity = protocol_identity(protocol_path)
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "checks": [_check("protocol_present", False, str(exc))],
            "identity": None,
        }

    checks.append(
        _check(
            "protocol_present",
            True,
            f"frozen protocol resolved: {identity['relpath']}",
            sha256=identity["sha256"],
        )
    )
    checks.append(
        _check(
            "protocol_schema",
            identity["schema"] == "rq5_protocol_freeze/v2",
            f"protocol schema is {identity['schema']!r}",
        )
    )
    checks.append(
        _check(
            "protocol_status_frozen",
            identity["status"] == "FROZEN",
            f"protocol status is {identity['status']!r}",
        )
    )

    payload = json.loads(Path(identity["path"]).read_text(encoding="utf-8"))
    decisions = payload.get("decisions") or {}

    required = [
        "model_architecture",
        "optimizer",
        "learning_rate",
        "epochs",
        "batch_size",
        "augmentations",
        "seed_policy",
        "checkpoint_selection",
        "validation_loop",
        "split_authority",
        "leakage_audit",
        "dataset_quality_gate",
        "dataset_identity_completeness",
        "research_strict_mode",
        "determinism_contract",
        "model_manifest",
        "convergence_gate",
        "evaluation_roles",
    ]
    missing = [name for name in required if name not in decisions]
    checks.append(
        _check(
            "protocol_required_decisions",
            not missing,
            "every required decision has a frozen value"
            if not missing
            else f"missing decisions: {missing}",
            missing=missing,
        )
    )

    contradiction = payload.get("v1_contradiction_found") or {}
    checks.append(
        _check(
            "protocol_amendment_rationale",
            bool(contradiction.get("defect")) and bool(contradiction.get("resolution_strategy")),
            "the v1 checkpoint-selection contradiction is recorded with a resolution strategy",
            resolution=contradiction.get("resolution_strategy"),
        )
    )

    selection = decisions.get("checkpoint_selection") or {}
    v2_values = selection.get("value", "")
    checks.append(
        _check(
            "protocol_v1_hyperparameters_preserved",
            _v1_values_preserved(decisions),
            "v1 architecture/optimizer/lr/epochs/batch/augmentation/seed values are carried "
            "over unchanged into v2",
        )
    )
    checks.append(
        _check(
            "checkpoint_selection_minimal_rule",
            "final-epoch" in v2_values.lower()
            and "never selects a different epoch" in v2_values.lower(),
            "checkpoint selection is resolved by the minimal non-post-hoc rule",
        )
    )
    checks.append(
        _check(
            "underpowered_contingency",
            bool(contradiction.get("contingency"))
            and "RQ5_PROTOCOL_UNDERPOWERED" in str(contradiction.get("contingency")),
            "an inadequate-epoch outcome is routed to RQ5_PROTOCOL_UNDERPOWERED with a "
            "preregistered v3, never to silent extra training",
        )
    )

    return {
        "ok": all(c["status"] == "PASS" for c in checks),
        "checks": checks,
        "identity": identity,
        "decision_count": len(decisions),
    }


def _v1_values_preserved(decisions: Mapping[str, Any]) -> bool:
    """v2 must not have quietly changed a v1 hyperparameter."""
    expected = {
        "model_architecture": "fcn_resnet50",
        "optimizer": "Adam",
        "learning_rate": 0.0001,
        "epochs": 3,
        "batch_size": 4,
        "augmentations": "none",
    }
    for name, want in expected.items():
        value = (decisions.get(name) or {}).get("value")
        if isinstance(want, float):
            try:
                if abs(float(value) - want) > 0:
                    return False
            except (TypeError, ValueError):
                return False
        elif isinstance(want, int):
            if int(value) != want:
                return False
        elif want.lower() not in str(value).lower():
            return False
    seed_text = str((decisions.get("seed_policy") or {}).get("value") or "")
    return all(str(s) in seed_text for s in SEED_LIST)


def check_candidate_clean(repo_root: Path, ignore_paths: Sequence[Path] = ()) -> Dict[str, Any]:
    """
    The candidate must be a committed tree, not a dirty working copy.

    ``ignore_paths`` excludes this tool's own evidence directory, so writing
    ``RQ5_PREFLIGHT.json`` does not make the candidate it just audited dirty.
    Any *other* modification still fails the check.
    """
    import subprocess

    ignored_resolved = []
    for path in ignore_paths:
        try:
            ignored_resolved.append(str(Path(path).resolve()))
        except OSError:  # pragma: no cover - defensive
            continue

    def _git(*args: str) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return proc.returncode == 0, proc.stdout.strip()

    ok_sha, sha = _git("rev-parse", "HEAD")
    ok_dirty, dirty = _git("status", "--porcelain")
    relevant = []
    ignored = []
    for line in (dirty.splitlines() if ok_dirty else []):
        path_text = line[3:].strip().strip('"')
        try:
            absolute = str((repo_root / path_text).resolve())
        except OSError:  # pragma: no cover
            absolute = path_text
        if any(absolute == i or absolute.startswith(i + os.sep) for i in ignored_resolved):
            ignored.append(line)
        else:
            relevant.append(line)
    clean = ok_dirty and not relevant
    return {
        "ok": bool(ok_sha) and clean,
        "checks": [
            _check("candidate_head_resolvable", ok_sha, f"git HEAD = {sha or 'unresolved'}", sha=sha),
            _check(
                "candidate_clean",
                clean,
                "working tree is clean"
                if clean
                else f"working tree is dirty:\n{chr(10).join(relevant[:20])}",
                ignored_evidence_entries=len(ignored),
            ),
        ],
        "head": sha,
        "ignored_evidence_entries": len(ignored),
    }


def check_seed_list(seed_list: Sequence[int] = SEED_LIST) -> Dict[str, Any]:
    """The protocol seed list must be exactly three distinct non-negative ints."""
    values = [int(s) for s in seed_list]
    ok = len(values) == 3 and len(set(values)) == 3 and all(v >= 0 for v in values)
    return {
        "ok": ok,
        "checks": [
            _check(
                "seed_list_valid",
                ok,
                f"seed list {values} is three distinct non-negative integers",
                seeds=values,
            )
        ],
        "seeds": values,
    }


def check_evaluation_roles() -> Dict[str, Any]:
    """Evaluation roles must stay explicit and accuracy must stay role-bound."""
    contracts = {}
    ok = True
    for role in ("generated_test", "manual_test", "real_unlabeled"):
        contract = evaluation_role_contract(role)
        contracts[role] = contract
    checks = [
        _check(
            "evaluation_roles_explicit",
            set(contracts) == {"generated_test", "manual_test", "real_unlabeled"},
            "generated_test / manual_test / real_unlabeled are all governed roles",
        ),
        _check(
            "unlabeled_role_forbids_accuracy",
            contracts["real_unlabeled"]["accuracy_claim_allowed"] is False
            and "entropy" in contracts["real_unlabeled"]["allowed_metric_families"],
            "real_unlabeled may only report shift measures, never accuracy",
        ),
        _check(
            "labeled_roles_allow_accuracy",
            all(contracts[r]["accuracy_claim_allowed"] for r in ("generated_test", "manual_test")),
            "labeled sim roles may report accuracy metrics",
        ),
    ]
    ok = all(c["status"] == "PASS" for c in checks)
    return {"ok": ok, "checks": checks, "contracts": contracts}


def check_output_isolation(out_dir: Path, seeds: Sequence[int] = SEED_LIST) -> Dict[str, Any]:
    """
    Each seed must own an isolated output directory.

    Three seeds writing into one directory would let the last writer's
    checkpoint satisfy the earlier seed's manifest binding.
    """
    planned = [out_dir / f"seed_{s}" for s in seeds]
    collisions = len({str(p.resolve()) for p in planned}) != len(planned)
    checks = [
        _check(
            "output_dirs_isolated",
            not collisions,
            "each seed writes to its own output directory",
            planned=[str(p) for p in planned],
        )
    ]
    return {"ok": not collisions, "checks": checks, "planned_dirs": [str(p) for p in planned]}


def check_trainer_strict_mode() -> Dict[str, Any]:
    """
    Exercise the research-strict contract without training anything.

    The trainer's strict gate is checked by importing it and calling it with a
    namespace that violates each rule in turn. Each violation must raise.
    """
    from ultimate_pipeline.perception import train_launcher

    checks: List[Dict[str, Any]] = []
    base_ns: Dict[str, Any] = dict(
        camera="front",
        seed=7,
        datasets=None,
        dataset=None,
        limit=0,
        epochs=3,
        batch=4,
        lr=1e-4,
        class_weight_scheme="median_frequency",
        no_manifest=False,
        dataset_identity_max_files=0,
    )
    for rule, override in (
        ("implicit_split_creation", {"split_dir": None}),
        ("implicit_camera", {"split_dir": str(REPO_ROOT), "camera": None}),
        ("implicit_seed", {"split_dir": str(REPO_ROOT), "camera": "front", "seed": None}),
    ):
        namespace = argparse.Namespace(**{**base_ns, "split_dir": str(REPO_ROOT), **override})
        try:
            train_launcher.enforce_research_strict(namespace)
            checks.append(_check(f"strict_forbids_{rule}", False, f"{rule} was not rejected"))
        except SystemExit as exc:
            checks.append(
                _check(f"strict_forbids_{rule}", True, f"{rule} rejected: {exc}", message=str(exc))
            )
        except Exception as exc:  # pragma: no cover - defensive
            checks.append(
                _check(f"strict_forbids_{rule}", False, f"unexpected {type(exc).__name__}: {exc}")
            )

    checks.append(
        _check(
            "strict_protocol_values_pinned",
            all(
                int(v) == int(train_launcher.STRICT_PROTOCOL_VALUES[k])
                for k, v in (("epochs", 3), ("batch_size", 4))
            )
            and abs(float(1e-4) - float(train_launcher.STRICT_PROTOCOL_VALUES["learning_rate"])) < 1e-12,
            f"strict mode pins {train_launcher.STRICT_PROTOCOL_VALUES}",
        )
    )
    checks.append(
        _check(
            "legacy_fallback_preserved",
            callable(getattr(train_launcher, "_find_latest_dataset", None)),
            "the legacy mtime-based discovery helper still exists for non-strict development use",
        )
    )
    ok = all(c["status"] == "PASS" for c in checks)
    return {"ok": ok, "checks": checks}


# ---------------------------------------------------------------------------
# dataset checks (only when explicit data is supplied)
# ---------------------------------------------------------------------------


def check_dataset_inputs(
    *,
    generated_root: Optional[Path],
    camera: Optional[str],
    manual_root: Optional[Path] = None,
    out_dir: Path,
    generated_metadata: Optional[Path] = None,
    manual_metadata: Optional[Path] = None,
    ratios: Optional[Mapping[str, float]] = None,
    write_evidence: bool = True,
) -> Dict[str, Any]:
    """
    Run quality gate, split authority and leakage audit on explicit datasets.

    With no explicit paths this reports ``dataset_blocked`` rather than
    searching the filesystem: preflight must never invent a dataset.
    """
    checks: List[Dict[str, Any]] = []
    evidence: Dict[str, Any] = {}

    if generated_root is None or camera is None:
        checks.append(
            _check(
                "dataset_inputs_supplied",
                False,
                "no explicit --generated-root/--camera supplied; no RQ3 paired dataset is "
                "available, so splits cannot be produced. Nothing was searched or guessed.",
            )
        )
        return {
            "ok": False,
            "dataset_blocked": True,
            "checks": checks,
            "evidence": evidence,
        }

    checks.append(
        _check(
            "dataset_inputs_supplied",
            True,
            f"explicit dataset inputs: generated={generated_root} camera={camera!r}",
        )
    )

    # --- quality gate per role --------------------------------------------
    quality_by_role: Dict[str, Any] = {}
    quality_ok = True
    for role, root in (("generated", generated_root), ("manual", manual_root)):
        if root is None:
            continue
        try:
            report = evaluate_dataset_quality(root, camera, role=role, num_classes=29)
        except Exception as exc:
            quality_ok = False
            quality_by_role[role] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
            continue
        quality_by_role[role] = report.to_dict()
        if report.status != QUALITY_PASS:
            quality_ok = False
    checks.append(
        _check(
            "dataset_quality_pass",
            quality_ok,
            "every supplied dataset passed the quality gate"
            if quality_ok
            else "at least one dataset failed the quality gate",
            roles={k: v.get("status") for k, v in quality_by_role.items()},
        )
    )
    evidence["dataset_quality"] = quality_by_role

    # --- split authority ---------------------------------------------------
    try:
        authority = build_split_authority(
            generated_root=generated_root,
            camera=camera,
            manual_root=manual_root,
            ratios=ratios,
            generated_metadata_path=generated_metadata,
            manual_metadata_path=manual_metadata,
            require_metadata=True,
        )
    except SplitAuthorityError as exc:
        checks.append(
            _check("split_authority_built", False, f"split authority refused: {exc}")
        )
        return {
            "ok": False,
            "dataset_blocked": False,
            "checks": checks,
            "evidence": evidence,
        }

    checks.append(
        _check(
            "split_authority_built",
            True,
            f"grouped split produced with group kind {authority.group_kind!r}",
            role_frame_counts={r: len(v) for r, v in authority.roles.items()},
        )
    )
    checks.append(
        _check(
            "split_grouping_governed",
            not authority.degraded,
            "grouping came from dataset metadata"
            if not authority.degraded
            else "grouping fell back to inferred filename blocks (DEGRADED)",
            group_kind=authority.group_kind,
        )
    )
    evidence["split_summary"] = authority.summary()

    identities_complete = all(
        bool(m.get("dataset_identity_complete")) for m in authority.manifests.values()
    )
    checks.append(
        _check(
            "dataset_identities_complete",
            identities_complete,
            "every split manifest records a complete dataset identity"
            if identities_complete
            else "at least one split manifest carries an incomplete dataset identity",
        )
    )

    # --- leakage -----------------------------------------------------------
    leakage = audit_leakage(authority.manifests)
    checks.append(
        _check(
            "split_leakage_free",
            bool(leakage["leak_free"]),
            "no content, group or temporal-adjacency overlap between governed roles"
            if leakage["leak_free"]
            else f"{len(leakage['violations'])} leakage violation(s)",
            violations=leakage["violations"][:5],
        )
    )
    evidence["leakage_audit"] = leakage

    if write_evidence:
        paths = write_split_manifests(out_dir, authority)
        leakage_path = write_leakage_audit(out_dir, leakage)
        evidence["written"] = {
            **{f"manifest::{role}": str(path) for role, path in paths.items()},
            "leakage_audit": str(leakage_path),
        }
        checks.append(
            _check(
                "split_manifests_written",
                len(paths) >= 3,
                f"wrote {len(paths)} split manifest(s) and the leakage audit to {out_dir}",
            )
        )

    ok = all(c["status"] == "PASS" for c in checks)
    return {
        "ok": ok,
        "dataset_blocked": False,
        "checks": checks,
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


def run_preflight(
    *,
    generated_root: Optional[Path] = None,
    camera: Optional[str] = None,
    manual_root: Optional[Path] = None,
    out_dir: Path = REPO_ROOT / "reports" / "parallel_wave" / "rq5",
    repo_root: Path = REPO_ROOT,
    seeds: Sequence[int] = SEED_LIST,
    protocol_path: Optional[Path] = None,
    generated_metadata: Optional[Path] = None,
    manual_metadata: Optional[Path] = None,
    ratios: Optional[Mapping[str, float]] = None,
    write_evidence: bool = True,
) -> Dict[str, Any]:
    """Run every offline readiness check and return the preflight report."""
    out_dir = Path(out_dir)
    if write_evidence:
        out_dir.mkdir(parents=True, exist_ok=True)

    sections: Dict[str, Any] = {
        "protocol": check_protocol(protocol_path),
        # The preflight output file is this tool's own product: writing it must
        # not make the candidate it just audited look dirty.
        "candidate": check_candidate_clean(
            repo_root, ignore_paths=(out_dir, out_dir / PREFLIGHT_FILENAME)
        ),
        "seeds": check_seed_list(seeds),
        "evaluation_roles": check_evaluation_roles(),
        "output_isolation": check_output_isolation(out_dir, seeds),
        "trainer_strict_mode": check_trainer_strict_mode(),
        "datasets": check_dataset_inputs(
            generated_root=generated_root,
            camera=camera,
            manual_root=manual_root,
            out_dir=out_dir,
            generated_metadata=generated_metadata,
            manual_metadata=manual_metadata,
            ratios=ratios,
            write_evidence=write_evidence,
        ),
    }

    offline_ok = all(
        sections[name]["ok"] for name in ("protocol", "candidate", "seeds", "evaluation_roles", "output_isolation", "trainer_strict_mode")
    )
    datasets = sections["datasets"]

    if not offline_ok:
        status = STATUS_PARTIAL
        rationale = "one or more offline authority checks failed; see checks for the exact blockers"
    elif datasets.get("dataset_blocked"):
        status = STATUS_READY_BLOCKED
        rationale = (
            "every offline authority check passed; no validated RQ3 paired dataset exists, so "
            "final RQ5 training is blocked on data rather than on code"
        )
    elif not datasets["ok"]:
        split_failed = any(
            c["code"] in ("split_authority_built", "split_leakage_free", "split_grouping_governed")
            and c["status"] == "FAIL"
            for c in datasets["checks"]
        )
        status = STATUS_SPLIT_FAIL if split_failed else STATUS_TRAINING_FAIL
        rationale = "a dataset was supplied but the governed split/quality contract failed"
    else:
        status = STATUS_PROTOCOL_READY
        rationale = "protocol v2 and every offline authority validated against a real dataset"

    report = {
        "schema": PREFLIGHT_SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "claim_scope": "OFFLINE_READINESS_AUDIT",
        "final_rq5_training_executed": False,
        "final_status": status,
        "rationale": rationale,
        "offline_authority_ok": offline_ok,
        "dataset_blocked": bool(datasets.get("dataset_blocked")),
        "dataset_inputs": {
            "generated_root": str(generated_root) if generated_root else None,
            "manual_root": str(manual_root) if manual_root else None,
            "camera": camera,
            "explicit": generated_root is not None,
        },
        "sections": sections,
        "claim_boundary": (
            "Preflight is an offline readiness audit. It performs no training, creates no "
            "capture, and proves nothing about RQ5 accuracy or generalization. "
            "RQ5_OFFLINE_READY_DATASET_BLOCKED is the correct outcome whenever no validated "
            "RQ3 paired dataset exists."
        ),
    }
    report["report_sha256"] = sha256_text(
        canonical_dumps({k: v for k, v in report.items() if k not in ("created_utc", "report_sha256")})
    )
    if write_evidence:
        report["evidence_sha256"] = _evidence_hashes(out_dir)
        target = out_dir / PREFLIGHT_FILENAME
        target.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        report["written_to"] = str(target)
    return report


def _evidence_hashes(out_dir: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    if not out_dir.is_dir():
        return hashes
    for name in (*SPLIT_FILENAMES.values(), "RQ5_SPLIT_LEAKAGE_AUDIT.json", "DATASET_QUALITY.json"):
        path = out_dir / name
        if path.is_file():
            hashes[name] = sha256_file(path)
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-root", type=Path, default=None,
                        help="explicit generated (simulator) capture root; never auto-discovered")
    parser.add_argument("--manual-root", type=Path, default=None,
                        help="explicit manual (target-world) capture root")
    parser.add_argument("--camera", type=str, default=None, help="explicit camera name")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "reports" / "parallel_wave" / "rq5")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--protocol", type=Path, default=None)
    parser.add_argument("--generated-metadata", type=Path, default=None)
    parser.add_argument("--manual-metadata", type=Path, default=None)
    parser.add_argument("--train-ratio", type=float, default=None)
    parser.add_argument("--validation-ratio", type=float, default=None)
    parser.add_argument("--test-ratio", type=float, default=None)
    parser.add_argument("--no-write", action="store_true", help="do not persist evidence files")
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args()

    ratios = None
    if args.train_ratio is not None and args.validation_ratio is not None and args.test_ratio is not None:
        ratios = {
            "generated_train": args.train_ratio,
            "generated_validation": args.validation_ratio,
            "generated_test": args.test_ratio,
        }

    write = not args.no_write
    report = run_preflight(
        generated_root=args.generated_root,
        camera=args.camera,
        manual_root=args.manual_root,
        out_dir=args.out_dir,
        repo_root=args.repo_root,
        protocol_path=args.protocol,
        generated_metadata=args.generated_metadata,
        manual_metadata=args.manual_metadata,
        ratios=ratios,
        write_evidence=write,
    )
    if write:
        if not (args.out_dir / PREFLIGHT_FILENAME).is_file():
            args.out_dir.mkdir(parents=True, exist_ok=True)
            args.out_json = args.out_dir / PREFLIGHT_FILENAME
            args.out_json.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        target = args.out_json or (args.out_dir / PREFLIGHT_FILENAME)
        print(f"wrote {target}")

    print(json.dumps({"final_status": report["final_status"],
                      "rationale": report["rationale"],
                      "dataset_blocked": report["dataset_blocked"]}, indent=2))
    return 0 if report["final_status"] in (STATUS_READY_BLOCKED, STATUS_PROTOCOL_READY) else 2


if __name__ == "__main__":
    raise SystemExit(main())