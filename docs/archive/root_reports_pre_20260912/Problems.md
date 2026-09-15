# problems.md — OSM→OpenDRIVE→CARLA Repository Problem Register

**Audit target:** `ultimate_pipeline(3).zip` (uploaded editable-source baseline)  
**Audit date:** 2026-07-28  
**Purpose:** stable, source-grounded issue register for structural map quality, CARLA runtime, visual cooking, domain-gap analysis, perception, and training.

## Evidence boundary

This register is based on the uploaded baseline archive, not on a newer local or unpublished DeepSeek branch. A problem marked `VERIFIED_IN_UPLOADED_BASELINE` is confirmed in that archive. It may already have been changed elsewhere, but it must remain open until the current published branch is rechecked on the active call path and the required acceptance test passes.

Status meanings:

- **VERIFIED_IN_UPLOADED_BASELINE** — directly confirmed in editable source.
- **VERIFIED_BY_RELATED_SOURCE_AND_PRIOR_REPORT** — exact active source is incomplete in the archive, but related source and prior code-level evidence identify the defect.
- **SOURCE_MISSING_IN_UPLOADED_ARCHIVE** — required behavior exists only as bytecode or is absent, so it cannot be certified.
- **TEST_BLOCKER** — prevents clean verification.
- **ARCHITECTURE_GAP** — a required system capability or invariant is absent.
- **RUNTIME_DIAGNOSIS_REQUIRED** — plausible root causes are identified, but a controlled CARLA/Unreal experiment is required before selecting one.

## Overall conclusion

The baseline is an advanced research prototype, not a production map compiler. The most important failure pattern is **non-monotonic validity**: later stages can alter geometry, road length, elevation, lanes, LaneLinks, markings, topology, or tiles after earlier checks have passed. The correct solution is not more heuristic enrichment. It is immutable stage artifacts, explicit mutation ownership, candidate/rollback repair, cumulative gates, exact artifact identity, and separate structural, visual, sensor, and perception products.

## Index

- **Repository and orchestration:** 18 problems
- **XODR conversion and provenance:** 6 problems
- **Horizontal geometry:** 14 problems
- **Junctions and topology:** 9 problems
- **Elevation and 3D road surface:** 11 problems
- **Lanes and cross-sections:** 7 problems
- **LaneLinks:** 5 problems
- **Markings and regulatory semantics:** 6 problems
- **Objects and enrichment:** 4 problems
- **Tiling and map partitioning:** 7 problems
- **Quality gates:** 10 problems
- **CARLA server and runtime:** 19 problems
- **Domain-gap analysis:** 5 problems
- **GNN analysis:** 9 problems
- **RL fuzzer:** 1 problems
- **OSM2World and Blender:** 6 problems
- **Unreal/CARLA cooking:** 6 problems
- **Perception and sensors:** 20 problems
- **Training pipeline:** 8 problems
- **Deployment and release:** 7 problems

**Total problems:** 178

---

## PROB-001 — No single canonical execution path

- **Subsystem:** Repository and orchestration
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** run_pipeline.py, main_pipeline.py, entrypoints.py, cli.py, pipeline_stages/*, duplicate/legacy runners
- **Root cause:** The repository preserves monolithic, extracted, deprecated, and alternate entry paths with different imports and settings. run_pipeline.py catches any import exception and retries a development import path.
- **What it causes:** A fix can exist without being called; different commands can produce different XODR artifacts; reports can describe a different path than the user executed.
- **Required correction:** Define one production entry point, generate an active call graph, deprecate alternate fronts, and fail on import-path ambiguity instead of retrying broadly.
- **Acceptance verification:** Run every supported command on the same fixture and require identical stage graph, settings hash, artifact hashes, and implementation module identities.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-002 — Stage modules depend on runtime global injection

- **Subsystem:** Repository and orchestration
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline.py and pipeline_stages/*
- **Root cause:** Extracted stages obtain names and state from the monolith rather than explicit typed inputs.
- **What it causes:** Tests may pass with injected globals while standalone use fails; stage behavior depends on import order and mutable module state.
- **Required correction:** Replace global injection with immutable StageContext and typed StageInput/StageResult contracts.
- **Acceptance verification:** Import and execute every stage independently in a fresh process; reject undeclared globals and verify deterministic outputs.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-003 — Production and submission package roots can drift

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** root ultimate_pipeline plus submission/infrastructure/ultimate_pipeline and copied variants
- **Root cause:** Source was copied between roots; similar modules can diverge silently.
- **What it causes:** Audits and tests may inspect one implementation while runtime imports another.
- **Required correction:** Choose one authoritative editable package; archive other copies outside import/test paths; compare hashes before removal.
- **Acceptance verification:** Resolve every active module with importlib and require its path under the canonical root.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-004 — Important modules exist only as compiled bytecode

- **Subsystem:** Repository and orchestration
- **Severity:** Critical
- **Evidence status:** `SOURCE_MISSING_IN_UPLOADED_ARCHIVE`
- **Evidence:** 55 module basenames are represented only by .pyc; examples include junction connector, regulatory writers, map loader, thesis contract
- **Root cause:** The source package is incomplete or generated from another checkout.
- **What it causes:** Critical topology, enrichment, loading, and contract behavior cannot be audited, reproduced, maintained, or safely patched.
- **Required correction:** Recover exact matching .py source from Git history or authoritative build; reject releases with active .pyc-only modules.
- **Acceptance verification:** Delete caches in a clean clone and require all imports/tests to succeed from source alone.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-005 — Offline test collection is not clean

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `TEST_BLOCKER`
- **Evidence:** pytest collection: 396 tests, 3 errors; missing RigVerification and eager carla import
- **Root cause:** Runtime-only dependencies and incomplete sensor APIs are imported during collection.
- **What it causes:** Regression testing is incomplete; changes may be accepted without exercising active code.
- **Required correction:** Isolate CARLA imports behind runtime adapters, implement/remove obsolete API expectations, and make optional integration tests marker-controlled.
- **Acceptance verification:** python -m pytest --collect-only -q and non-CARLA suite must complete with zero collection errors.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-006 — Broad exception handling hides causal failures

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** AST scan found about 1458 broad Exception handlers, 25 bare excepts, and hundreds of silent pass/continue paths
- **Root cause:** Exceptions are used as feature control and compatibility handling instead of typed error boundaries.
- **What it causes:** A failed repair, validator, callback, or report can be presented as continued progress; partial artifacts survive.
- **Required correction:** Replace broad catches in release paths with typed exceptions and explicit PASS/FAIL/BLOCKED/NOT_APPLICABLE results; retain broad catches only at process boundaries with re-raise or failure state.
- **Acceptance verification:** Inject representative failures and require exact failure classification, no output promotion, and preserved traceback/log.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-007 — Pass-only and placeholder functions remain in active-adjacent packages

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** elevation_seam_fixer.fix_elevation_seams, visualization lane drawing, dummy evaluators, RL fuzzer apply_to_map
- **Root cause:** Interfaces were scaffolded without implementation and not reliably excluded from readiness claims.
- **What it causes:** A stage may appear available while doing nothing; reports can contain fabricated success.
- **Required correction:** Classify every placeholder as required, optional, abstract, debug, deprecated, or dead; implement required ones and make optional ones return NOT_APPLICABLE.
- **Acceptance verification:** Static scan plus tests must reject pass-only required functions and placeholder success strings.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-008 — Configuration is fragmented across settings, environment variables, wrappers, and defaults

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** config/settings.py, runtime modules, Osm2Odr wrappers, quality gate env flags
- **Root cause:** No schema enforces one immutable configuration; conflicting defaults are resolved implicitly.
- **What it causes:** Runs are not comparable and strict behavior can be accidentally disabled.
- **Required correction:** Create a versioned configuration schema and one frozen settings snapshot; prohibit unrecorded environment overrides in release profiles.
- **Acceptance verification:** Two runs with identical snapshot must have identical semantic hashes; changed env values must change the configuration hash and manifest.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-009 — Strict behavior is opt-in rather than release-default

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** UP_STRICT_QUALITY_GATES, THESIS_STRICT, tile allow-fail/skip flags
- **Root cause:** The same code path is used for exploratory and release runs without a mandatory release profile.
- **What it causes:** Critical failures can become warnings or skipped checks.
- **Required correction:** Define explicit profiles: DEVELOPMENT, STRUCTURAL_RELEASE, CARLA_RELEASE, VISUAL_RELEASE, PERCEPTION_RELEASE; release profiles are immutable and fail-closed.
- **Acceptance verification:** Attempt to disable a required gate under a release profile and require immediate configuration rejection.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-010 — Run manifest and settings hash can be best-effort

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline manifest and hashing helpers; hash may become ERROR
- **Root cause:** Evidence generation is not a hard prerequisite to stage execution.
- **What it causes:** Artifacts can exist without reliable provenance, tool versions, input hashes, or exact settings.
- **Required correction:** Make manifest creation atomic and mandatory before Stage 0; use SHA-256, not error sentinel strings; bind every result to parent and Git SHA.
- **Acceptance verification:** Corrupt/unreadable input or unwritable manifest directory must block the run before map mutation.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-011 — Old runs are archived before the new run is proven viable

- **Subsystem:** Repository and orchestration
- **Severity:** Medium
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline startup sequence
- **Root cause:** Lifecycle cleanup precedes environment and input validation.
- **What it causes:** A failed new run can make the previous working evidence less accessible and complicate comparison.
- **Required correction:** Create a new immutable run directory first; archive only after successful promotion and retain indexed history.
- **Acceptance verification:** Force a preflight failure and prove the prior accepted run remains untouched and indexed.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-012 — Database schema is treated as mandatory for offline map generation

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline startup wiring
- **Root cause:** Operational metadata storage is coupled to the map compiler.
- **What it causes:** A database outage can block deterministic XODR generation; database side effects reduce reproducibility.
- **Required correction:** Make persistence an adapter: local immutable manifest is authoritative; database export is optional after stage completion.
- **Acceptance verification:** Run the complete offline structural pipeline with database disabled and compare artifacts to database-enabled execution.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-013 — Use of Python assert for release invariants

- **Subsystem:** Repository and orchestration
- **Severity:** Medium
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** tile metadata and other paths
- **Root cause:** Assertions disappear under python -O.
- **What it causes:** A release run can bypass checks depending on interpreter flags.
- **Required correction:** Replace assertions with explicit typed gate failures.
- **Acceptance verification:** Run tests with normal Python and -O and require identical failure behavior.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-014 — No enforced stage mutation contract

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** All XODR stages
- **Root cause:** Stage ownership is documented informally but not verified by semantic XML diff.
- **What it causes:** A downstream stage can change planView, length, elevation, lanes, signals, or objects outside its responsibility.
- **Required correction:** Define allowed XPath/domain mutations per stage and compare parent/candidate semantic trees before promotion.
- **Acceptance verification:** Deliberately mutate a forbidden domain in each stage fixture and require rejection.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-015 — No monotonic validity enforcement

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Stage-specific gates and final reporting
- **Root cause:** Each stage validates only selected concerns; earlier invariants are not systematically rerun.
- **What it causes:** Later enrichment, integrity, tiling, or repair can invalidate previously passed geometry/topology/elevation checks.
- **Required correction:** After every mutation stage, rerun all prior required gates and compare protected metrics to parent budgets.
- **Acceptance verification:** Inject a late geometry defect and require the downstream stage to fail even if its own local checks pass.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-016 — Validators and repairers are not separated

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** quality, tiling, elevation continuity and integrity paths
- **Root cause:** Some gates mutate the candidate or trigger repair in response to a failure.
- **What it causes:** The original defect and causality are lost; a validator can produce an unreviewed new artifact.
- **Required correction:** Use immutable parent → repair candidate → independent read-only validator → atomic promotion.
- **Acceptance verification:** Hash validator input before/after and require exact identity.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-017 — Class-global quality failure state can leak between runs

- **Subsystem:** Repository and orchestration
- **Severity:** Medium
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** quality_gate_manager._failures_by_name
- **Root cause:** Mutable class state is not reset per run.
- **What it causes:** Failures or passes can contaminate subsequent runs/tests and make reports nondeterministic.
- **Required correction:** Move state into per-run GateContext; forbid mutable class/global gate state.
- **Acceptance verification:** Execute two opposite fixtures in both orders and require identical independent reports.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-018 — No authoritative artifact promotion transaction

- **Subsystem:** Repository and orchestration
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Multiple successive final/intermediate paths
- **Root cause:** Stages overwrite or reassign authoritative file paths without one quarantine/promotion protocol.
- **What it causes:** A partially repaired candidate can replace the accepted map before all gates pass.
- **Required correction:** Write candidates to quarantine, require complete gate matrix, then atomically promote by hash/reference update.
- **Acceptance verification:** Interrupt each stage and prove accepted artifact and manifest remain unchanged.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-019 — Osm2Odr settings differ by entry point

- **Subsystem:** XODR conversion and provenance
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** osm/osm_to_xodr.py, osm_to_xodr_wrapper.py, settings
- **Root cause:** Lane width, traffic-light generation, road filters, projection, and offsets are not resolved through one authority.
- **What it causes:** Different commands generate structurally different maps from the same OSM input.
- **Required correction:** Create one ConverterProfile object recording all settings, source hash, converter/CARLA version, and output provenance.
- **Acceptance verification:** Run all entry points on a fixture and require identical XODR semantic hash.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-020 — Unrealistic 6.0 m default lane width exists in a conversion path

- **Subsystem:** XODR conversion and provenance
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** osm_to_xodr_wrapper.py
- **Root cause:** A wrapper default conflicts with 3.5/4.0 m elsewhere.
- **What it causes:** Roads and junctions can become excessively wide, increasing overlaps and domain-gap measurements.
- **Required correction:** Remove independent defaults; use road-class/evidence-aware width policy from the canonical profile.
- **Acceptance verification:** Fixture road widths must match profile and no entry point may override silently.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-021 — Native traffic-light generation is disabled in some conversion paths

- **Subsystem:** XODR conversion and provenance
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** Osm2Odr wrapper/default settings
- **Root cause:** Traffic semantics are later approximated through static object inference.
- **What it causes:** Functional signals/controllers are lost and visual objects can be mistaken for traffic control.
- **Required correction:** Enable/preserve converter-native signals where supported and record policy; never replace with object-count heuristics.
- **Acceptance verification:** Known signalized OSM fixture must produce valid signal/reference/controller relationships or explicit unmapped evidence.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-022 — OSM way IDs are treated as XODR road IDs

- **Subsystem:** XODR conversion and provenance
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** enrichment and provenance assumptions
- **Root cause:** One OSM way can split into multiple roads; connectors use synthetic IDs.
- **What it causes:** Speed, lanes, sidewalks, signs, and metadata can be applied to the wrong road or silently not applied.
- **Required correction:** Create bidirectional OSM↔XODR provenance with VERIFIED/AMBIGUOUS/UNMAPPED/SYNTHETIC states.
- **Acceptance verification:** Use split-way and connector fixtures; require all enrichments to consume provenance rather than ID equality.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-023 — OSM verification failure is warning-only

- **Subsystem:** XODR conversion and provenance
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline input flow
- **Root cause:** Input integrity is not a prerequisite for conversion.
- **What it causes:** Pipeline may generate and analyze a map from missing, stale, malformed, or wrong-bounds OSM.
- **Required correction:** Make OSM hash, bounds, XML validity, timestamp/license metadata, and expected study area mandatory.
- **Acceptance verification:** Wrong-bounds or changed-hash OSM must block before conversion.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-024 — Coordinate and vertical datum contracts are incomplete

- **Subsystem:** XODR conversion and provenance
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** OSM, DEM, XODR georeference, OSM2World/Blender
- **Root cause:** Horizontal CRS, local origin, axis convention, units, vertical datum, and transform chain are not governed end-to-end.
- **What it causes:** DEM, objects, visual meshes, and sensors can be offset, mirrored, scaled, or vertically shifted.
- **Required correction:** Create one coordinate contract with round-trip tests and transform provenance for every external asset.
- **Acceptance verification:** Use known control points and require horizontal/vertical residual within project thresholds.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-025 — Heading-only smoothing changes curve geometry inconsistently

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/planview_smoother.py smooth_heading_jumps
- **Root cause:** Segment headings are averaged without reconstructing the primitive or preserving end pose.
- **What it causes:** Endpoint displacement, seams, detached slabs, curvature discontinuities, and cumulative drift.
- **Required correction:** Disable in release; replace only with endpoint/tangent/curvature-constrained candidate reconstruction.
- **Acceptance verification:** A/B fixture and full map must show no endpoint/tangent/length regression; candidate accepted only if all metrics improve.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-026 — Short-segment merging ignores primitive type

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/planview_smoother.py merge_short_segments
- **Root cause:** Line, arc, spiral, and polynomial segments can be merged through length extension without compatible parameters.
- **What it causes:** Curves become invalid approximations, road length/end pose drift, and mesh discontinuities appear.
- **Required correction:** Disable generic merging; implement type-specific refit or quarantine micro-segments.
- **Acceptance verification:** Test every primitive combination and require endpoint, tangent, curvature, and sampled Hausdorff tolerances.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-027 — Small-geometry merge is unproven and can alter end pose

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/planview_smoother.py merge_small_geometries
- **Root cause:** Same-type is treated as sufficient even when curvature or polynomial coefficients differ.
- **What it causes:** Road geometry may silently change while counts improve.
- **Required correction:** Keep disabled until isolated A/B evidence proves benefit; use constrained refitting and mutation budget.
- **Acceptance verification:** Raw, operation-only, and safe-pipeline comparison on fixtures and full map.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-028 — ParamPoly3 is not recognized by geometry type detection

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/planview_smoother.py _geom_type
- **Root cause:** Unknown primitive falls through to line behavior.
- **What it causes:** Endpoints, sampling, bounds, smoothing, and connectors are wrong for parametric cubic roads.
- **Required correction:** Implement one authoritative evaluator for Line/Arc/Spiral/Poly3/ParamPoly3 and fail on unsupported forms.
- **Acceptance verification:** Use analytical fixtures with endpoint/tangent/curvature checks.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-029 — Legacy geometry-start recomputation is not primitive-aware

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** PlanViewSmoother.recompute_geometry_starts and active Stage 6 calls in uploaded baseline
- **Root cause:** Rechaining uses straight-line assumptions and/or wrong chaining semantics.
- **What it causes:** Curved downstream geometries are translated; visual slabs detach and bias becomes new XODR truth.
- **Required correction:** Remove legacy function from active path; delegate to verified primitive-aware evaluator only after tests.
- **Acceptance verification:** Curved multi-primitive fixture must remain continuous and sampled shape invariant.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-030 — Curvature clamping changes arc geometry without preserving boundary conditions

- **Subsystem:** Horizontal geometry
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** planview_smoother clamp_curvature
- **Root cause:** Only curvature parameter is changed.
- **What it causes:** End position and heading move; downstream records and connections become stale.
- **Required correction:** Treat excessive curvature as defect diagnosis; refit complete candidate with fixed end poses or reject.
- **Acceptance verification:** Clamp/refit fixture must preserve start/end position and tangent within strict tolerance.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-031 — Recomputing road length does not remap longitudinal records

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** planview_smoother and related repair paths
- **Root cause:** road.length and geometry s are modified independently of laneSection, laneOffset, elevation, signal, object, and profile s.
- **What it causes:** Records become out-of-range or refer to the wrong physical location.
- **Required correction:** Make length change an atomic road transformation with explicit dependent-record policy or prohibit it after semantic stages.
- **Acceptance verification:** Every road must satisfy sum geometry length and all longitudinal records within range; semantic landmarks retain projected position.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-032 — geometry_math module is incomplete and unsafe if activated

- **Subsystem:** Horizontal geometry
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/geometry_math.py
- **Root cause:** Missing imports and only line/arc support; curved forms fall back.
- **What it causes:** Future wiring can introduce runtime errors or silent geometric corruption.
- **Required correction:** Either implement and test it fully as the sole evaluator or remove/deprecate it to avoid split authority.
- **Acceptance verification:** Static import test and full primitive conformance suite.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-033 — Mesh continuity repair mutates reference lines through heuristic interpolation

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/mesh_continuity_repairer.py; default moderate mode
- **Root cause:** Position interpolation and heading averaging are performed without reconstructing primitive mathematics.
- **What it causes:** The repair intended to close a gap can create kinked/warped roads and stale profiles.
- **Required correction:** Set release mode read-only; move any repair to candidate fitter with G1/G2 constraints.
- **Acceptance verification:** Input/output semantic diff, endpoint/tangent/curvature metrics, and no protected-domain changes.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-034 — Mesh continuity endpoint evaluator treats spiral/poly geometry as lines

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** mesh_continuity_repairer endpoint logic
- **Root cause:** Only arc is specially evaluated.
- **What it causes:** Seam detection and repair anchors are wrong on non-line/non-arc roads.
- **Required correction:** Use the authoritative evaluator everywhere.
- **Acceptance verification:** Cross-module property test: all endpoint consumers return identical values for every primitive.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-035 — Heading-jump metric compares incompatible headings

- **Subsystem:** Horizontal geometry
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** mesh_continuity_repairer
- **Root cause:** Next start heading is compared with previous start heading instead of previous end tangent.
- **What it causes:** False positives/negatives trigger unnecessary repair or miss true kinks.
- **Required correction:** Compute end tangent from the primitive and compare to next start tangent.
- **Acceptance verification:** Analytical line/arc/spiral cases with known tangent continuity/discontinuity.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-036 — Lane sections are redistributed evenly during repair

- **Subsystem:** Horizontal geometry
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** mesh_continuity_repairer realign_lane_sections
- **Root cause:** Original section boundaries are discarded and replaced by equal spacing.
- **What it causes:** Lane merges, widths, links, markings, and turn-lane semantics move to wrong locations.
- **Required correction:** Never infer section positions from count; preserve or reproject boundaries using explicit geometry mapping.
- **Acceptance verification:** Fixture with irregular sections must retain physical boundary locations after allowed road changes.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-037 — No design-speed-based curvature and jerk policy

- **Subsystem:** Horizontal geometry
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Geometry quality gates
- **Root cause:** Global or ad hoc limits ignore road class and intended maneuver speed.
- **What it causes:** Natural through roads can be over-smoothed while junction turns remain harsh; vehicle dynamics are inconsistent.
- **Required correction:** Derive curvature and curvature-rate limits from documented design speed and lateral acceleration/jerk budgets.
- **Acceptance verification:** Report inferred speed/confidence and reject candidates exceeding class-specific limits.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-038 — No RoadRunner-equivalent clothoid/segmented-road authoring layer

- **Subsystem:** Horizontal geometry
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Pipeline repair tools versus RoadRunner addClothoidFitRoad/addSpiral/addParametricCubic
- **Root cause:** The repository diagnoses and heuristically edits curves but lacks a constrained road-design representation.
- **What it causes:** Hard curves, abrupt curvature transitions, and connector kinks are difficult to repair safely.
- **Required correction:** Add a candidate road authoring API supporting line, arc, clothoid, and normalized parametric cubic with fixed boundary poses.
- **Acceptance verification:** Compare candidate against original using sampled distance, G1/G2, length, self-intersection, and lane-surface metrics.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-039 — Topology repair deletes invalid links and empty junctions rather than repairing/quarantining them

- **Subsystem:** Junctions and topology
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** topology/topology_repair.py
- **Root cause:** Deletion is used to make references valid without preserving intended connectivity.
- **What it causes:** Road graph and legal routes can be silently lost while validators report fewer invalid references.
- **Required correction:** Build a topology candidate, preserve original, repair only from unambiguous evidence, and quarantine unresolved structures.
- **Acceptance verification:** Road/junction counts and route reachability must not regress without approved evidence.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-040 — Active/important connector rebuild source is missing

- **Subsystem:** Junctions and topology
- **Severity:** Critical
- **Evidence status:** `SOURCE_MISSING_IN_UPLOADED_ARCHIVE`
- **Evidence:** junction_connector_rebuild/snap and quality connector modules present only as .pyc
- **Root cause:** The exact implementation responsible for critical geometry cannot be reviewed.
- **What it causes:** Connector quality and safety cannot be certified.
- **Required correction:** Recover exact source or disable the feature; never rely on unreviewable bytecode in release.
- **Acceptance verification:** Clean source-only environment must execute connector tests and produce identical hashes.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-041 — Connector reconstruction can use a straight-chord fallback

- **Subsystem:** Junctions and topology
- **Severity:** Critical
- **Evidence status:** `VERIFIED_BY_RELATED_SOURCE_AND_PRIOR_REPORT`
- **Evidence:** connector rebuild paths documented in audit
- **Root cause:** Failed curved fitting becomes a direct line without both tangent constraints.
- **What it causes:** Turns cut across junctions/roundabout islands, produce holes and overlaps, and destabilize vehicles.
- **Required correction:** Remove unconditional chord fallback; allow line only when both endpoint tangents and lane-center continuity prove a straight movement.
- **Acceptance verification:** Turning fixtures must contain zero chord fallbacks and pass no-unrelated-road-crossing tests.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-042 — Connector fit validates endpoint position but not outgoing tangent

- **Subsystem:** Junctions and topology
- **Severity:** Critical
- **Evidence status:** `VERIFIED_BY_RELATED_SOURCE_AND_PRIOR_REPORT`
- **Evidence:** connector rebuild behavior
- **Root cause:** Meeting the end coordinate is treated as sufficient.
- **What it causes:** Connector can arrive facing the wrong direction, causing G1 discontinuity and lane mismatch.
- **Required correction:** Require start/end position, start/end tangent, curvature limits, lane-edge alignment, and route direction.
- **Acceptance verification:** Four contact-point combination fixtures and real junction route matrix.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-043 — Connector selection falls back to nearest endpoints under ambiguity

- **Subsystem:** Junctions and topology
- **Severity:** High
- **Evidence status:** `VERIFIED_BY_RELATED_SOURCE_AND_PRIOR_REPORT`
- **Evidence:** connector selection heuristics
- **Root cause:** Proximity substitutes for topology/provenance.
- **What it causes:** Wrong roads can be joined, especially at stacked crossings, dense junctions, or roundabouts.
- **Required correction:** Require reciprocal road/junction links and layer-compatible evidence; unresolved ambiguity must remain blocked.
- **Acceptance verification:** Stacked-road and close-parallel-road fixtures must never connect by distance alone.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-044 — Connector rollback is not an atomic full-road rollback

- **Subsystem:** Junctions and topology
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** repair transaction design
- **Root cause:** Only planView/length may be restored while lanes, elevation, signals, objects, and links were changed.
- **What it causes:** A rejected repair can leave a hybrid corrupt road.
- **Required correction:** Clone the complete affected subgraph and commit candidate atomically only after all dependent gates pass.
- **Acceptance verification:** Force late validation failure and compare complete semantic subtree to original hash.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-045 — Roundabout reconstruction is heuristic and enabled by default

- **Subsystem:** Junctions and topology
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** topology/roundabout_reconstructor.py and settings
- **Root cause:** Cluster/center/radius inference can rewrite valid native networks without full directed-route proof.
- **What it causes:** Duplicate rings, central chords, wrong direction, lost entries/exits, and invalid priority behavior.
- **Required correction:** Disable by default; preserve native rings; only accept candidate with closed directed cycle and complete entry/exit route matrix.
- **Acceptance verification:** Each roundabout: one ring, 360° route, all intended routes, zero central chords, continuous lane edges.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-046 — Duplicate roundabout implementations can drift

- **Subsystem:** Junctions and topology
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** roundabout_reconstructor.py and roundabout_rebuilder.py
- **Root cause:** Two algorithms share responsibility without one authority.
- **What it causes:** Different execution paths can rebuild the same junction differently.
- **Required correction:** Select one candidate API and deprecate the other after fixture comparison.
- **Acceptance verification:** Call-graph audit proves only one active implementation.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-047 — No RoadRunner-equivalent maneuver graph

- **Subsystem:** Junctions and topology
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No explicit Maneuver Tool/Rebuild Maneuver Roads model
- **Root cause:** Road-level and LaneLink heuristics are not represented as legal incoming-lane→outgoing-lane movements.
- **What it causes:** Illegal turns can exist; legal movements can be absent; traffic control cannot bind correctly.
- **Required correction:** Create explicit maneuver entities with provenance, direction, conflict group, signal/priority association, and route tests.
- **Acceptance verification:** Every junction movement is enumerated and route-valid; unexplained movement changes fail.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-048 — Elevation is fitted before final horizontal geometry

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline stage order
- **Root cause:** DEM sampling occurs before Stage 6 planView and connector mutations.
- **What it causes:** Elevation positions describe an obsolete curve; bridges, grades, and road surfaces can detach or fold.
- **Required correction:** Move elevation after final horizontal geometry and a cryptographic freeze.
- **Acceptance verification:** Any later horizontal mutation must invalidate elevation and all downstream evidence.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-049 — ElevationImporter samples only the first road point

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** enrichment/elevation_importer.py
- **Root cause:** One DEM query is used to create one constant profile for the entire road.
- **What it causes:** Roads are flattened; slopes, vertical curves, and terrain following are lost.
- **Required correction:** Sample the complete final reference line at controlled spacing and fit constrained piecewise profiles.
- **Acceptance verification:** Known synthetic grade/crest/sag fixtures and full-map coverage metrics.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-050 — Elevation import deletes native profiles

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** ElevationImporter
- **Root cause:** Existing elevation records are removed before candidate quality is known.
- **What it causes:** Valid converter/manual vertical geometry is irreversibly lost.
- **Required correction:** Preserve original, generate candidate separately, compare, and replace only when evidence improves.
- **Acceptance verification:** Candidate failure leaves original elevation subtree byte/semantically unchanged.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-051 — DEM errors, nodata, and out-of-bounds silently become 0.0

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** ElevationImporter
- **Root cause:** Failure fallback is indistinguishable from valid sea-level elevation.
- **What it causes:** Roads can plunge to zero, create cliffs, float objects, or collapse stacked roads.
- **Required correction:** Return explicit missing-data state; release requires complete approved coverage or a documented source-specific fallback.
- **Acceptance verification:** Inject nodata/out-of-bounds and require BLOCKED, not a numeric profile.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-052 — DEM CRS is assumed to match XODR coordinates

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** ElevationImporter sampling
- **Root cause:** No governed coordinate transformation is applied.
- **What it causes:** Samples can come from wrong locations or outside raster.
- **Required correction:** Use the coordinate contract and pyproj/raster transform with control-point verification.
- **Acceptance verification:** Known world/XODR/DEM points round-trip within tolerance.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-053 — ElevationSmoother resets absolute elevations above 20 m to zero

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/elevation_smoother.py
- **Root cause:** A magnitude heuristic assumes local relative heights without verifying datum/origin.
- **What it causes:** Real Ingolstadt absolute elevation can be erased, flattening or dropping the map.
- **Required correction:** Remove magnitude reset; validate against declared vertical datum and plausible local range.
- **Acceptance verification:** Absolute and local-coordinate fixtures must retain valid height and reject only nonfinite/outlier data with evidence.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-054 — ElevationSmoother zeroes b, c, and d coefficients

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** geometry/elevation_smoother.py
- **Root cause:** All grade and vertical-curvature terms are removed.
- **What it causes:** Roads become piecewise flat and can form grade discontinuities at boundaries.
- **Required correction:** Fit constrained cubic profiles preserving C0 height and C1 grade, optionally C2 smoothness.
- **Acceptance verification:** Synthetic vertical-curve tests and connected-road seam metrics.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-055 — Elevation seam fixer is a pass-only stub

- **Subsystem:** Elevation and 3D road surface
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** elevation/elevation_seam_fixer.py
- **Root cause:** A named repair stage has no behavior.
- **What it causes:** Vertical discontinuities remain while architecture implies they are addressed.
- **Required correction:** Implement as candidate fitting with read-only validator, or remove it from active/release claims.
- **Acceptance verification:** Fixture with known seam is repaired within grade/height limits and remains idempotent.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-056 — Bridge, tunnel, layer, and stacked-road constraints are not first-class

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** DEM/elevation and topology pipeline
- **Root cause:** All roads can be forced toward terrain without vertical semantic constraints.
- **What it causes:** Bridges collapse, underpasses rise, and intersections connect visually/physically at wrong Z.
- **Required correction:** Use OSM bridge/tunnel/layer plus reference evidence to create vertical constraint classes.
- **Acceptance verification:** Stacked-crossing fixture has correct separation and no accidental junction/collision.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-057 — Superelevation, crossfall, and lateral height are not governed

- **Subsystem:** Elevation and 3D road surface
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No RoadRunner-equivalent addSuperElevation/addLateralHeight layer
- **Root cause:** Only centerline elevation is considered.
- **What it causes:** Lane edges, shoulders, sidewalks, and junction surfaces can have walls, floating edges, or unrealistic banking.
- **Required correction:** Add bounded lateral-profile authoring after vertical centerline fit and before final surface closure.
- **Acceptance verification:** 3D lane-edge continuity, crossfall limits, and vehicle roll stability tests.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-058 — No first-class drivable-surface model

- **Subsystem:** Elevation and 3D road surface
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No complete lane polygon/junction-surface stage
- **Root cause:** Reference-line and XML checks do not prove the generated road surface is closed.
- **What it causes:** Holes, triangular slivers, overlaps, and detached slabs can reach CARLA.
- **Required correction:** Generate 2D/3D lane edges, lane polygons, and junction movement surfaces; classify holes by causal layer.
- **Acceptance verification:** Zero lane-center-intersecting holes, zero detached slabs, zero unexplained same-level overlaps.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-059 — LaneGenerator fabricates symmetric two-way lanes

- **Subsystem:** Lanes and cross-sections
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** enrichment/lane_generator.py
- **Root cause:** Absence of driving lanes is treated as evidence for ±1 lanes.
- **What it causes:** One-way, path, connector, or uncertain roads become false two-way roads.
- **Required correction:** Disable release synthesis without provenance; use road class, oneway, lane count, direction, and confidence.
- **Acceptance verification:** OSM fixtures for one-way, footway, cycleway, service road, and unknown road.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-060 — Connector center lane is created as width-bearing driving lane

- **Subsystem:** Lanes and cross-sections
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** LaneGenerator connector path
- **Root cause:** Lane 0 is used as a normal driving lane.
- **What it causes:** Invalid OpenDRIVE cross-section and incorrect routing/mesh generation.
- **Required correction:** Center lane remains type none with no width; connector driving lanes use proper signed IDs and movement evidence.
- **Acceptance verification:** Strict lane schema and CARLA waypoint generation fixture.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-061 — Normal center lane receives a width element

- **Subsystem:** Lanes and cross-sections
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** LaneGenerator
- **Root cause:** Center lane is assigned width 0.20 m.
- **What it causes:** Cross-section semantics are invalid and can shift lane boundaries.
- **Required correction:** Remove width from lane 0.
- **Acceptance verification:** Gate rejects any center-lane width element.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-062 — New laneSection s=0 can be appended beside existing nonempty sections

- **Subsystem:** Lanes and cross-sections
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** LaneGenerator ensure_lanes
- **Root cause:** Only some empty sections are handled; existing content is not normalized before addition.
- **What it causes:** Overlapping duplicate lane sections create undefined lane geometry.
- **Required correction:** Preserve valid sections; create a candidate only when lane model is absent and prove uniqueness/order.
- **Acceptance verification:** Exactly one section start at each s, first at 0, strict ordering.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-063 — Fixed 3.5 m widths replace uncertainty

- **Subsystem:** Lanes and cross-sections
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** LaneGenerator and related enrichment
- **Root cause:** Class/evidence-specific width is not used.
- **What it causes:** Domain gap and visual geometry are biased; narrow/urban/connector lanes become unrealistic.
- **Required correction:** Use source width/lane evidence or bounded class defaults with confidence, never silent certainty.
- **Acceptance verification:** Report source and confidence for every generated width; compare lane-edge residual to imagery/reference where available.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-064 — Sidewalks are added broadly from lane count

- **Subsystem:** Lanes and cross-sections
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** enrichment/sidewalk_builder.py
- **Root cause:** Roads with at least two lanes get 2 m sidewalks on both sides without reliable OSM evidence.
- **What it causes:** False sidewalks alter road width, collisions, semantics, and perception labels.
- **Required correction:** Ground sidewalks in OSM tags/imagery/manual source; scenario-only additions remain separate.
- **Acceptance verification:** Every production sidewalk has provenance; zero sidewalks on explicitly absent/unsupported classes.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-065 — No lane taper/form/carve authoring

- **Subsystem:** Lanes and cross-sections
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No RoadRunner-equivalent Lane Width/Form/Carve tools
- **Root cause:** Lane appearance/disappearance, turn pockets, merges, and splits are represented weakly or abruptly.
- **What it causes:** Lane-edge kinks and junction holes occur even if reference line is smooth.
- **Required correction:** Add cubic width profiles and explicit lane transition objects with boundary constraints.
- **Acceptance verification:** 3D inner/outer lane-edge G0/G1 checks at every section transition.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-066 — Native LaneLinks are deleted before replacement validation

- **Subsystem:** LaneLinks
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** lanes/lanelink_builder.py
- **Root cause:** Regeneration clears all laneLinks first.
- **What it causes:** A failed or partial heuristic can erase valid junction connectivity.
- **Required correction:** Build replacement in an isolated candidate and atomically swap only after route and geometry gates pass.
- **Acceptance verification:** Forced failure must preserve original LaneLinks exactly.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-067 — Incoming road contact is hard-coded to the road end

- **Subsystem:** LaneLinks
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** lanelink_builder get_edge_section(incoming, at_start=False)
- **Root cause:** All junction contact configurations are not handled.
- **What it causes:** Wrong lane section is matched for start-contact roads.
- **Required correction:** Resolve contact from road links/junction connection for both roads.
- **Acceptance verification:** Four start/end combinations with forward/reversed roads.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-068 — Lane matching ignores contact orientation and travel direction

- **Subsystem:** LaneLinks
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** lanelink_builder match_by_direction
- **Root cause:** Positive lanes map to positive and negative to negative regardless of contact point.
- **What it causes:** LaneLinks can reverse or cross lanes and route against traffic.
- **Required correction:** Transform lane orientation at contact poses and match lane-center geometry plus movement direction.
- **Acceptance verification:** Directionally varied junction fixtures and CARLA waypoint traversal.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-069 — Regeneration can produce zero links after deleting valid links

- **Subsystem:** LaneLinks
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** lanelink_builder control flow
- **Root cause:** Missing widths/sections abort matching after destructive clear.
- **What it causes:** Junction becomes disconnected without an exception.
- **Required correction:** Prevalidate all required inputs and candidate count before any replacement.
- **Acceptance verification:** Zero-candidate replacement is rejected and original remains.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-070 — LaneLink quality lacks route-level acceptance

- **Subsystem:** LaneLinks
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Current target-exists checks
- **Root cause:** Referential validity does not prove a legal drivable maneuver.
- **What it causes:** Links may exist but be geometrically impossible or directionally wrong.
- **Required correction:** Require lane-center endpoint/tangent/width continuity and route graph traversal.
- **Acceptance verification:** Every intended lane movement traversable; no unintended movement.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-071 — Basic marking generation overwrites converter/native markings

- **Subsystem:** Markings and regulatory semantics
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** lanes/markings_builder.py and Stage 8
- **Root cause:** Existing roadMark elements are removed/replaced by generic rules.
- **What it causes:** Valid country/context-specific semantics are lost.
- **Required correction:** Preserve native markings; fill only verified missing spans through a candidate layer.
- **Acceptance verification:** Native-marking fixture remains semantically identical after enrichment.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-072 — Hard-coded yellow center markings are not grounded for German context

- **Subsystem:** Markings and regulatory semantics
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** markings_builder
- **Root cause:** Generic road convention is applied regardless of jurisdiction or source.
- **What it causes:** Visual and semantic domain gap is increased.
- **Required correction:** Implement a Germany-specific policy tied to road/lane context and evidence; unknown remains unknown.
- **Acceptance verification:** German fixture and manual review/semantic inventory.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-073 — Traffic lights are created as static objects

- **Subsystem:** Markings and regulatory semantics
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** enrichment/traffic_light_infer.py
- **Root cause:** Junction complexity triggers object insertion rather than OpenDRIVE signal/reference/controller creation.
- **What it causes:** Lights may look present but do not control CARLA traffic or lanes.
- **Required correction:** Create functional signals/controllers from grounded OSM or manual evidence; visual assets are separate.
- **Acceptance verification:** CARLA traffic-light actor resolves OpenDRIVE ID, affected lanes, trigger, group, and red-light behavior.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-074 — Traffic-light inference duplicates by junction connection

- **Subsystem:** Markings and regulatory semantics
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** traffic_light_infer
- **Root cause:** Each incoming connection can add objects without stable unique control model.
- **What it causes:** Duplicate lights, contradictory placement, inflated readiness counts.
- **Required correction:** Build one normalized control graph and deduplicate by controlled approach/movement.
- **Acceptance verification:** Unique IDs and expected count per junction; no duplicate transform/control target.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-075 — Signal lane validation is globally scoped

- **Subsystem:** Markings and regulatory semantics
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** traffic_light validator behavior
- **Root cause:** Lane IDs are checked without road context.
- **What it causes:** Lane -1 on another road can falsely validate an invalid signal binding.
- **Required correction:** Validate road/section/lane tuple at signal s and movement context.
- **Acceptance verification:** Cross-road repeated lane-ID fixture must catch wrong binding.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-076 — No complete sign projection and asset mapping contract

- **Subsystem:** Markings and regulatory semantics
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** sign/object enrichment and missing regulatory writer source
- **Root cause:** Signs require unique road s/t, heading, lane validity, type/subtype/country/value, and asset mapping.
- **What it causes:** Signs can be misplaced, generic, or nonfunctional.
- **Required correction:** Create grounded regulatory inventory and exact geometric projection with ambiguity handling.
- **Acceptance verification:** Each sign has source, residual, orientation, lanes, and CARLA semantic/runtime verification.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-077 — Object projection uses geometry-start centroid and s=0,t=0 fallback

- **Subsystem:** Objects and enrichment
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** enrichment/object_injector.py
- **Root cause:** Nearest-road approximation is not projection onto the full reference line.
- **What it causes:** Buildings/objects can be attached to wrong road/position or silently concentrated at road start.
- **Required correction:** Use authoritative curve projection, road-relative frame, and ambiguity threshold; reject unresolved.
- **Acceptance verification:** Synthetic curved-road projection fixture and residual threshold.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-078 — Building/global geometry is mixed with road-relative object semantics

- **Subsystem:** Objects and enrichment
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** object injector
- **Root cause:** World-coordinate outlines are inserted into an XODR road object context without a verified transform contract.
- **What it causes:** Visual geometry can be offset/mirrored and objects cannot be consistently reconstructed.
- **Required correction:** Store global assets in a separate semantic visual manifest; use XODR objects only when road-relative representation is correct.
- **Acceptance verification:** Round-trip world↔road transform and mesh alignment tests.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-079 — Synthetic realism features can contaminate map truth

- **Subsystem:** Objects and enrichment
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** benches, lamps, bins, guardrails, realism modules/settings
- **Root cause:** Minimum-count or rule-based additions are not separated from grounded data.
- **What it causes:** Perception evaluation measures fabricated decoration as if it represented Ingolstadt.
- **Required correction:** Separate GROUNDED_MAP, SCENARIO_AUGMENTATION, and DEBUG_ONLY asset layers and reports.
- **Acceptance verification:** Production manifest contains zero synthetic assets; scenario runs explicitly list them.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-080 — Regulatory and OSM metadata writer sources are missing

- **Subsystem:** Objects and enrichment
- **Severity:** High
- **Evidence status:** `SOURCE_MISSING_IN_UPLOADED_ARCHIVE`
- **Evidence:** osm_meta_index, regulatory_sign_writer, speed_limit_writer, turn_lanes_writer .pyc-only
- **Root cause:** Critical enrichment claims cannot be audited.
- **What it causes:** Signals, speeds, and turn lanes may be inactive, stale, or unsafe.
- **Required correction:** Recover source and build provenance/fixture tests, or disable corresponding claims.
- **Acceptance verification:** Clean source-only run and exact mapping report.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-081 — Road tile bounds inspect geometry start points only

- **Subsystem:** Tiling and map partitioning
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** tiling/tile_extractor.py _road_bounds
- **Root cause:** Curve extrema, lane width, objects, and junction surfaces are omitted.
- **What it causes:** Curved roads can be excluded from tiles or clipped at boundaries.
- **Required correction:** Compute conservative exact/sampled bounds for all primitives plus lateral envelope and dependencies.
- **Acceptance verification:** Arc/spiral/ParamPoly3 extrema fixtures and no source-road loss.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-082 — Tile dependency closure is incomplete

- **Subsystem:** Tiling and map partitioning
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** tile_extractor road selection/link dropping
- **Root cause:** Buffered road bounds do not guarantee full junction, connector, signal, object, and lane context.
- **What it causes:** Standalone tiles lose semantics or routes at borders.
- **Required correction:** Build dependency graph and include complete junction/movement/control context or mark observational tiles non-standalone.
- **Acceptance verification:** Tile contains all referenced IDs and representative routes cross boundaries.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-083 — Lane successor/predecessor leakage check expects a road attribute that OpenDRIVE lane links do not carry

- **Subsystem:** Tiling and map partitioning
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** tile_extractor lane leakage helpers
- **Root cause:** The checker misinterprets lane link schema.
- **What it causes:** Valid lane links can be classified as outside and removed.
- **Required correction:** Resolve lane links through road/junction topology, not nonexistent attributes.
- **Acceptance verification:** Schema-correct fixtures retain valid links and detect true external dependencies.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-084 — Tiling drops links and repairs longitudinal records in place

- **Subsystem:** Tiling and map partitioning
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** tile_extractor and Stage 9
- **Root cause:** Partitioning mutates semantic content after prior gates.
- **What it causes:** Final tiles are not equivalent to the validated full map.
- **Required correction:** Tiling is a pure projection; any clipping policy must be explicit and followed by complete cumulative gates.
- **Acceptance verification:** Hash parent/full and semantic reassembly; zero unexplained loss.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-085 — No untiled→tiles→reassembly equivalence contract

- **Subsystem:** Tiling and map partitioning
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Stage 9/10
- **Root cause:** Per-tile validity does not prove union equivalence.
- **What it causes:** Roads, junctions, signals, objects, and profiles can disappear/duplicate.
- **Required correction:** Create semantic reassembly comparison and source coverage metrics.
- **Acceptance verification:** Union of tile semantic entities equals source according to declared partition policy.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-086 — Tile QA can be skipped or allowed to fail

- **Subsystem:** Tiling and map partitioning
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** UP_SKIP_TILE_QA, UP_ALLOW_TILE_QA_FAIL
- **Root cause:** Release behavior depends on permissive environment flags.
- **What it causes:** Broken tiles proceed to simulation/analysis.
- **Required correction:** Release profiles prohibit skip/allow-fail for required tiles; unavailable CARLA is BLOCKED.
- **Acceptance verification:** Configuration test and failed tile fixture stop promotion.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-087 — No visual tile/XODR alignment and streaming gate

- **Subsystem:** Tiling and map partitioning
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No cooked visual tiling pipeline
- **Root cause:** Logical tiles and future mesh tiles have no shared origin/bounds/semantic manifest.
- **What it causes:** Seams, collision disappearance, duplicates, and streaming stalls occur.
- **Required correction:** Create one tile manifest covering XODR, mesh, transform, semantic groups, collision, LOD, and neighbor dependencies.
- **Acceptance verification:** Drive and sensor routes across every tile edge; no visual/collision/semantic discontinuity.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-088 — Quality gates are explicitly best-effort

- **Subsystem:** Quality gates
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** quality/quality_gates.py
- **Root cause:** Gates collect failures but do not enforce release stop.
- **What it causes:** Invalid maps can be reported as completed.
- **Required correction:** Use typed gate matrix and mandatory enforcement by readiness profile.
- **Acceptance verification:** Any required FAIL/BLOCKED prevents promotion and nonzero process exit.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-089 — Missing gate modules can be marked passed/skipped safely

- **Subsystem:** Quality gates
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** quality_gates ModuleNotFoundError path and summary text
- **Root cause:** Absence is interpreted as a benign skip.
- **What it causes:** Removing a validator can improve the apparent score.
- **Required correction:** Required missing module/artifact/dependency is BLOCKED; NOT_APPLICABLE only if profile says optional.
- **Acceptance verification:** Delete a required validator in test and require blocked release.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-090 — Collision gate can no-op when Shapely is absent

- **Subsystem:** Quality gates
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** quality_gate_manager
- **Root cause:** Dependency absence does not fail the required spatial check.
- **What it causes:** Overlaps/crossings can pass untested.
- **Required correction:** Pin dependency for release or implement fallback; otherwise BLOCKED.
- **Acceptance verification:** Run without Shapely and require BLOCKED for profiles requiring surface/collision validation.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-091 — Gate exceptions are caught and execution continues

- **Subsystem:** Quality gates
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline quality wrapper and Stage 8/tiling paths
- **Root cause:** Validation failure is downgraded to log output.
- **What it causes:** Candidate promotion is disconnected from gate success.
- **Required correction:** Return structured StageResult and stop immediately on required gate exception.
- **Acceptance verification:** Inject validator exception and verify no later stage/artifact promotion.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-092 — Schema validation may be skipped when XSD is absent

- **Subsystem:** Quality gates
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** Stage 8
- **Root cause:** No release-supplied schema/tool is mandatory.
- **What it causes:** Malformed or unsupported OpenDRIVE can proceed.
- **Required correction:** Bundle/pin the supported checker/profile and record version.
- **Acceptance verification:** Missing checker produces BLOCKED; known invalid fixture fails.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-093 — Uniqueness and schema violations are report-only

- **Subsystem:** Quality gates
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** Stage 8
- **Root cause:** Detected violations do not control process outcome.
- **What it causes:** Duplicate IDs and malformed content can survive.
- **Required correction:** Make critical identity/schema defects hard failures before CARLA.
- **Acceptance verification:** Duplicate road/junction/signal/object fixture stops pipeline.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-094 — No artifact-hash-bound gate evidence

- **Subsystem:** Quality gates
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Reports are not consistently tied to exact XODR/mesh/config
- **Root cause:** Gate outputs can be reused with a different candidate.
- **What it causes:** Stale evidence certifies the wrong map.
- **Required correction:** Every report includes input SHA-256, parent, settings, Git, tool versions, and result hash.
- **Acceptance verification:** Change one byte in candidate and require report invalidation.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-095 — No full-map closure after all semantic changes and before tiling

- **Subsystem:** Quality gates
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Stage ordering
- **Root cause:** Final untiled candidate is not rerun through every structural invariant after Stage 8.
- **What it causes:** Late LaneLink/marking/safety changes can invalidate earlier checks.
- **Required correction:** Add immutable whole-map closure stage after all XODR mutations.
- **Acceptance verification:** All cumulative structural gates pass on exact final untiled hash.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-096 — No early stop based on protected metric regression

- **Subsystem:** Quality gates
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Stage reports
- **Root cause:** A stage can reduce invalid-count metrics by deleting content.
- **What it causes:** Superficial improvement masks road/junction/lane loss.
- **Required correction:** Use parent-child budgets for counts, graph components, total length, coverage, and defect metrics.
- **Acceptance verification:** Unexpected loss or component increase fails regardless of local validator count.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-097 — No property/metamorphic/idempotency suite for repairs

- **Subsystem:** Quality gates
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Tests
- **Root cause:** Example-based tests do not expose order sensitivity or repeated mutation.
- **What it causes:** Repairs can drift on repeated runs or depend on XML ordering.
- **Required correction:** Add repair(repair(X))=repair(X), validator immutability, ordering/translation/rotation/tiling invariance.
- **Acceptance verification:** Property suite runs on fixtures and full-map fingerprints.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-098 — CARLA connection is mandatory before offline XODR stages

- **Subsystem:** CARLA server and runtime
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** main_pipeline _connect_carla called before structural stages
- **Root cause:** Offline compiler and simulator lifecycle are coupled.
- **What it causes:** Server outage blocks geometry work; retries/restarts can affect unrelated stages.
- **Required correction:** Separate offline structural pipeline from runtime certification adapter.
- **Acceptance verification:** Generate identical final structural candidate with CARLA unavailable; runtime profile remains BLOCKED separately.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-099 — CARLA server readiness is reduced to TCP port availability

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** carla_server.py and recovery
- **Root cause:** A listening socket is treated as a healthy simulator.
- **What it causes:** Server can be booting, hung, wrong version, wrong map, or nonresponsive to ticks.
- **Required correction:** Implement state machine: process alive → RPC handshake → version → get_world/map → synchronous tick → generation/load test.
- **Acceptance verification:** Each state has timeout, logs, and typed failure; port-only mock never passes.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-100 — Recovery start command does not pass configured RPC/streaming ports

- **Subsystem:** CARLA server and runtime
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** carla_recovery.py
- **Root cause:** Server may start on default ports while client waits on configured ports.
- **What it causes:** Repeated false failures, duplicate servers, and port conflicts.
- **Required correction:** Pass explicit port arguments supported by target CARLA and persist PID/command manifest.
- **Acceptance verification:** Nondefault-port integration test confirms one server and successful RPC.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-101 — Recovery can kill generic UE4Editor processes

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** carla_recovery.py process cleanup
- **Root cause:** Process name matching is broad.
- **What it causes:** Unrelated Unreal/CARLA editor sessions and unsaved work can be terminated.
- **Required correction:** Track only owned PID/process tree with lock and start token; no global kill by name.
- **Acceptance verification:** Run with unrelated mock process and prove it survives recovery.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-102 — Recovery purges CARLA temp directories automatically

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** carla_recovery.py
- **Root cause:** Destructive cleanup occurs without ownership or diagnosis.
- **What it causes:** Useful crash evidence/cache and unrelated user data may be removed; root cause obscured.
- **Required correction:** Archive logs first; purge only explicitly owned cache under opt-in maintenance action.
- **Acceptance verification:** Dry-run report by default and path allow-list tests.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-103 — Server stdout/stderr are discarded

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** server start/recovery
- **Root cause:** Crash diagnostics are redirected away.
- **What it causes:** GPU/RHI/asset/assertion causes cannot be distinguished from client timeout.
- **Required correction:** Capture timestamped stdout/stderr and Unreal logs, plus exit code, command, GPU/RAM snapshot.
- **Acceptance verification:** Forced startup failure produces preserved diagnostic bundle.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-104 — No process ownership lock or lifecycle authority

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** Multiple loaders/runners/recovery utilities
- **Root cause:** Several clients can start, restart, tick, or kill the same server.
- **What it causes:** Race conditions, duplicate servers, deadlocks, and corrupted evidence.
- **Required correction:** Create one CarlaSupervisor service with lock, PID, owner session, heartbeat, graceful stop, and reference-counted clients.
- **Acceptance verification:** Concurrent startup test yields one owned process and deterministic client behavior.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-105 — Preflight may report okay after only version response

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** core/carla_preflight.py
- **Root cause:** get_world/get_map/tick failures do not necessarily dominate result.
- **What it causes:** A partially responsive server is accepted.
- **Required correction:** Require all profile-specific handshake states and exact version compatibility.
- **Acceptance verification:** Mock each failing state and require precise BLOCKED/FAIL.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-106 — Fallback built-in map can hide target XODR load failure

- **Subsystem:** CARLA server and runtime
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** carla_opendrive_loader and fallback settings
- **Root cause:** On failure, an existing map can be used.
- **What it causes:** Screenshots/sensors/routes can certify the wrong map.
- **Required correction:** Disable fallback in all evidence/release profiles; exact map identity guard is mandatory.
- **Acceptance verification:** Deliberately invalid XODR must fail; no built-in world result is accepted.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-107 — Map identity guard strictness is environment-gated

- **Subsystem:** CARLA server and runtime
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** map_identity_guard.py
- **Root cause:** Exact-artifact identity is optional.
- **What it causes:** Runtime evidence may not correspond to final XODR hash.
- **Required correction:** Embed candidate hash/manifest identity in runtime job and verify world/map generation lineage.
- **Acceptance verification:** Wrong-map fixture must fail before spawning actors or sensors.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-108 — World reload/tick errors are swallowed during OpenDRIVE generation

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** carla_opendrive_loader.py
- **Root cause:** Post-load readiness exceptions are tolerated.
- **What it causes:** Generation may return before stable world, leading to spawn/sensor failures.
- **Required correction:** Use bounded readiness state with stable consecutive ticks and map/topology inventory.
- **Acceptance verification:** Delayed/hung world fixture results in BLOCKED, not continued execution.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-109 — Strict XODR validator failures can be caught and loading continues

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** core/carla_utils.py
- **Root cause:** Validation is advisory in some paths.
- **What it causes:** Known-invalid map reaches CARLA and may crash or generate malformed mesh.
- **Required correction:** Make required preflight validator result a load prerequisite.
- **Acceptance verification:** Invalid geometry/lane fixture never invokes generate_opendrive_world.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-110 — Ego spawn adds a fixed Z offset without full clearance/settle validation

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** safe_spawn_ego.py
- **Root cause:** Spawn transform is not derived from vehicle bounding box, road surface normal, collision, or slope.
- **What it causes:** Vehicle may intersect/fall/bounce, misdiagnosed as map or sensor crash.
- **Required correction:** Compute safe ground clearance, probe collision, settle in physics, and validate transform/velocity.
- **Acceptance verification:** Spawn matrix on flat/slope/junction/bridge; no penetration or fall-through.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-111 — Spawn recovery retries the same transform

- **Subsystem:** CARLA server and runtime
- **Severity:** Medium
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** spawn_recovery.py
- **Root cause:** Retries do not change the causal condition.
- **What it causes:** Time is wasted and repeated failure is misclassified as instability.
- **Required correction:** Generate ranked alternative transforms/waypoints and record failure reason per attempt.
- **Acceptance verification:** Blocked spawn produces distinct collision, invalid waypoint, timeout, or map defects.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-112 — Local perception runner ignores requested map identity

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** carla_tools/local_perception_runner.py
- **Root cause:** It operates on current world rather than loading/verifying map_name/hash.
- **What it causes:** Manual/generated comparisons can capture different or stale worlds.
- **Required correction:** Require exact map job descriptor and identity before actor creation.
- **Acceptance verification:** Runner refuses mismatched world.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-113 — Synchronous world mode and Traffic Manager mode are not jointly owned

- **Subsystem:** CARLA server and runtime
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** local perception runner and multiple clients
- **Root cause:** World can be synchronous while Traffic Manager remains asynchronous/default; more than one client may tick.
- **What it causes:** Vehicles stall, client blocks, or runs become nondeterministic and are mistaken for map defects.
- **Required correction:** One tick authority configures world and Traffic Manager synchronously with fixed delta; all other clients wait.
- **Acceptance verification:** Deterministic N-tick route with two observers; no duplicate tick or deadlock.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-114 — Runtime validation is too short and spatially narrow

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** 45 ticks/first spawn/minimal probes in several tools
- **Root cause:** A few seconds and one location are treated close to drivability evidence.
- **What it causes:** Junction, roundabout, bridge, tile, and route defects remain undetected.
- **Required correction:** Require distributed spawn set, stable 500+ ticks, route matrix, and defect-category coverage.
- **Acceptance verification:** Coverage report tied to road/junction IDs and critical locations.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-115 — No systematic fall-through, Z-jump, stuck, collision, and lane-invasion attribution

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Runtime validators
- **Root cause:** Failures are aggregated without causal sensors and map references.
- **What it causes:** Ego/TM/sensor/server defects are confused with map defects.
- **Required correction:** Attach dedicated diagnostics and classify by world frame, actor, road/lane, transform, server health, and sensor backpressure.
- **Acceptance verification:** Injected cases produce correct taxonomy.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-116 — No GPU/VRAM/RHI/render preflight

- **Subsystem:** CARLA server and runtime
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Server and perception startup
- **Root cause:** Manual visual map may exceed render memory or use problematic assets when a camera triggers rendering.
- **What it causes:** Sensor attachment can kill the server even though map and ego alone work.
- **Required correction:** Record GPU driver/VRAM, renderer mode, resolution/texture/mesh budgets, shader state, and headless/offscreen capability before sensor runs.
- **Acceptance verification:** Progressive sensor matrix identifies budget threshold and captures Unreal crash log.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-117 — Multiple overlapping domain-gap implementations create authority ambiguity

- **Subsystem:** Domain-gap analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** domain_gap/*, analysis/*, thesis/*, experiments/*
- **Root cause:** No single package/manifest is designated as authoritative for each RQ.
- **What it causes:** Different metric definitions and alignments can produce inconsistent conclusions.
- **Required correction:** Define one governed analysis API and freeze metric/version/config/dataset hashes; mark supplementary tools explicitly.
- **Acceptance verification:** Same inputs produce one authoritative report; alternates cannot overwrite it.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-118 — Dummy perception evaluator returns zero-valued results

- **Subsystem:** Domain-gap analysis
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** domain_gap/perception_gap.py
- **Root cause:** Placeholder deterministic outputs remain callable.
- **What it causes:** A report can imply no perception gap without running a model.
- **Required correction:** Remove from production/RQ path or return NOT_APPLICABLE/BLOCKED; never numeric placeholder.
- **Acceptance verification:** Attempted release use fails with explicit reason.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-119 — Experiment evaluator and trainer are dummy implementations

- **Subsystem:** Domain-gap analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** experiments/evaluator.py and trainer.py
- **Root cause:** Scaffolds are not isolated from real experiment naming.
- **What it causes:** Users/agents can mistake smoke logic for scientific training/evaluation.
- **Required correction:** Rename/mark debug, exclude from release, or implement complete protocol.
- **Acceptance verification:** Static release scan rejects dummy/pass-only experiment paths.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-120 — Structural domain gap can include pipeline-induced corruption

- **Subsystem:** Domain-gap analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** Stage 6 confirmed regression and thesis comparison
- **Root cause:** Generated map defects are not fully separated from inherent OSM/manual modeling differences.
- **What it causes:** Scientific attribution is biased.
- **Required correction:** Report raw converter, safe structural candidate, and enriched/cooked variants separately; decompose gap by stage delta.
- **Acceptance verification:** Stage-attribution analysis with immutable artifacts and confidence limits.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-121 — No direct generated-versus-manual paired perception experiment

- **Subsystem:** Domain-gap analysis
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** RQ3/RQ5 deferred
- **Root cause:** Structural metrics and proxy analysis are used without matched visual/sensor evidence.
- **What it causes:** Cannot claim perceptual generalization or model performance difference.
- **Required correction:** After visual readiness, use identical routes, poses, actors, weather, sensor rig, frame schedule, and model checkpoint.
- **Acceptance verification:** Paired frame/route manifest and statistical comparison across locations.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-122 — GNN package eagerly imports torch_geometric

- **Subsystem:** GNN analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** domain_gap_gnn/__init__.py
- **Root cause:** Optional heavyweight dependency loads at import and has hung on Windows.
- **What it causes:** Test collection/CLI startup can hang even when GNN is unused.
- **Required correction:** Lazy capability adapter with subprocess timeout and explicit BLOCKED status.
- **Acceptance verification:** Import package without torch; GNN command detects dependency without hanging.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-123 — Node feature dimension does not match model default

- **Subsystem:** GNN analysis
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** Graph feature construction produces 12 values while MapEncoderConfig/train default node_dim is 16
- **Root cause:** Model input shape is inconsistent.
- **What it causes:** Training crashes or hidden padding/path differences invalidate evidence.
- **Required correction:** Derive node_dim from feature schema and assert exact match in manifest/model.
- **Acceptance verification:** Unit test constructs graph and runs forward pass with exact schema.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-124 — Lane successor edges are resolved within the same road/section incorrectly

- **Subsystem:** GNN analysis
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** GNN graph builder
- **Root cause:** OpenDRIVE lane successor semantics across sections/roads are not followed.
- **What it causes:** Graph topology does not represent the map.
- **Required correction:** Build edges through lane-section transitions, road links, junction connections, and LaneLinks with contact orientation.
- **Acceptance verification:** Synthetic topology fixtures and route correspondence.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-125 — Fallback creates all-to-all lanes across road successor

- **Subsystem:** GNN analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** GNN graph builder
- **Root cause:** Missing lane mapping becomes dense connectivity.
- **What it causes:** O(N²) false edges dominate embeddings and erase topology signal.
- **Required correction:** Unknown correspondence remains absent/ambiguous; never invent complete bipartite links.
- **Acceptance verification:** Fixture with missing links produces explicit unknown state, not dense edges.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-126 — Center/none lanes and fabricated defaults enter GNN features

- **Subsystem:** GNN analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** GNN feature extraction
- **Root cause:** Invalid/non-driving lanes and default 3.5 m widths are treated as data.
- **What it causes:** Embeddings encode pipeline artifacts as map characteristics.
- **Required correction:** Use validated lane inventory and missing-value/confidence masks.
- **Acceptance verification:** Feature manifest lists source/confidence; invalid lanes excluded.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-127 — Curvature features are arc-only and speed units are not governed

- **Subsystem:** GNN analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** GNN features
- **Root cause:** Spiral/polynomial curvature and speed-unit normalization are incomplete.
- **What it causes:** Feature values are inconsistent across roads/maps.
- **Required correction:** Use authoritative evaluator and explicit SI units with schema version.
- **Acceptance verification:** Primitive/unit fixtures and distribution sanity checks.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-128 — Positive-only consistency objective can collapse representations

- **Subsystem:** GNN analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** GNN training
- **Root cause:** No negatives, variance/covariance regularization, or downstream validation.
- **What it causes:** Constant embeddings can minimize loss.
- **Required correction:** Use contrastive negatives or VICReg/Barlow-style anti-collapse terms and monitor embedding variance.
- **Acceptance verification:** Collapse detector, train/validation split, retrieval/classification sanity benchmark.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-129 — Checkpoint condition misses final epoch

- **Subsystem:** GNN analysis
- **Severity:** Medium
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** training loop checks epoch == args.epochs in zero-based loop
- **Root cause:** Final checkpoint may never be saved; short runs can save nothing.
- **What it causes:** Training evidence and reproducibility are lost.
- **Required correction:** Save on epoch+1, best validation, and final in finally block with metadata.
- **Acceptance verification:** Run 1-epoch and 3-epoch fixtures; expected checkpoints exist and reload.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-130 — Dataset split and artifact hashes are missing

- **Subsystem:** GNN analysis
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** GNN training
- **Root cause:** Training and evaluation examples can overlap and data identity is unclear.
- **What it causes:** Reported performance is not reproducible and can leak.
- **Required correction:** Split by map/location/tile group; hash graph schema, artifacts, split, seed, and code.
- **Acceptance verification:** Manifest and rerun equality test.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-131 — RL fuzzer apply_to_map returns the original path unchanged

- **Subsystem:** RL fuzzer
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** experiments/rl_fuzzer.py
- **Root cause:** The named fuzzer has no mutation/reward/episode implementation.
- **What it causes:** Fuzz coverage claims are unsupported.
- **Required correction:** Return NOT_APPLICABLE until implemented, or build constrained candidate mutations with oracle gates and rollback.
- **Acceptance verification:** Known defect seeds are found without corrupting source; coverage/reward/episodes recorded.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-132 — OSM2World paths are hard-coded to a user installation

- **Subsystem:** OSM2World and Blender
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** enrichment/osm2world_runner.py
- **Root cause:** Runtime depends on machine-specific paths.
- **What it causes:** Pipeline is not portable or reproducible.
- **Required correction:** Use capability probe/configured toolchain manifest and no personal absolute defaults.
- **Acceptance verification:** Fresh machine/container reports BLOCKED with actionable setup or runs with pinned version.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-133 — OSM2World is supplemental and excludes roads/terrain

- **Subsystem:** OSM2World and Blender
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** runner configuration
- **Root cause:** It cannot serve as the complete visual map despite downstream expectations.
- **What it causes:** Buildings/objects can be exported without a coherent road/terrain base.
- **Required correction:** Declare role explicitly; pair with authoritative road/terrain mesh or RoadRunner/Unreal authoring pipeline.
- **Acceptance verification:** Visual manifest proves every required semantic layer source.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-134 — No XODR↔OSM2World mesh alignment proof

- **Subsystem:** OSM2World and Blender
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** OSM2World output checks only file existence/hash
- **Root cause:** Projection, origin, scale, axis, and elevation alignment are not measured.
- **What it causes:** Supplemental buildings/vegetation can be displaced or mirrored.
- **Required correction:** Fit/verify control-point transform and road/building residuals before import.
- **Acceptance verification:** Scale error, heading, translation, vertical residual within thresholds.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-135 — Blender runner only performs generic OBJ→FBX conversion

- **Subsystem:** OSM2World and Blender
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** blender_runner.py
- **Root cause:** No map-specific semantic processing is implemented.
- **What it causes:** FBX existence is mistaken for a CARLA-ready visual map.
- **Required correction:** Build deterministic scene pipeline for semantic split, transforms, materials, collisions, LOD, UV/lightmaps, tiles, and manifest.
- **Acceptance verification:** Reimport FBX and validate semantic objects, bounds, materials, and alignment.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-136 — Zero-mesh Blender export can still be treated as successful

- **Subsystem:** OSM2World and Blender
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** blender_runner
- **Root cause:** A warning does not necessarily fail nonempty FBX output.
- **What it causes:** Empty/invalid visual packages pass superficial file gates.
- **Required correction:** Require minimum expected semantic inventory and geometry counts, not file size alone.
- **Acceptance verification:** Empty OBJ/scene fixture fails.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-137 — No material, texture, UV, lightmap, collision, or LOD validation

- **Subsystem:** OSM2World and Blender
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** Blender/visual pipeline
- **Root cause:** Asset performance and rendering correctness are ungoverned.
- **What it causes:** Manual map may consume excessive VRAM/draw calls, render incorrectly, or lack collision.
- **Required correction:** Create visual budget and asset validators; generate collision proxies and LOD chain.
- **Acceptance verification:** Unreal import/cook report plus runtime FPS/VRAM/collision/semantic tests.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-138 — Existing Dockerfile is not an Unreal/CARLA cooking environment

- **Subsystem:** Unreal/CARLA cooking
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** hpc/Dockerfile.yolo_smoke
- **Root cause:** It only supports Python/HPC smoke tests.
- **What it causes:** No reproducible cooked map package can be built.
- **Required correction:** Add separate Linux CARLA source/binary map-ingestion workflow with pinned branch/toolchain and large storage requirements.
- **Acceptance verification:** Clean host builds/imports package and records image/tool hashes and cook logs.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-139 — Target engine/version is not explicitly separated

- **Subsystem:** Unreal/CARLA cooking
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Project targets CARLA 0.9.16 while user requests UE5
- **Root cause:** CARLA 0.9.16 uses its modified UE4.26 toolchain; UE5 development is a separate branch/profile.
- **What it causes:** A UE5-cooked asset cannot be assumed compatible with 0.9.16 binary/source.
- **Required correction:** Define STABLE_0916_UE426 and EXPERIMENTAL_UE5_DEV profiles with separate branches, plugins, packages, and evidence.
- **Acceptance verification:** Package metadata prevents cross-profile import and reports exact engine/CARLA commit.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-140 — No same-name FBX/XODR/package contract

- **Subsystem:** Unreal/CARLA cooking
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Visual export/import automation
- **Root cause:** CARLA map ingestion requires coordinated files and package metadata.
- **What it causes:** Wrong/missing logical map can be paired with mesh.
- **Required correction:** Generate immutable MapName.fbx + MapName.xodr + package JSON with matching hashes and authority.
- **Acceptance verification:** Import script rejects base-name/hash/profile mismatch.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-141 — No semantic content organization or CARLA actor setup

- **Subsystem:** Unreal/CARLA cooking
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No Unreal import pipeline
- **Root cause:** Road, road lines, sidewalk, terrain, buildings, vegetation, signs, signals are not mapped to CARLA semantics.
- **What it causes:** Semantic cameras and environment queries are wrong; traffic controls do not function.
- **Required correction:** Automate folder/tag/material classification, collisions, routes/spawns, traffic groups/triggers, and save/cook.
- **Acceptance verification:** CARLA semantic camera and actor inventory match manifest.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-142 — No pedestrian navigation build

- **Subsystem:** Unreal/CARLA cooking
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No final OBJ→nav .bin workflow
- **Root cause:** Walkers cannot navigate a cooked map.
- **What it causes:** Perception/traffic scenarios lack pedestrians or fail.
- **Required correction:** After final geometry, export recognized mesh names, build same-name .bin, clear cache, and test walkers.
- **Acceptance verification:** Random nav locations, controller routes, sidewalks/crosswalk connectivity, no building penetration.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-143 — No cooked-package acceptance and archive

- **Subsystem:** Unreal/CARLA cooking
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** No package-level gate
- **Root cause:** Cook success, missing assets, shader errors, redirects, and load identity are not verified.
- **What it causes:** Deployment can fail despite source assets existing.
- **Required correction:** Archive package, cook/import logs, asset registry, nav, settings, versions, and exact runtime test.
- **Acceptance verification:** Fresh CARLA install imports package, lists map, loads exact world, and passes visual/runtime gates.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-144 — DominikSensorSetup is an incomplete active stub

- **Subsystem:** Perception and sensors
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** sensors/dominik_sensor_setup.py
- **Root cause:** The module ignores calibration matrices and exposes only hard-coded camera/LiDAR setup.
- **What it causes:** Runners expecting a full rig fail or capture the wrong sensors.
- **Required correction:** Select one canonical rig implementation; implement typed calibration parsing and complete lifecycle.
- **Acceptance verification:** API contract tests and exact sensor manifest against calibration file.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-145 — Runners call missing setup_all_sensors

- **Subsystem:** Perception and sensors
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** multiple perception/dataset runners versus DominikSensorSetup
- **Root cause:** Interface and implementation drift.
- **What it causes:** Immediate AttributeError can be mistaken for CARLA/manual-map crash.
- **Required correction:** Fail at import/preflight with API compatibility check; implement or update callers.
- **Acceptance verification:** Instantiate every runner in offline mocked CARLA environment; zero missing-method errors.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-146 — Fuller sensor implementation exists as .txt rather than active Python source

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** sensors/dominik_sensor_setup_high_res.txt
- **Root cause:** Code was copied/exported without canonical integration.
- **What it causes:** Developers may edit the wrong file; expected functionality is unavailable.
- **Required correction:** Recover/review into canonical module or archive as reference; remove split authority.
- **Acceptance verification:** One source implementation and callers/tests agree.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-147 — Camera calibration transform is inverted contrary to documented contract

- **Subsystem:** Perception and sensors
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** sensors/attach_sensors_safe.py
- **Root cause:** cTv vehicle→camera is passed through a helper that inverts vehicle→sensor.
- **What it causes:** Camera pose is wrong; projections and manual/generated comparisons are invalid.
- **Required correction:** Define frame notation explicitly and convert exactly once to CARLA parent-relative transform.
- **Acceptance verification:** Matrix round-trip and known pose/reprojection fixture.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-148 — LiDAR transform is double-inverted

- **Subsystem:** Perception and sensors
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** attach_sensors_safe.py
- **Root cause:** vTl is inverted to vehicle→LiDAR, then helper inverts again.
- **What it causes:** LiDAR attaches in wrong pose; point clouds misalign or may intersect vehicle/map.
- **Required correction:** Normalize source transform convention once and use a single conversion function.
- **Acceptance verification:** Known LiDAR pose and camera-LiDAR reprojection test.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-149 — Sensor report describes intended transforms rather than actual implementation

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** attach_sensors_safe report text
- **Root cause:** Metadata is not generated from the applied transform.
- **What it causes:** Evidence falsely claims calibration compliance.
- **Required correction:** Serialize actual matrices/transforms returned by the canonical conversion code.
- **Acceptance verification:** Compare report matrix to CARLA actor transform and calibration source.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-150 — rig_transforms.py executes work and self-imports at import time

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** sensors/rig_transforms.py
- **Root cause:** Library and script concerns are mixed; relative calibration file is loaded immediately.
- **What it causes:** Imports can fail, recurse, or depend on working directory.
- **Required correction:** Convert to pure library plus separate CLI, no side effects, explicit calibration path.
- **Acceptance verification:** Import test in arbitrary working directory with no files.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-151 — Sensor defaults are too heavy and inconsistent

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** 1920x1080 camera, 1.3M LiDAR points/s in one setup; different defaults elsewhere
- **Root cause:** No governed resource budget or profile.
- **What it causes:** Manual visual map plus high-res sensors can exceed VRAM/bandwidth and crash or time out.
- **Required correction:** Define LOW_DIAGNOSTIC, STANDARD_DATASET, HIGH_QUALITY profiles with pixel/ray/VRAM budgets.
- **Acceptance verification:** Progressive load test records stable FPS, VRAM, callback latency, and drop rate.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-152 — sensor_tick is often 0.0 for all sensors

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** attachment code
- **Root cause:** Every simulation frame produces all camera/LiDAR data regardless of need.
- **What it causes:** GPU, network, disk, and Python callback saturation.
- **Required correction:** Set sensor_tick relative to fixed_delta_seconds and experiment rate; document expected frames.
- **Acceptance verification:** Measured capture rate matches manifest with bounded drops.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-153 — No canonical frame synchronization barrier

- **Subsystem:** Perception and sensors
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** multiple callbacks/runners
- **Root cause:** Sensors save/process independently with different GPU delay and queue behavior.
- **What it causes:** RGB, semantic, depth, and LiDAR examples do not represent the same world state.
- **Required correction:** Use frame-indexed synchronizer with allowed camera latency, timeout, drop/duplicate accounting, and one world tick owner.
- **Acceptance verification:** Every saved sample has complete required sensor set for one governed frame or explicit missing status.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-154 — Disk I/O occurs inside sensor callbacks

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** local perception and recording runners
- **Root cause:** Image/PLY encoding and writes block callback threads.
- **What it causes:** Backpressure, queue overflow, timeout, frame loss, and apparent server unresponsiveness.
- **Required correction:** Callbacks enqueue lightweight immutable data; bounded writer workers persist asynchronously.
- **Acceptance verification:** Stress test records queue depth, latency, drops, and no callback exception.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-155 — Callback exceptions are broadly swallowed

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** sensor/perception runners
- **Root cause:** Queue full, conversion, disk, and actor lifecycle errors are hidden.
- **What it causes:** Incomplete datasets appear successful.
- **Required correction:** Capture typed callback failures and fail the run when required stream health is violated.
- **Acceptance verification:** Inject disk/queue error and require run failure plus diagnostic manifest.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-156 — Sensor healthcheck can tick the world itself

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** thesis_sensor_rig.py
- **Root cause:** A helper assumes tick ownership.
- **What it causes:** Multiclient synchronous runs can deadlock or advance unexpected frames.
- **Required correction:** Healthcheck requests ticks through the supervisor or observes existing ticks; one owner only.
- **Acceptance verification:** Two-client test proves one tick source and deterministic frames.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-157 — Healthcheck queue callback can raise queue.Full

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** maxsize=1 put_nowait without robust handling
- **Root cause:** Repeated frames race with consumer.
- **What it causes:** Listener callback can fail silently and sensors appear unhealthy.
- **Required correction:** Use nonblocking replace/drop counter or adequate bounded queue with exception handling.
- **Acceptance verification:** High-rate callback test has no unhandled exception and reports drops.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-158 — Temporary and recording listener lifecycle is unclear

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** sensor rig healthcheck then recorder
- **Root cause:** Listeners can overlap or remain attached.
- **What it causes:** Duplicate callbacks, memory growth, incorrect frame counts, actor destruction errors.
- **Required correction:** Explicit sensor state machine: spawned→healthchecked→listener transferred→recording→stopped→destroyed.
- **Acceptance verification:** Lifecycle tests show one listener and zero live actors/callbacks after shutdown.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-159 — Manual-map crash cause is not isolated between map, ego, renderer, and sensor rig

- **Subsystem:** Perception and sensors
- **Severity:** Critical
- **Evidence status:** `RUNTIME_DIAGNOSIS_REQUIRED`
- **Evidence:** Reported failure when sensor attaches
- **Root cause:** Current code has Python API errors and calibration issues, while a camera also activates rendering load.
- **What it causes:** Treating every failure as a map crash can lead to wrong repairs.
- **Required correction:** Run staged matrix: map only; ego only; CPU sensor; low-res RGB; semantic; low-rate LiDAR; then scale. Capture client exception, server exit, UE log, GPU/RAM, frame health.
- **Acceptance verification:** Classification: B fail=map/ego/spawn; C pass/D fail=renderer/GPU/assets; low profiles pass/full fail=resource/backpressure; server alive/client timeout=sync/tick/queue.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-160 — Manual map may have render-asset pathologies revealed only by camera

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `RUNTIME_DIAGNOSIS_REQUIRED`
- **Evidence:** Cooked/manual visual map unknown
- **Root cause:** High-poly meshes, many materials/draw calls, invalid collision, huge textures, shader errors, or no LOD can overload CARLA.
- **What it causes:** Server can remain stable without sensors but crash when GPU camera renders the scene.
- **Required correction:** Run Unreal asset audit and optimize mesh segmentation, instancing, LODs, textures, collision, lightmaps, and culling.
- **Acceptance verification:** Low-res camera sweep plus Unreal/GPU metrics; no fatal logs and stable budget.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-161 — No exact sensor and ego lifecycle owner

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Multiple runners/setup/cleanup tools
- **Root cause:** Actor creation, autopilot, tick, listener, and destruction responsibilities overlap.
- **What it causes:** Zombie actors, duplicate sensors, TM inconsistencies, and nondeterministic shutdown.
- **Required correction:** Create one ExperimentSession owning world settings, ego, TM, sensors, synchronizer, recorder, and teardown.
- **Acceptance verification:** Repeated runs leave zero owned actors and restore world settings exactly.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-162 — No calibrated reprojection acceptance gate

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Calibration files and sensor transforms
- **Root cause:** Matrix parsing alone does not prove rendered data alignment.
- **What it causes:** Wrong axis/sign/inversion can survive and invalidate domain-gap data.
- **Required correction:** Project LiDAR/known 3D landmarks into RGB/depth and measure residual; verify handedness and units.
- **Acceptance verification:** Residual threshold by image region/range; visual diagnostic overlays archived.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-163 — Standalone OpenDRIVE world cannot supply full perception semantics

- **Subsystem:** Perception and sensors
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Generated OpenDRIVE mesh
- **Root cause:** Logical road generation lacks complete buildings, materials, semantic classes, and grounded assets.
- **What it causes:** Perception results are not comparable to a manually modeled visual map.
- **Required correction:** Require cooked aligned visual map before perceptual readiness; keep standalone runs structural/drivability-only.
- **Acceptance verification:** Readiness gate checks semantic class inventory, visual mesh hash, and cooked package identity.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-164 — Segmentation trainer assumes 256 raw classes without governed remapping

- **Subsystem:** Training pipeline
- **Severity:** Critical
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** perception/min_train_segmentation.py
- **Root cause:** CARLA raw IDs are consumed directly and ignore/valid labels are not defined.
- **What it causes:** Loss/metrics are dominated by unused classes and labels may be semantically wrong.
- **Required correction:** Create versioned CARLA→training class map, ignore index, and dataset validator.
- **Acceptance verification:** Class histogram, unknown-label rejection, and mapped mask visualization.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-165 — No train/validation/test split

- **Subsystem:** Training pipeline
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** min_train_segmentation.py
- **Root cause:** All paired frames can be used without location/route separation.
- **What it causes:** Performance is not measured and adjacent-frame leakage is likely.
- **Required correction:** Split by route/location/map/weather group, never random adjacent frames.
- **Acceptance verification:** Manifest proves disjoint groups and reports counts/class balance.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-166 — No meaningful evaluation metrics

- **Subsystem:** Training pipeline
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** training script
- **Root cause:** Only basic training loss is available.
- **What it causes:** Cannot determine segmentation quality or domain gap.
- **Required correction:** Compute per-class IoU, mIoU, confusion, accuracy with ignored classes, calibration/uncertainty if needed.
- **Acceptance verification:** Metrics on validation/test with saved predictions and reproducible checkpoint.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-167 — Minimal model/training configuration is not production-ready

- **Subsystem:** Training pipeline
- **Severity:** Medium
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** weights=None, few epochs, no normalization/augmentation
- **Root cause:** Training is a smoke test.
- **What it causes:** Results are weak and non-comparable.
- **Required correction:** Define baseline/pretrained options, normalization, bounded augmentation, scheduler, early stopping, and ablations.
- **Acceptance verification:** Config-locked reproducible training and baseline comparison.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-168 — No deterministic data-loader and experiment manifest

- **Subsystem:** Training pipeline
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** training scripts
- **Root cause:** Worker seeds, dependency versions, dataset hash, map hash, and rig hash are not complete.
- **What it causes:** Runs cannot be reproduced exactly.
- **Required correction:** Record environment/container, seeds, splits, source hashes, class map, sensor profile, route/weather/actor seeds.
- **Acceptance verification:** Two short runs with same manifest produce matching sample order and near-identical metrics.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-169 — No robust checkpoint/resume/artifact registry

- **Subsystem:** Training pipeline
- **Severity:** High
- **Evidence status:** `VERIFIED_IN_UPLOADED_BASELINE`
- **Evidence:** run_training.py and scripts
- **Root cause:** SLURM/environment handling is placeholder-level.
- **What it causes:** Interrupted training is lost and model/data provenance unclear.
- **Required correction:** Add atomic checkpoints, resume validation, best/final models, registry metadata, and storage checks.
- **Acceptance verification:** Interrupt/resume test reproduces uninterrupted trajectory within tolerance.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-170 — No domain-balanced paired training/evaluation protocol

- **Subsystem:** Training pipeline
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Manual/generated maps and route data
- **Root cause:** Differences in route, weather, actors, frame counts, and class distribution confound map domain effects.
- **What it causes:** Performance difference cannot be attributed to map domain.
- **Required correction:** Generate paired manifests with matched conditions and analyze within-pair plus cross-domain transfer.
- **Acceptance verification:** Statistical report includes paired tests, confidence intervals, and per-location results.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-171 — No complete multimodal dataset contract

- **Subsystem:** Training pipeline
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** RGB/semantic/depth/LiDAR outputs
- **Root cause:** Files are not guaranteed synchronized, calibrated, complete, or tied to map/route.
- **What it causes:** Training consumes corrupted/mismatched data.
- **Required correction:** Create sample manifest with frame, timestamp, sensor hashes, transforms, intrinsics, ego pose, route, map/package hash, and health flags.
- **Acceptance verification:** Dataset validator rejects missing/mismatched/late/duplicate frames.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-172 — Truly 3D map product is not defined as a governed artifact set

- **Subsystem:** Deployment and release
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Current focus often treats XODR as the map
- **Root cause:** A CARLA map requires logical roads plus aligned visual/collision/semantic/navigation assets.
- **What it causes:** Project may call a standalone generated road surface a complete map.
- **Required correction:** Define package: XODR, terrain, road/junction/sidewalk mesh, buildings/props, materials, collision, LOD, semantic labels, signals, routes/spawns, nav .bin, package metadata.
- **Acceptance verification:** Fresh runtime loads package and all layers pass identity/alignment/behavior gates.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-173 — No environment/toolchain lock for map cooking and training

- **Subsystem:** Deployment and release
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** CARLA/Unreal/Blender/OSM2World/Python/HPC
- **Root cause:** Local installations and hard-coded paths produce irreproducible results.
- **What it causes:** Builds and training differ by machine.
- **Required correction:** Pin commits/images/tool versions and record checksums; separate licensed external tools from reproducible adapters.
- **Acceptance verification:** Clean-machine bootstrap or explicit BLOCKED report with exact missing dependencies.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-174 — Readiness labels are not mechanically hierarchical

- **Subsystem:** Deployment and release
- **Severity:** Critical
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Structural, drivable, visual, sensor, perception claims
- **Root cause:** A later label can be asserted from screenshots or one frame without satisfying lower layers.
- **What it causes:** Stakeholders overestimate map maturity.
- **Required correction:** Implement monotonic readiness state machine with required gate matrix and artifact identities.
- **Acceptance verification:** Cannot promote VISUAL_MAP_READY unless structural/drivable gates and cooked-package gates pass.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-175 — No unified problem/issue register linked to commits and artifacts

- **Subsystem:** Deployment and release
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Scattered reports/prompts
- **Root cause:** Issues are rediscovered, renamed, or declared fixed without evidence.
- **What it causes:** Progress cannot be audited reliably.
- **Required correction:** Maintain stable problem IDs, status, first/last SHA, evidence, fix commit, tests, and readiness impact.
- **Acceptance verification:** Every integration updates problems.md/JSON and unresolved issues remain visible.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-176 — No independent post-fix audit before merge/promotion

- **Subsystem:** Deployment and release
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Agents implement and self-report
- **Root cause:** A model can claim success based on its own tests or inactive code path.
- **What it causes:** Regressions and unwired fixes reach the main branch.
- **Required correction:** Use independent read-only reviewer on exact remote commit and active call path, then guarded integration.
- **Acceptance verification:** Reviewer verdict and report SHA required for promotion.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-177 — GitHub publication is not a hard completion criterion

- **Subsystem:** Deployment and release
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Prior branches missing/empty/unpublished
- **Root cause:** Local work is inaccessible to external audit and consolidation.
- **What it causes:** Progress claims cannot be verified and branches cannot be merged.
- **Required correction:** After every bounded commit push and compare local/remote SHA; reject empty/no-divergence branches.
- **Acceptance verification:** Remote branch and commit are fetchable and contain expected diff/tests/report.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## PROB-178 — No release rollback and compatibility policy

- **Subsystem:** Deployment and release
- **Severity:** High
- **Evidence status:** `ARCHITECTURE_GAP`
- **Evidence:** Map/compiler/visual packages
- **Root cause:** A new stage or package can replace the last working version without tested rollback.
- **What it causes:** Recovery after regression is manual and evidence can be lost.
- **Required correction:** Version immutable artifacts/packages and maintain tested rollback pointer with migration notes.
- **Acceptance verification:** Rollback loads prior exact map/package and passes its recorded smoke gates.
- **Current disposition:** `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

---

# Cross-stage implementation order

1. Recover complete editable source and make offline tests collect.
2. Establish one canonical call path, configuration schema, immutable manifests, stage mutation contracts, and candidate promotion.
3. Preserve raw Osm2Odr output as the baseline; disable unsafe plan-view, connector, roundabout, lane, LaneLink, marking, signal, and synthetic enrichment mutations.
4. Implement one authoritative OpenDRIVE primitive evaluator and read-only defect localization.
5. Repair topology/horizontal geometry using bounded candidate reconstruction; freeze geometry cryptographically.
6. Rebuild elevation/lateral profile against the frozen final reference line.
7. Build lane/cross-section/maneuver/LaneLink candidates from evidence; preserve native semantics by default.
8. Add a first-class drivable-surface/hole stage and whole-map cumulative closure.
9. Partition only after closure and prove tile semantic reassembly equivalence.
10. Separate offline structural release from CARLA server supervision and exact-artifact runtime certification.
11. Build an aligned visual-map pipeline and cook a version-pinned CARLA package; treat UE5 as a separate experimental profile from CARLA 0.9.16.
12. Replace dummy domain/GNN/RL paths with governed implementations or explicit NOT_APPLICABLE states.
13. Consolidate one calibrated sensor rig and diagnose manual-map crashes with a staged map/ego/sensor/render matrix.
14. Generate synchronized multimodal datasets and deploy reproducible, evaluated training.
15. Promote readiness levels only through independent, hash-bound, fail-closed review.

# Critical stop conditions

Stop the pipeline and preserve evidence when any of these occurs:

- active source is missing or bytecode-only;
- input/config/artifact identity is unknown;
- test collection has errors;
- a validator changes its input;
- a stage modifies an undeclared domain;
- road/junction/lane content is unexpectedly deleted;
- horizontal geometry changes after freeze;
- elevation coverage is missing or silently falls back;
- a required gate is skipped, missing, or raises;
- CARLA loads a fallback or wrong map;
- server health cannot be distinguished from port availability;
- sensor data cannot be synchronized or calibrated;
- local and remote Git SHAs differ;
- an implementation branch has no unique verified commit.
