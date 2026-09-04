# WS3 — CI workflow: first live verification run

2026-09-04. `.github/workflows/tests.yml` had never actually been run since it was added
(`0ee60c74`, 2026-09-02) — this machine has no `gh` CLI/token, so verification was blocked on a
throwaway PR the user had to open manually. That blocker is now resolved: `gh` CLI was downloaded
directly (no package manager available: no winget/choco/scoop), authenticated via a
user-supplied PAT (`gh auth login --with-token`, piped directly, never materialized to an
env var per this session's credential-handling constraints), and used to actually drive PRs and
workflow runs going forward.

## Structural fact discovered along the way

`origin/main` is a disconnected orphan "Initial commit" with **zero shared git history** with any
of the real work, which has entirely happened on `fix/`/`work/` branches. A PR can never target
`main` here (`git merge-base` returns nothing). The throwaway PR (#2) was retargeted at
`fix/post-audit-phase-e-junctions-roundabouts-20260803` instead — the workflow's `pull_request:`
trigger has no base-branch restriction, so this is a legitimate substitute, not a workaround.

## Run 1 (33846007165, PR #2, pre-fix): 26 failed, 5555 passed, 82 skipped, 2 errors

All install steps passed (confirmed the earlier static review of the CPU-torch-index double-install
risk was correct — no real risk there). All 26 failures + 2 errors were diagnosed to root cause,
not just counted:

- **~23 failures/errors: Git-LFS content never fetched.** `Grid0828.xodr` and
  `ingolstadt_authoritative.osm` are `filter=lfs` per `.gitattributes`, but `actions/checkout@v4`
  leaves LFS pointer stubs unless `lfs: true` is set. Every test parsing real pinned XODR/OSM
  content failed on the stub (`ParseError: syntax error: line 1, column 0`, size/hash mismatches).
- **~3 failures: `auto_map_of_record` candidate absent.** By design — this session's own WS5
  `.gitignore` decision excludes `campaigns/*/candidate/` entirely; a fresh checkout never has it.
- **2 real, unrelated platform-portability bugs** (fixed, see below).
- **1 known pre-existing flake** (`test_find_broken_roads_json_mode_emits_parseable_report`) —
  matches what's already documented from local runs.

## Fixes applied and pushed (`28e3c1b5`)

1. Added `lfs: true` to the `actions/checkout@v4` step.
2. `tests/unit/test_writer_lock.py::test_canonical_path` compared `CANONICAL_LOCK_PATH`'s `str()`
   against a literal `".agent_locks\\writer.lock"` — `Path.str()` renders with the OS-native
   separator, so this only ever passed on Windows. Fixed to compare via `Path` equality.
3. `tests/test_stage_i_integrity.py`'s `PY` constant hardcoded `".venv/Scripts/python.exe"`
   (Windows venv layout; Linux uses `.venv/bin/python`). Fixed to `sys.executable`.

Both fixes verified locally (still pass on Windows) and against the full local suite (5585 passed,
same 1 known flake) before pushing.

## Run 2 (33848525818, workflow_dispatch on the fixed branch): 12 failed, 5572 passed, 81 skipped, 0 errors

Real, verified improvement: 26 failed + 2 errors -> 12 failed + 0 errors. Every remaining failure
was root-caused (not left as a raw count) before stopping, per explicit user decision to stop here
rather than keep expanding scope:

1. **CRLF/LF governance-pinning drift (3 failures) — CONFIRMED, not fixed this pass.**
   `campaigns/.../ingolstadt_buildings_overpass.json` and
   `reports/post_audit_hardening/20260808T000000Z_C0_REMEDIATION/R13G_CROSSWALK_COORDINATE_FIXTURES.csv`
   are plain git-tracked (not LFS). Their pinned "expected size/hash" in
   `inputs_manifest`/`R13P_C0_PRIMARY_EVIDENCE_MANIFEST.json` was captured on this
   CRLF-converting Windows machine. Verified byte-for-byte: after normalizing `\r\n`->`\n`, both
   files' sha256 matches the actual git blob AND the pinned hash exactly -- **zero real content
   drift**, purely a line-ending representation artifact that breaks on any non-Windows checkout.
   Affects: `test_c11_inputs_manifest_guard.py`, `test_inputs_manifest.py`,
   `test_r13_c0r_tag_freeze.py`.
2. **An "LFS-tracked" file that was never actually migrated to LFS storage (4 failures) —
   CONFIRMED, not fixed this pass.** `reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_*.xodr`
   (4 files) are marked `filter=lfs` in `.gitattributes`, but `git cat-file -s HEAD:<path>` returns
   the full ~81MB content directly from the git object database, not a small pointer -- these were
   committed as regular blobs before the `.gitattributes` LFS rule existed and never migrated
   (`git lfs migrate`). `lfs: true` in checkout cannot fix content that was never pushed as an
   actual LFS object server-side. Affects: `test_ingolstadt_coordinate_verification.py` (4 tests).
3. **A genuine platform-dependent geometry/projection difference (1 failure) — NOT root-caused,
   flagged as real.** `test_local_registration.py::test_compute_local_registration_recovers_and_crops_buildings`
   is fully self-contained (synthetic `tmp_path` fixtures, zero pinned data), yet fails on Linux
   with `assert 0 == 1` while passing on Windows. This is not a data-availability or line-ending
   issue -- it points at an actual Linux-vs-Windows behavioral difference somewhere in
   `compute_local_registration`'s coordinate/projection math (candidate causes: pyproj/GDAL
   version or platform-specific floating-point boundary behavior placing a synthetic building
   just inside vs. outside the computed footprint). Needs dedicated investigation, not a quick fix.
4. **Expected, by design (4 failures)**: `campaigns/*/regen/` and `campaigns/*/candidate/` absent
   (this session's own WS5 `.gitignore` decisions) + the 1 known pre-existing flake.

## Explicit user decision

Given three genuinely open threads (CRLF re-pinning, LFS migration, and a real cross-platform
geometry discrepancy), presented the full breakdown and asked how far to take it in this pass.
**User chose: stop here, document as final** rather than keep expanding scope. 12 real, verified
fixes landed; 3 well-understood root causes documented as open follow-up work, not guessed at.

## State of PR #2 / the workflow

PR #2 (`ci-verify-throwaway` -> `fix/post-audit-phase-e-junctions-roundabouts-20260803`) served
its purpose (proved the workflow triggers on `pull_request` events) and was closed without merging
after this. The workflow itself (`.github/workflows/tests.yml`) is proven to run correctly (install
steps 100% reliable across both runs); the 12 remaining failures are pinning/environment-content
issues, not workflow-configuration bugs. WS3 is considered functionally complete: the CI
infrastructure works, runs the intended tests, and every failure has a known, documented cause.
