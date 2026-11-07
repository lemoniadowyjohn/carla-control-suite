# Mandatory adversarial negative controls

Each negative control must fail for the correct reason under a known-bad fixture, then pass only after correction. Log exact nodeid, exit code, seed, SHA, expected-vs-actual and transport/runtime calls (always zero when prohibited).

## IC: CI/ownership
- IC-01 `ok="yes"` or `ok="false"` never becomes strict PASS. Verify all canonical truth/waiver precedence and legacy conversion.
- IC-02 mirrored loader files differ in one executable line -> drift gate FAIL; authoritative correction cannot silently lose code.
- IC-03 Windows C: not present on POSIX -> either OS-scoped test, or explicit test of Linux mount; unknown volumes fail closed.
- IC-04 two threads/processes acquire lock simultaneously, delayed/partial creation and crash -> never both ACTIVE; no stale deletion of live uncommitted lock.
- IC-05 PID reused, start-time changed, invalid creation-time, dead owner, lease journal corruption and handoff -> deny/needs reconciliation; never release live owner.
- IC-06 native Windows mutex truly exercised on Windows; Linux should not claim success from mock-only tests; document OS matrix.

## RQ1/RQ3
- RQ1-01 import/file compile non-CARLA; undefined names are caught in actual callable path without invoking CARLA; entrypoint failure produces nonzero exit and FAILED receipt where possible.
- RQ1-02 per-stage digest missing, run-index mismatch, git SHA unknown, placeholder metrics, timestamp/seed mismatch -> not PASS. Repeated runs input identity fixed; outputs independently hashed.
- RQ3-01 two matching metadata JSON objects but missing capture files -> no dataset-integration PASS.
- RQ3-02 symlink outside approved dataset root, existing file wrong SHA, duplicate frames, timestamp nonmonotonic, mismatched route, sensor, map/CRS, class map, modality and image dimension -> FAIL.
- RQ3-03 `quality_evaluation` absent/NOT_RUN -> no scientific PASS even if pair contract matched; require actual metrics and counts for scientific review.

## RQ2/RQ4/RQ5
- RQ2-01 reversed lane links, orphan 92–175m case, zero-length connector, wrong lane direction, impossible contact point, topology disconnected, wrong CRS, flattened elevation, final-XODR-only edit -> FAIL.
- RQ2-02 GAP-026 acceptance fails if tolerance raised, baseline changed or source-stage mutation missing even when final artifact passes a lax check.
- RQ4-01 same scene/time/map/seed across train/test, replicated derivative with distinct filename, near-duplicate image and shared graph neighborhood -> FAIL.
- RQ4-02 leakage auditor fails on missing manifest, unknown split identities, empty dataset, corrupted hashes and ambiguous grouping.
- RQ5-01 synthetic metadata alone, model checkpoint absent, training aborted, val/test leakage, train-time tuning on held-out test, incomplete 3 commits and invalid baseline -> NOT_ADMITTED.
- RQ5-02 evaluation wrong denominator, missing confidence interval, cherry-picked subset, contaminated baseline or insufficient held-out split -> FAIL/INCOMPLETE.

## RPC & proofs
- RPC-01 mock or successful socket connection without actual CARLA RPC response -> BLOCKED_EXTERNAL or NOT_EXECUTED, never runtime PASS.
- REC-01 audit log with command recorded but no result -> NOT_EXECUTED/UNKNOWN, not PASS.
- REC-02 `pytest` exit 1 or missing collected/passed fields -> never PASS.
- REC-03 historical artifact silently overwritten, evidence checksum mismatch or candidate SHA changed mid-run -> REQUIRES_CHANGES / stop.
