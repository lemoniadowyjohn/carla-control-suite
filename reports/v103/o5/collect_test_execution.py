"""V103-O5 — read-only GitHub CI/branch-policy probe (no credentials).

Uses only the public GitHub REST API.  Prints the evidence used by
``V103_O5_CI_AUDIT.md``: PR states and head SHAs, the combined commit status
on the production branch head, the branch-protection state, the ruleset
list, and the recent workflow-run history.

    py reports/v103/o5/collect_test_execution.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

REPO = "lemoniadowyjohn/carla-control-suite"
BASE = f"https://api.github.com/repos/{REPO}"
BRANCH = "integration/production-large-map-20260918"


def api(path: str):
    url = path if path.startswith("http") else f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        return {
            "__http_error__": exc.code,
            "__body__": exc.read().decode("utf-8", "replace")[:300],
        }
    except Exception as exc:  # noqa: BLE001
        return {"__error__": str(exc)}


def main() -> None:
    print("=" * 72)
    print("PR STATES + HEAD SHAs")
    print("=" * 72)
    for number in (31, 32, 34, 35, 36, 37):
        pr = api(f"/pulls/{number}")
        if "__http_error__" in pr:
            print(f"PR#{number}: HTTP {pr['__http_error__']} {pr.get('__body__', '')[:120]}")
            continue
        print(
            "PR#%-3d %-6s draft=%-5s merged=%-5s head=%s base=%s"
            % (
                number,
                pr.get("state"),
                pr.get("draft"),
                pr.get("merged"),
                pr.get("head", {}).get("sha", "")[:9],
                pr.get("base", {}).get("ref", "")[:44],
            )
        )
        print("        title=%s" % pr.get("title", "")[:90])

    print()
    print("=" * 72)
    print("COMBINED STATUS ON THE PRODUCTION BRANCH HEAD")
    print("=" * 72)
    branch = api(f"/branches/{BRANCH}")
    head_sha = branch.get("commit", {}).get("sha", "")
    print("production head sha =", head_sha[:12] or "(unavailable)")
    if head_sha:
        combined = api(f"/commits/{head_sha}/status")
        print("combined state  =", combined.get("state"))
        print("total statuses =", combined.get("total_count"))
        for status in (combined.get("statuses") or [])[:20]:
            print(
                "   %-10s %-24s %s"
                % (
                    status.get("state"),
                    status.get("context", "")[:24],
                    status.get("description", "")[:40],
                )
            )

    print()
    print("=" * 72)
    print("BRANCH PROTECTION / RULESETS")
    print("=" * 72)
    protection = api(f"/branches/{BRANCH}/protection")
    if "__http_error__" in protection:
        print("branch protection:", protection)
    else:
        print("protection keys:", sorted(protection.keys()) if protection else "(empty)")
        print(
            "required_status_checks:",
            json.dumps(protection.get("required_status_checks"))[:300],
        )
        print(
            "required_pull_request_reviews:",
            json.dumps(protection.get("required_pull_request_reviews"))[:200],
        )
        print("enforce_admins:", protection.get("enforce_admins"))

    rulesets = api("/rulesets")
    if isinstance(rulesets, list):
        print("rulesets: %d" % len(rulesets))
        for ruleset in rulesets:
            print(
                "   id=%s name=%s target=%s enforcement=%s"
                % (
                    ruleset.get("id"),
                    ruleset.get("name"),
                    ruleset.get("target"),
                    ruleset.get("enforcement"),
                )
            )
        if not rulesets:
            print("   (EMPTY -> no repository rulesets)")
    else:
        print("rulesets:", json.dumps(rulesets)[:300])

    print()
    print("=" * 72)
    print("RECENT WORKFLOW RUNS")
    print("=" * 72)
    runs = api("/actions/runs?branch=" + BRANCH.replace("/", "%2F") + "&per_page=20")
    if isinstance(runs, dict) and "workflow_runs" in runs:
        for run in runs["workflow_runs"][:20]:
            print(
                "  %-11s %-10s %-9s sha=%s  %s"
                % (
                    run.get("status"),
                    run.get("conclusion"),
                    run.get("event"),
                    (run.get("head_sha") or "")[:9],
                    (run.get("name") or "")[:30],
                )
            )
    else:
        print(json.dumps(runs)[:400])


if __name__ == "__main__":
    main()
