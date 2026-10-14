"""Generate B6 failure recovery matrix report."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.quality._b6_failure_injection import run_campaign

REPORT_DIR = REPO_ROOT / "reports" / "post_audit_hardening"
REPORT_PATH = REPORT_DIR / "B6_FAILURE_RECOVERY_MATRIX.md"


def write_report() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = run_campaign()
    lines: list[str] = []
    lines.append("# B6 Failure Recovery Matrix")
    lines.append("")
    lines.append("Temporary-fixture fault injection across pipeline stages. Each stage")
    lines.append("receives an injected fault and the observed recovery/failure-closed")
    lines.append("behavior is recorded against the expected outcome.")
    lines.append("")
    lines.append("| Stage | Injected Fault | Observed | Expected | PASS/FAIL |")
    lines.append("|-------|----------------|----------|----------|-----------|")
    for r in rows:
        lines.append(f"| {r['stage']} | {r['injected fault']} | {r['observed']} | {r['expected']} | {r['PASS/FAIL']} |")
    lines.append("")
    passed = sum(1 for r in rows if r["PASS/FAIL"] == "PASS")
    lines.append(f"**Total stages: {len(rows)}**")
    lines.append("")
    lines.append(f"**Passed: {passed}, Failed: {len(rows)-passed}**")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    for r in rows:
        print(f"{r['stage']}: {r['PASS/FAIL']}")


if __name__ == "__main__":
    write_report()