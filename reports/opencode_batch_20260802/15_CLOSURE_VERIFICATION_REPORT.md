# 15 - Closure Verification Report (Batch 14B)

Date: 2026-08-02 | Branch: `integration/governed-map-quality-20260729`
Closure HEAD: `b18ddde99adacebebebd8a162e2625bafa1eb290`

## Status: CLOSED - ALL GATES PASS

Completes the 3-task closure requested after P14
(`14_INTEGRATION_REPORT.md` verdict
`READY_FOR_UNREAL_TOOLCHAIN_PROVISIONING`).

## Task 1 - Tracked-ID verification (232/232) - PASS

- `01_REQUIREMENTS_REGISTRY_218.json`: 218 formal requirements.
- `02_ISSUES_REGISTRY_14.json`: 14 issues (ENR-I01..I06, OSM-I01..I04,
  REP-I01..I04) extracted from
  `F:\pulpit\CARLA_PIPELINE_STAGE_REQUIREMENTS_AND_GAP_ASSESSMENT.md`.
- `03_ID_VERIFICATION.json`: 218 + 14 = 232 tracked; unknown 0,
  duplicate 0, unassessed 0; registry vs inventory diff 0; req/issue
  overlap 0.
- `reports/post_audit_hardening/20260801T221042Z/issues_registry.jsonl`
  enriched (issue/impact/required_correction/disposition/evidence;
  stub preserved as `issues_registry_stub_backup.jsonl`).

## Task 2 - Dirty-file ledger - PASS

- `04_DIRTY_FILE_LEDGER.json/.csv`: per-path tracked/untracked state,
  pre-batch vs current SHA-256, reason, owner, classification
  (safe_to_ignore / must_preserve / move_to_isolated_evidence).
- Ledger drove the SYS-001 closure commit `1bc6dd3d`: only 108 of 615
  canonical `.py` files were tracked; 512 files (incl. full 7466-line
  `run_full_domain_gap.py`, previously a 233-line stub) are now tracked.
  Secret scan: 0 hits. `.pytest_cache/` already ignored.
- Remaining dirty paths are pre-existing by design (stage_08 submission
  copies, `.githooks`, `.idea`, `audit_output/`, `audit_output.zip`,
  `carla_governed/`, `external/`, `work/`, `worktrees/`) and are
  documented in the ledger.

## Task 3 - Clean-worktree reproduction - PASS (11/11 gates)

Detached worktree at closure HEAD, fresh venv (pytest 9.1.1, numpy 2.5.1,
lxml 6.1.1, NO carla wheel), hash-pinned `audit_output/` input.
`05_P14_CLEAN_WORKTREE_VERIFY_REPORT.json`:

| Gate | Result |
|------|--------|
| G1 HEAD identity | `b18ddde9` matches |
| G2 compileall | ok |
| G3 canonical imports | 18/18 |
| G4 collection | 2606 tests, 0 errors |
| G5 full offline suite | 2528 passed, 78 skipped, 0 failed |
| G6 negative controls | 11/11 passed |
| G7 map structural | lane ok (0 fails); 45632 seams, max_delta 0.0; 32710 roads, 0 non-finite bounds |
| G8 authoritative hashes | OSM `b9e074656f`, XODR `ff2a05e7b0` |
| G9 evidence manifest | 32 checks, 0 new findings (known finding: stale 07_BLOCKING_ISSUES.md claim, accepted in Phase A) |
| G10 tracked IDs | 218 + 14 = 232 |
| G11 untracked sources | 0 |

Environment provisioning fixes applied during reproduction (mirror of the
original environment): pydantic, click, requests, shapely, scipy,
rasterio, matplotlib, pyproj, and canonical `pyproject.toml` (commit
`b18ddde9`) enabling `pip install -e .` in fresh venvs - required because
`conftest.py` imports the editable-install finder.

## Passage gate

Clean-tree reproduction of the full offline verification at the closure
HEAD succeeded with zero failures, zero untracked source dependencies,
and unchanged authoritative artifact hashes. The release tree is ready
for Unreal toolchain provisioning, subject to the standing rule: the next
campaign must first prove the toolchain on a small OSM-derived fixture
(curve, junction, sidewalks, elevation, signals, collision/semantic
assets) before the full Ingolstadt map.
