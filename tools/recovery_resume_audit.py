"""Read-only failure recovery/resume audit for long-running package stages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def audit(repo: Path) -> dict[str, Any]:
    files = {
        "tile_generation": repo / "scripts/cook_full_grid_tiles.py",
        "fbx_conversion": repo / "ultimate_pipeline/tiling/tile_fbx_generator.py",
        "import_staging": repo / "ultimate_pipeline/tiling/large_map_package.py",
        "unreal_import": repo / "tools/stage_large_map_import_package.py",
        "cook_package": repo / "reports/production_readiness/20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN/DESIGN.md",
    }
    rows = []
    for stage, path in files.items():
        exists = path.is_file()
        text = path.read_text(encoding="utf-8", errors="ignore") if exists else ""
        rows.append({"stage": stage, "path": str(path), "source_present": exists, "partial_naming": any(token in text for token in (".tmp", ".partial", "part-")), "atomic_rename": "replace" in text or "rename" in text or "os.replace" in text, "checkpoint_or_resume": any(token in text.lower() for token in ("checkpoint", "resume", "rebuild")), "hash_verification": "sha256" in text, "safe_interruption_tested": False})
    failures = [row["stage"] for row in rows if not row["source_present"]]
    incomplete = [row["stage"] for row in rows if row["source_present"] and not row["hash_verification"]]

    # NEW-247: a stage whose recovery/resume capability was never actually
    # exercised cannot be reported as verified. Previously PASS was derived only
    # from "source file exists AND text mentions sha256", so an audit that
    # admitted in its own limitations that no process was ever interrupted could
    # still say PASS while reporting safe_interruption_tested=false everywhere.
    untested_interruption = [
        row["stage"] for row in rows if not row["safe_interruption_tested"]
    ]
    no_resume_capability = [
        row["stage"]
        for row in rows
        if row["source_present"] and not row["checkpoint_or_resume"]
    ]

    if failures:
        status = "FAIL"
    elif untested_interruption or no_resume_capability or incomplete:
        # INCOMPLETE, not PASS: nothing here is a verified recovery result.
        status = "INCOMPLETE"
    else:
        status = "PASS"

    return {
        "schema": "failure_recovery_resume_audit/v2",
        "status": status,
        "stages": rows,
        "failures": failures,
        "incomplete": incomplete,
        "safe_interruption_untested_stages": untested_interruption,
        "stages_without_resume_capability": no_resume_capability,
        "pass_criteria": (
            "PASS requires every stage to have been actually interrupted and recovered "
            "from, and to expose a checkpoint/resume capability. A source-text audit "
            "alone can never yield PASS."
        ),
        "limitations": [
            "No Unreal process interrupted; source/read-only audit plus safe synthetic tests only.",
            "No production artifact was manipulated.",
            "Recovery/resume behaviour was NOT executed for any stage, so no stage is "
            "certified as interrupt-safe by this audit.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(audit(Path(__file__).resolve().parents[1]), indent=2, sort_keys=True))
