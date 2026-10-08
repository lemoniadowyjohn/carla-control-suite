"""Mechanically regenerate MASTER_GAP_REGISTER.md from MASTER_GAP_REGISTER.json.

The .json is authoritative. This script reads the .json's actual current
content and emits the .md in the existing format, so the .md stays
mechanically re-derivable (no hand-copying).

Usage:
    python tools/sync_gap_register_md.py
    python tools/sync_gap_register_md.py --check   # verify md matches json without writing

Rules (documented so re-derivation is deterministic):
- Table columns: ID | Severity | Subsystem | Status | Fixing commit / owner
- Status cell: full JSON `status` collapsed to one line (newlines -> space,
  `|` -> `/`), truncated to STATUS_MAX (120) chars with `...` if longer.
  Wrapped in **...** iff the normalized status starts with `fixed` or
  `closed` (case-insensitive, including `checker fixed...`).
- Fix cell: `fixing_commit` if truthy else `owner_subagent`, collapsed to one
  line, `|` -> `/`, truncated to FIX_MAX (200) chars with `...` if longer.
- Totals line: derived from the .json `counts` block (fixed/open/closed/
  closed_non_reproducible/deferred/blocked_external/in_progress/total) plus a
  recomputed cross-check that scans every issue `status` field with
  classify_status() and asserts it matches the counts block.
- Active section: one bullet per issue whose classified bucket is open,
  blocked_external, deferred, or in_progress, with severity, subsystem, and
  the full (collapsed, untruncated) status plus fix/owner and evidence artifact.
- Historical tail: everything in the existing .md from the
  `## V5 incremental hardening merge` marker onward is preserved verbatim
  (history, not register state).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = (
    REPO_ROOT
    / "reports"
    / "production_readiness"
    / "20260918T000000Z_PRODUCTION_CLOSURE"
    / "MASTER_GAP_REGISTER.json"
)
DEFAULT_MD = (
    REPO_ROOT
    / "reports"
    / "production_readiness"
    / "20260918T000000Z_PRODUCTION_CLOSURE"
    / "MASTER_GAP_REGISTER.md"
)
TAIL_MARKER = "## V5 incremental hardening merge"
STATUS_MAX = 120
FIX_MAX = 200


def collapse(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    return text.replace("|", "/")


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def classify_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s.startswith("fixed") or s.startswith("checker fixed"):
        return "fixed"
    if s.startswith("closed"):
        if "non-reproducible" in s or "non_reproducible" in s:
            return "closed_non_reproducible"
        return "closed"
    if s.startswith("deferred"):
        return "deferred"
    if s.startswith("blocked_external"):
        return "blocked_external"
    if s.startswith("in_progress"):
        return "in_progress"
    if s.startswith("open"):
        return "open"
    return "unclassified"


def status_cell(status: str) -> str:
    full = collapse(status)
    short = truncate(full, STATUS_MAX)
    if classify_status(status) in ("fixed", "closed", "closed_non_reproducible"):
        return f"**{short}**"
    return short


def fix_cell(issue: dict) -> str:
    raw = issue.get("fixing_commit") or issue.get("owner_subagent") or ""
    return truncate(collapse(raw), FIX_MAX)


def recomputed_counts(issues: list[dict]) -> dict[str, int]:
    buckets: dict[str, int] = {
        "fixed": 0,
        "open": 0,
        "closed": 0,
        "closed_non_reproducible": 0,
        "deferred": 0,
        "blocked_external": 0,
        "in_progress": 0,
        "unclassified": 0,
    }
    for issue in issues:
        buckets[classify_status(issue.get("status", ""))] += 1
    return buckets


def render_totals_line(counts: dict, issues: list[dict], last_updated: str) -> str:
    total = int(counts.get("total", len(issues)))
    fixed = int(counts.get("fixed", 0))
    closed = int(counts.get("closed", 0))
    cnr = int(counts.get("closed_non_reproducible", 0))
    deferred = int(counts.get("deferred", 0))
    open_n = int(counts.get("open", 0))
    blocked = int(counts.get("blocked_external", 0))
    inprog = int(counts.get("in_progress", 0))
    date = (last_updated or "")[:10]
    parts = [
        f"{total} tracked",
        f"{fixed} fixed",
        f"{closed} closed",
        f"{cnr} closed (non-reproducible)",
        f"{deferred} deferred",
        f"{open_n} open",
        f"{blocked} blocked_external",
    ]
    if inprog:
        parts.append(f"{inprog} in_progress")
    summation = f"{fixed}+{closed}+{cnr}+{deferred}+{open_n}+{blocked}"
    if inprog:
        summation += f"+{inprog}"
    summation += f" = {total}"
    return (
        f"Totals: {', '.join(parts)}. Recomputed {date} by direct scan of all "
        f"{total} `status` fields; {summation}, 0 unclassified."
    )


def render_active_section(issues: list[dict]) -> list[str]:
    active = [
        i for i in issues if classify_status(i.get("status", "")) in ("open", "blocked_external", "deferred", "in_progress")
    ]
    lines = [
        "",
        f"## Active open / blocked items ({len(active)} items, from live .json scan)",
        "",
    ]
    for issue in active:
        gid = issue.get("id", "?")
        sev = issue.get("severity", "?")
        sub = collapse(issue.get("subsystem", ""))
        st = collapse(issue.get("status", ""))
        fix = collapse(issue.get("fixing_commit") or issue.get("owner_subagent") or "")
        ev = collapse(issue.get("evidence_artifact") or "")
        bucket = classify_status(issue.get("status", ""))
        lines.append(f"- **{gid} ({sev}, {bucket})**: {sub}")
        lines.append(f"  - Status: {st}")
        if fix:
            lines.append(f"  - Fix/owner: {fix}")
        if ev:
            lines.append(f"  - Evidence: {ev}")
    lines.append("")
    return lines


def build_markdown(data: dict, existing_md: str) -> str:
    issues = data["issues"]
    last_updated = data.get("last_updated_utc", "")
    counts = data.get("counts", {})

    # Cross-check: independent scan must match the counts block.
    recomp = recomputed_counts(issues)
    for key in ("fixed", "open", "closed", "closed_non_reproducible", "deferred", "blocked_external", "in_progress"):
        expected = int(counts.get(key, 0))
        got = recomp.get(key, 0)
        if expected != got:
            raise SystemExit(
                f"counts block mismatch for {key}: block says {expected}, "
                f"scan of status fields says {got}. Refusing to emit a misleading .md."
            )
    total = int(counts.get("total", len(issues)))
    if total != len(issues):
        raise SystemExit(f"counts.total={total} != len(issues)={len(issues)}")

    out: list[str] = []
    out.append("# Master Gap Register — Production Closure 20260918")
    out.append("")
    out.append("Machine-readable version: `MASTER_GAP_REGISTER.json`. This file is kept in sync at each update.")
    out.append("")
    out.append(f"Last updated: `{last_updated}`")
    out.append("")
    out.append("| ID | Severity | Subsystem | Status | Fixing commit / owner |")
    out.append("|---|---|---|---|---|")
    for issue in issues:
        gid = issue.get("id", "")
        sev = issue.get("severity", "")
        sub = collapse(issue.get("subsystem", ""))
        st = status_cell(issue.get("status", ""))
        fx = fix_cell(issue)
        out.append(f"| {gid} | {sev} | {sub} | {st} | {fx} |")
    out.append("")
    out.append(render_totals_line(counts, issues, last_updated))
    out.extend(render_active_section(issues))

    # Preserve the historical tail verbatim (from the marker line onward).
    marker_idx = existing_md.find(TAIL_MARKER)
    if marker_idx != -1:
        # Back up to the start of the marker's line so the full heading survives.
        line_start = existing_md.rfind("\n", 0, marker_idx) + 1
        tail = existing_md[line_start:].rstrip()
        out.append(tail)
        out.append("")
    else:
        out.append("See `MASTER_GAP_REGISTER.json` for full detail per issue (proof, affected files, consequence,")
        out.append("fixing commit, regression test, evidence artifact, residual risk). Updated after every subagent")
        out.append("handback per this program's integration discipline (Section 33).")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate MASTER_GAP_REGISTER.md from its .json.")
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_MD))
    parser.add_argument("--check", action="store_true", help="verify only, do not write")
    args = parser.parse_args()

    json_path = Path(args.json)
    md_path = Path(args.md)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    existing_md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    rendered = build_markdown(data, existing_md)

    if args.check:
        if existing_md == rendered:
            print("IN SYNC: .md matches .json")
            return 0
        print("OUT OF SYNC: .md does not match .json output")
        return 1
    md_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {md_path} ({len(data['issues'])} issues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
