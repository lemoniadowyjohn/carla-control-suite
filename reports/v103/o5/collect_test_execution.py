"""V104 — read-only GitHub CI/branch-policy probe.

Corrections applied (V104 review of PR #41):

  4551961642 High  the slash-containing branch is now URL-encoded as a single
                    path segment, so the branch and protection lookups do
                    not 404 on a "/" in the name
  4551961655 Med   the legacy commit-status endpoint is reported as legacy;
                    the GitHub Actions check-runs endpoint is the
                    authoritative one and is read separately
  4551961669 Med   a failed probe is reported as a failure and exits
                    non-zero instead of printing an empty measurement
  4551961692 Med   the branch ref is re-read after the status lookup and a
                    drift is reported, so the evidence is never labelled
                    with a stale SHA

Uses only the public GitHub REST API.  No credential is read, stored or
logged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

REPO = "lemoniadowyjohn/carla-control-suite"
BASE = f"https://api.github.com/repos/{REPO}"
BRANCH = "integration/production-large-map-20260918"


def api(path: str):
    """GET a GitHub API path.

    Returns the parsed body, or a sentinel dict on failure.  A failure is
    never silently turned into an empty measurement.
    """
    url = path if path.startswith("http") else f"{BASE}{path}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json"}
    )
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
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def probe_failed(result) -> bool:
    """True when a probe failed and its result is NOT evidence."""
    return isinstance(result, dict) and (
        "__error__" in result or "__http_error__" in result
    )


def probe_detail(result) -> str:
    if not isinstance(result, dict):
        return "unexpected response shape"
    return str(
        result.get("__error__")
        or f"HTTP {result.get('__http_error__')}: {result.get('__body__','')[:120]}"
    )


def main() -> int:
    # V104 review 4551961642: the branch name contains "/" and must be
    # encoded as ONE path segment.
    branch_param = urllib.parse.quote(BRANCH, safe="")
    failures = 0

    print("=" * 72)
    print("PR STATES + HEAD SHAs")
    print("=" * 72)
    for number in (28, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43):
        pr = api(f"/pulls/{number}")
        if probe_failed(pr):
            print(f"PR#{number}: PROBE FAILED - {probe_detail(pr)}")
            failures += 1
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
    branch = api(f"/branches/{branch_param}")
    if probe_failed(branch):
        print("BRANCH PROBE FAILED - %s" % probe_detail(branch))
        return 2
    head_sha = branch.get("commit", {}).get("sha", "")
    print("production head sha =", head_sha[:12] or "(unavailable)")

    if head_sha:
        # V104 review 4551961655: the legacy commit-status endpoint reports
        # LEGACY statuses, not GitHub Actions check runs.
        combined = api(f"/commits/{head_sha}/status")
        if probe_failed(combined):
            print("legacy combined state  = PROBE FAILED - %s" % probe_detail(combined))
            failures += 1
        else:
            print("legacy combined state  =", combined.get("state"))
            print("legacy total statuses =", combined.get("total_count"))
            for status in (combined.get("statuses") or [])[:20]:
                print(
                    "   %-10s %-24s %s"
                    % (
                        status.get("state"),
                        status.get("context", "")[:24],
                        status.get("description", "")[:40],
                    )
                )

        checks = api(f"/commits/{head_sha}/check-runs")
        if probe_failed(checks) or not isinstance(checks.get("check_runs"), list):
            print("check runs           = PROBE FAILED (not evidence)")
            failures += 1
        else:
            check_runs = checks["check_runs"]
            print("check runs           =", len(check_runs))
            for run in check_runs[:20]:
                print(
                    "   %-10s %-34s %s"
                    % (
                        run.get("conclusion") or run.get("status"),
                        (run.get("name") or "")[:34],
                        (run.get("html_url") or "")[:40],
                    )
                )

        # V104 review 4551961692: re-read the ref so the evidence is never
        # labelled with a stale SHA.
        branch_again = api(f"/branches/{branch_param}")
        if probe_failed(branch_again):
            print("branch re-read       = PROBE FAILED - %s" % probe_detail(branch_again))
            failures += 1
        else:
            head_after = branch_again.get("commit", {}).get("sha", "")
            if head_after and head_after != head_sha:
                print(
                    "WARNING: the production branch advanced during the probe "
                    f"({head_sha[:9]} -> {head_after[:9]}); the evidence above "
                    "belongs to the earlier SHA"
                )
            else:
                print("branch head stable   =", head_after[:9])

    print()
    print("=" * 72)
    print("BRANCH PROTECTION / RULESETS")
    print("=" * 72)
    protection = api(f"/branches/{branch_param}/protection")
    if probe_failed(protection):
        print("branch protection: PROBE FAILED - %s" % probe_detail(protection))
        failures += 1
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
    if probe_failed(rulesets):
        print("rulesets: PROBE FAILED - %s" % probe_detail(rulesets))
        failures += 1
    elif isinstance(rulesets, list):
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
    runs = api("/actions/runs?branch=" + branch_param + "&per_page=20")
    if probe_failed(runs) or not isinstance(runs.get("workflow_runs"), list):
        print("workflow runs: PROBE FAILED (not evidence)")
        failures += 1
    else:
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

    print()
    if failures:
        print(f"PROBE COMPLETED WITH {failures} FAILED PROBE(S) - the missing")
        print("sections above are NOT evidence.")
        return 2
    print("PROBE COMPLETED - every section above is a measured value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
