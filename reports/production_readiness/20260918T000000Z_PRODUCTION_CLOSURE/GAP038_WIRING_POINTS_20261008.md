# GAP-038 Wiring-Points Scout (read-only)

Date: 2026-10-08
Scope: read-only reconnaissance of where GAP-038's two contract modules would
attach to production code. **No policy decision is made here.**
`MASTER_GAP_REGISTER.json` and the gap-038 policy document are untouched by this
scout. Nothing outside this file was modified.

Baseline: production tip `68868f76` (`origin/integration/production-large-map-20260918`).

---

## A. Modules under decision

| Module | Tests | Production callers |
| --- | --- | --- |
| `ultimate_pipeline/tiling/carla_0916_import_process_contract.py` | `ultimate_pipeline/tests/unit/test_v4_import_contracts.py` | **0** |
| `ultimate_pipeline/tiling/carla_0916_large_map_contract.py` | `ultimate_pipeline/tests/unit/test_v4_large_map_contract.py` | **0** |

Zero-caller evidence (repo-wide `grep carla_0916_import_process_contract|carla_0916_large_map_contract`
over `ultimate_pipeline/`, `tools/`, `scripts/`, `tests/`): only the two modules'
own self-references and the two test files above. Both are fail-closed reference
implementations with no attachment to any commandlet runner or package stager.

What wiring means for each:

- **Import contract**: make at least one real commandlet execution path run
  through `run_mandatory_process` (import process state machine, receipt with
  `ALLOWED_STATUSES`, expected-output/hash binding, `ImportProcessError` on violation).
- **Large-map contract**: make at least one real package staging/identity path
  produce a validated `PackageIdentity` via `resolve_package_identity` (identity
  bound to `package.json` descriptor sha, import manifest sha, source XODR sha)
  instead of passing bare package-name strings around.

---

## B. Commandlet-execution call sites

### C1 — external `Import.py` `supervise_child` (the real choke point)

File: `G:\CARLA\carla_source_probe\Util\BuildTools\Import.py` (outside this repo).

| Line | What |
| --- | --- |
| `:164` | `def supervise_child(command, label, timeout=None, output_validator=None, cwd=None)` |
| `:217` | the only `subprocess.Popen(` in the file — spawn |
| `:733` | `def invoke_commandlet(name, arguments, output_validator=None)` |
| `:756` | `return supervise_child(...)` — sole call inside `invoke_commandlet` |
| `:923` `:932` `:938` `:1027` `:1033` `:1045` | `invoke_commandlet(...)` call sites — every `-run=` commandlet |
| `:1102` `:1104` | direct `supervise_child` use: Recast `chmod +x build.sh` / `build.sh` run |

Today it is a hand-rolled supervision state machine with receipts
(`STATE_OK` / `STATE_NONZERO` / `STATE_TIMEOUT` / `STATE_SPAWN_FAILED` /
`STATE_CHILD_TERMINATED_UNEXPECTEDLY` / `STATE_OUTPUT_VALIDATION_FAILED`) that
raises `ChildProcessError`. So it **already fails closed**, but it has:

- no expected-output existence/hash binding against a contract-declared set,
- no `ALLOWED_STATUSES` vocabulary (its own status vocabulary differs from the
  import contract's),
- no `ImportProcessResult` receipt objects.

**Minimal diff**: delegate the body of `supervise_child` (or just the
`invoke_commandlet` call at `:756`) to
`run_mandatory_process(command, cwd=..., timeout_s=..., log_dir=<label dir>,
expected_outputs=<from output_validator>, runner=...)`, catch
`ImportProcessError` and re-raise as `ChildProcessError(err.receipt)` so the
external contract pinned by `tests/test_import_supervision.py` (raises
`ChildProcessError` at `:278`, `:297`, `:344`, `:391`, `:403`) is preserved.
Recast (`:1102`, `:1104`) can route through the same helper.

**Caveat**: the file lives outside this repo (a probed source tree), so wiring
C1 requires either a `sys.path` import of this repo's `ultimate_pipeline` from
`Import.py`, or a vendored copy of the contract module — an ownership decision
the policy must make. `tests/test_import_supervision.py:574` already asserts
`"subprocess.check_call(" not in source` and `:536` forbids bare
`subprocess.call/check_call`, i.e. the test suite already treats `Import.py` as
in-scope for supervision hardening.

### C2 — in-repo `run_supervised` does not fail closed

File: `tools/carla_import_supervision.py`

- `:296` `def run_supervised(command, *, state, ...)`
- `:319` `subprocess.Popen(...)`
- `:376` on child failure: `state.transition("CHILD_FAILED", ...)`
- `:379` `return receipt` — **no raise on failure**; callers must inspect the receipt.

**Minimal diff**: after the receipt is written (~`:368`), add

```python
if not (classification or {}).get("is_success"):
    raise ImportProcessError("supervised child failed", receipt=receipt)
```

imported from `ultimate_pipeline.tiling.carla_0916_import_process_contract`,
optionally with `expected_outputs` plumbed through. Receipt schema
(`COMMANDLET_EXECUTION_RECEIPT.json`) stays intact — the raise is additive to
the file format.

**Test-contract touch point**: `tests/unit/test_carla_import_supervision.py:196`
pins the current non-raising behavior (`rec = run_supervised([... SystemExit 4])
` then inspects `rec`), likewise `:188`, `:209`, `:225`. Fail-closed wiring
deliberately changes this contract; those tests need a conscious update (or the
raise becomes a `strict=True` opt-in, which makes the wiring inert by default).

### C3 — sites checked and excluded (do not re-search)

- `ultimate_pipeline/hpc/carla_server_launcher.py:59` — `subprocess.call(cmd)`:
  CARLA server launch only; explicitly excluded by GAP-038 `MODULE_JUSTIFICATION`.
- `ultimate_pipeline/main_pipeline.py:1456`, `:1475` — generic `subprocess.run`
  helpers; `:4100` — `git rev-parse HEAD`; `:4371` — tile-worker probe.
  None builds a UE4Editor `-run=` argv.
- Repo-wide: no in-repo Python constructs `... -run=...` commandlets (the string
  appears only in reports/prose, tests, and `Import.py` itself).
- The process that runs `python Import.py ...` is external/manual: no in-repo
  spawner exists (`scripts/ownership_discovery.py` classifies such processes as
  `ORCHESTRATOR:Import.py` from the outside).

**Net**: the only executable commandlet choke points are C1 (external) and the
in-repo-but-inert `run_supervised` (C2).

---

## C. Package-identity call sites

### P1 — staging constructs identity itself

File: `ultimate_pipeline/tiling/large_map_package.py`

- `:286` `def stage_large_map_package(...)` — writes `package.json`, the
  `<PackageName>.json` mirror, and a hash-bound manifest sidecar.
- `:637` `def validate_staged_package(...)`.

Drivers:

- `tools/stage_large_map_import_package.py:121` calls
  `stage_large_map_package(...)`, `:143` calls `validate_staged_package(...)`,
  `:154` writes `<pkg>.stage_and_validate.json`.
- `tools/preflight_import_package.py:307`,
  `tools/revalidate_promoted_package.py:84`,
  `tools/rq3_batch9_stage_promote.py:137`.

**Minimal diff**: in `stage_large_map_import_package.py` after `:143`, add

```python
identity = resolve_package_identity(requested_package=result.package_name,
                                    import_root=args.import_root)
```

add `"package_identity": identity.to_dict()` to the `combined` summary at
`:154`, and exit non-zero on `PackageBindingError` (fail closed). Optionally
mirror the call inside `validate_staged_package` so every consumer inherits it.

### P2 — RQ3 cooked-arm identity is a bare string

File: `ultimate_pipeline/perception/rq3_capture_contract.py`

- `:602` `cooked_package_identity: Optional[str] = None`
- `:617-618` inserted raw into the identity dict.

Test passes a bare `"Grid0828"` (`ultimate_pipeline/tests/test_rq3_paired_capture_contract.py`).

**Minimal diff**: accept `PackageIdentity | dict | str`; when given an identity,
store `identity.to_dict()` under `cooked_package_identity` and keep the bare
name under a new `cooked_package_name` for backward compatibility; P1's driver
passes the resolved identity.

### P3 — registry read of a key that does not exist (dead-config sibling of NEW-291)

File: `ultimate_pipeline/perception/experiment_map_pair_authority.py`

- `:35-37` `GRID0828_*_SHA256 = "PLACEHOLDER_SET_FROM_REGISTRY"` (incl.
  `GRID0828_COOKED_PACKAGE_SHA256` at `:36`).
- `:49` `"cooked_package_sha256": entry.get("cooked_package_identity", "")`.

Verified: `ultimate_pipeline/carla_tools/map_registry.py` `PINNED_MAP_REGISTRY`
entries contain **no** `cooked_package_identity` key (nor
`manual_source_xodr_sha256` / `runtime_identity_sha256`), so `:49` always yields
`""` and the placeholders are never overwritten.

**Minimal diff**: this is a data change, not just code — populate the registry
entry from P1's `PackageIdentity.to_dict()` (`source_json_sha256`,
`import_manifest_sha256`) plus the known source-XODR sha, then read it at `:49`.

### P4 — runtime identity receipts record only the requested name

- `tools/live_map_identity.py:109` — `"requested_package": args.map` (name only,
  no resolution).
- `tools/world_settings_transaction.py:286` — literal `"requested_package": "Grid0828"`.

**Minimal diff**: after `load_world`, attach
`resolve_package_identity(...).to_dict()` (or P1's staged identity receipt) as
`"package_identity"` so runtime receipts bind to descriptor/manifest shas.

### P5 — material config binding has no call path

- `ultimate_pipeline/tiling/carla_0916_large_map_contract.py:170`
  `def resolve_material_config(identity)` — **zero callers** outside the
  contract module and its test (verified repo-wide).

RoadPainter decal binding is currently implicit in C++ `LoadAssetMaterials`
(`scripts/material_receipts.py` documents the commandlet invocation).

**Minimal diff**: pre-flight inside P1's driver —
`cfg = resolve_material_config(resolve_package_identity(...))`, fail on
`PackageBindingError` before any commandlet runs. No C++ change.

### P6 — TilesInfo (NEW-199): no Python consumer exists

Repo-wide: `parse_tilesinfo*` / `format_tilesinfo*` appear only in the contract
module and its tests; the only TilesInfo parsers are C++. There is no Python
call site to wire. When a Python consumer arrives (natural home:
`ultimate_pipeline/tiling/tile_metadata.py` or `tile_validator.py`), it should
consume the contract's parser. Deferred.

---

## D. Cost sketch (options, not a decision)

**Option "wire in" — smallest real cut (all in-repo):**

| Piece | Diff size | Notes |
| --- | --- | --- |
| C2 fail-closed raise | ~5-10 lines | must update 4 pinned tests at `tests/unit/test_carla_import_supervision.py:188/:196/:209/:225` |
| P1 identity at staging | ~10-20 lines | driver-level, fail-closed on `PackageBindingError` |
| P3 registry data | data + ~5 lines | fills the dead-config hole |
| P2/P4 receipt enrichment | ~15-30 lines | additive receipt fields; keep old keys |
| P5 material pre-flight | ~5 lines | no C++ change |
| C1 external Import.py | external-file ownership decision | delegate to `run_mandatory_process`, translate to `ChildProcessError` |
| P6 | nothing | no consumer exists |

**Option "defer"**: relabel both modules as reference/scaffolding in the gap
register's residual-risk text (the current GAP-038 recommendation), no code
change.

**Test-contract touch points if wiring**:
`tests/unit/test_carla_import_supervision.py:188/:196/:209/:225` (non-raising
receipt contract) and `tests/test_import_supervision.py:536-574`
(`Import.py` source assertions — already satisfied by delegation, not by
`Popen` removal).

---

*Generated by the GAP-038 wiring-points scout, 2026-10-08. Read-only: this file
is the sole artifact added.*
