#!/usr/bin/env python3
"""OC-58 §23: generate reports/production_readiness/<RUN_ID>_MAP_REGISTRY_INTEGRITY/.

Deterministic, offline, no map mutation. 06_TEST_RESULTS.json is written as
PENDING here and filled by the pytest step afterward.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.carla_tools.map_registry import (  # noqa: E402
    PINNED_MAP_REGISTRY,
    audit_registry,
    build_alias_authority,
    resolve_historical_sha,
    validate_frame_metadata,
)


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(REPO_ROOT),
                             capture_output=True, text=True, timeout=30)
        return (out.stdout or "").strip()
    except Exception:
        return "UNKNOWN"


def _write(bundle: Path, name: str, payload: object) -> None:
    p = bundle / name
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
    print(f"wrote {p}")


LIMITATIONS_MD = """\
# OC-58 remaining limitations (2026-09-21)

1. **No map regeneration or recertification.** Pins, bytes and the production
   map itself are untouched. The registry answers "what exact bytes does
   `auto_map_of_record` name" — it does not re-attest map quality.
2. **Historical files trusted when pruned.** If a `supersedes_path` file is
   absent from disk, the chain link is a WARNING (metadata-only trust), not
   an error. In this checkout every superseded auto file is present and
   hash-verified, so no such warning is live.
3. **Cooked-name registry untouched.** `COOKED_MAP_ALIASES` (CARLA runtime
   names) is out of scope; only `PINNED_MAP_REGISTRY` is hardened.
4. **Receipt is call-time evidence.** `verify_pinned_map` proves content at
   call time; long-lived processes must re-verify rather than cache receipts.
5. **Cross-role override is a loaded gun.** `allow_cross_role_content: true`
   exists for tests only; any production use must be called out in review.
6. **External absolute paths remain a test affordance**
   (`allow_external_absolute_paths`); production audit requires
   repository-contained paths.
7. **Frames are identity, not geometry.** Structured frame fields pin which
   frame a map claims, not the correctness of any transform. Historical
   entries stay `LEGACY_TEXT_ONLY` rather than carrying invented values.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="20260921")
    args = ap.parse_args()

    bundle = (REPO_ROOT / "reports" / "production_readiness"
              / f"{args.run_id}_MAP_REGISTRY_INTEGRITY")
    bundle.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    _write(bundle, "00_BASELINE.json", {
        "run_id": args.run_id,
        "generated_at_utc": generated_at,
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "audited_baseline_head": "398193d4fc3cfb4164daf805438168813ae36aec",
        "registry_vs_audited_baseline": (
            "IDENTICAL at start of task (git diff 398193d4..HEAD empty for "
            "all §1 files); every §2 weakness CONFIRMED present, none "
            "partially fixed or superseded."
        ),
        "recent_log": _git("log", "-10", "--oneline").splitlines(),
    })

    audit = audit_registry()
    entries = audit["entries"]
    _write(bundle, "01_REGISTRY_SCHEMA_AUDIT.json", {
        "registry_valid": audit["registry_valid"],
        "registry_sha256": audit["registry_sha256"],
        "entry_count": audit["entry_count"],
        "schema_per_entry": {
            k: {"schema": v.get("schema"), "bytes_match": v.get("bytes_match"),
                "sha_match": v.get("sha_match"), "role": v.get("role"),
                "frame_status": v.get("frame_status")}
            for k, v in entries.items()
        },
        "errors": audit["errors"],
    })

    authority = build_alias_authority(PINNED_MAP_REGISTRY)
    _write(bundle, "02_ALIAS_AUDIT.json", {
        "alias_count": audit["alias_count"],
        "authority": authority,
        "alias_collisions": audit["alias_collisions"],
        "canonical_key_resolution": "every canonical key resolves via "
                                    "build_alias_authority even when omitted "
                                    "from its own aliases (covered by test)",
        "collision_domain_probe": ["manual", "MANUAL", "Manual"],
    })

    _write(bundle, "03_CONTENT_IDENTITY_AUDIT.json", {
        "content_groups": audit["content_collisions"],
        "policy": "same-content/same-role requires explicit equivalent_names; "
                  "cross-role same-content authority fails without an "
                  "explicit test-only override",
        "manual_equivalence": "Grid0821/Grid0828 byte-identical, declared via "
                              "equivalent_names on manual_grid0828 (not inferred)",
    })

    chains = audit["supersession_chains"]
    _write(bundle, "04_SUPERSESSION_CHAIN_AUDIT.json", {
        "chains": chains,
        "chain_found_by_audit": "missing predecessor at "
            "auto_map_of_record_c29_superseded (69b1f520 tail had no owning "
            "entry) -- corrected as verified metadata completion "
            "(auto_map_of_record_prec29_superseded) after hashing the on-disk "
            "file (69b1f520..., 144142210 bytes). No active pin changed.",
        "historical_resolution_probe": resolve_historical_sha(
            "744757f3f01da835269b5678eeb269cf5d534984213c551b9c475699aa73aec8"),
        "warnings": audit["warnings"],
    })

    _write(bundle, "05_ROLE_FRAME_AUDIT.json", {
        "active_map_roles": audit["active_map_roles"],
        "frames": validate_frame_metadata(PINNED_MAP_REGISTRY),
        "policy": "active pins carry proven structured frames; historical "
                  "entries stay LEGACY_TEXT_ONLY",
    })

    _write(bundle, "06_TEST_RESULTS.json", {
        "status": "PENDING",
        "note": "Filled by the pytest step after bundle generation.",
    })
    _write(bundle, "07_REMAINING_LIMITATIONS.md", LIMITATIONS_MD)
    print(f"registry_sha256={audit['registry_sha256']} valid={audit['registry_valid']}")
    return 0 if audit["registry_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
