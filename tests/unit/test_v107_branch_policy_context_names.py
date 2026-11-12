"""V107: branch-policy required contexts must match the actual CI job display names."""
from __future__ import annotations

from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/tests.yml"
POLICY = REPO / "reports/v103/o5/BRANCH_POLICY_CHECKLIST.md"


def test_branch_policy_uses_exact_workflow_job_display_names():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")

    # Only job-level display names (four spaces) count, not job IDs.
    emitted = set(re.findall(r"(?m)^    name: (.+)$", workflow))
    assert len(emitted) == 8

    section = policy.split("## 2. Required check names (exact)", 1)[1].split(
        "## 3. Owner-executable change plan", 1
    )[0]
    documented = set(
        re.findall(
            r"(?m)^\| `([^`]+)` \| `[^`]+` \| `tests\.yml` \|$",
            section,
        )
    )
    assert documented == emitted

    # The executable plan, not only its preceding explanatory table, must
    # require every emitted job by its EXACT display name.
    ruleset = policy.split("**Preferred — a ruleset**", 1)[1].split(
        "**Alternative — classic branch protection**", 1
    )[0]
    match = re.search(
        r"(?m)^        required contexts:\s*\n((?:\s+- [^\n]+\n)+)",
        ruleset,
    )
    assert match is not None
    configured = set(re.findall(r"(?m)^\s+- (.+)$", match.group(1)))
    assert configured == emitted
