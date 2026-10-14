"""Mutation-domain model for governed CARLA operations.

Until finer-grained concurrency is independently proven:
GLOBAL_MUTATING_EXCLUSIVITY = True -- any live mutating lease denies every
other mutating operation, regardless of domain. The domain map below exists
so the DENY receipts name the exact conflict pair.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

DOMAIN_UNREAL_CONTENT = "DOMAIN_UNREAL_CONTENT"
DOMAIN_IMPORT_SETTINGS = "DOMAIN_IMPORT_SETTINGS"
DOMAIN_DDC = "DOMAIN_DDC"
DOMAIN_SAVED_INTERMEDIATE = "DOMAIN_SAVED_INTERMEDIATE"
DOMAIN_COOK_OUTPUT = "DOMAIN_COOK_OUTPUT"
DOMAIN_UE_BUILD_OUTPUT = "DOMAIN_UE_BUILD_OUTPUT"
DOMAIN_PLUGIN_BINARIES = "DOMAIN_PLUGIN_BINARIES"
DOMAIN_SOURCE_WORKTREE = "DOMAIN_SOURCE_WORKTREE"

GLOBAL_MUTATING_EXCLUSIVITY = True

# operation -> (write domains, description)
OPERATION_DOMAINS: Dict[str, Tuple[List[str], str]] = {
    "IMPORT": (
        [DOMAIN_UNREAL_CONTENT, DOMAIN_IMPORT_SETTINGS, DOMAIN_DDC,
         DOMAIN_SAVED_INTERMEDIATE],
        "Import.py commandlets into Content + importsetting.json + DDC",
    ),
    "COOK": (
        [DOMAIN_UNREAL_CONTENT, DOMAIN_DDC, DOMAIN_SAVED_INTERMEDIATE,
         DOMAIN_COOK_OUTPUT],
        "UE4Editor -run=cook reading Content/DDC, writing cook output",
    ),
    "BUILD_LINK": (
        [DOMAIN_UE_BUILD_OUTPUT, DOMAIN_PLUGIN_BINARIES, DOMAIN_DDC],
        "UBT/Build.bat producing engine/project binaries",
    ),
    "RUNTIME_SERVE": (
        [DOMAIN_SAVED_INTERMEDIATE],
        "CARLA server writing Saved/Logs + DDC reads (lease required only when conflicting)",
    ),
    "RECAST_NAV": (
        [DOMAIN_UNREAL_CONTENT, DOMAIN_SAVED_INTERMEDIATE],
        "Recast navmesh generation into Content",
    ),
}

# Explicitly denied pairs (both directions implied).
DENIED_PAIRS = {
    ("IMPORT", "IMPORT"),
    ("IMPORT", "COOK"),
    ("IMPORT", "BUILD_LINK"),
    ("COOK", "COOK"),
    ("COOK", "BUILD_LINK"),
}


def check_conflict(new_operation: str, live_operation: str) -> Dict[str, object]:
    """Decide whether a new operation conflicts with a live lease."""
    if new_operation == live_operation:
        return {"conflict": True,
                "reason": f"DUPLICATE_OPERATION_ALREADY_RUNNING: {live_operation}"}
    if (new_operation, live_operation) in DENIED_PAIRS or (
            live_operation, new_operation) in DENIED_PAIRS:
        return {"conflict": True,
                "reason": f"{new_operation}+{live_operation} explicitly denied"}
    if GLOBAL_MUTATING_EXCLUSIVITY:
        return {"conflict": True,
                "reason": "GLOBAL_MUTATING_EXCLUSIVITY: one mutator at a time"}
    new_domains = set(OPERATION_DOMAINS.get(new_operation, ([], ""))[0])
    live_domains = set(OPERATION_DOMAINS.get(live_operation, ([], ""))[0])
    overlap = sorted(new_domains & live_domains)
    if overlap:
        return {"conflict": True,
                "reason": f"domain overlap: {overlap}"}
    return {"conflict": False, "reason": "no shared write domain"}


def domains_for(operation: str) -> List[str]:
    return list(OPERATION_DOMAINS.get(operation, ([], ""))[0])
