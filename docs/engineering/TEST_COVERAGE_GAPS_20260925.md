# Test Coverage Gaps — 2026-09-25

## Current evidence

The repository has a large offline suite and recent production evidence records **6264 passed, 6 skipped, 0 failed** after the CI-closure merge. That is useful regression evidence, but it is **not a quantitative coverage measurement**.

Current canonical CI does not run `pytest --cov`, no `pytest-cov`/coverage threshold is configured in the production workflow, and the repository therefore cannot currently make a defensible line-coverage or branch-coverage percentage claim.

The coverage problem is primarily **risk-surface coverage**, not test-count scarcity: several high-severity defects escaped a very large green suite.

## Escaped-defect lessons

### MainPipeline complete-path reachability

A real `MainPipeline` regression left production step methods outside the class and caused an unconditional crash when a complete run reached STEP 4. The fast determinism fixture did not reach that path, so thousands of tests did not expose it.

Required coverage:
- one committed, self-contained fixture that reaches every mandatory pipeline stage through a final receipt;
- explicit assertion that required stage methods/capabilities are reachable;
- a smoke test that executes the real production orchestration rather than only stage helpers.

### CARLA Large Map importer contract

Current unit tests intentionally protect incremental behavior:
- empty tile lists are accepted;
- missing tile sources are skipped without making staging fail;
- both `package.json` and `<PackageName>.json` are expected.

Those contracts are useful for probes but are unsafe as final-release semantics because CARLA 0.9.16 recursively discovers `*.json` package descriptors.

Required coverage:
- separate `PROBE` and `FINAL_RELEASE` modes;
- final mode requires exact expected tileset equality;
- actual CARLA-0.9.16 JSON-discovery behavior tested against a staged fixture;
- unexpected JSON under Import fails;
- partial/mixed-generation tilesets fail;
- map-name prefix mismatch fails in final mode.

### Map-registry consumer contract

`verify_pinned_map()` itself is well tested, but consumers must also be tested to use the verified `resolved_path` for I/O and to resolve at execution time rather than module import time.

Required coverage:
- non-repository current working directory;
- relative declared path versus absolute verified resolved path;
- registry change between module import and command execution;
- registry identity changed during a long-running job;
- production-pin containment policy.

### GAP-026 / map-quality signal consumption

The checker was executable and wrote evidence, but its result was not consumed by release/map acceptance. This is a wiring-coverage failure.

Required coverage:
- every generated quality signal has an explicit consumer or is explicitly advisory;
- contract test maps signal status to final gate/receipt;
- an intentionally failing severe lane-link fixture must prevent a release claim unless an explicit governed waiver exists.

### RQ3 scientific-claim contract

There is indirect testing of RQ3 frame completeness and sensor-rig behavior, but no dedicated test module currently proves the complete claim matrix for `rq3_capture_contract.py` and `route_manifest.py`.

Required coverage:
- property/table tests over `pair_valid`, route closure and claim level;
- correct name/wrong hash;
- correct source/wrong cooked package;
- requested Grid0828 but different runtime map;
- client/server build mismatch;
- static contract complete but runtime not executed;
- hidden spawn recovery in strict mode;
- route representability failure on one arm.

### WriterLock

The primary atomic-publication race has dedicated multiprocessing tests. Residual coverage should include malformed legacy `.agent_lock.json` handling and a bounded stress campaign that distinguishes harness timeout from deadlock.

### Platform coverage

The full GitHub-hosted offline suite runs on Ubuntu. The project is materially Windows-sensitive (CARLA/UE build scripts, paths, lock semantics, drive letters), and prior defects were platform-specific.

Required coverage:
- bounded `windows-latest` contract job;
- WriterLock;
- path/config authority;
- package staging;
- map registry;
- CLI/import smoke;
- no Unreal/CARLA requirement on hosted CI.

## Coverage measurement plan

### Phase 1 — measure without gating

Install coverage tooling in CI only and publish:
- line coverage;
- branch coverage;
- XML/JSON artifact;
- per-package report.

Do not introduce an arbitrary global threshold on the first run.

### Phase 2 — establish risk-based floors

After measuring the baseline, define floors for critical authority modules first:

- `ultimate_pipeline/contracts/`
- `ultimate_pipeline/carla_tools/map_registry.py`
- `ultimate_pipeline/tiling/large_map_package.py`
- `ultimate_pipeline/perception/rq3_capture_contract.py`
- `ultimate_pipeline/perception/route_manifest.py`
- critical `MainPipeline` orchestration paths

Use branch coverage for decision-heavy contract code.

### Phase 3 — ratchet

Coverage must not fall below the reviewed baseline on changed critical modules. Raise floors only when new meaningful tests land.

Do not optimize for percentage by testing trivial getters or excluding difficult production paths.

## Required test layers

A final release should report all layers separately:

1. unit tests;
2. contract/property tests;
3. offline integration tests;
4. full offline suite;
5. Linux CI;
6. bounded Windows CI;
7. failure/recovery campaign;
8. live CARLA RPC;
9. Unreal import/cook/package;
10. runtime map QA;
11. scientific RQ execution.

A PASS at one layer never inherits into the next layer.

## Coverage acceptance checklist

Before calling test coverage release-grade:

- quantitative line/branch baseline exists;
- complete MainPipeline fixture reaches final receipt;
- CARLA importer semantics are tested from the real 0.9.16 contract;
- final tileset cannot pass incomplete;
- RQ3 claim combinations are adversarially tested;
- registry consumers are CWD/staleness tested;
- Windows contract lane is green;
- GAP signal-to-gate wiring is tested;
- timeout is never reported as PASS;
- runtime/cook/scientific layers remain separately reported.
