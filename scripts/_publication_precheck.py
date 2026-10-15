import json
import subprocess
from datetime import datetime, timezone


def g(*a):
    # git.exe is resolvable by the PowerShell tool wrapper but not by a bare
    # CreateProcess lookup, so shell resolution is required here.
    cmd = " ".join('"%s"' % p if " " in p else p for p in a)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return (r.stdout or "").strip()


T = "origin/integration/production-large-map-20260918"
C = "462f816d5ce29c62ea7ffa52f7f01473cf6cded4"

pre = {
    "schema": "PROCESS_CONTROL_PUBLICATION_PRECHECK/v1",
    "schema_version": 1,
    "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "current_branch": g("git", "rev-parse", "--abbrev-ref", "HEAD"),
    "local_head": g("git", "rev-parse", "HEAD"),
    "verified_commit": C,
    "commit_files": g("show", "--name-only", "--format=", C).split(),
    "commit_is_process_control_only": True,
    "staged_paths": [],
    "unstaged_tracked_paths": g("diff", "--name-only").split(),
    "untracked_path_count": len(
        g("ls-files", "--others", "--exclude-standard").splitlines()),
    "pre_existing_modified_files_untouched": True,
    "authoritative_target": "integration/production-large-map-20260918",
    "authoritative_target_sha": g("git", "rev-parse", T),
    "remote_default_head": "fa1116ef1e3f8286b6d75ef043e2fc77a44fae71",
    "remote_default_head_is_not_authority": True,
    "merge_base": g("git", "merge-base", C, T),
    "target_is_ancestor_of_head": True,
    "source_only_commits": int(g("git", "rev-list", "--count", T + ".." + C)),
    "target_only_commits": int(g("git", "rev-list", "--count", C + ".." + T)),
    "full_pr_changed_paths": 219,
    "full_pr_insertions": 43189,
    "full_pr_deletions": 635,
    "intended_commit_files": 8,
    "intended_commit_insertions": 2262,
    "PR_LINEAGE": "NEEDS_REBASE_OR_CHERRY_PICK",
    "PUBLICATION_SCAN": "PASS_WITH_FINDINGS",
    "publication_findings": [
        "Absolute machine path REPO = r'C:\\Users\\admin\\PycharmProjects\\..."
        "carla_-main' is hardcoded in all 3 new harness scripts. No other "
        "committed script in this repository uses that pattern, so it is newly "
        "introduced by this commit and is non-portable for CI "
        "(.github/workflows/tests.yml exists and runs on other machines).",
    ],
    "scan_clean": {
        "diff_check": "PASS",
        "credentials": "NONE_FOUND",
        "unreal_content": "NONE (.uasset/.umap/.fbx/.xodr)",
        "binary_assets": "NONE",
        "unrelated_files_in_commit": "NONE",
    },
    "direct_push_to_integration": False,
    "auto_merge": False,
    "remote_review_branch": "review/carla-production-convergence-20261002",
    "remote_review_sha": g(
        "git", "ls-remote", "origin",
        "refs/heads/review/carla-production-convergence-20261002").split()[0],
    "push_type": "FAST_FORWARD (3a8491ec..462f816d)",
    "pr_created": False,
    "pr_blocked_reason": (
        "A PR from this branch would contain 31 commits / 219 files / +43189 "
        "lines of unrelated historical work, because the authoritative target "
        "is already an ancestor of HEAD. The required PR description covers "
        "only the 8-file process-supervision change and would misrepresent "
        "the diff."),
}

with open("reports/PROCESS_CONTROL_PUBLICATION_PRECHECK.json", "w",
          encoding="utf-8") as fh:
    json.dump(pre, fh, indent=2)

print("PR_LINEAGE", pre["PR_LINEAGE"])
print("REMOTE_REVIEW_SHA", pre["remote_review_sha"])
print("PR_CREATED", pre["pr_created"])
