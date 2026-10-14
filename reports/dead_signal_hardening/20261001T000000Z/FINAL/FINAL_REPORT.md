# Dead-Signal Hardening Campaign — FINAL Report

**Campaign:** NEW-334 through NEW-349 (zero-dead-signal pipeline hardening)
**Branch:** `integration/production-large-map-20260918`
**Baseline SHA:** `f897e0eb747ac827941ac4883170a5181a603111`
**Report date:** 2026-10-01
**Status:** COMPLETE — all 16 findings addressed

---

## 1. Scope

This campaign addressed findings NEW-334 through NEW-349 only. NEW-200 through
NEW-333 were not re-implemented. Concurrent OpenCode work that already changed
affected code was inspected and verified against contract where found.

The objective was to eliminate every path by which a governed pipeline signal
could be declared in the registry but never satisfied in production — a "dead
signal" that reads forever as MISSING or silently as NOT_APPLICABLE.

---

## 2. Findings addressed

| Finding | Title | Resolution |
|---------|-------|------------|
| NEW-334 | `final_run_verdict.json` as sole run authority | Verdict computed from registry; `SUCCESS.txt` only on PASS; stale SUCCESS invalidated at run start |
| NEW-335 | Pipeline health summary | `pipeline_health_summary.json` written fail-closed; health status merged into verdict |
| NEW-336 | Reordered SUCCESS finalization | Stages → gates → validation report → gate_failures → health → run_summary → verdict → finalize → verify → SUCCESS |
| NEW-337 | Signal index in run_summary | `build_signal_index` publishes per-signal class, enablement, artifact digest, normalized status |
| NEW-338 | Dead-signal auditor | `tools/audit_pipeline_signal_graph.py` — static gate: producer resolvable, artifact written, predicate known |
| NEW-339 | Domain gap stage status | `domain_gap_stage_status.json` written on all paths (blocked/success/exception) |
| NEW-340 | Strict profile alias normalization | `_STRICT_PROFILE_ALIASES` aligned to settings semantics; `resolve_strict_quality_gates` normalizes |
| NEW-341 | Transport gates in quality gate manager | `TRANSPORT_GATES` + `BLOCKING_GATE_NAMES`; hard stops recorded via `_transport` |
| NEW-342 | Wrapper failures reaching gate_failures.json | `_run_quality_gates_wrapper` passes `out_dir`/`vreport`/`qgate`; raises on transport then drivability failures |
| NEW-343 | Identity vs experiment-readiness cross-checks | Receipt digest cross-checked against bytes on disk; identity and readiness reported separately |
| NEW-344 | G6 hygiene report honesty | `ok`/`status`/`blocks_release` on all paths; exception path writes `ok: False` |
| NEW-345 | Geometry freeze wiring | `StageContext` fingerprint API wired into `_freeze_geometry_fingerprint`/`_verify_geometry_fingerprint`; GEOM-FREEZE-001 enforced at two points |
| NEW-346 | RQ1 receipt schema + null-field honesty | `rq1_run_receipt/v1` schema stamped; `None == None` → INCOMPLETE; unreadable receipt → INCOMPLETE |
| NEW-347 | Dead env vars in safe runner | `UP_ENABLE_SEMSEG` and `UP_WEATHER_PRESET` removed; only `UP_TM_SEED` forwarded |
| NEW-348 | Determinism binding | `_determinism_binding()` in run_summary; `ledger.record_evidence` kept as-is |
| NEW-349 | Governed signal persistence | `write_governed_signal` — atomic, verified, fail-closed; persistence failures block verdict |

---

## 3. Signal registry

22 signals registered. Every signal has:
- A resolvable producer (module-level callable or `MainPipeline` method)
- At least one production writer for its artifact
- A known enablement predicate (settings attribute, env contract, or pseudo-predicate)
- Declared pass/failure/missing states and skip/missing policies

**Shared artifacts** (intentional):
- `gate_failures.json` — CUMULATIVE_GATES + WRAPPED_GATE_FAILURES
- `map_acceptance.json` — MAP_ACCEPTANCE + EXPERIMENT_READINESS (field view)

---

## 4. Static audit

```
[SIGNAL_AUDIT] status=PASS signals=22 dead=0 scanned_sources=902
```

The auditor (`tools/audit_pipeline_signal_graph.py`) verifies:
1. Every producer path resolves to a callable
2. Every artifact has ≥1 production writer (excluding signals/contracts/tests)
3. Every `enabled_by` predicate names a settings attribute, env contract, or pseudo-predicate
4. Blocking signal classes (HARD_GATE, REQUIRED_WHEN_ENABLED) are required by ≥1 profile
5. Mandatory pack paths resolve to registered artifacts or safe relative paths

---

## 5. Test results

**Full suite:** 6897 passed, 7 skipped, 3 failed (33m 19s)

The 3 failures are pre-existing and not attributable to this campaign:

| Test | Cause |
|------|-------|
| `test_workflow_hardening.py::test_runtime_workflow_does_not_claim_offline_ci_certifies_runtime` | Concurrent campaign's uncommitted changes to `.github/workflows/carla-runtime.yml` (364 lines) |
| `test_a1_a2_path_and_frame_resolution.py::test_no_hardcoded_username_in_production_defaults` | cwd-dependent: `DEFAULT_OSM2WORLD_HOME` embeds `C:\Users\admin\...` when run from home dir |
| `test_a1_a2_path_and_frame_resolution.py::test_missing_osm2world_fails_precisely` | Environment-dependent: osm2world dir exists so SystemExit not raised |

**New tests added:**
- `tests/contracts/test_no_dead_pipeline_signals.py` — 11 tests (static dead-signal gate)
- `tests/contracts/test_signal_verdict_semantics.py` — 40 tests (verdict/index/health semantics)
- `tests/unit/test_o15_rq1_five_run_matrix.py` — 8 tests (updated to NEW-346 contract)

**Updated tests:**
- `tests/unit/test_stage8h_map_hygiene.py` — G6 exception expectation updated for `ok: False`
- `tests/unit/test_o15_rq1_five_run_matrix.py` — null-field receipts now INCOMPLETE

---

## 6. Lint and typecheck

- **ruff:** All new/modified files pass. Pre-existing F821s in `stage_10_tile_qa.py` (runtime injection pattern) reduced from 56 to 52.
- **mypy:** All new/modified files pass. Pre-existing errors in `signal_enrichment.py` (Sept 23) unchanged.

---

## 7. Artifacts

| File | Description |
|------|-------------|
| `FINAL/SIGNAL_GRAPH_AUDIT.json` | Static audit report (22 signals, 0 dead) |
| `FINAL/SIGNAL_REGISTRY_INVENTORY.json` | Full registry inventory with profiles |
| `FINAL/SHA256SUMS.txt` | SHA-256 checksums for all FINAL artifacts |

---

## 8. Runtime verification status

Runtime verification (CARLA/UE4) was not attempted in this environment. The
campaign's changes are structural and static: they ensure that when runtime
verification is attempted, no signal can be silently skipped, mislabeled, or
left missing. The verdict vocabulary supports
`ZERO_DEAD_SIGNAL_OFFLINE_PASS_RUNTIME_BLOCKED` as the expected outcome for
offline runs.

---

## 9. Conclusion

All 16 findings (NEW-334 through NEW-349) are addressed. The signal registry is
the single source of truth for what constitutes a complete run. Every signal
has a resolvable producer, a production writer, and a known enablement
predicate. The static auditor gates future changes. The verdict is computed
from the registry and cross-checked against bytes on disk. No dead signals
remain.
