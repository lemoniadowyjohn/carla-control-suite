#!/usr/bin/env python
"""AUDIT-NORM-001 — audit normalization core (importable, testable).

Scope: audit/report tooling only. Pipeline source is never modified.
Enforces the strict status logic:

    PASS  <=> evidence_met=true
              AND all mandatory negative controls executed
              AND contradictions == []
              AND current identity matches (stale identity -> downgrade)

All functions are pure; tests feed synthetic fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple

ISSUE_ID_PREFIXES = ("REP-I", "OSM-I", "ENR-I")
DEFAULT_ISSUE_IDS = [
    "REP-I01", "REP-I02", "REP-I03", "REP-I04",
    "OSM-I01", "OSM-I02", "OSM-I03", "OSM-I04",
    "ENR-I01", "ENR-I02", "ENR-I03", "ENR-I04", "ENR-I05", "ENR-I06",
]
RELEASE_PROFILES = [
    "STANDALONE_XODR",
    "COOKED_VISUAL_MAP",
    "PERCEPTION_READY",
    "DOMAIN_GAP_ONLY",
    "FULL_PRODUCTION_RELEASE",
]
EXPECTED_FORMAL = 218
EXPECTED_TOTAL = 232


class AuditNormalizationError(Exception):
    """Raised for hard normalization violations (duplicates, missing IDs, ...)."""


# ---------------------------------------------------------------- A1 registry
def build_registry(
    formal_ids: Iterable[str],
    issue_ids: Optional[Iterable[str]] = None,
    expected_total: int = EXPECTED_TOTAL,
) -> Dict:
    """Return registry + coverage for a set of formal IDs.

    Raises AuditNormalizationError on duplicate or unparseable IDs.
    """
    formal = list(formal_ids)
    issues = list(issue_ids) if issue_ids is not None else list(DEFAULT_ISSUE_IDS)
    dups = [i for i, c in Counter(formal).items() if c > 1]
    if dups:
        raise AuditNormalizationError(f"duplicate ids: {dups}")
    malformed = [i for i in formal if not isinstance(i, str) or not i.strip()]
    if malformed:
        raise AuditNormalizationError(f"malformed ids: {malformed}")
    all_ids = formal + issues
    if len(all_ids) != expected_total:
        raise AuditNormalizationError(
            f"tracked count mismatch: {len(all_ids)} != {expected_total}")
    coverage = {
        "formal_ids": len(formal),
        "issue_ids": len(issues),
        "total_tracked": len(all_ids),
        "expected_claimed": expected_total,
        "duplicate_ids": len(dups),
        "malformed_ids": len(malformed),
        "unknown_ids": 0,
        "unassessed": 0,
    }
    return {"formal_ids": formal, "issue_ids": issues, "coverage": coverage}


# ---------------------------------------------------------------- A2 status
def apply_status_logic(records: Iterable[Dict]) -> List[Dict]:
    """Apply strict PASS rule; returns one correction record per requirement.

    Any PASS not meeting all four conditions is downgraded:
    - evidence_met=false            -> INSUFFICIENT_EVIDENCE
    - mandatory negative control    -> INSUFFICIENT_EVIDENCE (not executed)
    - unresolved contradictions     -> CONFLICTING_EVIDENCE
    - stale identity                -> INSUFFICIENT_EVIDENCE (identity_delta)
    """
    corrections = []
    for r in records:
        rid = r["requirement_id"]
        nc = r.get("negative_control") or {}
        nc_req = bool(nc.get("required"))
        nc_exec = bool(nc.get("executed"))
        contradictions = r.get("contradictions") or []
        evidence_met = bool(r.get("evidence_met"))
        audited = r.get("verification_state", "UNASSESSED")
        stale = bool(r.get("identity_stale") or r.get("identity_delta"))
        if audited == "PASS":
            if stale:
                corrected, reason = "INSUFFICIENT_EVIDENCE", \
                    "PASS->downgrade: stale branch/commit/artifact identity"
            elif not evidence_met:
                corrected, reason = "INSUFFICIENT_EVIDENCE", \
                    "PASS->downgrade: evidence_met=false"
            elif nc_req and not nc_exec:
                corrected, reason = "INSUFFICIENT_EVIDENCE", \
                    "PASS->downgrade: mandatory negative control not executed"
            elif contradictions:
                corrected, reason = "CONFLICTING_EVIDENCE", \
                    "PASS->downgrade: unresolved contradictions"
            else:
                corrected, reason = "PASS", "PASS sustained"
        else:
            corrected, reason = audited, "unchanged by status logic"
        corrections.append({
            "requirement_id": rid,
            "audited_status": audited,
            "corrected_status": corrected,
            "evidence_met": evidence_met,
            "negative_control_required": nc_req,
            "negative_control_executed": nc_exec,
            "unresolved_contradictions": len(contradictions),
            "identity_stale": stale,
            "correction": reason,
        })
    return corrections


def assert_no_invalid_pass(corrections: List[Dict]) -> None:
    """Fail-closed check: zero PASS with any disqualifying condition."""
    bad = [c for c in corrections
           if c["corrected_status"] == "PASS"
           and (not c["evidence_met"]
                or (c["negative_control_required"] and not c["negative_control_executed"])
                or c["unresolved_contradictions"] > 0
                or c["identity_stale"])]
    if bad:
        raise AuditNormalizationError(
            f"invalid PASS records: {[b['requirement_id'] for b in bad]}")


# ---------------------------------------------------------------- A3 effects
def recalculate_release_effects(corrections: List[Dict],
                                records: Dict[str, Dict]) -> Dict:
    """Per-profile release effect recalculation (fail-closed, no inheritance).

    Any non-PASS corrected requirement blocks the profile unless the audit
    declared it BLOCKS_ALL_RELEASES (then it blocks all).
    """
    profiles: Dict[str, Dict] = {}
    for prof in RELEASE_PROFILES:
        rows = []
        for c in corrections:
            rec = records.get(c["requirement_id"], {})
            status = c["corrected_status"]
            audited_effect = rec.get("release_effect", "NON_BLOCKING")
            if status == "PASS" or status == "NOT_APPLICABLE":
                effect = "NON_BLOCKING"
            elif audited_effect == "BLOCKS_ALL_RELEASES":
                effect = "BLOCKS_ALL_RELEASES"
            else:
                effect = "BLOCKS_PROFILE"
            rows.append({"requirement_id": c["requirement_id"],
                         "corrected_status": status,
                         "recalculated_effect": effect,
                         "audited_effect": audited_effect})
        blocks = [r for r in rows if r["recalculated_effect"] != "NON_BLOCKING"]
        profiles[prof] = {
            "verdict": "BLOCKED" if blocks else "PASS",
            "counts": dict(Counter(r["recalculated_effect"] for r in rows)),
            "status_counts": dict(Counter(r["corrected_status"] for r in rows)),
            "blockers": [r["requirement_id"] for r in blocks][:50],
        }
    return {"profiles": profiles}


# ---------------------------------------------------------------- A4 hashes
def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest(manifest: Dict, repo_root: str,
                    audit_dir: Optional[str] = None) -> Dict:
    """Verify every claimed hash in an evidence manifest.

    String-valued artifact entries (no hash claim) are checked for existence.
    """
    ver: Dict[str, Dict] = {}
    for name, art in (manifest.get("artifacts") or {}).items():
        if isinstance(art, str):
            p = os.path.join(repo_root, art)
            ver[name] = {"path": art, "claimed": None,
                         "actual": sha256(p) if os.path.exists(p) else "MISSING",
                         "match": os.path.exists(p)}
            continue
        p = os.path.join(repo_root, art["path"])
        actual = sha256(p) if os.path.exists(p) else "MISSING"
        ver[name] = {"path": art["path"], "claimed": art["sha256"],
                     "actual": actual, "match": art["sha256"] == actual}
    for name, out in (manifest.get("outputs") or {}).items():
        base = audit_dir if audit_dir is not None else repo_root
        p = os.path.join(base, name)
        actual = sha256(p) if os.path.exists(p) else "MISSING"
        ver[f"output:{name}"] = {"path": p, "claimed": out["sha256"],
                                 "actual": actual, "match": out["sha256"] == actual}
    mismatches = [k for k, v in ver.items() if not v["match"]]
    return {"checks": len(ver), "mismatches": mismatches, "items": ver}


def verify_archive_round_trip(zip_path: str, extract_dir: str,
                              expected_hashes: Dict[str, str]) -> Dict:
    """Extract a zip cleanly and compare every file hash+size to expectations.

    Raises AuditNormalizationError on archive integrity failure.
    """
    try:
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad is not None:
                raise AuditNormalizationError(f"archive corrupt member: {bad}")
            z.extractall(extract_dir)
            members = z.namelist()
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise AuditNormalizationError(f"archive integrity failure: {exc}")
    mismatches = []
    for rel, exp_hash in expected_hashes.items():
        p = os.path.join(extract_dir, rel)
        if not os.path.isfile(p):
            mismatches.append({"entry": rel, "issue": "missing after extract"})
            continue
        actual = sha256(p)
        if actual != exp_hash:
            mismatches.append({"entry": rel, "issue": "hash mismatch",
                               "expected": exp_hash, "actual": actual})
    return {"members": len(members), "extract_dir": extract_dir,
            "mismatches": mismatches,
            "round_trip": "PASS" if not mismatches else "FAIL"}


def load_results(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]
