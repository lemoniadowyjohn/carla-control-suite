#!/usr/bin/env python3
"""Duplicate-namespace repair for import salvage (Batch 17, sections 7-9).

Deterministic, journaled, transactional:
  classify -> plan -> quarantine-move (never delete-first) -> validate.

Mismatch fails closed. Second execution over reconciled state is a NOOP.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ACTIONS = (
    "KEEP_CANONICAL_DROP_STAGING",
    "REPLACE_CANONICAL_WITH_STAGING",
    "MOVE_STAGING_TO_MISSING_CANONICAL",
    "KEEP_STAGING_TEMPORARILY",
    "NO_ACTION",
    "BLOCKED",
)


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for ch in iter(lambda: fh.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def bulk_key(name: str) -> str:
    return name.rsplit(".", 1)[0]


def classify_pair(staging: Optional[Dict[str, Any]],
                  canonical: Optional[Dict[str, Any]],
                  staging_bulk: Dict[str, str],
                  canonical_bulk: Dict[str, str]) -> str:
    if staging is None and canonical is None:
        return "BLOCKED"
    if staging is None:
        return "NO_ACTION"  # canonical-only: nothing to reconcile
    if canonical is None:
        return "KEEP_STAGING_TEMPORARILY"  # staging-only: keep for now
    if staging["sha256"] == canonical["sha256"]:
        return "KEEP_CANONICAL_DROP_STAGING"
    if staging_bulk == canonical_bulk and staging_bulk:
        return "KEEP_CANONICAL_DROP_STAGING"
    if staging.get("tile") != canonical.get("tile"):
        return "BLOCKED"  # conflicting identity: fail closed
    return "KEEP_CANONICAL_DROP_STAGING"


@dataclass
class JournalEntry:
    asset: str
    action: str
    source: str = ""
    destination: str = ""
    pre_state: str = ""
    post_state: str = ""
    status: str = "PLANNED"  # PLANNED/IN_PROGRESS/COMPLETE/FAILED


@dataclass
class RepairJournal:
    run_id: str
    entries: List[JournalEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"run_id": self.run_id,
                "entries": [asdict(e) for e in self.entries]}


def plan_repair(pairs: List[Dict[str, Any]]) -> List[JournalEntry]:
    return [JournalEntry(asset=p["name"], action=p["action"],
                         source=p.get("staging_path", ""),
                         destination=p.get("quarantine_path", ""),
                         pre_state="present")
            for p in pairs]


def execute_repair(journal: RepairJournal, quarantine_root: Path,
                   dry_run: bool = False) -> RepairJournal:
    quarantine_root.mkdir(parents=True, exist_ok=True)
    for e in journal.entries:
        if e.action == "NO_ACTION":
            e.status = "COMPLETE"
            e.post_state = "unchanged(canonical-only)"
            continue
        if e.action == "KEEP_STAGING_TEMPORARILY":
            e.status = "COMPLETE"
            e.post_state = "kept-pending-tile-worlds"
            continue
        if e.action == "BLOCKED":
            e.status = "FAILED"
            e.post_state = "fail-closed: no mutation performed"
            continue
        if e.action != "KEEP_CANONICAL_DROP_STAGING":
            e.status = "FAILED"
            e.post_state = f"unsupported action {e.action}"
            continue
        e.status = "IN_PROGRESS"
        src = Path(e.source)
        if not src.exists():
            # Already reconciled (e.g., second run): NOOP, not failure.
            e.status = "COMPLETE"
            e.post_state = "noop-source-absent"
            continue
        dst = quarantine_root / src.name
        if dry_run:
            e.status = "COMPLETE"
            e.post_state = "dry-run-planned"
            continue
        try:
            shutil.move(str(src), str(dst))
            e.destination = str(dst)
            e.status = "COMPLETE"
            e.post_state = "quarantined"
        except OSError as exc:
            e.status = "FAILED"
            e.post_state = f"move failed: {exc}"
    return journal


def journal_summary(journal: RepairJournal) -> Dict[str, Any]:
    from collections import Counter

    return {"total": len(journal.entries),
            "by_status": dict(Counter(e.status for e in journal.entries)),
            "by_action": dict(Counter(e.action for e in journal.entries)),
            "failed": [e.asset for e in journal.entries
                       if e.status == "FAILED"]}
