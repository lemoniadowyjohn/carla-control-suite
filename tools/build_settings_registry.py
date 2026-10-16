"""Generate the versioned settings metadata registry from SETTINGS_MASTER.csv.

Run once; output is committed as ``settings_metadata.json`` so the GUI has a
stable, versioned registry that does not require the documentation pack at
runtime.

Every entry is anchored to the catalog's declared evidence AND checked against
the CURRENT source tree. Entries whose declaring code no longer exists at HEAD
are recorded as ``ABSENT_AT_HEAD`` - never silently dropped, never invented.
"""

from __future__ import annotations

import ast
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

DOCS = Path(
    r"F:\pulpit\CARLA_GUI_OpenCode_Tailored_Prompt_Pack_2026-10-15"
    r"\CARLA_GUI_OpenCode_Tailored_Prompt_Pack\extracted"
    r"\CARLA-GUI-DOCUMENTATION-FOUNDATION-20261015\CARLA_GUI_DOC_FOUNDATION"
)
WT = Path(r"F:\wt\carla-gui-integration-20261015")
OUT = WT / "ultimate_pipeline" / "gui" / "config" / "settings_metadata.json"
CSV_PATH = DOCS / "03_CONFIGURATION" / "SETTINGS_MASTER.csv"

REGISTRY_SCHEMA = "carla-gui-settings-registry/v1"
BASE_SHA = "c69b60d2fe4ac018136ea0fa26e435a09c15dd73"

#: Lifecycle classification. Derived from the catalog's apply_mode column; a
#: setting whose apply_mode cannot be parsed keeps the catalog's own wording
#: rather than being guessed into a lifecycle.
LIFECYCLE_BY_APPLY_MODE = (
    (re.compile(r"restart", re.I), "restart"),
    (re.compile(r"import-time", re.I), "restart"),
    (re.compile(r"stage", re.I), "stage"),
    (re.compile(r"apply", re.I), "apply"),
)

#: Anything that starts a process, touches a port, mutates a world, spawns
#: actors, cooks a map or writes outside the worktree needs typed confirmation.
IRREVERSIBLE_HINTS = (
    "spawn", "cook", "kill", "rmtree", "delete", "reset", "world", "tick",
    "synchronous", "traffic", "launch", "train", "rpc", "port", "host",
)

_SECRET_HINTS = ("password", "secret", "token", "api_key", "apikey", "credential", "auth")


def classify_lifecycle(apply_mode: str) -> str:
    for pattern, lifecycle in LIFECYCLE_BY_APPLY_MODE:
        if pattern.search(apply_mode or ""):
            return lifecycle
    return "UNKNOWN"


def classify_safety(setting_id: str, default_expr: str) -> str:
    blob = f"{setting_id} {default_expr}".lower()
    if any(hint in blob for hint in _SECRET_HINTS):
        return "SECRET"
    if any(hint in blob for hint in IRREVERSIBLE_HINTS):
        return "IRREVERSIBLE"
    return "ORDINARY"


def head_blob_lines(commit: str) -> dict[str, list[str]]:
    """All .py sources at HEAD, so presence checks read the commit not the disk."""
    proc = subprocess.run(
        ["git", "-C", str(WT), "ls-tree", "-r", "--name-only", commit],
        capture_output=True, text=True, check=True,
    )
    wanted = [p for p in proc.stdout.splitlines() if p.endswith(".py")]
    files: dict[str, list[str]] = {}
    for path in wanted:
        blob = subprocess.run(
            ["git", "-C", str(WT), "show", f"{commit}:{path}"],
            capture_output=True, text=True,
        )
        if blob.returncode == 0:
            files[path] = blob.stdout.splitlines()
    return files


def live_bindings() -> dict[str, str]:
    """Where each identifier actually lives in the live settings module.

    The catalog claims 298 ``Settings`` fields; the live dataclass has fewer.
    Rather than trusting either number, each entry is bound to reality and the
    remainder is reported as ``UNBOUND``.
    """
    sys.path.insert(0, str(WT))
    import dataclasses
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from ultimate_pipeline.config import settings as live_settings

    bound: dict[str, str] = {}
    if dataclasses.is_dataclass(live_settings.Settings):
        for field in dataclasses.fields(live_settings.Settings):
            bound[field.name] = "SETTINGS_FIELD"
    for name in dir(live_settings):
        if name.isupper():
            bound.setdefault(name, "MODULE_GLOBAL")
    return bound


def main() -> int:
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    print(f"catalog rows: {len(rows)}")

    sources = head_blob_lines(BASE_SHA)
    settings_src = sources.get("ultimate_pipeline/config/settings.py", [])
    binding = live_bindings()
    print(f"live Settings fields + globals: {len(binding)}")

    entries = []
    for index, row in enumerate(rows, start=1):
        setting_id = row.get("setting_id", "").strip()
        declaration = row.get("declaration", "").strip()
        decl_line_raw = (row.get("decl_line") or "").strip()
        try:
            decl_line = int(decl_line_raw)
        except ValueError:
            decl_line = 0

        # Presence at HEAD: the declaring file must exist and the identifier must
        # appear in it. Never assume presence from the catalog alone.
        file_present = declaration in sources
        source_lines = sources.get(declaration, [])
        present = file_present and any(
            re.search(rf"\b{re.escape(setting_id)}\b", line) for line in source_lines
        )

        # Live binding: where the value can actually be read from and written to.
        binds_to = binding.get(setting_id)
        if binds_to is None:
            binds_to = "SHIM_OR_DERIVED" if row.get("kind", "").startswith("settings.py shim") else "UNBOUND"

        default_expr = row.get("default_expr", "").strip()
        apply_mode = row.get("apply_mode", "").strip()

        entries.append({
            "index": index,
            "setting_id": setting_id,
            "kind": row.get("kind", "").strip(),
            "python_type": row.get("python_type", "").strip() or None,
            "default_expr": default_expr or None,
            "declaration": declaration or None,
            "decl_line": decl_line or None,
            "catalog_evidence": row.get("evidence", "").strip() or None,
            "duplicated": row.get("duplicated", "").strip().upper() == "TRUE",
            "declaration_sites": int(row["declarations"]) if (row.get("declarations") or "").strip().isdigit() else None,
            "apply_mode": apply_mode or None,
            "lifecycle": classify_lifecycle(apply_mode),
            "binds_to": binds_to,
            "range_or_enum": row.get("range_or_enum", "").strip() or None,
            "range_is_known": False,   # never claimed without a real validation layer
            "gui_widget": row.get("gui_widget", "").strip() or None,
            "validation": row.get("validation", "").strip() or None,
            "persistence": row.get("persistence", "").strip() or None,
            "catalog_status": row.get("status", "").strip() or None,
            "safety_class": classify_safety(setting_id, default_expr),
            "present_at_head": present,
            "presence": "PRESENT_AT_HEAD" if present else "ABSENT_AT_HEAD",
            "citation": f"{declaration}:{decl_line}@{BASE_SHA[:12]}" if file_present else None,
        })

    payload = {
        "schema": REGISTRY_SCHEMA,
        "generated_from": "03_CONFIGURATION/SETTINGS_MASTER.csv",
        "catalog_row_count": len(rows),
        "base_sha": BASE_SHA,
        "lifecycle_vocabulary": ["restart", "stage", "apply", "UNKNOWN"],
        "safety_vocabulary": ["ORDINARY", "IRREVERSIBLE", "SECRET"],
        "counts": {
            "total": len(entries),
            "distinct_setting_ids": len({e["setting_id"] for e in entries}),
            "duplicate_setting_ids": sorted({
                e["setting_id"] for e in entries if e["duplicated"]
            }),
            "present_at_head": sum(1 for e in entries if e["present_at_head"]),
            "absent_at_head": sum(1 for e in entries if not e["present_at_head"]),
            "duplicated_declaration": sum(1 for e in entries if e["duplicated"]),
            "range_known": 0,
            "by_lifecycle": {
                value: sum(1 for e in entries if e["lifecycle"] == value)
                for value in ("restart", "stage", "apply", "UNKNOWN")
            },
            "by_safety": {
                value: sum(1 for e in entries if e["safety_class"] == value)
                for value in ("ORDINARY", "IRREVERSIBLE", "SECRET")
            },
            "by_binding": {
                value: sum(1 for e in entries if e["binds_to"] == value)
                for value in sorted({e["binds_to"] for e in entries})
            },
        },
        "env_coverage": {
            "env_reads_discovered": 589,
            "env_reads_outside_settings_sampled": 479,
            "sampled_not_exhaustive": True,
            "note": "Env reads outside Settings were SAMPLED, not exhaustively read. "
                    "Complete environment coverage is NOT claimed.",
        },
        "entries": entries,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print("counts:", json.dumps(payload["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())