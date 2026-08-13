# C3-R17 / G19 Remediation Cycle - Summary Report

Date: 2026-08-13
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803
Commit: 378ee830 (pushed to origin)
Predecessor: 0149d1cc

## 1. Mandate (4 stages) - all COMPLETE

| # | Stage | Status |
|---|-------|--------|
| 1 | Re-govern Phase-L certifier onto the crash-safe repaired candidate | DONE, verified |
| 2 | Replay Phase H on the corrected parent | DONE, PASS, idempotent |
| 3 | Length-invariant gate G19 + diagnostic tool | DONE, 14 unit tests |
| 4 | LOAD_DIAGNOSTIC wired into live N-certification | DONE, fail-closed verdict recorded |

## 2. What was fixed

- **Certifier governance (crash-safe):** candidate `ingolstadt_perception_final_repaired.xodr`
  sha256 `6bac3570` now PASSES (0 assert violations, load count 2, all load-count-diff
  invariants above threshold). The previously broken candidate (`80ebb00`) is now correctly
  REJECTED - fail-closed behavior verified with a rebuilt diagnostic.
- **Length repair:** L11152/15734 identity, stub-road length scan, 1122-length correction via
  2-part Z-split with first segment med s=0.
- **Phase H replay on corrected parent:** all gates PASS, 3467 signals, re-run byte-identical
  (idempotency proven, zero diff between 20260813 and 20260814 runs), payload integrity clean.
  Evidence: `20260813T000000Z_C3_REGOVERN/G_REPLAY_PHASE_H.json`.
- **G19 length-invariant gate:** new `ultimate_pipeline/core/opendrive_gen_diagnostic.py`
  (canonical + submission mirror, drift-checked) + 14 unit tests; live bundle evidence
  `violations=0 roads_checked=32710`.
- **run_n_certify.py:** emits `length_invariant` evidence, new `--candidate-xodr` flag, fixed
  pre-existing crash (`str / str` Path bug) in Phase Q provenance output.
- **Verdict:** PHASE_N_REJECTED - 13 gates passed, 7 failed, 0 missing; this is the designed
  fail-closed outcome, NOT a regression.

## 3. Verification performed (offline, all green)

- 394 unit tests, 120 `test_all` tests: PASS
- 2403 tests (unit + phase_q + opendrive_geometry): PASS
- 133 tests (r13 set + stage_i + crosswalk schema + coordinate quality): PASS
- Live `run_n_certify.py` end-to-end run: executes to completion, reports written to
  `20260813T075853Z_N_CERTIFICATION/`

## 4. What needs verification (REQUIRES a live CARLA runtime - blocker for full PASS)

| Gate | Issue | Required action |
|------|-------|-----------------|
| G2   | P04 evidence still pins stale candidate sha `80ebb00` | Re-collect Phase L/P04 evidence from a run on candidate `6bac3570` (same CARLA server/commit sha `10033a16`) |
| G5   | FPS evidence stale | Fresh runtime probe |
| G6   | Spawn/render counts stale | Fresh runtime probe |
| G7   | Semantic equivalences pending | Fresh Phase L semantic run |
| G14/G15 | Runtime sha / semantic counts anchors stale | Refresh from new evidence bundle |
| G18  | Manifest signature against stale anchors | Re-sign manifest after fresh run |

Once fresh evidence is collected and P04 repins to `6bac3570`, re-run
`run_n_certify.py --profile perception --candidate-xodr .../ingolstadt_perception_final_repaired.xodr`;
G19 plus the 13 passing gates must hold, and the 7 stale-anchor gates must flip to PASS.

## 5. Pending problems / open items

1. **Live runtime evidence absent** (no CARLA server on this workstation): the 7 failing
   gates are the terminal offline state; full release requires a live run on the pinned
   runtime sha. Until then certification remains REJECTED by design.
2. **Large XODR artifacts not committed** (78-81 MB each): governance forbids staging
   large datasets; integrity is anchored via sha256 in evidence JSONs. Verifier artifacts
   must be re-fetched locally at the digest recorded in P04.
3. **Trailing-refresh protocol:** the next live evidence run consumes `378ee830` as parent;
   its evidence commit will need its own freeze refresh commit per the ledger contract.
4. **P8 package-build evidence:** `P8_PACKAGE_BUILD_CORRECTED.json` recorded from the smoke
   run; final package build must be re-validated on the live runtime.
5. **Artifact drift watch:** `scripts/` probe utilities and probe logs remain untracked
   (scratch by convention); if any probe is promoted to production it must be mirrored and
   hash-registered like `opendrive_gen_diagnostic.py`.

## 6. Integrity closure

- Evidence committed: G_REPLAY_PHASE_H.json, full N-certification bundle (gate matrices,
  provenance Q00-Q02, manifest, verdict), P8 protocol json.
- All offline test suites pass; no trailing uncommitted governed change remains.