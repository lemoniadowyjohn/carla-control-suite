"""Generate the V105 continuous-closure execution state from verified facts.

Every value written here was measured in this session.  Nothing is inferred
or asserted without a command behind it.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "reports" / "continuous_closure" / "v105"
OUT.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc).isoformat()
PROD_SHA = "225ed15d0da6444cc257835ca777aba281553f3c"

ARCHIVE_REFS = {
    "refs/archive/opencode-v97/v94-lifecycle-v97-20261112": "b043d57635c089e26ba883aa548637840df42f01",
    "refs/archive/opencode-v97/v94-terminal-authority-v97-20261112": "974b81c9140b605c62e9c407b91694850956646a",
    "refs/archive/opencode-v97/v95-geometry-strict-v97-20261112": "6d18b6c441d6874876bcc073034fb82e96d5cd63",
    "refs/archive/opencode-v97/v95-gui-authority-v97-20261112": "e40cda3185e4143b0f47a79265d6d25556999eed",
    "refs/archive/opencode-v97/v95-research-guarded-v97-20261112": "bb69157711ca7067d2ebe82f50e9c24833f4f1d7",
    "refs/archive/opencode-v97/v97-staging-20261112": "89b2b22b294be47fb55ed40fb78e2d86081ceb3a",
}


def write_json(name, payload):
    path = OUT / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))
    print("wrote", path)


def write_jsonl(name, rows):
    path = OUT / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(str(tmp), str(path))
    print("wrote", path)


STATE = {
    "schema": "v105_execution_state/v1",
    "updated_utc": NOW,
    "production_branch": "integration/production-large-map-20260918",
    "production_sha": PROD_SHA,
    "production_sha_source": "git ls-remote origin refs/heads/integration/production-large-map-20260918",
    "main_lineage_warning": (
        "main has a disconnected Git history from the production branch; "
        "ordinary merging between them is not valid"
    ),
    "git_common_dir": "F:/v103/_gitdirs/base.git (independent clone, own common dir)",
    "open_pull_requests_observed": {
        "28": {"head": "b8a93e7205182d0b92d1ed730f43f214497d3a19", "review_threads": 7, "draft": False},
        "30": {"head": "4d38a1fc1ebdf47bb308fa80c4fc1a0d78a9b86f", "review_threads": 19, "draft": True},
        "31": {"head": "884f019c5", "review_threads": None, "draft": True},
        "32": {"head": "6b2c348b5", "review_threads": None, "draft": True},
        "33": {"head": "cf24666edae14943969c0f32d1266f5916a6e542", "review_threads": None, "draft": True},
        "34": {"head": "aea4aea5cd4d4c00ece00ba75dc99a5a9fbcd1aa", "review_threads": 0, "draft": True},
        "35": {"head": "9c4c0f264", "review_threads": None, "draft": True},
        "36": {"head": "941cace20", "review_threads": None, "draft": True},
        "37": {"head": "a72700bb1", "review_threads": 2, "draft": True},
        "38": {"head": "a954194967a21da4c49b26a90850be22df57fa10", "review_threads": None, "draft": True},
        "39": {"head": "102a588cf3336c9b28a3260298f240bd328d513d", "review_threads": 23, "draft": False},
        "40": {"head": "ee94abca8f4c94972329306ecabbd4530886dc71", "review_threads": None, "draft": False},
        "41": {"head": "6f0b02a227872ae3dfc056f4e6ab97c586c4c6e3", "review_threads": None, "draft": False},
        "42": {"head": "6b0894b605dc36b0681a8d6b25450f7fbc6e684d", "review_threads": None, "draft": False},
        "43": {"head": "bf9ba23f4366652d8959d9a9f81583a1614ffa5b", "review_threads": None, "draft": False},
    },
    "v97_archive_refs": ARCHIVE_REFS,
    "v97_archive_ref_count": len(ARCHIVE_REFS),
    "v97_archive_refs_preserved": True,
    "staging_quarantine": {
        "path": "E:/wt-v97/staging",
        "access": "read-only, not mutated",
        "branch": "integration/v97-staging-20261112",
        "unique_history": "mixed-author, preserved via refs/archive/opencode-v97/v97-staging-20261112",
    },
    "environment": {
        "platform": "win32",
        "python": "3.14.5",
        "pytest": "9.1.1",
        "git_lfs": "3.5.1 (GitHub; windows amd64)",
        "defusedxml": "NOT INSTALLED",
        "torch": "NOT INSTALLED (23 pre-existing collection errors)",
    },
    "disk": {"C:": "6.9 GB free", "E:": "6.9 GB free", "F:": "41.2 GB free"},
    "release_state": "NO_GO",
    "release_state_reason": [
        "V96-XMLBOUND-001 still reproduced on PR #30 head 4d38a1fc (no repair exists)",
        "6 GUI release-authority defects reproduced (unbound PASS, stale, contradictory, missing receipt, digest mismatch)",
        "9 locking review findings open (PR #28 + PR #37), not independently reproduced",
        "no integrated candidate SHA exists; no independent final audit; no operator approval",
    ],
}

ISSUES = [
    {
        "id": "V96-XMLBOUND-001", "priority": "P0", "area": "XML safety",
        "owner": "Chat 1 / Codex (PR #30)", "status": "REPRODUCED",
        "affected_sha": "4d38a1fc1ebdf47bb308fa80c4fc1a0d78a9b86f",
        "affected_file": "ultimate_pipeline/quality/final_artifact_gates.py:128-145",
        "reproducer": "reports/v104/v104_xml_scope1_repro.py",
        "command": "py reports/v104/v104_xml_scope1_repro.py",
        "expected": "rejected before parsing",
        "observed": "ACCEPTED (utf-16 / >64KiB / fake-token) and PARSED (utf-16 -> live)",
        "corrected_sha": None,
        "mutation_result": "n/a - no corrected implementation exists",
        "result": "FAIL",
        "independent_review": "CONFIRMED by Codex thread 4543949125 (unresolved)",
        "evidence": "reports/v104/V104_FINAL_REVIEW_REPORT.md",
        "retry_eligible": False,
    },
    {
        "id": "V104-GUI-001", "priority": "P0", "area": "GUI release authority",
        "owner": "Codex (PR #34 / GUI lineage)", "status": "REPRODUCED",
        "affected_sha": "3d7665fc361e17156c6552c83b98982fdfbeee4e",
        "affected_file": "ultimate_pipeline/gui/jobs/governance.py:165",
        "reproducer": "tests/unit/v104_gui_authority_adversarial.py (PR #43)",
        "command": "py -m pytest tests/unit/v104_gui_authority_adversarial.py -q",
        "expected": "6 attack shapes never certify",
        "observed": "6 failed, 9 passed - unbound PASS x2, stale, contradictory, missing receipt, digest mismatch",
        "corrected_sha": None,
        "mutation_result": "n/a - no corrected implementation exists",
        "result": "FAIL",
        "independent_review": "NEWLY REPORTED; 3 of 6 already flagged in the PR #34 body",
        "evidence": "reports/v104/V104_FINAL_REVIEW_REPORT.md",
        "retry_eligible": False,
    },
    {
        "id": "V104-LOCK-001", "priority": "P1", "area": "Locking",
        "owner": "Codex (PR #37, single writer)", "status": "BLOCKED_OWNERSHIP",
        "affected_sha": "b8a93e7205182d0b92d1ed730f43f214497d3a19 / a72700bb1...",
        "affected_file": "ultimate_pipeline/governance/single_writer/worktree_lock.py",
        "reproducer": "not written (single-writer ownership; no live worktree mutated)",
        "command": "git ls-remote / GitHub API review comments enumeration",
        "expected": "9 findings resolved under one owner",
        "observed": "9 open findings enumerated: PR #28 x7 (no-op cleanup, stale generation republish, malformed lease deletion, retired lease recovery, malformed lease blocks cleanup, renewal no-op, disabled cleanup recheck), PR #37 x2",
        "corrected_sha": None,
        "mutation_result": "NOT_RUN",
        "result": "NOT_RUN",
        "independent_review": "DEFERRED to Codex; PR #28 must not be retired automatically",
        "evidence": "reports/v104/V104_FINAL_REVIEW_REPORT.md",
        "retry_eligible": False,
    },
    {
        "id": "V104-PR39-001", "priority": "P1", "area": "OSM directionality",
        "owner": "OpenCode (PR #39)", "status": "TEST_PASSED",
        "affected_sha": "7d21e4763efb06e429561286b3651f595daddf29",
        "affected_file": "ultimate_pipeline/enrichment/osm_direction.py and 5 siblings",
        "reproducer": "tests/unit/test_v104_pr39_review_fixes.py (28 tests, one per finding)",
        "command": "py -m pytest tests/unit/test_v104_pr39_review_fixes.py -q",
        "expected": "each of the 23 review findings corrected and regression-tested",
        "observed": "28/28 pass; 146 pass across the related suites; the wider offline run shows the identical 23 pre-existing torch collection errors as the unmodified base",
        "corrected_sha": "102a588cf3336c9b28a3260298f240bd328d513d",
        "mutation_result": "mutation control removes the source proof -> the repair test fails",
        "result": "PASS",
        "independent_review": "pending a second reviewer on 102a588c",
        "evidence": "reports/v104/V104_FINAL_REVIEW_REPORT.md",
        "retry_eligible": False,
    },
    {
        "id": "V103-O1-001", "priority": "P0", "area": "OSM correspondence",
        "owner": "OpenCode (PR #39)", "status": "INTEGRATED_UNVERIFIED",
        "affected_sha": "7d21e476...",
        "affected_file": "ultimate_pipeline/enrichment/osm_meta_index.py",
        "reproducer": "tests/unit/test_v103_o1_red_baseline.py",
        "command": "py -m pytest tests/unit/test_v103_o1_red_baseline.py -q",
        "expected": "RED on the unmodified base",
        "observed": "4 failed on base 225ed15d; the OSM was projected with a hardcoded bare-tmerc instead of the map's declared CRS, giving 0/3057 matched ways on the pinned pair",
        "corrected_sha": "102a588cf3336c9b28a3260298f240bd328d513d",
        "mutation_result": "n/a - real-map defect",
        "result": "PASS",
        "independent_review": "one independent review completed on the earlier head; re-review pending on 102a588c",
        "evidence": "reports/v103/o1/OSM_XODR_DIRECTION_COVERAGE_REALMAP.json",
        "retry_eligible": False,
    },
    {
        "id": "V103-O3-001", "priority": "P0", "area": "Orphan road repair",
        "owner": "OpenCode (PR #40)", "status": "TEST_PASSED",
        "affected_sha": "ee94abca...",
        "affected_file": "ultimate_pipeline/topology/orphan_road_repair.py",
        "reproducer": "tests/unit/test_v103_o3_osm_road_graph.py (19 tests)",
        "command": "py -m pytest tests/unit/test_v103_o3_osm_road_graph.py -q",
        "expected": "a repair requires a shared OSM node; geometry may only veto",
        "observed": "39 pass; the six historical orphan ids do not resolve on the current map (5 absent, 1 not an orphan); current population is 326 unreachable / 0 isolated",
        "corrected_sha": "ee94abca8f4c94972329306ecabbd4530886dc71",
        "mutation_result": "mutation control removes the source proof -> the repair test fails",
        "result": "PASS",
        "independent_review": "pending",
        "evidence": "reports/v103/o3/ORPHAN_ROAD_SOURCE_RECONCILIATION.csv",
        "retry_eligible": False,
    },
    {
        "id": "V103-O5-001", "priority": "P0", "area": "Branch governance",
        "owner": "OpenCode audit + repository owner (apply)", "status": "READY_FOR_IMPLEMENTATION",
        "affected_sha": PROD_SHA,
        "affected_file": "GitHub branch protection / rulesets (not a source file)",
        "reproducer": "GET /branches/{b}/protection -> 404 'Branch not protected'; GET /rulesets -> []",
        "command": "py reports/v103/o5/collect_test_execution.py",
        "expected": "production branch protected with required checks",
        "observed": "not protected, zero rulesets, combined status pending with 0 statuses",
        "corrected_sha": None,
        "mutation_result": "n/a - administrative change",
        "result": "FAIL - owner action required",
        "independent_review": "verified by two independent API reads",
        "evidence": "reports/v103/o5/BRANCH_POLICY_CHECKLIST.md",
        "retry_eligible": True,
    },
    {
        "id": "V104-RESEARCH-001", "priority": "P4", "area": "Research / GNN",
        "owner": "OpenCode (O6)", "status": "BLOCKED_RESOURCES",
        "affected_sha": PROD_SHA,
        "affected_file": "23 torch-dependent test modules",
        "reproducer": "py -m pytest tests/unit ultimate_pipeline/tests/unit -q",
        "expected": "the full offline suite collects",
        "observed": "23 collection errors, all ModuleNotFoundError: No module named 'torch'; identical on the unmodified base",
        "corrected_sha": None,
        "mutation_result": "n/a",
        "result": "NOT_RUN",
        "independent_review": "n/a",
        "evidence": "reports/v104/V104_FINAL_REVIEW_REPORT.md",
        "retry_eligible": True,
    },
]

OWNERSHIP = {
    "schema": "v105_ownership_matrix/v1",
    "updated_utc": NOW,
    "single_writers": {
        "Chat 1 / Codex": [
            "ultimate_pipeline/quality/map_acceptance.py",
            "ultimate_pipeline/quality/final_artifact_gates.py",
            "ultimate_pipeline/contracts/artifact_authority.py",
            "ultimate_pipeline/main_pipeline.py",
        ],
        "Codex C3": [
            "ultimate_pipeline/governance/single_writer/worktree_lock.py",
        ],
        "Codex C4": ["ultimate_pipeline/gui/** (lifecycle-owned files)"],
    },
    "opencode_owned": {
        "O1": [
            "ultimate_pipeline/enrichment/lane_width_policy.py",
            "ultimate_pipeline/enrichment/lane_generator.py",
            "ultimate_pipeline/enrichment/osm_xodr_correspondence.py",
            "ultimate_pipeline/enrichment/osm_direction.py",
            "ultimate_pipeline/enrichment/osm_meta_index.py",
            "ultimate_pipeline/pipeline_stages/stage_07_lanes.py",
        ],
        "O2": ["ultimate_pipeline/osm/restriction_*", "ultimate_pipeline/osm/legal_movement_*"],
        "O3": [
            "ultimate_pipeline/quality/osm_road_link_topology.py",
            "ultimate_pipeline/topology/orphan_road_repair.py",
        ],
        "O4": [
            "ultimate_pipeline/quality/map_realism_p0_oracle.py",
            "ultimate_pipeline/topology/connector_elevation_reconciler.py",
        ],
        "O5": ["CI audit + patch proposal only (DOC_ONLY_NO_WRITE)"],
        "O6": ["research-owned files and tests"],
    },
    "read_only_for_opencode": [
        "ultimate_pipeline/governance/single_writer/worktree_lock.py",
        "ultimate_pipeline/quality/final_artifact_gates.py",
        "ultimate_pipeline/quality/map_acceptance.py",
        "ultimate_pipeline/contracts/artifact_authority.py",
        "ultimate_pipeline/main_pipeline.py",
    ],
}

BLOCKERS = {
    "schema": "v105_blockers/v1",
    "updated_utc": NOW,
    "blockers": [
        {
            "id": "B-XML-001",
            "class": "BLOCKED_EXTERNAL",
            "summary": "V96-XMLBOUND-001 has no corrected implementation; the file is Chat 1 owned and the fix must land on the Chat 1 branch with its own review.",
            "recovery_action": "Port the encoding-aware, comment-aware, whole-document scan semantics demonstrated in reports/v103/o1/safe_xml.py into quality/final_artifact_gates.py, re-run the four Scope 1 cases plus the two legitimate controls.",
            "owner": "Chat 1 / Codex",
        },
        {
            "id": "B-GUI-001",
            "class": "BLOCKED_EXTERNAL",
            "summary": "6 GUI release-authority defects reproduced; the source is Codex owned.",
            "recovery_action": "Implement the six corrections in reports/v104/V104_FINAL_REVIEW_REPORT.md section 6.2 and drive tests/unit/v104_gui_authority_adversarial.py from 6 failed / 9 passed to 15 passed.",
            "owner": "Codex (PR #34)",
        },
        {
            "id": "B-LOCK-001",
            "class": "BLOCKED_OWNERSHIP",
            "summary": "9 locking review findings are open across PR #28 and PR #37; worktree_lock.py is a Codex single-writer file.",
            "recovery_action": "Codex resolves all nine under one owner and an approved dependency order; PR #28 is reconciled into PR #37 rather than retired.",
            "owner": "Codex C3",
        },
        {
            "id": "B-BRANCH-001",
            "class": "BLOCKED_EXTERNAL",
            "summary": "The production branch is not protected and the repository has zero rulesets; governance cannot be reported as enforced.",
            "recovery_action": "Owner applies the ruleset in reports/v103/o5/BRANCH_POLICY_CHECKLIST.md and passes the refusal test (a push without the gate must be refused).",
            "owner": "repository owner",
        },
        {
            "id": "B-TORCH-001",
            "class": "BLOCKED_RESOURCES",
            "summary": "The torch optional extra is not installed, so 23 research test modules cannot be collected; R30/R31 cannot be honestly moved.",
            "recovery_action": "Install the gnn extra, or partition the 23 torch-dependent modules for the approved offline profile so the non-GNN research tests can run.",
            "owner": "CI / research owner",
        },
        {
            "id": "B-CARLA-001",
            "class": "BLOCKED_EXTERNAL",
            "summary": "No CARLA runtime, Unreal cook or operator authorization was used; no runtime certification exists.",
            "recovery_action": "Operator approval for a live CARLA 0.9.16 certification run against the accepted candidate SHA.",
            "owner": "operator",
        },
    ],
}

INTEGRATION = {
    "schema": "v105_integration_manifest/v1",
    "updated_utc": NOW,
    "integrated_candidate_sha": None,
    "candidate_status": "NOT_BUILT - no single integration commit exists",
    "branches": {
        "fix/v103-o1-osm-direction-lane-counts": {
            "sha": "102a588cf3336c9b28a3260298f240bd328d513d", "pr": 39,
            "base": "integration/production-large-map-20260918", "state": "open",
        },
        "fix/v103-o3-osm-road-graph-orphans": {
            "sha": "ee94abca8f4c94972329306ecabbd4530886dc71", "pr": 40,
            "base": "integration/production-large-map-20260918", "state": "open",
        },
        "fix/v103-o5-ci-audit": {
            "sha": "6f0b02a227872ae3dfc056f4e6ab97c586c4c6e3", "pr": 41,
            "base": "integration/production-large-map-20260918", "state": "open",
        },
        "fix/v103-opencode-coordination": {
            "sha": "6b0894b605dc36b0681a8d6b25450f7fbc6e684d", "pr": 42,
            "base": "integration/production-large-map-20260918", "state": "open",
        },
        "fix/v104-gui-authority-adversarial": {
            "sha": "bf9ba23f4366652d8959d9a9f81583a1614ffa5b", "pr": 43,
            "base": "integration/carla-gui-integration-20261015", "state": "open",
        },
    },
    "codex_branches_awaiting_convergence": {
        "PR #28": "b8a93e7205182d0b92d1ed730f43f214497d3a19 (7 open findings)",
        "PR #30": "4d38a1fc1ebdf47bb308fa80c4fc1a0d78a9b86f (19 open findings; XML P2 open)",
        "PR #37": "a72700bb1 (2 open findings)",
        "PR #34": "aea4aea5cd4d4c00ece00ba75dc99a5a9fbcd1aa (0 review comments; 6 defects reproduced by PR #43)",
    },
    "uncommitted_required_changes": "none in the OpenCode worktrees",
}

ITERATIONS = [
    {
        "iteration": 1,
        "utc": NOW,
        "phase": "V104 review + V105 init",
        "work": [
            "read all 23 PR #39 review threads and reproduced each defect",
            "corrected all 23 findings in the source and added one regression test per finding",
            "fixed the CodeQL XML findings on the evidence runners with a whole-document, encoding-aware, comment-aware boundary",
            "reproduced V96-XMLBOUND-001 on PR #30 head 4d38a1fc (not repaired)",
            "reproduced 6 GUI release-authority defects with independent tests (PR #43)",
            "enumerated 9 locking review findings across PR #28 / PR #37 (not reproduced - ownership)",
            "verified all 6 V97 archive refs are published on the remote",
        ],
        "defects_fixed": ["V104-PR39-001"],
        "defects_discovered": ["V96-XMLBOUND-001 (re-confirmed)", "V104-GUI-001"],
        "tests": {
            "targeted": "146 passed (V94/V103 lane + correspondence + stage-07 + turn/cycle + acceptance)",
            "full_offline": "23 pre-existing collection errors (torch) - identical to the unmodified base",
        },
        "release_state": "NO_GO",
        "next_action": "Codex: land the XML admission repair on PR #30 and the six GUI corrections; OpenCode: start O2 (legal movement graph) against O1's stable contract.",
    },
]

TEST_RECEIPTS = [
    {
        "id": "v104.pr39.review_fixes",
        "command": "py -m pytest tests/unit/test_v104_pr39_review_fixes.py -q",
        "sha": "102a588cf3336c9b28a3260298f240bd328d513d",
        "platform": "win32", "python": "3.14.5", "pytest": "9.1.1",
        "exit_code": 0, "passed": 28, "failed": 0, "errors": 0, "git_dirty": False,
    },
    {
        "id": "v104.safe_xml_boundary",
        "command": "py -m pytest tests/unit/test_v104_safe_xml_boundary.py -q",
        "sha": "102a588cf3336c9b28a3260298f240bd328d513d",
        "platform": "win32", "python": "3.14.5", "pytest": "9.1.1",
        "exit_code": 0, "passed": 8, "failed": 0, "errors": 0, "git_dirty": False,
    },
    {
        "id": "v104.related_suites",
        "command": "py -m pytest tests/unit/test_v103_o1_osm_direction.py tests/unit/test_v103_o1_red_baseline.py tests/unit/test_v104_pr39_review_fixes.py tests/unit/test_v104_safe_xml_boundary.py tests/unit/test_stage07_structural_osm_metadata.py tests/unit/test_osm_xodr_correspondence.py tests/unit/test_turn_cycle_lane_geometry.py tests/unit/test_lane_generator_osm_count.py tests/unit/test_osm_road_link_topology.py tests/unit/test_lane_count_changes.py ultimate_pipeline/tests/unit/test_classify_lane_count_transitions.py tests/unit/test_measure_candidate_acceptance_drivability_gates.py -q",
        "sha": "102a588cf3336c9b28a3260298f240bd328d513d",
        "platform": "win32", "python": "3.14.5", "pytest": "9.1.1",
        "exit_code": 0, "passed": 146, "failed": 0, "errors": 0, "git_dirty": False,
    },
    {
        "id": "v104.full_offline",
        "command": "py -m pytest tests/unit ultimate_pipeline/tests/unit -q -p no:cacheprovider",
        "sha": "102a588cf3336c9b28a3260298f240bd328d513d",
        "platform": "win32", "python": "3.14.5", "pytest": "9.1.1",
        "exit_code": 1, "passed": 2, "skipped": 2, "failed": 0, "errors": 23,
        "git_dirty": False,
        "note": "23 collection errors, all ModuleNotFoundError: No module named 'torch'; identical on the unmodified base 225ed15d",
    },
    {
        "id": "v104.xml_scope1_repro",
        "command": "py reports/v104/v104_xml_scope1_repro.py",
        "sha": "4d38a1fc1ebdf47bb308fa80c4fc1a0d78a9b86f",
        "platform": "win32", "python": "3.14.5",
        "exit_code": 0, "passed": 0, "failed": 3, "errors": 0,
        "note": "3 bypasses reproduced on the PR #30 head; one payload was PARSED (live entity expansion)",
    },
    {
        "id": "v104.gui_scope2",
        "command": "py -m pytest tests/unit/v104_gui_authority_adversarial.py -q",
        "sha": "bf9ba23f4366652d8959d9a9f81583a1614ffa5b",
        "platform": "win32", "python": "3.14.5", "pytest": "9.1.1",
        "exit_code": 1, "passed": 9, "failed": 6, "errors": 0,
        "note": "6 GUI release-authority defects reproduced; 9 properties already hold",
    },
]


def main():
    write_json("STATE.json", STATE)
    write_json("ISSUE_REGISTRY.json", {"schema": "v105_issue_registry/v1", "updated_utc": NOW, "issues": ISSUES})
    write_json("OWNERSHIP_MATRIX.json", OWNERSHIP)
    write_json("BLOCKERS.json", BLOCKERS)
    write_json("INTEGRATION_MANIFEST.json", INTEGRATION)
    write_jsonl("ITERATION_HISTORY.jsonl", ITERATIONS)
    write_jsonl("TEST_RECEIPTS.jsonl", TEST_RECEIPTS)


if __name__ == "__main__":
    main()
